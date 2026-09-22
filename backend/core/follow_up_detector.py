"""
follow_up_detector.py — 追问检测与解析（前端逻辑后端化）

设计目标：
- 命中追问时跳过 LLM analyze_question，节省 1-2s + 一次计费
- 代词解析（"那个最高的明细"）进入 LLM 前重写，提高准确率 + 省 token

对应前端：detectFollowUpType / resolveFollowUp / resolvePronoun / computeOverlap
（index.html 3407-3731）
"""
from __future__ import annotations

import re
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ===== 工具：n-gram Jaccard 相似度 =====
def compute_overlap(a: Optional[str], b: Optional[str]) -> float:
    """2-字符 n-gram 的 Jaccard 相似度（衡量两段文本的字符重叠程度）

    Returns:
        0.0-1.0 之间的浮点数；任意输入为空时返回 0
    """
    try:
        if not a or not b:
            return 0.0
        sa = str(a)
        sb = str(b)
        if not sa or not sb:
            return 0.0
        n = 2
        grams_a = {sa[i:i + n] for i in range(len(sa) - n + 1)}
        grams_b = {sb[i:i + n] for i in range(len(sb) - n + 1)}
        if not grams_a or not grams_b:
            return 0.0
        common = len(grams_a & grams_b)
        union = len(grams_a | grams_b)
        return common / union if union > 0 else 0.0
    except Exception as e:
        logger.debug(f"[compute_overlap] 异常: {e}")
        return 0.0


# ===== 代词解析 =====
def resolve_pronoun(text: str, last_turn: Optional[Dict[str, Any]]) -> str:
    """"那个最高的明细" / "这个产品再看下" / "它的趋势" → 上轮 top 实体

    Args:
        text: 用户输入的原始问句
        last_turn: {analysis: {dimension, ...}, raw_result: [{dim: val, ...}, ...]}

    Returns:
        重写后的问句（无法解析时返回原 text）
    """
    if not text or not last_turn:
        return text or ""

    t = str(text).strip()
    prev = last_turn.get("analysis") or {}
    raw = last_turn.get("raw_result") or prev.get("raw_result") or []
    dim = prev.get("dimension")

    if not dim or not raw:
        return t

    try:
        top_entity = raw[0].get(dim)
    except (AttributeError, IndexError):
        return t

    if top_entity is None:
        return t

    top_entity = str(top_entity)

    # 实体已在问句中，无需替换
    if top_entity in t:
        return t

    orig = t

    # 模式 1："那个 X / 这个 X" → "topEntity X"
    t = re.sub(
        r"(那个|这个)([^的]*)",
        lambda m: top_entity + (m.group(2) or ""),
        t,
    )
    # 模式 2："它 / 它们" → "topEntity"
    t = re.sub(r"(它|它们)(?!的)", top_entity, t)
    # 模式 3："它的 / 它们的" → "topEntity 的"
    t = re.sub(r"(它|它们)的", top_entity + "的", t)
    # 模式 4："再看下 / 看看" 后跟 "它的" → 补实体
    t = re.sub(
        r"(再看下?|再看一下|看看|看)\s*它的",
        lambda m: m.group(1) + top_entity + "的",
        t,
    )

    return t if t != orig else orig


# ===== 时间相对引用解析 =====
def resolve_relative_time(text: str) -> Optional[Dict[str, Any]]:
    """把 "上周"/"本月"/"近7天" 转成 {start, end, label, days}"""
    now = datetime.now()
    try:
        if text == "上周":
            last_mon = now - timedelta(days=now.weekday() + 7)
            last_mon = last_mon.replace(hour=0, minute=0, second=0, microsecond=0)
            last_sun = last_mon + timedelta(days=6, hours=23, minutes=59, seconds=59)
            return {"start": last_mon, "end": last_sun, "label": "上周", "days": 7}
        if text in ("本周", "这周"):
            mon = now - timedelta(days=now.weekday())
            mon = mon.replace(hour=0, minute=0, second=0, microsecond=0)
            return {"start": mon, "end": now, "label": "本周", "days": 7}
        if text == "本月":
            return {
                "start": now.replace(day=1, hour=0, minute=0, second=0, microsecond=0),
                "end": now,
                "label": "本月",
                "days": 30,
            }
        if text == "上月":
            first_this_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            last_month_end = first_this_month - timedelta(seconds=1)
            last_month_start = last_month_end.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            return {"start": last_month_start, "end": last_month_end, "label": "上月", "days": 30}
        if text in ("今年", "本年"):
            return {
                "start": now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0),
                "end": now,
                "label": "今年",
                "days": 365,
            }
        if text == "去年":
            last_year = now.year - 1
            return {
                "start": datetime(last_year, 1, 1),
                "end": datetime(last_year, 12, 31, 23, 59, 59),
                "label": "去年",
                "days": 365,
            }
        m = re.search(r"近\s*(\d+)\s*(天|周|月|年)", text)
        if m:
            n = int(m.group(1))
            unit = m.group(2)
            unit_days = {"天": 1, "周": 7, "月": 30, "年": 365}.get(unit, 1)
            start = now - timedelta(days=n * unit_days)
            return {"start": start, "end": now, "label": text, "days": n * unit_days}
        if text == "昨天":
            y = now - timedelta(days=1)
            return {"start": y, "end": y, "label": "昨天", "days": 1}
        if text == "今天":
            return {"start": now, "end": now, "label": "今天", "days": 1}
        return None
    except Exception as e:
        logger.debug(f"[resolve_relative_time] 异常: {e}")
        return None


# ===== 追问检测 =====
def detect_follow_up_type(text: str, ctx: Dict[str, Any]) -> Dict[str, Any]:
    """识别追问类型（9 种 + 长追问兜底）

    Args:
        text: 用户问题
        ctx: {
            last_turn: {analysis, question, raw_result, ...},
            resolve_field: callable(alias) -> real_field_name | None,
        }

    Returns:
        {type: 'reference'|'field_swap'|'chart_swap'|'axis_swap'|'time_relative'|
              'limit_swap'|'weak'|'filter_add'|'rerun'|'none',
         confidence: 0-1,
         payload: dict}
    """
    if not text or not ctx:
        return {"type": "none", "confidence": 0, "payload": {}}

    last_turn = ctx.get("last_turn") or {}
    last = last_turn.get("analysis") or {}
    if not last:
        return {"type": "none", "confidence": 0, "payload": {}}

    t = str(text).strip()
    length = len(t)

    # 1. 显式引用：它/那个/上一轮
    if re.match(r"^(它|这个|那个|上面那个|上一轮|前面的|前述|此)\s*[的呢吧？\?]?$", t):
        return {"type": "reference", "confidence": 0.95, "payload": {"ref": "previous"}}

    # 2. 字段别名
    resolve_field = ctx.get("resolve_field")
    if callable(resolve_field):
        aliased = resolve_field(t)
        if aliased and aliased != t:
            return {
                "type": "field_swap",
                "confidence": 0.85,
                "payload": {"swap_to": aliased},
            }

    # 3. 图表类型切换（必须在 axis_swap 之前）
    chart_map = {
        "柱状图": "bar", "条形": "bar",
        "折线图": "line", "面积图": "line",
        "饼图": "pie",
        "散点图": "scatter",
        "表格": "table",
        "数字": "number",
        "雷达图": "radar",
    }
    cm = re.match(r"^换成?\s*(柱状图|折线图|饼图|散点图|表格|数字|条形|面积图|雷达图)$", t)
    if cm:
        new_type = chart_map.get(cm.group(1), "bar")
        return {"type": "chart_swap", "confidence": 0.92, "payload": {"new_chart_type": new_type}}
    if re.match(r"^返回卡片", t):
        return {"type": "chart_swap", "confidence": 0.85, "payload": {"new_chart_type": "card"}}

    # 4. 维度/聚合切换
    m = re.match(r"^(按|改成|换成|切到|换作|改用)\s*(.+?)(?:呢|吧|？|\?)?$", t)
    if m:
        swap_to = m.group(2).strip()
        # 注：后端没有 parsedData.fieldInfo，swapKind 推到前端检测更准确
        # 此处先用 unknown，下游按 dimension/metric 关键字判
        swap_kind = "unknown"
        if re.match(r"^(平均|均值|总和|总计|累计|最大|最小|最高|最低|求和|求平均)$", swap_to):
            swap_kind = "aggregation"
        return {
            "type": "axis_swap",
            "confidence": 0.7,
            "payload": {"swap_to": swap_to, "swap_kind": swap_kind},
        }

    # 5. 时间相对引用
    if re.match(r"^(上|这|下|近|最近)\s*(周|月|季|年|天)\s*[的呢吧？\?]*$", t):
        return {
            "type": "time_relative",
            "confidence": 0.9,
            "payload": {"text": re.sub(r"\s*[的呢吧？\?]*$", "", t)},
        }
    if re.match(
        r"^(本周|上周|本月|上月|本季|上季|今年|去年|前年|近\s*\d+\s*(?:天|周|月|年))\s*[的吧呢]*$", t
    ):
        return {
            "type": "time_relative",
            "confidence": 0.92,
            "payload": {"text": re.sub(r"\s*[的吧呢]*$", "", t)},
        }
    if re.match(r"^(昨天|今天|明天|前天|后天|大前天)$", t):
        return {"type": "time_relative", "confidence": 0.9, "payload": {"text": t}}

    # 6. 顺序/排序/limit 切换
    if re.match(r"^(倒序|正序|从小到大|从大到小|升序|降序)$", t, re.IGNORECASE):
        sort_order = "desc" if re.search(r"倒序|从大到小|降序", t) else "asc"
        return {"type": "limit_swap", "confidence": 0.85, "payload": {"sort_order": sort_order}}
    lm = re.match(r"^(?:前|top|TOP)\s*(\d+)\s*(?:个|名|位|条|家)?\s*[的吧呢]*$", t)
    if lm:
        return {
            "type": "limit_swap",
            "confidence": 0.85,
            "payload": {"limit": int(lm.group(1))},
        }
    if re.match(r"^(只看前\s*\d+|前\s\d+个)\s*[的吧呢]*$", t):
        n_match = re.search(r"\d+", t)
        if n_match:
            return {
                "type": "limit_swap",
                "confidence": 0.8,
                "payload": {"limit": int(n_match.group(0))},
            }

    # 7a. 模糊复用（"再看看"等）：优先级高于弱追问
    if re.match(r"^(再看看|再来|再来一次|重新来|还是)$", t):
        return {"type": "weak", "confidence": 0.85, "payload": {"hint": "re_reuse"}}

    # 7b. 过滤追加（"只看 X / 只要 X / 仅 X"）
    fm = re.match(r"^(只看|只要|仅仅|仅)\s*(.+?)\s*[的吧呢]*$", t)
    if fm:
        return {
            "type": "filter_add",
            "confidence": 0.8,
            "payload": {"filter": fm.group(2).strip()},
        }

    # 7c. 重新生成（"重新分析"等）
    if re.match(r"^(重新分析|重新算|再来一遍|重跑)$", t):
        return {"type": "rerun", "confidence": 0.95, "payload": {}}

    # 8. 弱追问（兜底）：极短句 + 含上一轮字段
    if length < 12:
        last_entities = list((last_turn.get("entities") or {}).keys())
        last_dimension = last.get("dimension")
        last_metric = last.get("metric") or last.get("y_field")
        all_prev = [e for e in last_entities + [last_dimension, last_metric] if e]
        all_prev_str = [str(e) for e in all_prev]

        # 短句本身是上一轮 dimension 的值（弱引用）
        if length <= 6:
            for e in all_prev_str:
                if t == e or t == e[:2]:
                    return {
                        "type": "weak",
                        "confidence": 0.55,
                        "payload": {"fallback": "recompute", "shared_field": e},
                    }
        # 短句包含上一轮的字段名或实体别名
        for e in all_prev_str:
            slice_len = max(2, int(len(e) * 0.4))
            if e[:slice_len] in t:
                return {
                    "type": "weak",
                    "confidence": 0.5,
                    "payload": {"fallback": "recompute"},
                }
        # 短句 + 含追问词
        if re.search(r"(呢|吧|怎么样|如何|多少)$", t) or re.search(r"(看|看)?下$", t):
            return {
                "type": "weak",
                "confidence": 0.5,
                "payload": {"fallback": "recompute"},
            }

    # 9. 长追问兜底：与上轮相似度高 + 含复用词
    try:
        if length > 30:
            last_q = last_turn.get("question") or ""
            overlap = compute_overlap(t, last_q)
            if overlap > 0.3 and re.search(r"(再|还是|也|另外)", t):
                return {
                    "type": "weak",
                    "confidence": 0.7,
                    "payload": {"fallback": "long_overlap", "overlap": round(overlap, 2)},
                }
    except Exception as e:
        logger.debug(f"[detect_follow_up] 长追问兜底异常: {e}")

    return {"type": "none", "confidence": 0, "payload": {}}


# ===== 追问解析（复用上轮 analysis）=====
def resolve_follow_up(
    text: str,
    detect: Dict[str, Any],
    last_turn: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """根据追问类型生成新的 analysis dict（deep copy + 修改）

    Args:
        text: 用户问题（已 resolvePronoun 重写）
        detect: detect_follow_up_type 的输出
        last_turn: {id, analysis, ...}

    Returns:
        新的 analysis dict（含 follow_up_type / resolved_from 标记），失败返回 None
    """
    if not detect or detect.get("type") == "none" or not last_turn:
        return None
    prev = last_turn.get("analysis") or {}
    if not prev:
        return None
    last_id = last_turn.get("id") or ""

    try:
        dtype = detect["type"]
        payload = detect.get("payload") or {}

        if dtype in ("reference", "weak"):
            # 整体复用
            new = dict(prev)
            new["follow_up_type"] = dtype
            new["resolved_from"] = last_id
            return new

        if dtype == "field_swap":
            new = dict(prev)
            new["metric"] = payload.get("swap_to")
            new["y_field"] = payload.get("swap_to")
            new["secondary_metric"] = None
            new["follow_up_type"] = "field_swap"
            new["resolved_from"] = last_id
            return new

        if dtype == "axis_swap":
            new = dict(prev)
            new["follow_up_type"] = "axis_swap"
            new["resolved_from"] = last_id
            swap_kind = payload.get("swap_kind", "unknown")
            swap_to = payload.get("swap_to")
            if swap_kind == "dimension":
                new["dimension"] = swap_to
                new["groupBy"] = swap_to
                new["x_field"] = swap_to
            elif swap_kind == "metric":
                new["metric"] = swap_to
                new["y_field"] = swap_to
            elif swap_kind == "aggregation":
                agg_map = {
                    "平均": "avg", "均值": "avg",
                    "总和": "sum", "总计": "sum", "累计": "sum",
                    "最大": "max", "最小": "min",
                    "最高": "max", "最低": "min",
                    "求和": "sum", "求平均": "avg",
                }
                if swap_to in agg_map:
                    new["aggregation"] = agg_map[swap_to]
            else:
                new["follow_up_type"] = "weak"  # 兜底
            return new

        if dtype == "time_relative":
            tr = resolve_relative_time(payload.get("text") or text)
            if not tr:
                # 解析失败 → 弱复用
                new = dict(prev)
                new["follow_up_type"] = "weak"
                new["resolved_from"] = last_id
                return new
            new_filters = list(prev.get("filters") or [])
            new_filters.append({
                "field": "_timeRange",
                "op": "between",
                "value": [tr["start"], tr["end"]],
                "label": tr["label"],
            })
            new = dict(prev)
            new["timeRange"] = tr
            new["filters"] = new_filters
            new["follow_up_type"] = "time_relative"
            new["resolved_from"] = last_id
            return new

        if dtype == "limit_swap":
            new = dict(prev)
            new["follow_up_type"] = "limit_swap"
            new["resolved_from"] = last_id
            if payload.get("limit") is not None:
                new["limit"] = payload["limit"]
            if payload.get("sort_order"):
                new["sortOrder"] = payload["sort_order"]
                new["sort_order"] = payload["sort_order"]
            return new

        if dtype == "chart_swap":
            new_chart = payload.get("new_chart_type")
            new = dict(prev)
            new["chartType"] = new_chart
            new["chart_type"] = new_chart
            new["follow_up_type"] = "chart_swap"
            new["resolved_from"] = last_id
            return new

        if dtype == "filter_add":
            new_filters = list(prev.get("filters") or [])
            new_filters.append({
                "field": "auto",
                "op": "=",
                "value": payload.get("filter"),
                "label": payload.get("filter"),
                "_autoResolve": True,
            })
            new = dict(prev)
            new["filters"] = new_filters
            new["follow_up_type"] = "filter_add"
            new["resolved_from"] = last_id
            new["_pendingFilterValue"] = payload.get("filter")
            return new

        if dtype == "rerun":
            new = dict(prev)
            new["follow_up_type"] = "rerun"
            new["resolved_from"] = last_id
            new["_rerunRequested"] = True
            return new

        return None
    except Exception as e:
        logger.warning(f"[resolve_follow_up] 异常: {e}")
        return None


# ===== 一站式：检测 + 解析 =====
def detect_and_resolve_follow_up(
    text: str,
    last_turn: Optional[Dict[str, Any]],
    resolve_field: Optional[callable] = None,
    confidence_threshold: float = 0.5,
) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]], str]:
    """一站式追问处理（代词解析 + 检测 + 解析）

    Args:
        text: 原始问题
        last_turn: 上一轮的 {id, question, analysis, raw_result, ...}
        resolve_field: 字段别名解析 callable(alias) -> real_field
        confidence_threshold: 追问置信度阈值（默认 0.5）

    Returns:
        (detect_result, resolved_analysis, rewritten_text)
        - detect_result 为 None 表示未命中追问
        - resolved_analysis 为 None 表示命中但解析失败
        - rewritten_text 是经过 resolvePronoun 重写后的文本
    """
    if not text or not last_turn:
        return None, None, text or ""

    # Step 1：代词解析
    rewritten = resolve_pronoun(text, last_turn) or text

    # Step 2：追问检测
    ctx = {"last_turn": last_turn, "resolve_field": resolve_field}
    detect = detect_follow_up_type(rewritten, ctx)

    if not detect or detect["type"] == "none":
        return None, None, rewritten
    if detect["confidence"] < confidence_threshold:
        return None, None, rewritten

    # Step 3：追问解析
    resolved = resolve_follow_up(rewritten, detect, last_turn)
    return detect, resolved, rewritten


# ===== 模块暴露 =====
__all__ = [
    "compute_overlap",
    "resolve_pronoun",
    "resolve_relative_time",
    "detect_follow_up_type",
    "resolve_follow_up",
    "detect_and_resolve_follow_up",
]