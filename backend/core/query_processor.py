"""
query_processor.py — 查询编排器（核心）

数据流（与 plan 阶段 5.2 一致）：
  1. DataManager.get_dataset()
  2. DataProfiler.build_data_profile() → Markdown 画像
  3. L1 精确缓存（SemanticCache.lookup → L1）
  4. L2 FAISS 缓存（SemanticCache.lookup → L2）
  5. LLM Function Calling（LLMClient.analyze_question）
  6. SQL Generator（生成 SQL 字符串）
  7. SQL Executor（执行 → result）
  8. Chart Config Generator（生成 chart_config）
  9. Insight Generator（生成 insight 文字）
  10. 写回 L1 + L2 缓存
  11. 写 QueryHistory
  12. 返回前端期望的 JSON 形状

返回 JSON 形状（与 HttpQueryService 契约一致）：
{
    "query_id": "q-...",
    "dataset_id": "ds-...",
    "question": "...",
    "sql": "SELECT ...",
    "data": {"columns": [...], "rows": [...], "row_count": N},
    "chart_config": {...},
    "chart_data": {...},  # 兼容字段
    "insight": "...",
    "analysis": {...},
    "cached": false,
    "cache_level": "L1|L2|miss",
    "response_time_ms": 1850,
    "llm_tokens_used": {"prompt": N, "completion": N}
}
"""
import asyncio
import logging
import re
import time
import uuid
from typing import Any, Dict, List, Optional, Set

from cache.semantic_cache import get_semantic_cache
from core.chart_config_generator import generate_chart_config, make_chart_data_payload
from core.data_manager import DataManagerError, DatasetNotFoundError, data_manager
from core.data_profiler import build_data_profile
from core.follow_up_detector import (
    detect_and_resolve_follow_up,
    resolve_pronoun,
)
from core.insight_generator import generate as generate_insight
from core.rule_engine import classify as rule_classify
from core.sql_executor import SQLExecutionError, SQLExecutor
from core.sql_generator import SQLGenerationError, generate as generate_sql, validate_llm_sql
from core.rules_store import rules_store
from llm.function_schema import EXECUTE_DATA_QUERY_FUNCTION
from llm.llm_client import LLMClient, get_llm_client
from llm.prompts import build_user_message
from models import db_session_scope
from models.dataset import Dataset
from models.query_history import QueryHistory

logger = logging.getLogger(__name__)


# ===== 自定义异常 =====
class QueryProcessorError(Exception):
    """查询处理错误"""
    pass


# ===== 主类 =====
class QueryProcessor:
    """查询编排器（LLM → SQL → 执行 → 图表 → 洞察 → 缓存 → 历史）"""

    def __init__(self):
        self.cache = get_semantic_cache()
        self.llm_client: LLMClient = get_llm_client()
        self.sql_executor = SQLExecutor()

    async def process(
        self,
        question: str,
        dataset_id: str,
        conversation_history: Optional[List[Dict[str, Any]]] = None,
        entity_memory: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """处理用户查询（核心入口）

        Args:
            question: 用户自然语言问题
            dataset_id: 数据集 ID
            conversation_history: 对话历史 list[{question, sql, interpretation_summary}, ...]
            entity_memory: 字段别名记忆 dict{alias: realField, ...}

        Returns:
            前端期望的 JSON 形状（含 sql/data/chart_config/insight/...）

        Raises:
            DatasetNotFoundError: 数据集不存在
            QueryProcessorError: 处理过程中其他错误
        """
        t0 = time.time()

        # 构造 LLM 用的对话历史 Markdown（如有）
        history_md = None
        if conversation_history:
            try:
                from llm.prompts import build_conversation_history
                history_md = build_conversation_history(conversation_history)
            except Exception as e:
                logger.debug(f"[QueryProcessor] build_conversation_history 失败: {e}")
                history_md = None

        if not question or not question.strip():
            raise QueryProcessorError("问题不能为空")
        if not dataset_id:
            raise QueryProcessorError("dataset_id 不能为空")

        question = question.strip()

        # 1. 获取数据集
        try:
            dataset = data_manager.get_dataset(dataset_id)
        except DatasetNotFoundError:
            raise

        # 2. 构建数据画像
        try:
            data_profile = build_data_profile(dataset)
        except Exception as e:
            logger.warning(f"[QueryProcessor] 数据画像失败: {e}")
            data_profile = ""

        # 2.4 代词解析（Backend Item A3）：用 prev raw_result 把"那个最高的"换成实体名
        if conversation_history and isinstance(conversation_history, list) and len(conversation_history) > 0:
            last_turn_for_pronoun = conversation_history[-1]
            if (
                isinstance(last_turn_for_pronoun, dict)
                and last_turn_for_pronoun.get("analysis")
                and last_turn_for_pronoun.get("raw_result")
            ):
                try:
                    resolved_q = resolve_pronoun(question, last_turn_for_pronoun)
                    if resolved_q and resolved_q != question:
                        logger.info(
                            f"[QueryProcessor] 代词解析: '{question[:30]}' → '{resolved_q[:30]}'"
                        )
                        question = resolved_q
                except Exception as e:
                    logger.debug(f"[QueryProcessor] 代词解析失败: {e}")

        # 2.5 追问快路径（Backend Item A）：命中追问 → 复用上轮 analysis，跳过 LLM
        shortcut_response = self._try_follow_up_shortcircuit(
            question=question,
            dataset=dataset,
            data_profile=data_profile,
            conversation_history=conversation_history,
            entity_memory=entity_memory,
            t0=t0,
        )
        if shortcut_response is not None:
            return shortcut_response

        # 3+4. L1 + L2 缓存查询
        cached_result = self.cache.lookup(question, dataset_id)
        if cached_result is not None:
            cache_level = cached_result.get("cache_level", "L1")
            return self._build_response(
                question=question,
                dataset=dataset,
                sql=cached_result["sql"],
                data=cached_result["data"],
                chart_config=cached_result.get("chart_config"),
                insight=cached_result.get("insight"),
                analysis=None,  # 缓存命中不返回完整 analysis
                cached=True,
                cache_level=cache_level,
                t0=t0,
            )

        # 5. LLM Function Calling
        # Layer 2：先用 rules_store 检索与当前问题相关的规则，注入 prompt
        relevant_rules = self._retrieve_rules(question, dataset_id)

        # Layer 3 前置主动检测：单句多问题 → 优先走拆解路径
        if self._is_multi_question(question):
            logger.info(
                f"[QueryProcessor] 主动检测到多问题，优先拆解: {question[:50]}"
            )
            multi = await self._decompose_and_execute(
                question, dataset, dataset_id,
                entity_memory=entity_memory,
                data_profile=data_profile,
                t0=t0,
            )
            if multi is not None:
                return multi
            # 拆解失败 → 退回到正常 LLM 路径
            logger.info("[QueryProcessor] 拆解失败或为空，退回 LLM 路径")

        analysis = await self._llm_analyze(
            question, data_profile, dataset,
            conversation_history=history_md,
            entity_memory=entity_memory,
            relevant_rules=relevant_rules,
        )

        # 6. 规则引擎降级（LLM 失败时）
        if analysis is None:
            logger.info(f"[QueryProcessor] LLM 失败，降级到规则引擎: {question[:50]}")
            # P1-B：构建字段类型映射 + 透传 entity_memory
            field_type_map = {
                f["name"]: f.get("type", "text")
                for f in dataset.get_field_info()
            }
            analysis = rule_classify(
                question=question,
                field_info=dataset.get_field_info(),
                columns=dataset.get_columns(),
                entity_memory=entity_memory,
                field_type_map=field_type_map,
            )

            # P1-E：规则引擎也无法识别 → 再尝试一次 LLM 兜底（minimal prompt）
            if analysis is None and self.llm_client.is_configured():
                logger.info(
                    f"[QueryProcessor] 规则引擎无法识别，再尝试 LLM 兜底: {question[:50]}"
                )
                analysis = await self._llm_fallback_classify(
                    question, data_profile, dataset,
                    entity_memory=entity_memory,
                    relevant_rules=relevant_rules,
                )

            # Layer 3：复杂问题拆解（最后一次兜底）
            if analysis is None and self.llm_client.is_configured():
                logger.info(
                    f"[QueryProcessor] 兜底仍失败，尝试拆解复杂问题: {question[:50]}"
                )
                multi = await self._decompose_and_execute(
                    question, dataset, dataset_id,
                    entity_memory=entity_memory,
                    data_profile=data_profile,
                    t0=t0,
                )
                if multi is not None:
                    return multi

        if analysis is None:
            raise QueryProcessorError(
                "无法理解您的问题。请尝试更明确的描述（如'各部门平均薪资'或'各城市销售额'）。"
            )

        # 7. SQL 生成
        try:
            sql = self._build_sql(analysis, dataset)
        except SQLGenerationError as e:
            raise QueryProcessorError(f"SQL 生成失败: {e}")

        # 8. SQL 执行
        try:
            sql_result = self.sql_executor.execute(sql, dataset.db_path)
        except SQLExecutionError as e:
            raise QueryProcessorError(f"SQL 执行失败: {e}")

        # 修复 y_field：SQL 生成的列别名（如 avg_薪资）才是真正的 row key
        # 规则引擎路径：analysis.metric='薪资' → SQL 列别名='avg_薪资'
        analysis = self._align_analysis_with_sql_result(analysis, sql_result)

        # 9. 图表配置
        chart_config = generate_chart_config(analysis, sql_result)
        chart_data = make_chart_data_payload(chart_config)

        # 10. 洞察生成
        insight = generate_insight(
            question=question,
            analysis=analysis,
            sql_result=sql_result,
            data_profile=data_profile,
            use_llm=self.llm_client.is_configured(),
        )

        # 11. 写回缓存
        self.cache.store(
            question=question,
            dataset_id=dataset_id,
            sql=sql,
            result=sql_result,
            chart_config=chart_config,
            insight=insight,
        )

        # 12. 写查询历史
        self._save_query_history(
            dataset_id=dataset_id,
            question=question,
            sql=sql,
            sql_result=sql_result,
            chart_config=chart_config,
            cached=False,
            response_time_ms=int((time.time() - t0) * 1000),
        )

        # 13. 构建响应
        return self._build_response(
            question=question,
            dataset=dataset,
            sql=sql,
            data=sql_result,
            chart_config=chart_config,
            chart_data=chart_data,
            insight=insight,
            analysis=analysis,
            cached=False,
            cache_level="miss",
            t0=t0,
        )

    # ===== Layer 3：单句多问题检测（启发式，主动拆解） =====
    @staticmethod
    def _is_multi_question(question: str) -> bool:
        """检测用户单句问题中是否包含多个独立子问题

        触发信号（任一即视为多问题）：
        1) 多个问号（"？"/"?"，连续出现 2+）
        2) 明确分点词："分别是" / "分别是多少" / "分别有多少"
        3) 并列+对比模式："X 和 Y 分别" / "X 跟 Y 各" / "X 与 Y 对比"
        4) 多实体并列 + 求值动词："X 和 Y 的（销量/销售额/数量）"
        5) 时间段并列 + 同一指标："今年和去年（销售额）对比"

        排除信号（即使有上述信号也不算多问题）：
        - 太短的问题（< 8 字，几乎不包含多问题）
        - 明显的对比单问题（"近 7 天和上个月销售额对比" 通常是一个对比查询，单 SQL 可解）

        Returns:
            True 表示应该走拆解路径
        """
        if not question:
            return False
        q = question.strip()
        if len(q) < 4:
            return False

        # 0) 负面信号：单纯对比查询（"X 和 Y 的 [求值] 对比"）→ 单 SQL 可解
        # 例外：仍带"分别/各" → 多问题
        is_pure_compare = bool(
            re.search(
                r"(?:和|跟|与|及)[\s\S]*?(?:对比|比较|比一下|对比一下)",
                q,
            )
        )
        # 时间段并列 + 同一求值（无"分别/各"）→ 也是单对比（如"近 7 天和上个月销售额"）
        if not re.search(r"分别|各是|各|分别是", q):
            time_compare = bool(
                re.search(
                    r"(?:近\s*\d+\s*[天周月年]|今年|去年|前年|本季|上季|上个月|上季度|本月|上月|本周|上周)"
                    r"(?:和|跟|与|及)"
                    r"(?:近\s*\d+\s*[天周月年]|今年|去年|前年|本季|上季|上个月|上季度|本月|上月|本周|上周)",
                    q,
                )
            )
            if time_compare and not re.search(r"对比|比较", q):
                # 时间段对比 + 无分别/对比词 → 单 SQL 即可
                is_pure_compare = True
        if is_pure_compare and not re.search(r"分别|各是|各|分别是", q):
            return False  # 显式短路：单纯对比

        score = 0

        # 1) 多个问号
        question_marks = len(re.findall(r"[？\?]", q))
        if question_marks >= 2:
            score += 3
        elif question_marks == 1 and re.search(r"[；;，,、][^？\?]*[？\?]", q):
            # 一个问号但前面有分号/逗号/顿号（"X；Y？" 或 "X，Y？"）→ 仍是多问题
            score += 3

        # 2) 明确分点词（"分别" / "各" 等单字也算）
        if re.search(r"分别是|分别多少|分别有|各是|各有多少|分别列|分别看|分别(?:$|（|，)", q):
            score += 3
        # 单独的 "分别" 出现在求值动词前/后
        elif re.search(r"分别", q) and re.search(r"是|多少|有|列|看|查|对比", q):
            score += 3
        # 单独的 "各"（"各部门销售额" 不会触发，因"各"在名词前不是"各是多少"）
        elif re.search(r"各是|各有多少|各(多少|是几|是哪个|表现如何)", q):
            score += 3

        # 3) "X 和/跟/与 Y + 求值动词" → 多实体
        # 例：上海和北京的销量 / 苹果跟华为的销售额
        # 注：去掉 "对比/比较" 避免单对比查询误触发
        if re.search(
            r"([一-鿿\w]{2,8})[\s]*(?:和|跟|与|及|、)[\s]*([一-鿿\w]{2,8})[\s]*(?:的)?[\s]*(销量|销售额|数量|总数|金额|利润|增长率|增长|排名|表现|趋势|占比|分布)",
            q,
        ):
            score += 3  # 直接给 3 分（不再 +2，避免边界 case 漏判）

        # 4) 时间段并列 + 同一指标（不是单纯对比）
        if re.search(
            r"(今年|去年|前年|本季|上季|上个月|上季度|本月|上月|本周|上周|近\s*\d+\s*[天周月年])(?:和|跟|与|及)(今年|去年|前年|本季|上季|上个月|上季度|本月|上月|本周|上周|近\s*\d+\s*[天周月年])",
            q,
        ) and re.search(r"分别|各是|各|分别是|分别是多少", q):
            score += 3

        # 5) "对比/比一下" 但带"分别" → 多
        if re.search(r"(对比|比一下|比较|对比一下)", q) and re.search(r"分别|各是|各|分别是", q):
            score += 2

        # 6) "和 / 跟" 后面是查询类动词（"看看 / 查查 / 查一下"）
        if re.search(
            r"([一-鿿\w]{2,15})[\s]*(?:和|跟|与)[\s]*([一-鿿\w]{2,15})[\s]*(?:的)?[\s]*(分别|各|看看|查查|查一下|显示一下|列一下|列出来|看一下)",
            q,
        ):
            score += 3

        # 7) 逗号/分号/顿号分隔的并列问句
        # "A 销量是多少，B 销量是多少" / "上海、北京、广州的销量"
        clauses = [c.strip() for c in re.split(r"[,，;；、]", q) if c.strip()]
        if len(clauses) >= 2:
            # 各分句里都有求值动词 → 多
            metric_pat = r"(?:销量|销售额|数量|总数|金额|利润|是多少|多少|几个|哪些|如何|怎么样|趋势|增长率|占比)"
            hits = sum(1 for c in clauses if re.search(metric_pat, c))
            if hits >= 2:
                score += 3
            # 顿号连接 ≥ 3 个实体 + 末尾有求值动词
            if re.search(r"、", q) and re.search(metric_pat, q) and len(re.findall(r"、", q)) >= 1:
                # 至少 2 个顿号分割
                顿号_count = len(re.findall(r"、", q))
                if 顿号_count >= 1 and len(clauses) >= 3:
                    score += 3
                elif 顿号_count >= 1 and len(clauses) >= 2:
                    score += 2

        # 8) "A 和 B 和 C" 三连并列（≥ 2 个连接词）
        if len(re.findall(r"(?:和|跟|与|及)", q)) >= 2:
            # 三连并列本身就强烈暗示多问题 → 直接 +3
            score += 3

        # 9) "A 销量；B 销量" 求值在前（更隐晦的并列）
        # 用 re.findall 看是否有 2+ 求值动词
        metric_words = re.findall(r"(?:销量|销售额|数量|总数|金额|利润|增长率|趋势|占比)", q)
        if len(metric_words) >= 2 and re.search(r"[,，;；、和跟与及]", q):
            score += 2

        # 10) 空格分隔的多实体 + 末尾求值："A B C D 四城市销售额"
        # 提取空格分隔的短词（1-6 字），看 ≥ 3 个 + 末尾求值
        space_entities = re.findall(r"[一-鿿A-Za-z]{1,6}", q)
        # 排除常见的非实体词（包括求值动词）
        stopwords = {
            "查询", "统计", "数据", "分析", "对比", "分别是", "分别", "总计", "总",
            "的", "我", "是", "有", "看", "查", "要", "把", "被", "给", "让",
            "销量", "销售额", "数量", "总数", "金额", "利润", "增长率", "趋势",
            "占比", "城市", "省份", "品牌", "产品", "渠道", "部门", "用户",
            "近", "天", "周", "月", "年", "今天", "昨天", "明天",
        }
        real_entities = [e for e in space_entities if e not in stopwords and len(e) >= 1]
        if len(real_entities) >= 3 and re.search(
            r"(?:销量|销售额|数量|总数|金额|利润|增长率|趋势|占比|城市|省份|品牌|产品|渠道)$",
            q,
        ):
            score += 3

        # 11) 顿号连接的两实体 + 求值（"A、B 销量"）— 补充规则 7
        if re.search(r"[一-鿿A-Za-z]{1,6}、[一-鿿A-Za-z]{1,6}", q) and re.search(
            r"(?:销量|销售额|数量|总数|金额|利润|增长率|趋势|占比)$", q
        ):
            # 但要排除 "X、Y 的对比/比较"
            if not re.search(r"对比|比较", q):
                score += 2

        # 阈值：>= 3 视为多问题
        return score >= 3

    # ===== Layer 2：检索与当前问题相关的规则（注入 prompt） =====
    def _retrieve_rules(
        self,
        question: str,
        dataset_id: str,
        k: int = 3,
    ) -> List[Dict[str, Any]]:
        """从 rules_store 检索与 question 相关的规则

        同时检查 dataset_id 与 'global' 两个 scope。
        返回 dict 列表（避免 detached instance），便于 JSON 序列化。

        Args:
            question: 用户自然语言问题
            dataset_id: 当前数据集 ID
            k: 每个 scope 最多取几条

        Returns:
            list of {'id', 'category', 'text', 'scope'}
        """
        if not question:
            return []
        try:
            results: List[Dict[str, Any]] = []
            seen_ids = set()
            for scope in (dataset_id, "global"):
                try:
                    rules = rules_store.retrieve_relevant_rules(
                        question, scope=scope, k=k,
                    )
                except Exception as e:
                    logger.debug(f"[QueryProcessor] 检索规则失败 (scope={scope}): {e}")
                    continue
                for r in rules:
                    if r.id in seen_ids:
                        continue
                    seen_ids.add(r.id)
                    results.append({
                        "id": r.id,
                        "category": r.category,
                        "text": r.text,
                        "scope": r.scope,
                    })
                if len(results) >= k:
                    break
            return results[:k]
        except Exception as e:
            logger.warning(f"[QueryProcessor] _retrieve_rules 异常: {e}")
            return []

    # ===== Backend Item A：追问快路径（复用上轮 analysis，跳过 LLM）=====
    def _try_follow_up_shortcircuit(
        self,
        question: str,
        dataset: Dataset,
        data_profile: str,
        conversation_history: Optional[List[Dict[str, Any]]],
        entity_memory: Optional[Dict[str, str]],
        t0: float,
    ) -> Optional[Dict[str, Any]]:
        """检测追问 → 复用上轮 analysis → 重跑 SQL → 直接返回

        Args:
            question: 用户原始问题（未被 resolve_pronoun 重写，保留给 cache/history）
            dataset: 数据集对象
            data_profile: 数据画像（用于 insight 生成）
            conversation_history: 最近 N 轮对话历史，最后一轮需含 analysis + raw_result
            entity_memory: 字段别名记忆 dict{alias: realField}
            t0: 处理起始时间戳（用于响应时间统计）

        Returns:
            命中追问时返回完整响应 dict（与正常路径一致）；未命中或异常返回 None
        """
        if not conversation_history or not isinstance(conversation_history, list):
            return None
        last_turn = conversation_history[-1] if conversation_history else None
        if not last_turn or not isinstance(last_turn, dict):
            return None
        prev_analysis = last_turn.get("analysis")
        if not prev_analysis or not isinstance(prev_analysis, dict):
            return None

        try:
            # 把 entity_memory 转成 resolve_field callable（精确 + 模糊匹配）
            resolve_field = None
            if entity_memory and isinstance(entity_memory, dict):
                em = dict(entity_memory)
                def _resolve(alias, _em=em):
                    if alias in _em:
                        return _em[alias]
                    for k, v in _em.items():
                        if alias and k and (alias in k or k in alias):
                            return v
                    return None
                resolve_field = _resolve

            # 一站式追问处理（代词解析 + 检测 + 解析）
            detect, resolved, rewritten = detect_and_resolve_follow_up(
                question,
                last_turn={
                    "id": last_turn.get("id") or "",
                    "question": last_turn.get("question") or "",
                    "analysis": prev_analysis,
                    "raw_result": last_turn.get("raw_result") or [],
                    "entities": last_turn.get("entities") or {},
                },
                resolve_field=resolve_field,
                confidence_threshold=0.5,
            )
            if not detect or not resolved:
                return None

            logger.info(
                f"[QueryProcessor] 追问快路径命中 type={detect['type']} "
                f"confidence={detect['confidence']} 原始='{question[:30]}' "
                f"重写='{rewritten[:30]}'"
            )

            # 生成 SQL（filter/timeRange 变化需重跑）
            try:
                sql = self._build_sql(resolved, dataset)
            except (SQLGenerationError, Exception) as e:
                logger.warning(f"[QueryProcessor] 追问 SQL 生成失败: {e}, 降级走 LLM")
                return None

            # 执行 SQL
            try:
                sql_result = self.sql_executor.execute(sql, dataset.db_path)
            except SQLExecutionError as e:
                logger.warning(f"[QueryProcessor] 追问 SQL 执行失败: {e}, 降级走 LLM")
                return None

            # 对齐 analysis 与 SQL 结果
            analysis = self._align_analysis_with_sql_result(resolved, sql_result)

            # 生成图表 + 洞察
            chart_config = generate_chart_config(analysis, sql_result)
            chart_data = make_chart_data_payload(chart_config)
            insight = generate_insight(
                question=question,
                analysis=analysis,
                sql_result=sql_result,
                data_profile=data_profile,
                use_llm=self.llm_client.is_configured(),
            )

            # 写缓存 + 写历史
            try:
                self.cache.store(
                    question=question,
                    dataset_id=dataset.id,
                    sql=sql,
                    result=sql_result,
                    chart_config=chart_config,
                    insight=insight,
                )
            except Exception as e:
                logger.debug(f"[QueryProcessor] 追问缓存写入失败: {e}")

            try:
                self._save_query_history(
                    dataset_id=dataset.id,
                    question=question,
                    sql=sql,
                    sql_result=sql_result,
                    chart_config=chart_config,
                    cached=False,
                    response_time_ms=int((time.time() - t0) * 1000),
                )
            except Exception as e:
                logger.debug(f"[QueryProcessor] 追问历史写入失败: {e}")

            # 标记 follow_up_type 给前端识别
            analysis_meta = dict(analysis)
            analysis_meta["_follow_up_type"] = detect["type"]
            analysis_meta["_follow_up_confidence"] = detect["confidence"]

            return self._build_response(
                question=question,
                dataset=dataset,
                sql=sql,
                data=sql_result,
                chart_config=chart_config,
                chart_data=chart_data,
                insight=insight,
                analysis=analysis_meta,
                cached=False,
                cache_level="miss",
                t0=t0,
            )
        except Exception as e:
            logger.warning(f"[QueryProcessor] 追问快路径异常: {e}")
            return None

    async def _llm_analyze(
        self,
        question: str,
        data_profile: str,
        dataset: Dataset,
        conversation_history: Optional[str] = None,
        entity_memory: Optional[Dict[str, str]] = None,
        relevant_rules: Optional[List[Dict[str, Any]]] = None,
    ) -> Optional[Dict[str, Any]]:
        """调用 LLM Function Calling 分析问题

        Args:
            question: 用户自然语言问题
            data_profile: 数据画像
            dataset: 数据集对象
            conversation_history: 对话历史（Markdown 摘要）
            entity_memory: 字段别名记忆 {alias: realField}
            relevant_rules: 相关规则列表 [{category, text}, ...]（Layer 2 注入）
        """
        if not self.llm_client.is_configured():
            return None

        try:
            result = await self.llm_client.analyze_question(
                question, data_profile,
                conversation_history=conversation_history,
                entity_memory=entity_memory,
                relevant_rules=relevant_rules,
            )
            if result is None:
                return None

            # 把 LLM 输出转换为 SQL Generator 期望的 analysis 格式
            normalized = self._normalize_llm_result(result, dataset)
            # 把 LLM 错误的 `=` 改成 `LIKE`（基于原问题的"包含/有/姓/中/里"模式）
            normalized = self._fix_filter_op_for_substring(question, normalized)
            # P1-A：字段 fuzzy 校验（修正 dimension / metric / filters.field 等）
            from core.field_resolver import resolve_analysis_fields
            corrected, unresolved = resolve_analysis_fields(
                normalized, dataset.get_columns(), entity_memory,
            )
            if unresolved:
                logger.warning(
                    f"[QueryProcessor] LLM 输出字段无法解析: {unresolved}"
                )
            # Layer 4：把命中的规则记录 hit_count
            if relevant_rules and corrected:
                for r in relevant_rules:
                    rid = r.get("id")
                    if rid:
                        try:
                            rules_store.record_hit(rid)
                        except Exception:
                            pass
            return corrected
        except Exception as e:
            logger.warning(f"[QueryProcessor] LLM 分析失败: {e}")
            return None

    # ===== P1-E：LLM 兜底分类（规则引擎无法识别时再尝试一次）=====
    async def _llm_fallback_classify(
        self,
        question: str,
        data_profile: str,
        dataset: Dataset,
        entity_memory: Optional[Dict[str, str]] = None,
        relevant_rules: Optional[List[Dict[str, Any]]] = None,
    ) -> Optional[Dict[str, Any]]:
        """P1-E：当 LLM Function Calling 和规则引擎都无法识别问题时，用 minimal prompt 再试一次

        Args:
            question: 用户问题
            data_profile: 数据画像
            dataset: 数据集实例
            entity_memory: 字段别名记忆
            relevant_rules: 相关规则列表（Layer 2）

        Returns:
            analysis dict（与 SQLGenerator.generate() 输入一致），失败返回 None
        """
        try:
            # 用更简洁的 prompt + 字段提示，节省 token
            from llm.prompts import SYSTEM_PROMPT_SQL
            columns = dataset.get_columns()
            field_info = dataset.get_field_info()
            type_parts = []
            for f in field_info[:10]:
                t = f.get("type", "text")
                type_parts.append(f"{f['name']}({t})")
            # Layer 2：把规则拼到 hint 里
            rules_block = ""
            if relevant_rules:
                rule_lines = [
                    f"- [{r.get('category', 'other')}] {r.get('text', '').strip()}"
                    for r in relevant_rules
                    if r.get("text")
                ]
                if rule_lines:
                    rules_block = (
                        "\n\n## 用户自定义业务规则（必须遵守）\n"
                        + "以下规则由用户显式声明，**任何情况下都必须遵守**：\n"
                        + "\n".join(rule_lines)
                    )
            minimal_hint = (
                f"可选字段（限使用）：{', '.join(columns)}\n"
                f"字段类型：{', '.join(type_parts)}"
                + rules_block
            )
            messages = [
                {"role": "system", "content": SYSTEM_PROMPT_SQL + "\n\n请尽量返回一个合理的 analysis，即使不完美。"},
                {"role": "user", "content": minimal_hint + "\n\n用户问题：" + question},
            ]
            # 直接调 _call_with_retry 拿到原始 arguments
            result = await self.llm_client._call_with_retry(
                messages=messages,
                functions=[EXECUTE_DATA_QUERY_FUNCTION],
                function_call={"name": "execute_data_query"},
            )
            if result is None:
                return None
            normalized = self._normalize_llm_result(result, dataset)
            normalized = self._fix_filter_op_for_substring(question, normalized)
            from core.field_resolver import resolve_analysis_fields
            corrected, unresolved = resolve_analysis_fields(
                normalized, columns, entity_memory,
            )
            if unresolved:
                logger.warning(
                    f"[QueryProcessor] LLM 兜底字段无法解析: {unresolved}"
                )
            # Layer 4：记录命中
            if relevant_rules and corrected:
                for r in relevant_rules:
                    rid = r.get("id")
                    if rid:
                        try:
                            rules_store.record_hit(rid)
                        except Exception:
                            pass
            return corrected
        except Exception as e:
            logger.warning(f"[QueryProcessor] LLM 兜底分类失败: {e}")
            return None

    # ===== Layer 3：复杂问题拆解（CoT-light） =====
    async def _decompose_and_execute(
        self,
        question: str,
        dataset: Dataset,
        dataset_id: str,
        entity_memory: Optional[Dict[str, str]] = None,
        data_profile: str = "",
        t0: float = 0.0,
    ) -> Optional[Dict[str, Any]]:
        """Layer 3：当所有兜底都失败时，尝试用 LLM 把复杂问题拆成多个子问题，
        每个子问题独立运行分析流程，最后合并结果返回。

        Args:
            question: 用户原始问题
            dataset: 数据集实例
            dataset_id: 数据集 ID
            entity_memory: 字段别名记忆
            data_profile: 数据画像
            t0: 起始时间戳

        Returns:
            合并后的响应 dict（与正常路径一致），失败返回 None
        """
        if not self.llm_client.is_configured():
            return None

        # 1) 让 LLM 拆解
        sub_questions = await self._decompose_question(question, data_profile)
        if not sub_questions or len(sub_questions) < 2:
            return None
        logger.info(
            f"[QueryProcessor] 拆解为 {len(sub_questions)} 个子问题: {sub_questions}"
        )

        # 2) 依次执行每个子问题（顺序，避免并发对 LLM 配额冲击）
        # Layer 3.2 优化：去重 + 用语义缓存避免重复执行
        from cache.semantic_cache import get_semantic_cache
        cache = get_semantic_cache()
        sub_results: List[Dict[str, Any]] = []
        seen_questions: Set[str] = set()

        for sq in sub_questions[:3]:  # 最多 3 个子问题
            # 规范化做去重
            sq_key = re.sub(r"\s+", "", sq).lower()
            if sq_key in seen_questions:
                logger.debug(f"[QueryProcessor] 跳过重复子问题: {sq[:30]}")
                continue
            seen_questions.add(sq_key)
            try:
                # 先查语义缓存
                cached = cache.lookup(sq, dataset_id)
                if cached is not None:
                    logger.info(f"[QueryProcessor] 子问题命中缓存: {sq[:30]}")
                    # 构造 sub_resp 形态
                    sub_resp = {
                        "question": sq,
                        "sql": cached.get("sql", ""),
                        "data": cached.get("data", {}),
                        "chart_config": cached.get("chart_config"),
                        "insight": cached.get("insight", ""),
                    }
                    sub_results.append(sub_resp)
                    continue
                # 否则走完整流程
                sub_resp = await self.process(
                    question=sq,
                    dataset_id=dataset_id,
                    conversation_history=None,
                    entity_memory=entity_memory,
                )
                if sub_resp and sub_resp.get("data"):
                    sub_results.append(sub_resp)
            except Exception as e:
                logger.warning(f"[QueryProcessor] 子问题执行失败 '{sq[:30]}': {e}")
                continue

        if not sub_results:
            return None

        # 3) 合并结果
        return self._merge_sub_results(question, sub_results, dataset, t0)

    async def _decompose_question(
        self,
        question: str,
        data_profile: str,
    ) -> List[str]:
        """让 LLM 把复杂问题拆成 2-3 个独立子问题（Layer 3.2 优化）

        优化点：
        - 更严格的反重复规则（明确"每个子问题互不重复"）
        - 输出格式更明确（加 JSON 示例）
        - 解析时去重 + 规范化

        Returns:
            子问题列表；失败或不可拆解返回 []
        """
        try:
            from llm.prompts import SYSTEM_PROMPT_SQL
            system = (
                "你是一个数据分析问题拆解助手，专门把用户的多问题拆成 2-3 个独立子问题。\n\n"
                '## 何时需要拆解\n'
                '用户单条消息里包含多个独立分析诉求，例如：\n'
                '- 多个实体并列（"上海和北京的销量" → "上海销量" + "北京销量"）\n'
                '- 多个时间维度并列（"今年和去年销售额" → "今年销售额" + "去年销售额"）\n'
                '- 多个分点问句（"X 是多少？Y 怎么样？" → "X 是多少" + "Y 怎么样"）\n\n'
                '## 何时不要拆解（直接返回原问题）\n'
                '- 单纯对比查询（"X 和 Y 的对比"）：单 SQL 即可，不拆\n'
                '- 单维度问题（"各部门销售额"）\n'
                '- 排行/TopN 问题（"前 5 名"）\n\n'
                '## 输出格式（严格）\n'
                '可拆解时：每行一个子问题，2-3 行，不要编号、不要解释、不要空行、不要 Markdown。\n'
                '不可拆解时：仅返回原问题一行。\n\n'
                '## 示例\n'
                '输入：今年和去年的销售额对比\n'
                '输出：\n今年总销售额\n去年总销售额\n\n'
                '输入：苹果、华为、小米的销量和增长率\n'
                '输出：\n苹果的销量\n华为的销量\n小米的销量\n\n'
                '输入：各部门销售额\n'
                '输出：各部门销售额'
            )
            user = f"数据画像：\n{data_profile[:500]}\n\n用户问题：{question}"
            messages = [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ]
            content = await self.llm_client._chat_with_retry(
                messages=messages,
            )
            if not content:
                return []
            # 解析：每行一个子问题
            lines = [ln.strip() for ln in content.splitlines() if ln.strip()]
            subs = []
            seen = set()
            for ln in lines:
                # 去掉编号前缀
                ln_clean = re.sub(r"^[\d]+[\.\)、\s]+", "", ln)
                ln_clean = ln_clean.lstrip("-•·").strip()
                # 长度校验 + 排除明显解释性文字
                if not (4 <= len(ln_clean) <= 80):
                    continue
                if "：" in ln_clean or ":" in ln_clean:
                    continue
                if re.search(r"^(注|例如|解释|说明|分析)", ln_clean):
                    continue
                # 规范化去重
                key = re.sub(r"\s+", "", ln_clean).lower()
                if key in seen:
                    continue
                seen.add(key)
                subs.append(ln_clean)
            # 拆解失败：只返回 1 行（不可拆）或 0 行 → 视作不可拆
            if len(subs) <= 1:
                return []
            return subs[:3]
        except Exception as e:
            logger.warning(f"[QueryProcessor] _decompose_question 失败: {e}")
            return []

    def _merge_sub_results(
        self,
        question: str,
        sub_results: List[Dict[str, Any]],
        dataset: Dataset,
        t0: float,
    ) -> Dict[str, Any]:
        """合并多个子问题结果为一个响应（Layer 3.2 优化）

        优化点：
        - 智能图表选择：子问题都返回单行数值 → 横向 bar；否则沿用第一个子问题图表
        - 标量子问题（每个 1 行）→ 合并成 number card
        - 洞察拼接 + 提炼（"X、Y、Z 中最高是 A"）
        """
        n = len(sub_results)
        first = sub_results[0]

        # 1) 智能判定：是否所有子问题都是单行数值（标量查询）？
        all_scalar = all(
            (sr.get("data", {}).get("row_count") or 0) == 1
            for sr in sub_results
        )
        # 所有子问题都 ≤ 2 行 → 横向 bar 适合做对比
        all_small = all(
            (sr.get("data", {}).get("row_count") or 0) <= 2
            for sr in sub_results
        )

        # 2) 合并数据
        merged_rows = []
        # 用第一个子问题的列名作为基准
        first_cols = first.get("data", {}).get("columns") or []
        merged_columns = ["子问题"] + first_cols

        for i, sr in enumerate(sub_results, 1):
            sub_label = sr.get("question", f"子问题{i}")
            cols = sr.get("data", {}).get("columns") or []
            for row in sr.get("data", {}).get("rows", []):
                if isinstance(row, dict):
                    merged_row = {"子问题": sub_label}
                    for c in merged_columns[1:]:
                        merged_row[c] = row.get(c)
                    merged_rows.append(merged_row)
                else:
                    merged_row = {"子问题": sub_label}
                    for c, v in zip(merged_columns[1:], row):
                        merged_row[c] = v
                    merged_rows.append(merged_row)

        merged_data = {
            "columns": merged_columns,
            "rows": merged_rows,
            "row_count": len(merged_rows),
        }

        # 3) 智能图表选择（按优先级）
        chart_config = first.get("chart_config")
        chart_data = first.get("chart_data")

        if n >= 5:
            # 太多子问题 → 强制用 table（避免柱状图太挤）
            chart_config = {"type": "table"}
            chart_data = None
        elif all_scalar and n >= 2:
            # 标量比较 → 横向 bar（子问题为 y 轴，数值列为 x 轴）
            # 找出第一个数值列
            value_col = None
            for c in first_cols:
                # 启发：含 "sum_" / "avg_" / "count_" / "数量" / "总额" / "总数" / "率"
                if re.search(r"sum_|avg_|count_|数量|总额|总数|率$|金额$|销量$|销售额$", c):
                    value_col = c
                    break
            if value_col is None and first_cols:
                # 退化：取最后一列（通常 metrics 在最后）
                value_col = first_cols[-1]
            if value_col:
                # 提取 label + value
                bar_rows = []
                for sr in sub_results:
                    label = sr.get("question", "")
                    sr_cols = sr.get("data", {}).get("columns") or []
                    sr_rows = sr.get("data", {}).get("rows", [])
                    # 用同样的启发找 value_col
                    val = None
                    if sr_rows:
                        row = sr_rows[0]
                        if isinstance(row, dict):
                            for c in sr_cols:
                                if re.search(r"sum_|avg_|count_|数量|总额|总数|率$|金额$|销量$|销售额$", c):
                                    val = row.get(c)
                                    break
                            if val is None and sr_cols:
                                val = row.get(sr_cols[-1])
                    if val is not None:
                        bar_rows.append({"label": label, "value": val})
                if bar_rows:
                    chart_config = {
                        "type": "bar",
                        "x_field": "value",
                        "y_field": "label",
                        "orientation": "horizontal",
                        "title": f"对比：{' / '.join(sr.get('question', '') for sr in sub_results)[:60]}",
                    }
                    chart_data = {
                        "type": "bar",
                        "labels": [r["label"] for r in bar_rows],
                        "values": [r["value"] for r in bar_rows],
                    }
        # else: 2-4 个子问题 + 混合数据 → 沿用第一个（保持简洁）

        # 4) 洞察拼接 + 提炼
        insights = []
        for i, sr in enumerate(sub_results, 1):
            ins = (sr.get("insight") or "").strip()
            if ins:
                insights.append(f"**【{i}】{sr.get('question', '')}**\n{ins}")

        # 提炼：标量场景下追加对比总结
        if all_scalar and len(sub_results) >= 2:
            vals = []
            for sr in sub_results:
                sr_rows = sr.get("data", {}).get("rows", [])
                if sr_rows and isinstance(sr_rows[0], dict):
                    for c in sr.get("data", {}).get("columns", []):
                        v = sr_rows[0].get(c)
                        if isinstance(v, (int, float)):
                            vals.append((sr.get("question", ""), v, c))
                            break
            if len(vals) >= 2:
                vals_sorted = sorted(vals, key=lambda x: x[1], reverse=True)
                top, top_v, top_c = vals_sorted[0]
                bot, bot_v, bot_c = vals_sorted[-1]
                summary = f"\n\n**对比总结**：{top_v}（{top}）> {bot_v}（{bot}）"
                insights.append(summary)

        merged_insight = "\n\n".join(insights) if insights else "已拆解为多个子问题并分别查询。"

        return self._build_response(
            question=question,
            dataset=dataset,
            sql=";\n".join(
                (r.get("sql") or "").strip() for r in sub_results if r.get("sql")
            ),
            data=merged_data,
            chart_config=chart_config,
            chart_data=chart_data,
            insight=merged_insight,
            analysis={
                "intent": "multi_decompose",
                "dimensions": [r.get("question") for r in sub_results],
                "sub_questions": [r.get("question") for r in sub_results],
                "merged_chart_type": chart_config.get("type") if chart_config else None,
            },
            cached=False,
            cache_level="miss",
            t0=t0,
        )

    # ===== 姓名模糊查询修复：把 LLM 错误的 `=` 改成 `LIKE` =====
    @staticmethod
    def _fix_filter_op_for_substring(
        question: str,
        analysis: Dict[str, Any],
    ) -> Dict[str, Any]:
        """根据原问题的中文模式修正 LLM 输出的 filter op

        触发模式（任一即视为子串匹配意图）：
        - "X 包含 Y" / "X 含 Y" / "X 有 Y"
        - "X 中 Y" / "X 里 Y" / "X 中有 Y" / "X 里有 Y"
        - "姓 X" / "姓是 X" / "名字含 X" / "名字是 X"

        修正：filter.op = "=" → "LIKE"（仅作用于字符串字段）
        """
        if not question or not analysis:
            return analysis
        q = question.strip()

        # 触发模式：包含 / 含 / 有 / 中 / 里 / 姓 X（X 是 1-2 字姓氏）
        # 注意：要排除"姓名是 X"这种 = 完全匹配的情况
        # 用每字符 lookahead 防止 是/叫/被 吞进姓氏段内
        surname_intent = bool(
            re.search(r"(?<![一-龥])姓\s*[一-龥](?!是|叫|为)(?:\s*[一-龥](?!是|叫|为))?", q)
        )
        has_substring_intent = bool(
            re.search(r"包含|含(?![有量])|有|中(?![国间均])|里", q)
        ) or surname_intent

        if not has_substring_intent:
            return analysis

        # 修正 filters
        filters = analysis.get("filters") or []
        if not filters:
            return analysis

        modified = False
        for f in filters:
            if not isinstance(f, dict):
                continue
            op = f.get("op", "=")
            value = f.get("value")
            field = f.get("field", "")
            # 只在 op = "=" 时修正，且 value 必须是字符串（不能转 LIKE 数字）
            if op == "=" and isinstance(value, str) and value:
                # 数字字符串（如"3"）不当 LIKE 处理
                if value.replace(".", "").replace("-", "").isdigit():
                    continue
                # 修正为 LIKE
                f["op"] = "LIKE"
                modified = True
                logger.info(
                    f"[QueryProcessor] 修正 filter op: {field} {op} '{value}' → "
                    f"LIKE '%{value}%' (question='{q[:30]}')"
                )
            elif op == "=" and value is not None and not isinstance(value, str):
                # 数字/布尔：保持 =（不当 LIKE）
                pass

        if modified:
            analysis["filters"] = filters
        return analysis

    def _align_analysis_with_sql_result(
        self,
        analysis: Dict[str, Any],
        sql_result: Dict[str, Any],
    ) -> Dict[str, Any]:
        """修正 analysis 中的 y_field 与 SQL 实际列名对齐

        规则引擎路径：analysis.metric='薪资' + aggregation='avg'
                     → SQL 生成列别名='avg_薪资'
                     → 但 analysis.y_field 仍是 '薪资'（找不到 row key）

        修复策略：如果 sql_result.columns 包含 metric + aggregation 组合的列名，
        更新 y_field；如果包含 COUNT(*) 别名（数量），更新为 '数量'。
        """
        columns = sql_result.get("columns", [])
        if not columns:
            return analysis

        metric = analysis.get("metric")
        aggregation = analysis.get("aggregation", "sum")

        # 候选 y_field 值
        candidates = []
        if metric and aggregation in ("sum", "avg", "max", "min", "count"):
            candidates.append(f"{aggregation}_{metric}")
        if aggregation == "count" and not metric:
            candidates.append("数量")
            dim = analysis.get("dimension")
            if dim:
                candidates.append(f"{dim}_数量")

        # 找到第一个匹配的列名
        for c in candidates:
            if c in columns:
                analysis["y_field"] = c
                break

        return analysis

    def _normalize_llm_result(
        self,
        llm_result: Dict[str, Any],
        dataset: Dataset,
    ) -> Dict[str, Any]:
        """把 LLM Function Calling 输出转换为 SQL Generator 期望的 analysis dict

        LLM 输出格式（function_schema）：
            {sql, chart_type, insight, x_field, y_field, aggregation, intent, filters, sort_order, limit}

        SQL Generator 期望格式：
            {dimension, metric, aggregation, is_scalar, filters, sort_order, limit, intent, chart_type, ...}
        """
        # 字段映射：x_field → dimension, y_field → metric
        dimension = llm_result.get("x_field")
        metric = llm_result.get("y_field")
        intent = llm_result.get("intent", "summary")
        aggregation = llm_result.get("aggregation") or "sum"
        chart_type = llm_result.get("chart_type") or "bar"
        filters = llm_result.get("filters") or []
        sort_order = llm_result.get("sort_order") or "desc"
        limit = llm_result.get("limit") or 10

        # is_scalar 判断：无 dimension 即为标量
        is_scalar = dimension is None

        # 兼容字段（chartConfig 与 chart_type 两种命名）
        return {
            "dimension": dimension,
            "metric": metric,
            "secondary_metric": None,
            "aggregation": aggregation,
            "is_scalar": is_scalar,
            "is_having_cond": False,
            "filters": filters,
            "having_cond": None,
            "sort_order": sort_order,
            "limit": limit,
            "ratio_column": None,
            "ratio_value": None,
            "intent": intent,
            "chart_type": chart_type,
            # 保留原始 SQL 字段（供 _build_sql 使用）
            "_llm_sql": llm_result.get("sql"),
            "_llm_insight": llm_result.get("insight"),
        }

    def _build_sql(self, analysis: Dict[str, Any], dataset: Dataset) -> str:
        """生成 SQL 字符串（优先使用 LLM 直接输出的 SQL，回退到 SQL Generator）

        Args:
            analysis: _normalize_llm_result 或 rule_classify 输出
            dataset: 数据集实例

        Returns:
            SQL 字符串
        """
        # 路径 A：LLM 直接输出了 SQL（Function Calling 模式）
        llm_sql = analysis.get("_llm_sql")
        if llm_sql:
            try:
                return validate_llm_sql(llm_sql, dataset)
            except (SQLGenerationError, Exception) as e:
                logger.warning(f"[QueryProcessor] LLM SQL 校验失败: {e}，回退到 SQL Generator")

        # 路径 B：从 analysis dict 生成 SQL
        return generate_sql(analysis, dataset)

    def _build_response(
        self,
        question: str,
        dataset: Dataset,
        sql: str,
        data: Dict[str, Any],
        chart_config: Optional[Dict[str, Any]] = None,
        chart_data: Optional[Dict[str, Any]] = None,
        insight: Optional[str] = None,
        analysis: Optional[Dict[str, Any]] = None,
        cached: bool = False,
        cache_level: str = "miss",
        t0: float = 0.0,
    ) -> Dict[str, Any]:
        """构建前端期望的 JSON 响应"""
        if chart_data is None and chart_config is not None:
            chart_data = make_chart_data_payload(chart_config)

        response = {
            "query_id": f"q-{uuid.uuid4().hex[:12]}",
            "dataset_id": dataset.id,
            "question": question,
            "sql": sql,
            "data": data,
            "chart_config": chart_config,
            "chart_data": chart_data,
            "insight": insight or "",
            "cached": cached,
            "cache_level": cache_level,
            "response_time_ms": int((time.time() - t0) * 1000),
            "analysis": analysis,
            "llm_tokens_used": None,
        }
        return response

    def _save_query_history(
        self,
        dataset_id: str,
        question: str,
        sql: str,
        sql_result: Dict[str, Any],
        chart_config: Optional[Dict[str, Any]],
        cached: bool,
        response_time_ms: int,
    ) -> None:
        """写查询历史"""
        try:
            import json
            with db_session_scope() as session:
                entry = QueryHistory(
                    dataset_id=dataset_id,
                    question=question,
                    sql_text=sql,
                    result_json=json.dumps(sql_result, ensure_ascii=False),
                    chart_config_json=json.dumps(chart_config, ensure_ascii=False) if chart_config else None,
                    cached=cached,
                    response_time_ms=response_time_ms,
                )
                session.add(entry)
        except Exception as e:
            logger.warning(f"[QueryProcessor] 保存查询历史失败: {e}")


# ===== 同步入口（Flask 路由用） =====
_processor_instance: Optional[QueryProcessor] = None


def get_query_processor() -> QueryProcessor:
    """获取 QueryProcessor 单例"""
    global _processor_instance
    if _processor_instance is None:
        _processor_instance = QueryProcessor()
    return _processor_instance


def process_sync(
    question: str,
    dataset_id: str,
    conversation_history: Optional[List[Dict[str, Any]]] = None,
    entity_memory: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """同步入口（Flask 路由调用）

    Args:
        question: 用户问题
        dataset_id: 数据集 ID
        conversation_history: 对话历史 list（透传给 LLM）
        entity_memory: 字段别名记忆 dict（透传给 LLM）

    Returns:
        API 响应 dict
    """
    processor = get_query_processor()
    return asyncio.run(processor.process(
        question, dataset_id,
        conversation_history=conversation_history,
        entity_memory=entity_memory,
    ))


# ===== 模块暴露 =====
__all__ = [
    "QueryProcessor",
    "QueryProcessorError",
    "get_query_processor",
    "process_sync",
]