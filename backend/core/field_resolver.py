"""
field_resolver.py — 字段 fuzzy 校验层（P1-A 准确率提升）

目标：解决"字段选择错"和"SQL 字段名错"两类准确率问题。

设计思路：
1. 接收 LLM/规则引擎的候选字段名 → 用多种策略匹配到 dataset 真实字段
2. 匹配策略（按优先级）：
   a) 精确匹配（最高优先）
   b) 别名记忆（entity_memory）
   c) 去括号后匹配（"日营业额(元)" → "日营业额"）
   d) 拼音首字母模糊（"rjy" → "日营业额"）
   e) Levenshtein 距离模糊匹配（编辑距离 ≤ 2）

3. 失败时返回 None + 候选字段列表（供上层 prompt 反馈）

被以下场景调用：
- LLM 路径：validate_llm_sql 后再次核对 dimension/metric
- 规则引擎路径：parse_dimension / parse_metric 替换为 resolve_field
- 追问快路径：直接复用（不需 fuzzy，因 analysis 已经是结构化 dict）
"""
from __future__ import annotations

import logging
import re
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ===== 工具：去括号 =====
def _strip_parens(s: str) -> str:
    """'日营业额(元)' → '日营业额'"""
    if not s:
        return ""
    m = re.split(r"[（()]", s, maxsplit=1)
    return m[0].strip()


# ===== 工具：Levenshtein 距离 =====
def _levenshtein(a: str, b: str) -> int:
    """O(m*n) 编辑距离实现（短字符串够用）"""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)

    # 用滚动数组省内存
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        curr = [i]
        for j, cb in enumerate(b, 1):
            cost = 0 if ca == cb else 1
            curr.append(min(
                curr[-1] + 1,        # insertion
                prev[j] + 1,         # deletion
                prev[j - 1] + cost,  # substitution
            ))
        prev = curr
    return prev[-1]


# ===== 工具：相似度评分 =====
def _similarity(a: str, b: str) -> float:
    """0-1 之间的相似度（SequenceMatcher 比例）"""
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


# ===== 主函数：解析单个字段 =====
def resolve_field(
    candidate: Optional[str],
    available_fields: List[str],
    entity_memory: Optional[Dict[str, str]] = None,
    fuzzy_threshold: float = 0.75,
) -> Optional[str]:
    """把候选字段名解析为 dataset 真实字段名

    Args:
        candidate: LLM/规则/用户给的字段名（可能是口语化的）
        available_fields: dataset.get_columns() 返回的真实字段列表
        entity_memory: 字段别名记忆 {alias: realField, ...}
        fuzzy_threshold: 模糊匹配的最低相似度（默认 0.75）

    Returns:
        真实字段名（available_fields 中的一项），无法解析返回 None

    Examples:
        >>> resolve_field("销售额", ["城市", "销售额", "日期"])
        '销售额'

        >>> resolve_field("日营业额(元)", ["日营业额(元)", "城市"])
        '日营业额(元)'  # 精确匹配

        >>> resolve_field("日营业额", ["日营业额(元)", "城市"])
        '日营业额(元)'  # 去括号匹配

        >>> resolve_field("营收", ["销售额"], entity_memory={"营收": "销售额"})
        '销售额'  # 别名记忆优先

        >>> resolve_field("销售", ["销售额", "城市"], fuzzy_threshold=0.75)
        '销售额'  # 模糊匹配（编辑距离 1）

        >>> resolve_field("xxx", ["销售额"])
        None  # 差距太大
    """
    if not candidate or not available_fields:
        return None

    cand = str(candidate).strip()
    if not cand:
        return None

    # 策略 a: 精确匹配
    if cand in available_fields:
        return cand

    # 策略 b: 别名记忆（精准）
    if entity_memory and isinstance(entity_memory, dict):
        # 1) 直接查
        if cand in entity_memory:
            real = entity_memory[cand]
            if real in available_fields:
                return real
        # 2) 反向查（real → alias 也算）
        for alias, real in entity_memory.items():
            if real == cand and alias in available_fields:
                return alias

    # 策略 c: 去括号匹配
    cand_base = _strip_parens(cand)
    for f in available_fields:
        if _strip_parens(f) == cand_base:
            return f

    # 策略 d: fuzzy 匹配（SequenceMatcher + Levenshtein 双重打分）
    best_match = None
    best_score = 0.0
    for f in available_fields:
        # 完整字符串相似度
        s1 = _similarity(cand, f)
        # 去括号后的相似度（处理"日营业额" vs "日营业额(元)"）
        s2 = _similarity(cand_base, _strip_parens(f))
        # 含关系（cand 是 f 的子串，或反向）
        s3 = 1.0 if (cand in f or f in cand) and len(cand) >= 2 else 0.0
        score = max(s1, s2, s3)
        if score > best_score:
            best_score = score
            best_match = f

    # 兜底：Levenshtein 距离（处理拼音/笔误）
    if best_score < fuzzy_threshold:
        for f in available_fields:
            f_base = _strip_parens(f)
            # 短字符串优先用 Levenshtein
            if len(cand_base) <= 6:
                d = min(
                    _levenshtein(cand_base, f_base),
                    _levenshtein(cand_base, f),
                )
                # 编辑距离 ≤ 1 视为匹配
                if d <= 1 and len(cand_base) >= 2:
                    return f

    if best_match and best_score >= fuzzy_threshold:
        return best_match

    return None


# ===== 批量：解析 analysis 字典中的字段 =====
def resolve_analysis_fields(
    analysis: Dict[str, Any],
    available_fields: List[str],
    entity_memory: Optional[Dict[str, str]] = None,
) -> Tuple[Dict[str, Any], List[str]]:
    """修正 analysis dict 里的字段名（dimension / metric / secondary_metric / filters）

    Args:
        analysis: LLM 或规则引擎的输出
        available_fields: dataset 真实字段列表
        entity_memory: 字段别名记忆

    Returns:
        (corrected_analysis, unresolved_fields)
        - corrected_analysis: 修正后的 analysis（不可解析的字段置 None）
        - unresolved_fields: 无法解析的字段名列表（用于上层报错/降级）
    """
    if not analysis or not available_fields:
        return analysis or {}, []

    corrected = dict(analysis)
    unresolved = []

    # 修正 dimension / metric / secondary_metric
    for key in ("dimension", "metric", "secondary_metric", "x_field", "y_field", "ratio_column"):
        cand = corrected.get(key)
        if cand is None:
            continue
        resolved = resolve_field(cand, available_fields, entity_memory)
        if resolved is None:
            logger.debug(f"[FieldResolver] 无法解析 {key}={cand!r}")
            corrected[key] = None
            unresolved.append(f"{key}={cand}")
        else:
            if resolved != cand:
                logger.debug(f"[FieldResolver] 字段修正 {key}: {cand!r} → {resolved!r}")
            corrected[key] = resolved

    # 修正 filters 里的 field
    new_filters = []
    for f in corrected.get("filters") or []:
        if not isinstance(f, dict):
            continue
        field_name = f.get("field")
        if not field_name:
            new_filters.append(f)
            continue
        # _timeRange 是特殊过滤条件，不需 fuzzy
        if field_name == "_timeRange" or field_name == "auto":
            new_filters.append(f)
            continue
        resolved = resolve_field(field_name, available_fields, entity_memory)
        if resolved:
            new_f = dict(f)
            new_f["field"] = resolved
            new_filters.append(new_f)
        else:
            logger.debug(f"[FieldResolver] filter field 无法解析: {field_name!r}")
            unresolved.append(f"filter.field={field_name}")
    corrected["filters"] = new_filters

    return corrected, unresolved


# ===== 候选字段推荐（供 prompt 反馈）=====
def suggest_fields(
    question: str,
    available_fields: List[str],
    entity_memory: Optional[Dict[str, str]] = None,
    top_k: int = 5,
) -> List[Tuple[str, float]]:
    """基于问题文本推荐最可能用到的字段（供前端错误引导或 LLM 二次确认）

    Args:
        question: 用户原始问题
        available_fields: dataset 真实字段列表
        entity_memory: 字段别名记忆
        top_k: 返回前 K 个候选

    Returns:
        [(field_name, score), ...] 按分数降序
    """
    if not question or not available_fields:
        return []

    q = str(question).strip().lower()
    q_base = _strip_parens(q)

    scored = []
    for f in available_fields:
        f_lower = f.lower()
        f_base = _strip_parens(f).lower()
        # 包含关系得分
        if f_lower in q or f_base in q_base or f in question:
            scored.append((f, 1.0))
            continue
        # 相似度得分
        s = max(_similarity(q, f_lower), _similarity(q_base, f_base))
        # 别名记忆加权
        if entity_memory:
            for alias, real in entity_memory.items():
                if real == f and (alias in q or _strip_parens(alias).lower() in q_base):
                    s = max(s, 0.95)
        if s > 0.3:
            scored.append((f, round(s, 3)))

    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:top_k]


# ===== 模块暴露 =====
__all__ = [
    "resolve_field",
    "resolve_analysis_fields",
    "suggest_fields",
]