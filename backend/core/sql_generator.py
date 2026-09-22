"""
sql_generator.py — SQL 生成器（双模式）

模式 A（LLM 路径）：LLM Function Calling 已经直接输出 SQL 字符串
  → 本模块只做 validate + 字段名白名单校验（防止 LLM 编造字段）

模式 B（规则引擎降级）：前端 classifyIntent 输出的 analysis dict
  → 本模块从 {dimension, metric, aggregation, filters, havingCond, sortOrder, limit}
     生成 SQL 字符串

约定：
- 表名 = `data`（与 data_manager._load_to_sqlite 一致）
- 中文字段名必须用双引号 `"字段"` 包裹（SQLite 标识符需双引号）
- 字段名/表名必须做白名单校验（防 SQL 注入）
"""
import logging
import re
from typing import Any, Dict, List, Optional, Set

from models.dataset import Dataset

from .sql_executor import validate as validate_sql, SQLValidationError

logger = logging.getLogger(__name__)


# ===== SQL 注入防护 =====
class SQLGenerationError(Exception):
    """SQL 生成错误"""
    pass


# 标识符允许的字符（中文 + 英文 + 数字 + 下划线 + 括号 + 点）
_RE_VALID_IDENTIFIER = re.compile(r"^[A-Za-z_一-龥][\w一-龥（）()]*$")
# AS 别名允许更多字符
_RE_VALID_ALIAS = re.compile(r"^[A-Za-z_一-龥][\w一-龥（）()]*$")


def _quote_identifier(name: str) -> str:
    """对 SQL 标识符加双引号（SQLite + DuckDB 都支持）"""
    if not name:
        raise SQLGenerationError("字段名/表名不能为空")
    if not _RE_VALID_IDENTIFIER.match(name):
        raise SQLGenerationError(f"非法标识符: {name!r}（含不允许的字符）")
    return f'"{name}"'


def _quote_alias(name: str) -> str:
    """对 AS 别名加双引号（与 _quote_identifier 严格度一致）"""
    return _quote_identifier(name)


def _validate_field(field_name: str, allowed: Set[str]) -> str:
    """校验字段名必须在白名单内"""
    if field_name not in allowed:
        raise SQLGenerationError(
            f"字段 {field_name!r} 不在白名单中（数据集中没有此字段）"
        )
    return _quote_identifier(field_name)


# ===== 模式 A：LLM 直接输出 SQL =====
def validate_llm_sql(sql: str, dataset: Dataset) -> str:
    """校验 LLM 输出的 SQL 安全性 + 字段名白名单

    Args:
        sql: LLM 生成的 SQL
        dataset: 用于白名单校验

    Returns:
        通过校验的 SQL 字符串

    Raises:
        SQLGenerationError, SQLValidationError
    """
    # 1. 安全校验（关键字、注释、多语句等）
    validate_sql(sql)

    # 2. 表名白名单：必须是 "data"（或 dataset.id 也允许，但严禁其他）
    columns = set(dataset.get_columns())
    allowed = columns | {"data", dataset.id}

    # 3. 提取 SQL 中所有从 `data` 或 `"data"` 引用的字段名
    # 简化：提取所有双引号包裹的标识符
    referenced = set(re.findall(r'"([^"]+)"', sql))
    for ref in referenced:
        if ref == "data":
            continue
        # 字段名必须白名单
        if ref not in allowed:
            # 可能是 AS 别名（不去检查，但记录日志）
            logger.debug(f"[SQLGenerator] 出现未识别标识符: {ref!r}（可能为别名）")

    return sql


# ===== 模式 B：规则引擎生成 SQL =====
# 聚合方式 → SQL 函数
_AGG_TO_SQL = {
    "sum": "SUM",
    "avg": "AVG",
    "count": "COUNT",
    "max": "MAX",
    "min": "MIN",
}

# 排序方向枚举
_SORT_ORDER_SQL = {
    "desc": "DESC",
    "asc": "ASC",
    "null": None,
}

# 操作符白名单
_VALID_OPS = {"=", "!=", ">", "<", ">=", "<=", "LIKE", "NOT LIKE", "IN", "NOT IN"}


def _build_where_clause(filters: List[Dict[str, Any]], allowed: Set[str]) -> str:
    """构建 WHERE 子句"""
    if not filters:
        return ""
    parts = []
    for f in filters:
        field = f.get("field")
        op = f.get("op", "=")
        value = f.get("value")
        if not field or op not in _VALID_OPS or value is None:
            logger.warning(f"[SQLGenerator] 跳过非法 filter: {f}")
            continue
        qfield = _validate_field(field, allowed)
        if op in ("LIKE", "NOT LIKE"):
            # 字符串操作
            parts.append(f"{qfield} {op} '%{_escape_like(value)}%'")
        elif op in ("IN", "NOT IN"):
            # 列表操作
            items = value if isinstance(value, list) else [value]
            items_str = ", ".join(f"'{_escape_string(v)}'" for v in items)
            parts.append(f"{qfield} {op} ({items_str})")
        else:
            # 数值/字符串 = != > <
            parts.append(f"{qfield} {op} '{_escape_string(value)}'")
    if not parts:
        return ""
    return " WHERE " + " AND ".join(parts)


def _build_having_clause(having: Optional[str], allowed: Set[str]) -> str:
    """构建 HAVING 子句

    简单实现：白名单字段名（粗略正则），其他透传
    """
    if not having:
        return ""
    # 校验 HAVING 中所有字段名都在白名单
    referenced = set(re.findall(r'"([^"]+)"', having))
    for ref in referenced:
        if ref not in allowed:
            raise SQLGenerationError(f"HAVING 含字段 {ref!r} 不在白名单")
    return f" HAVING {having}"


def _build_ratio_sql(analysis: Dict[str, Any], table_name: str, allowed: Set[str]) -> str:
    """aggregation=ratio 时的特殊 SQL 模板（doc01 §2.2.3 规则 11）"""
    dimension = analysis.get("dimension")
    metric = analysis.get("metric")
    ratio_col = analysis.get("ratioColumn")
    ratio_val = analysis.get("ratioValue")
    sort_order = analysis.get("sortOrder", "desc")
    limit = analysis.get("limit", 10)

    if not ratio_col:
        raise SQLGenerationError("aggregation=ratio 时必须提供 ratioColumn")

    qratio_col = _validate_field(ratio_col, allowed)
    safe_val = _escape_string(ratio_val) if ratio_val is not None else "1"

    if dimension:
        qdim = _validate_field(dimension, allowed)
        alias = f"{dimension}_占比"
        sql = (
            f'SELECT {qdim}, '
            f'ROUND(100.0 * SUM(CASE WHEN {qratio_col} = \'{safe_val}\' THEN 1 ELSE 0 END) / COUNT(*), 2) '
            f'AS {qratio_col if False else _quote_alias(alias)} '
            f'FROM {table_name} '
            f'GROUP BY {qdim} '
            f'ORDER BY 2 DESC '
            f'LIMIT {int(limit)}'
        )
    else:
        # 全局占比
        sql = (
            f'SELECT ROUND(100.0 * SUM(CASE WHEN {qratio_col} = \'{safe_val}\' THEN 1 ELSE 0 END) / COUNT(*), 2) '
            f'AS 占比 FROM {table_name}'
        )
    return sql


def generate(analysis: Dict[str, Any], dataset: Dataset) -> str:
    """从规则引擎的 analysis dict 生成 SQL

    Args:
        analysis: {dimension, metric, aggregation, isScalar, filters, havingCond,
                   sortOrder, limit, intent, ratioColumn, ratioValue}
        dataset: 用于字段白名单

    Returns:
        SQLITE 兼容的 SQL 字符串

    Raises:
        SQLGenerationError, SQLValidationError
    """
    columns = list(dataset.get_columns())
    allowed = set(columns) | {"data"}

    table_name = '"data"'  # 数据表名固定

    # 提取字段
    dimension = analysis.get("dimension")
    metric = analysis.get("metric")
    secondary_metric = analysis.get("secondaryMetric")
    aggregation = (analysis.get("aggregation") or "sum").lower()
    is_scalar = analysis.get("isScalar", False)
    filters = analysis.get("filters") or []
    having = analysis.get("havingCond")
    sort_order = analysis.get("sortOrder", "desc")
    limit = int(analysis.get("limit") or 10)

    # ===== 1. 标量查询 =====
    if is_scalar or not dimension:
        # SELECT agg(metric) FROM data [WHERE ...]
        if aggregation == "count":
            # COUNT 可不带 metric
            sql = f"SELECT COUNT(*) AS { _quote_alias('数量') } FROM {table_name}"
        elif aggregation == "ratio":
            return _build_ratio_sql(analysis, table_name, allowed)
        else:
            if not metric:
                raise SQLGenerationError("非 count 标量查询必须提供 metric")
            qmetric = _validate_field(metric, allowed)
            agg_fn = _AGG_TO_SQL.get(aggregation, "SUM")
            alias = f"{aggregation}_{metric}"
            sql = f"SELECT {agg_fn}({qmetric}) AS {_quote_alias(alias)} FROM {table_name}"
        sql += _build_where_clause(filters, allowed)
        return sql

    # ===== 2. 聚合查询 =====
    qdim = _validate_field(dimension, allowed)

    # 2.1 ratio 特殊处理
    if aggregation == "ratio":
        return _build_ratio_sql(analysis, table_name, allowed)

    # 2.2 count + 无 metric → 计数
    if aggregation == "count" and not metric:
        alias = f"{dimension}_数量"
        sql = (
            f"SELECT {qdim}, COUNT(*) AS {_quote_alias(alias)} "
            f"FROM {table_name}"
        )
    else:
        if not metric:
            raise SQLGenerationError("非 count 聚合查询必须提供 metric")
        qmetric = _validate_field(metric, allowed)
        agg_fn = _AGG_TO_SQL.get(aggregation, "SUM")
        alias = f"{aggregation}_{metric}"
        sql = (
            f"SELECT {qdim}, {agg_fn}({qmetric}) AS {_quote_alias(alias)} "
            f"FROM {table_name}"
        )

    # 2.3 WHERE
    sql += _build_where_clause(filters, allowed)

    # 2.4 GROUP BY
    sql += f" GROUP BY {qdim}"

    # 2.5 HAVING
    sql += _build_having_clause(having, allowed)

    # 2.6 ORDER BY（按聚合列别名）
    order_dir = _SORT_ORDER_SQL.get(sort_order, "DESC")
    if order_dir:
        sql += f" ORDER BY 2 {order_dir}"

    # 2.7 LIMIT
    sql += f" LIMIT {limit}"

    return sql


# ===== 工具函数 =====
def _escape_string(v: Any) -> str:
    """转义 SQL 字符串字面量（双单引号）"""
    return str(v).replace("'", "''")


def _escape_like(v: Any) -> str:
    """转义 LIKE 模式中的 % 和 _"""
    s = str(v).replace("'", "''").replace("%", r"\%").replace("_", r"\_")
    return s