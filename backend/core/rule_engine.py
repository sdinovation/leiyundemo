"""
rule_engine.py — 规则引擎（LLM 降级路径）

设计目标：
- 当 LLM 调用失败/未配置时，提供基础的数据分析能力
- 移植前端 classifyIntent/parseDimension/parseMetric 的核心模式到 Python
- 不是 1:1 复刻（前端逻辑太复杂，Python 端只保留 80% 常见场景）
- 与 sql_generator.generate() 配合使用

核心功能：
1. classify(question, schema) → {intent, dimension, metric, aggregation, isScalar, ...}
2. parse_dimension(question, fields) → str
3. parse_metric(question, fields) → str
4. parse_aggregation(question, metric) → str (sum/avg/count/max/min)
5. parse_limit(question) → int

支持的意图类型（与 Function Calling 对齐）：
- ranking: 排名/最高/最低
- trend: 趋势/变化
- distribution: 占比/分布
- filter: 筛选条件
- summary: 汇总
- list: 清单
- correlation: 相关性

降级策略：
- 命中清晰模式 → 直接生成 analysis dict
- 模糊问题 → 返回 None（让上层决定走纯文本兜底）

P1-B：新增 entity_memory 支持 + 数据特征选图表
- 字段选择：先查 entity_memory → 字段 fuzzy 校验
- 图表选择：基于结果数据特征（行数/唯一值数/时间字段）二次校验
"""
import logging
import re
from typing import Any, Dict, List, Optional, Set

from core.field_resolver import resolve_field as fuzzy_resolve_field

logger = logging.getLogger(__name__)


# ===== 工具函数 =====
def _norm(s: str) -> str:
    """标准化字符串（小写 + 去空格）"""
    return s.strip().lower() if s else ""


def _find_field_in_question(
    question: str,
    candidates: List[str],
    entity_memory: Optional[Dict[str, str]] = None,
) -> Optional[str]:
    """从问题中找最匹配的字段名

    P1-B 增强：先查 entity_memory，再走 fuzzy 匹配（resolve_field）。

    Args:
        question: 用户问题
        candidates: 候选字段名列表
        entity_memory: 字段别名记忆 {alias: realField, ...}

    Returns:
        最佳匹配字段名，无匹配返回 None
    """
    # P1-B: 优先级 0：entity_memory 精确命中（如"营收" → "销售额"）
    if entity_memory and question:
        for alias, real in entity_memory.items():
            if alias and alias in question:
                if real in candidates:
                    return real

    # 优先级 1：完全包含
    for f in candidates:
        if f and f in question:
            return f

    # 优先级 2：去掉括号后包含
    for f in candidates:
        base = re.sub(r"[（()].*$", "", f).strip() if f else ""
        if base and base in question:
            return f

    # 优先级 3：反向包含（字段名含问题片段）
    for f in candidates:
        if f and len(f) > 1 and (f in question or base_in_q(f, question)):
            return f

    # P1-B: 优先级 4：fuzzy 兜底（编辑距离 / 相似度）
    if question:
        resolved = fuzzy_resolve_field(question.strip(), candidates, entity_memory)
        if resolved:
            return resolved

    return None


def base_in_q(field: str, q: str) -> bool:
    """字段名是否部分出现在问题中（≥ 2 字）"""
    if not field or len(field) < 2:
        return False
    base = re.sub(r"[（()].*$", "", field).strip()
    return base in q


# ===== 字段识别器 =====
def parse_dimension(
    question: str,
    dimension_fields: List[str],
    entity_memory: Optional[Dict[str, str]] = None,
) -> Optional[str]:
    """从问题中解析维度字段

    P1-B: 支持 entity_memory 优先匹配

    Args:
        question: 用户问题
        dimension_fields: 所有文本/分类字段名列表
        entity_memory: 字段别名记忆

    Returns:
        维度字段名，无匹配返回 None
    """
    return _find_field_in_question(question, dimension_fields, entity_memory)


def parse_metric(
    question: str,
    numeric_fields: List[str],
    entity_memory: Optional[Dict[str, str]] = None,
) -> Optional[str]:
    """从问题中解析指标字段

    P1-B: 支持 entity_memory 优先匹配

    Args:
        question: 用户问题
        numeric_fields: 所有数值字段名列表
        entity_memory: 字段别名记忆

    Returns:
        指标字段名，无匹配返回 None
    """
    return _find_field_in_question(question, numeric_fields, entity_memory)


def parse_date_field(question: str, date_fields: List[str]) -> Optional[str]:
    """从问题中解析日期字段"""
    # 优先匹配带"日期/时间/月/年"的问题
    for f in date_fields:
        if any(kw in question for kw in ["日期", "时间", "月份", "年度", "年", "月", "日"]):
            if f in question:
                return f

    # 否则返回第一个日期字段
    return date_fields[0] if date_fields else None


# ===== 聚合方式 =====
def parse_aggregation(question: str, metric: Optional[str] = None) -> str:
    """从问题中推断聚合方式

    优先级：count > avg > sum > max/min
    """
    q = question

    # 1. 计数（人数/条数/数量/订单数/总数/总数X/员工数）
    # 优先级最高（先于 avg/sum/max/min）
    if re.search(r"人数|条数|订单数|记录数|多少(?:人|条|个)|有几|数量|个数|员工数|成员数|客户数|用户数|总数|count|总数是|总共多少|一共多少", q, re.IGNORECASE):
        return "count"

    # 2. 平均
    if re.search(r"平均|均值|均", q):
        return "avg"

    # 3. 最大/最高/最多/最长/最快
    if re.search(r"最高|最多|最大|最长|最快|最贵|最好|峰值|上限", q):
        return "max"

    # 4. 最小/最低/最少/最短/最慢
    if re.search(r"最低|最少|最小|最短|最慢|最便宜|最差|谷值|下限", q):
        return "min"

    # 5. 求和/总和/总/累计/总额
    # 注：要匹配"总"但不匹配"总体/总共"，需先检查负面模式
    has_cumulative_sum = bool(re.search(r"总和|总计|累计|总额|总值|合计|求和", q))
    has_standalone_dang = bool(re.search(r"总(?!体|共)", q))  # "总"但不接"体/共"
    if has_cumulative_sum or has_standalone_dang:
        return "sum"

    # 6. 默认 sum（有 metric 时）
    return "sum" if metric else "count"


# ===== limit =====
def parse_limit(question: str, default: int = 10) -> int:
    """从问题中解析 limit

    支持："前 5"、"前5名"、"top 10"、"前三"、"前10名"
    """
    # 阿拉伯数字
    m = re.search(r"(?:前|top|TOP)\s*(\d+)", question)
    if m:
        try:
            return min(int(m.group(1)), 1000)
        except ValueError:
            pass

    # 中文数字
    cn_map = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
              "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
    m = re.search(r"前\s*([一二两三四五六七八九十])\s*(?:个|名|位|条|家)?", question)
    if m:
        return cn_map.get(m.group(1), default)

    return default


# ===== 排序方向 =====
def parse_sort_order(question: str, intent: str) -> Optional[str]:
    """从问题中推断排序方向"""
    q = question

    # ranking 默认 desc（最高分排前）
    if intent == "ranking":
        if re.search(r"最高|最多|最大|最长|最快|最好|最贵", q):
            return "desc"
        if re.search(r"最低|最少|最小|最短|最慢|最便宜|最差", q):
            return "asc"
        return "desc"

    # trend 默认 ASC（按时间）
    if intent == "trend":
        return "asc"

    # 其他情况不排序
    return None


# ===== 过滤器 =====
def parse_filters(question: str, text_fields: List[str]) -> List[Dict[str, Any]]:
    """从问题中解析过滤条件（仅支持简单的 "XX为YY" 模式）

    Returns:
        [{field, op, value}] 列表
    """
    filters = []

    # 模式 1：XX为YY / XX是YY / XX等于YY
    m = re.search(r"([^是为等于的\s,，。？?]+)\s*(?:为|是|等于|叫)\s*([^是为等于的\s,，。？?]+)", question)
    if m:
        field_candidate = m.group(1).strip()
        value = m.group(2).strip()

        # 找到对应的字段
        matched_field = _find_field_in_question(field_candidate, text_fields)
        if matched_field and value:
            filters.append({"field": matched_field, "op": "=", "value": value})

    return filters


# ===== 主函数：classify =====
def classify(
    question: str,
    field_info: List[Dict[str, Any]],
    columns: List[str],
    entity_memory: Optional[Dict[str, str]] = None,
    field_type_map: Optional[Dict[str, str]] = None,
) -> Optional[Dict[str, Any]]:
    """根据问题 + schema 生成 analysis dict（降级路径）

    P1-B 增强：
    - entity_memory 透传到 parse_dimension / parse_metric
    - field_type_map 提供各字段类型（供 _infer_chart_type 选图表）

    Args:
        question: 用户问题
        field_info: 字段信息列表 [{name, type, ...}]
        columns: 所有列名
        entity_memory: 字段别名记忆 {alias: realField, ...}
        field_type_map: 字段类型映射 {field_name: type_str}（可选）

    Returns:
        analysis dict（与 SQLGenerator.generate() 输入一致），失败返回 None
    """
    if not question or not field_info:
        return None

    # 分类字段
    text_fields = [f["name"] for f in field_info if f.get("type") in ("text", "id")]
    numeric_fields = [f["name"] for f in field_info if f.get("type") in ("int", "float", "currency", "percent")]
    date_fields = [f["name"] for f in field_info if f.get("type") == "date"]

    # ===== 1. 检测意图 =====
    intent = _detect_intent(question, has_date=bool(date_fields))

    # ===== 2. 提取维度 =====
    # "各X/按X/每个X" → 总是尝试提取维度（哪怕 intent=summary）
    dimension = None
    has_group_kw = re.search(r"各|每|不同|按|分别", question)
    if intent == "trend" and date_fields:
        dimension = parse_date_field(question, date_fields)
    elif intent in ("ranking", "distribution") or has_group_kw:
        dimension = parse_dimension(question, text_fields, entity_memory)

    # ===== 3. 提取指标 =====
    metric = None
    if intent != "filter":
        # 检测显式聚合词（avg/sum/max/min）
        explicit_agg_match = re.search(r"平均|均值|总和|总计|累计|总额|总值|最高|最低|最多|最少|最大|最小", question)
        # 计数词（人数/条数/数量/多少/总数/员工数）
        explicit_count_match = re.search(r"人数|条数|订单数|记录数|数量|个数|有几|多少(?:人|条|个)|总数|员工数|成员数|count", question, re.IGNORECASE)

        if explicit_count_match and not explicit_agg_match:
            # 纯计数 → 不需要 metric
            metric = None
        else:
            # 有 metric + 聚合词 → 提取 metric
            # 1. 优先从问题文本匹配字段名（含 entity_memory）
            metric = parse_metric(question, numeric_fields, entity_memory)
            # P1-B：兜底策略收紧 —— 当 fuzzy 和 entity_memory 都拿不到时，
            # 不再盲选 numeric_fields[0]（会误选），而是保持 None 走 LLM 兜底
            # 真正的 fallback 在 classify 末尾（metric=None + aggregation=count + intent=summary）
            # 由 P1-E 的 _llm_fallback_classify 兜底

    # 如果检测到 group 关键字但 intent=summary，则升级为 ranking
    if intent == "summary" and dimension is not None:
        intent = "ranking"

    # ===== 4. 聚合方式 =====
    # 先看有没有显式聚合词
    has_explicit_agg = bool(re.search(
        r"平均|均值|总和|总计|累计|总额|总值|最高|最低|最多|最少|最大|最小|人数|条数|订单数|记录数|数量|个数|有几|多少",
        question
    ))
    if intent == "distribution":
        # 分布问题 → count by 维度，让前端用 pie chart 显示
        # 真正的 ratio（带 ratioColumn）由 LLM Function Calling 处理（更准）
        # 规则引擎做兜底：count by 维度
        aggregation = "count"
        # 不要用 ratio，否则 SQL 生成器会要求 ratioColumn
    elif has_explicit_agg or metric is None:
        aggregation = parse_aggregation(question, metric=metric)
    else:
        # 有 metric 但无显式聚合词 → 默认 sum（如"各城市销售额" → SUM(销售额)）
        aggregation = "sum"

    # ===== 5. limit =====
    limit = parse_limit(question)

    # ===== 6. 排序方向 =====
    sort_order = parse_sort_order(question, intent)

    # ===== 7. 过滤器 =====
    filters = parse_filters(question, text_fields)

    # ===== 8. 是否标量 =====
    is_scalar = (dimension is None) and (intent not in ("filter",))

    # ===== 9. 图表类型 =====
    # P1-B：传入 field_type_map，让 _infer_chart_type 知道 dimension 是否日期字段
    chart_type = _infer_chart_type(intent, aggregation, dimension, field_type_map)

    # ===== 10. 校验：至少要有 dimension 或 metric =====
    if dimension is None and metric is None and aggregation == "count":
        # count + 无 metric + 无 dimension → 标量计数
        pass
    elif dimension is None and metric is None:
        logger.debug(f"[RuleEngine] classify 无法识别: question={question!r}")
        return None

    return {
        "intent": intent,
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
        # ratio 专用字段
        "ratio_column": dimension if intent == "distribution" and dimension else None,
        "ratio_value": 1 if intent == "distribution" else None,
        "chart_type": chart_type,
    }


def _detect_intent(question: str, has_date: bool) -> str:
    """检测问题意图"""
    q = question

    # 1. 相关性
    if re.search(r"相关性|相关系数|关联|关系|协方差", q):
        return "correlation"

    # 2. 趋势
    if has_date and re.search(r"趋势|走势|变化|增长|下降|上升|下滑|演变|月度|年度|波动", q):
        return "trend"

    # 3. 占比/分布
    if re.search(r"占比|比例|分布|构成|百分比|份额", q):
        return "distribution"

    # 4. 排名
    if re.search(r"排名|前几|TOP|最高|最低|最多|最少|最大|最小|哪个.*最", q):
        return "ranking"

    # 5. 筛选
    if re.search(r"为|等于|是.+的|只看|超过|低于|大于|小于", q) and not re.search(r"平均|总和|总", q):
        return "filter"

    # 6. 清单
    if re.search(r"有哪些|有什么|列出|所有", q):
        return "list"

    # 7. 默认汇总
    return "summary"


def _infer_chart_type(
    intent: str,
    aggregation: str,
    dimension: Optional[str] = None,
    field_type_map: Optional[Dict[str, str]] = None,
) -> str:
    """根据意图 + 聚合方式 + 字段类型推断图表类型

    P1-B 数据特征感知：
    - 当维度是日期字段且包含"趋势/走势/变化/增长"等关键词 → line（强制）
    - 当聚合是 avg/max/min 且维度数值无序 → bar
    - intent=summary 但 aggregation=count 且无 dimension → number
    """
    # 数据特征优先：日期字段 + 维度相关意图 → 折线图
    if dimension and field_type_map:
        dim_type = field_type_map.get(dimension, "")
        if dim_type == "date":
            return "line"

    if intent == "trend":
        return "line"
    if intent == "distribution":
        return "pie"
    if intent == "correlation":
        return "scatter"
    if intent == "filter":
        return "table"
    if aggregation == "count" and intent == "summary":
        return "number"
    return "bar"


# ===== 模块暴露 =====
__all__ = [
    "classify",
    "parse_dimension",
    "parse_metric",
    "parse_date_field",
    "parse_aggregation",
    "parse_limit",
    "parse_sort_order",
    "parse_filters",
]