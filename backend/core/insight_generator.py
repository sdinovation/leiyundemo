"""
insight_generator.py — 自动洞察生成器

职责（doc05 §2）：
- 基于查询结果生成 2-4 句中文洞察
- 两种模式：
  1. 统计模式（兜底）：基于数值特征生成模板化洞察（不依赖 LLM）
  2. LLM 模式（增强）：调用 LLMClient.generate_insight() 生成更自然解读

输出形状：纯文本字符串

典型洞察模式：
- 排名类："X 最高（Y），Z 最低（W），差距 N 倍"
- 趋势类："整体上升/下降，从 X 增至 Y"
- 分布类："X 类占整体的 N%，前 3 名合计 M%"
- 标量类："总共有 N 条记录"
"""
import logging
from typing import Any, Dict, List, Optional

from llm.prompts import build_data_profile_summary
from llm.llm_client import get_llm_client

logger = logging.getLogger(__name__)


# ===== 统计模式洞察模板 =====
def _format_value(v: Any) -> str:
    """格式化数值为易读字符串"""
    if v is None:
        return "N/A"
    if isinstance(v, float):
        if abs(v) >= 1_000_000:
            return f"{v/1_000_000:.2f}M"
        if abs(v) >= 1_000:
            return f"{v/1_000:.2f}K"
        return f"{v:.2f}"
    if isinstance(v, int):
        return str(v)
    return str(v)


def _extract_numeric_rows(rows: List[Dict[str, Any]], y_field: str) -> List[float]:
    """提取数值列"""
    values = []
    for row in rows:
        v = row.get(y_field)
        if v is None:
            continue
        try:
            values.append(float(v))
        except (ValueError, TypeError):
            continue
    return values


def _rank_insight(rows: List[Dict[str, Any]], x_field: str, y_field: str) -> str:
    """排名类洞察：前 N + 后 N"""
    if not rows:
        return "暂无数据。"

    sorted_rows = sorted(rows, key=lambda r: r.get(y_field, 0), reverse=True)
    top = sorted_rows[0]
    bottom = sorted_rows[-1]

    parts = []
    top_val = _format_value(top.get(y_field))
    top_cat = top.get(x_field, "N/A")
    parts.append(f"{top_cat} 的 {y_field} 最高，为 {top_val}")

    if len(sorted_rows) >= 3:
        top3 = sorted_rows[:3]
        top3_cats = "、".join(str(r.get(x_field, "?")) for r in top3)
        parts.append(f"前 3 名依次为：{top3_cats}")

    if len(sorted_rows) >= 2:
        bottom_val = _format_value(bottom.get(y_field))
        bottom_cat = bottom.get(x_field, "N/A")
        parts.append(f"{bottom_cat} 最低（{bottom_val}）")

    return "。".join(parts) + "。"


def _scalar_insight(rows: List[Dict[str, Any]], analysis: Dict[str, Any]) -> str:
    """标量洞察：单值 + 与上下文的对比"""
    if not rows:
        return "未返回任何数据。"

    first = rows[0]
    # 找第一个数值字段
    value = None
    field_name = None
    for k, v in first.items():
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            value = v
            field_name = k
            break

    if value is None:
        return "查询执行成功，但未返回数值。"

    agg = analysis.get("aggregation", "")
    agg_cn = {
        "sum": "总和", "avg": "平均", "count": "数量",
        "max": "最大值", "min": "最小值",
    }.get(agg, "数值")

    formatted = _format_value(value)
    return f"{agg_cn} {field_name} 为 {formatted}。"


def _distribution_insight(rows: List[Dict[str, Any]], x_field: str, y_field: str) -> str:
    """分布类洞察：占比 + 集中度"""
    if not rows:
        return "暂无分布数据。"

    total = sum(_extract_numeric_rows(rows, y_field) or [_extract_scalar(r, y_field) for r in rows])
    if total <= 0:
        total = sum(1 for _ in rows)

    sorted_rows = sorted(rows, key=lambda r: _to_float(r.get(y_field, 0)), reverse=True)
    top = sorted_rows[0]
    top_val = _to_float(top.get(y_field, 0))
    top_cat = top.get(x_field, "N/A")
    pct = (top_val / total * 100) if total else 0

    parts = [f"{top_cat} 占整体的 {pct:.1f}%"]

    if len(sorted_rows) >= 3:
        top3 = sorted_rows[:3]
        top3_pct = sum(_to_float(r.get(y_field, 0)) for r in top3) / total * 100 if total else 0
        parts.append(f"前 3 名合计 {top3_pct:.1f}%")

    return "，".join(parts) + "。"


def _to_float(v: Any) -> float:
    try:
        return float(v) if v is not None else 0.0
    except (ValueError, TypeError):
        return 0.0


def _extract_scalar(row: Dict[str, Any], field: str) -> float:
    v = row.get(field)
    return _to_float(v)


def _trend_insight(rows: List[Dict[str, Any]], x_field: str, y_field: str) -> str:
    """趋势类洞察：方向 + 幅度"""
    if len(rows) < 2:
        return "数据点过少，无法识别趋势。"

    sorted_rows = sorted(rows, key=lambda r: str(r.get(x_field, "")))
    first_val = _to_float(sorted_rows[0].get(y_field, 0))
    last_val = _to_float(sorted_rows[-1].get(y_field, 0))

    if first_val == 0:
        change_pct = 0
    else:
        change_pct = (last_val - first_val) / first_val * 100

    direction = "上升" if change_pct > 0 else "下降" if change_pct < 0 else "持平"
    parts = [f"整体呈{direction}趋势，从 {_format_value(first_val)} 变化到 {_format_value(last_val)}"]

    if abs(change_pct) >= 1:
        parts.append(f"（变动 {change_pct:+.1f}%）")

    return "".join(parts) + "。"


# ===== 主函数 =====
def generate(
    question: str,
    analysis: Dict[str, Any],
    sql_result: Dict[str, Any],
    data_profile: str,
    use_llm: bool = True,
) -> str:
    """生成数据洞察

    Args:
        question: 用户问题
        analysis: LLM 或规则引擎输出的 analysis dict
        sql_result: {columns, rows, row_count}
        data_profile: 数据画像（用于 LLM 模式）
        use_llm: 是否使用 LLM 增强（默认 True，未配置 LLM 时自动降级）

    Returns:
        2-4 句中文洞察字符串
    """
    rows = sql_result.get("rows", [])
    columns = sql_result.get("columns", [])

    # ===== 1. 统计模式（兜底，必返回） =====
    stat_insight = _generate_statistical(analysis, rows, columns)

    # ===== 2. LLM 增强（可选） =====
    if use_llm:
        llm_insight = _try_llm_insight(question, data_profile, sql_result)
        if llm_insight:
            return llm_insight

    return stat_insight


def _generate_statistical(
    analysis: Dict[str, Any],
    rows: List[Dict[str, Any]],
    columns: List[str],
) -> str:
    """基于统计特征生成洞察（兜底）"""
    if not rows:
        return "查询未返回任何数据，请检查数据源或筛选条件。"

    intent = analysis.get("intent", "summary")
    chart_type = analysis.get("chart_type") or analysis.get("chartType")
    x_field = analysis.get("x_field") or analysis.get("dimension")
    y_field = analysis.get("y_field") or analysis.get("metric")

    # 自动推断字段
    if not x_field and len(columns) >= 1:
        x_field = columns[0]
    if not y_field and len(columns) >= 2:
        y_field = columns[1]

    try:
        # 根据意图选择洞察模板
        if intent == "trend" or chart_type == "line":
            return _trend_insight(rows, x_field, y_field)
        if intent == "distribution" or chart_type == "pie":
            return _distribution_insight(rows, x_field, y_field)
        if intent == "ranking" or chart_type == "bar":
            return _rank_insight(rows, x_field, y_field)
        # summary / scalar / 其他
        return _scalar_insight(rows, analysis)
    except Exception as e:
        logger.warning(f"[InsightGenerator] 统计洞察生成失败: {e}")
        return f"查询返回 {len(rows)} 条记录。"


def _try_llm_insight(
    question: str,
    data_profile: str,
    sql_result: Dict[str, Any],
) -> Optional[str]:
    """尝试用 LLM 生成更自然的洞察"""
    try:
        client = get_llm_client()
        if not client.is_configured():
            return None

        import asyncio
        summary = build_data_profile_summary(data_profile, max_field_lines=5)
        loop = asyncio.new_event_loop()
        try:
            insight = loop.run_until_complete(
                client.generate_insight(question, summary, sql_result)
            )
            return insight
        finally:
            loop.close()
    except Exception as e:
        logger.warning(f"[InsightGenerator] LLM 洞察失败: {e}")
        return None


# ===== 数据集整体洞察（doc05 §3，POST /api/insight） =====
def generate_dataset_overview(
    dataset_name: str,
    profile_stats: Dict[str, Any],
) -> Dict[str, Any]:
    """生成数据集整体洞察报告

    Args:
        dataset_name: 数据集名
        profile_stats: {total_rows, total_columns, numeric_summary, ...}

    Returns:
        {summary, statistics, recommendations}
    """
    total_rows = profile_stats.get("total_rows", 0)
    total_columns = profile_stats.get("total_columns", 0)
    numeric_summary = profile_stats.get("numeric_summary", [])
    type_distribution = profile_stats.get("type_distribution", {})

    # Summary
    summary_parts = [
        f"数据集「{dataset_name}」包含 {total_rows} 条记录、{total_columns} 个字段。",
    ]
    if type_distribution:
        type_str = "、".join(f"{k} 字段 {v} 个" for k, v in list(type_distribution.items())[:3])
        summary_parts.append(f"字段类型分布：{type_str}。")
    summary = "".join(summary_parts)

    # Statistics
    statistics = {
        "total_rows": total_rows,
        "total_columns": total_columns,
        "type_distribution": type_distribution,
        "numeric_fields": numeric_summary,
    }

    # Recommendations
    recommendations = []
    if total_rows < 100:
        recommendations.append("数据量较少（<100 条），统计结论的可靠性有限，建议补充更多数据。")
    if total_columns > 20:
        recommendations.append(f"字段较多（{total_columns} 个），建议聚焦核心维度进行分析。")
    numeric_count = type_distribution.get("numeric", 0)
    if numeric_count == 0:
        recommendations.append("未检测到数值字段，所有分析将以计数和分类为主。")
    if numeric_count >= 3:
        recommendations.append(f"有 {numeric_count} 个数值字段，可尝试相关性和趋势分析。")

    return {
        "summary": summary,
        "statistics": statistics,
        "recommendations": recommendations,
    }


# ===== 模块暴露 =====
__all__ = [
    "generate",
    "generate_dataset_overview",
]