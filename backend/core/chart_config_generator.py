"""
chart_config_generator.py — 生成前端兼容的 chart_config（按 doc03 契约）

输出形状（与 HttpQueryService 消费一致）：
- bar / line / pie: {type: 'bar', x_field, y_field, categories: [...], values: [...], aggregation}
- scatter: {type: 'scatter', points: [[x, y], ...], x_field, y_field}
- table: {type: 'table', rows: [...], columns: [...]}
- number: {type: 'number', value: scalar, label: '...'}

P1-C：在 chart_type 二次校验器中，根据 SQL 实际结果数据特征（行数、唯一值数、
时间字段存在性）对 LLM/规则给出的 chart_type 做强制调整，避免：
- 行数过多（>15 类）却给 bar → 改为 table
- 占比且类别少（≤8）→ 强制 pie
- 单行结果 + number 聚合 → number
- 时间序列 + 多行 → line（即便 LLM 给 bar）
"""
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ===== P1-C：图表类型二次校验阈值 =====
_MAX_BAR_CATEGORIES = 15     # 超过此值 bar 不合适，应改为 table
_MAX_PIE_CATEGORIES = 8      # 超过此值 pie 不合适，应改为 bar
_MIN_LINE_POINTS = 3         # 折线图至少 3 个点
_TIME_FIELD_HINT = ("日期", "时间", "月份", "年度", "年", "月", "日", "date", "time", "month", "year")


def _looks_like_time_field(name: str) -> bool:
    """粗略判断字段名是否像时间字段"""
    if not name:
        return False
    n = name.lower()
    return any(h in n for h in _TIME_FIELD_HINT)


def refine_chart_type(
    analysis: Dict[str, Any],
    sql_result: Dict[str, Any],
) -> str:
    """P1-C：根据数据特征对 chart_type 做二次校验，返回调整后的 chart_type

    调整规则（优先级从高到低）：
    1. 单行 + aggregation=count 且无 dimension → number
    2. 多行 + dimension 像时间字段 + 行数 >= 3 → line（强制覆盖 bar/pie）
    3. 占比语义（intent=distribution/aggregation=ratio）+ 类别 ≤8 → pie
    4. 类别过多（>15） → table（bar 不清晰）
    5. pie 类别过多（>8） → bar
    6. 其他保持原样
    """
    chart_type = (analysis.get("chartType") or analysis.get("chart_type") or "bar").lower()
    intent = analysis.get("intent", "summary")
    aggregation = analysis.get("aggregation", "sum")
    dimension = analysis.get("x_field") or analysis.get("dimension")
    rows = sql_result.get("rows", [])

    row_count = len(rows)

    # 规则 1：单行 + count 聚合 → number
    if row_count <= 1 and (aggregation == "count" or chart_type == "number"):
        return "number"

    # 规则 2：dimension 像时间字段 → line
    if dimension and _looks_like_time_field(dimension) and row_count >= _MIN_LINE_POINTS:
        if chart_type in ("bar", "pie", "number"):
            logger.debug(f"[ChartRefine] 时间维度 {dimension!r} → line（原 {chart_type}）")
            return "line"

    # 规则 3：占比语义 → pie（仅当类别不多）
    if intent == "distribution" or aggregation == "ratio":
        if row_count <= _MAX_PIE_CATEGORIES:
            return "pie"
        # 类别过多 → bar 更合适
        return "bar"

    # 规则 4：bar/pie 类别过多 → table
    if chart_type in ("bar", "line", "pie") and row_count > _MAX_BAR_CATEGORIES:
        logger.debug(f"[ChartRefine] 类别数 {row_count} 过多 → table（原 {chart_type}）")
        return "table"

    # 规则 5：pie 类别过多 → bar
    if chart_type == "pie" and row_count > _MAX_PIE_CATEGORIES:
        logger.debug(f"[ChartRefine] pie 类别数 {row_count} 过多 → bar")
        return "bar"

    return chart_type


# ===== 辅助函数 =====
def _extract_categories_values(rows: List[Dict[str, Any]], x_field: str, y_field: str) -> tuple:
    """从查询结果中提取 categories 和 values"""
    categories = []
    values = []
    for row in rows:
        cat = row.get(x_field)
        val = row.get(y_field)
        # 跳过无值行
        if cat is None:
            continue
        categories.append(str(cat))
        # 数值字段：None / 非法值 → 0
        if val is None:
            values.append(0)
        elif isinstance(val, (int, float)):
            values.append(float(val))
        else:
            try:
                values.append(float(val))
            except (ValueError, TypeError):
                values.append(0)
    return categories, values


def _extract_scalar(rows: List[Dict[str, Any]], y_field: str) -> Optional[float]:
    """从单行结果中提取数值"""
    if not rows:
        return None
    first = rows[0]
    val = first.get(y_field)
    if val is None:
        val = first.get("value") or first.get("scalar")
    if isinstance(val, (int, float)):
        return float(val)
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


# ===== 主函数 =====
def generate_chart_config(
    analysis: Dict[str, Any],
    sql_result: Dict[str, Any],
) -> Dict[str, Any]:
    """根据分析结果 + SQL 执行结果生成 chart_config

    Args:
        analysis: LLM 或规则引擎输出的查询方案（{chartType, x_field, y_field, aggregation, ...}）
        sql_result: SQLExecutor 返回的 {columns, rows, row_count}

    Returns:
        前端 ECharts 直接消费的 chart_config dict
    """
    # P1-C：先用 refine_chart_type 调整 chart_type
    chart_type = refine_chart_type(analysis, sql_result)
    x_field = analysis.get("x_field") or analysis.get("dimension")
    y_field = analysis.get("y_field") or analysis.get("metric")
    aggregation = analysis.get("aggregation", "sum")
    intent = analysis.get("intent", "summary")
    rows = sql_result.get("rows", [])
    columns = sql_result.get("columns", [])

    # Fix: 空结果直接返回 number 卡片，不画无意义的空柱状图
    if len(rows) == 0:
        logger.info(
            f"[ChartConfig] 空结果（row_count=0），返回 number 占位 (原 {chart_type})"
        )
        return {
            "type": "number",
            "title": analysis.get("title") or "查询结果",
            "value": 0,
            "metric": "未找到数据",
            "columns": columns,
            "rows": rows,
            "row_count": 0,
            "empty": True,
        }

    # ===== bar / line / pie =====
    if chart_type in ("bar", "line", "pie"):
        if not x_field or not y_field:
            # 自动从 columns 推断
            if len(columns) >= 2:
                x_field = x_field or columns[0]
                y_field = y_field or columns[1]
            else:
                logger.warning(f"[ChartConfig] 缺少 x_field/y_field，降级到 table")
                return {
                    "type": "table",
                    "columns": columns,
                    "rows": rows,
                }

        categories, values = _extract_categories_values(rows, x_field, y_field)

        # 对 pie 图排序：按值降序
        if chart_type == "pie" and len(categories) > 0:
            paired = sorted(zip(categories, values), key=lambda x: x[1], reverse=True)
            categories = [p[0] for p in paired]
            values = [p[1] for p in paired]

        return {
            "type": chart_type,
            "x_field": x_field,
            "y_field": y_field,
            "categories": categories,
            "values": values,
            "aggregation": aggregation,
            "intent": intent,
            "row_count": len(rows),
        }

    # ===== scatter =====
    if chart_type == "scatter":
        if not x_field or not y_field:
            if len(columns) >= 2:
                x_field = x_field or columns[0]
                y_field = y_field or columns[1]
        points = []
        for row in rows:
            x = row.get(x_field) if x_field else None
            y = row.get(y_field) if y_field else None
            if x is None or y is None:
                continue
            try:
                points.append([float(x), float(y)])
            except (ValueError, TypeError):
                continue
        return {
            "type": "scatter",
            "x_field": x_field,
            "y_field": y_field,
            "points": points,
            "row_count": len(points),
        }

    # ===== table =====
    if chart_type == "table":
        # 截断到 100 行（防止 UI 卡顿）
        MAX_TABLE_ROWS = 100
        truncated = rows[:MAX_TABLE_ROWS]
        return {
            "type": "table",
            "columns": columns,
            "rows": truncated,
            "row_count": len(rows),
            "truncated": len(rows) > MAX_TABLE_ROWS,
        }

    # ===== number =====
    if chart_type == "number":
        value = _extract_scalar(rows, y_field or "")
        # 生成 label
        agg_cn = {
            "sum": "总和",
            "avg": "平均值",
            "count": "数量",
            "max": "最大值",
            "min": "最小值",
        }.get(aggregation, "数值")
        label = f"{agg_cn}{('-' + y_field) if y_field else ''}"
        return {
            "type": "number",
            "value": value,
            "label": label,
            "y_field": y_field,
        }

    # ===== 兜底 =====
    logger.warning(f"[ChartConfig] 未知 chartType: {chart_type}，降级到 table")
    return {
        "type": "table",
        "columns": columns,
        "rows": rows,
        "row_count": len(rows),
    }


# ===== 前端期望形状的辅助函数 =====
def make_chart_data_payload(chart_config: Dict[str, Any]) -> Dict[str, Any]:
    """把内部 chart_config 转换为前端 ECharts 的 chartData 形状

    前端期望（HttpQueryService 契约）：
    chartData: {categories: [...], values: [...], metric: '...', dimension: '...'}

    返回值映射：
    - bar/line/pie: {categories, values, metric, dimension}
    - scatter: {points: [...], metric, dimension}
    - table: {rows: [...]}
    - number: {value, label}
    """
    ctype = chart_config.get("type")
    if ctype in ("bar", "line", "pie"):
        return {
            "categories": chart_config.get("categories", []),
            "values": chart_config.get("values", []),
            "metric": chart_config.get("y_field"),
            "dimension": chart_config.get("x_field"),
        }
    if ctype == "scatter":
        return {
            "points": chart_config.get("points", []),
            "metric": chart_config.get("y_field"),
            "dimension": chart_config.get("x_field"),
        }
    if ctype == "table":
        return {
            "rows": chart_config.get("rows", []),
            "columns": chart_config.get("columns", []),
        }
    if ctype == "number":
        return {
            "value": chart_config.get("value"),
            "label": chart_config.get("label"),
        }
    return chart_config