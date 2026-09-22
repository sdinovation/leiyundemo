"""
field_inference.py — 字段类型推断（移植前端 index.html:3490-3525）

类型枚举：`date | text | int | float | currency | percent`

推断优先级（与前端完全一致）：
1. name 匹配 `日期|时间|date|time` → date
2. name 匹配 `金额|价格|销售额|收入|revenue|sales|price|amount|gmv` → currency
3. name 匹配 `率|比例|rate|percent|ratio` → percent
4. name 匹配 `代码|编号|^id$|code|序列号|序号` → text（标识符）
5. 样本中第一个 number：
   - 唯一值比例 > 80% 且 name 不含"量/数/额/价/率/总/均/和/差/比/分" → text（ID 字段）
   - 整数 → int
   - 浮点 → float
6. 其他 → text

注：使用 camelCase 字段名 `nullRate`（与前端保持一致，agent 报告冲突 #11）
"""
import re
from typing import Any, List, Dict, Optional


# ===== 类型常量 =====
TYPE_DATE = "date"
TYPE_TEXT = "text"
TYPE_INT = "int"
TYPE_FLOAT = "float"
TYPE_CURRENCY = "currency"
TYPE_PERCENT = "percent"

ALL_TYPES = {TYPE_DATE, TYPE_TEXT, TYPE_INT, TYPE_FLOAT, TYPE_CURRENCY, TYPE_PERCENT}
NUMERIC_TYPES = {TYPE_INT, TYPE_FLOAT, TYPE_CURRENCY, TYPE_PERCENT}


# ===== 推断正则（与前端编译时一致）=====
RE_DATE = re.compile(r"日期|时间|date|time", re.IGNORECASE)
RE_CURRENCY = re.compile(r"金额|价格|销售额|收入|revenue|sales|price|amount|gmv", re.IGNORECASE)
RE_PERCENT = re.compile(r"率|比例|rate|percent|ratio", re.IGNORECASE)
RE_ID = re.compile(r"代码|编号|^id$|code|序列号|序号", re.IGNORECASE)
# 指标关键词：含"量/数/额/价/率/总/均/和/差/比/分"等关键字的字段名，更可能是真实指标而非 ID
RE_METRIC_KEYWORD = re.compile(r"量|数|额|价|率|总|均|和|差|比|分")


def _is_number(v: Any) -> bool:
    """判断是否为数值（int / float），排除 bool"""
    if isinstance(v, bool):
        return False
    return isinstance(v, (int, float))


def infer_field_type(name: str, values: List[Any]) -> str:
    """
    推断单字段类型。

    Args:
        name: 字段名（保留原始大小写）
        values: 字段样本值（已过滤空值/None）

    Returns:
        类型字符串：'date' | 'text' | 'int' | 'float' | 'currency' | 'percent'
    """
    lower = name.lower()

    # 1. 日期
    if RE_DATE.search(lower):
        return TYPE_DATE

    # 2. 货币
    if RE_CURRENCY.search(lower):
        return TYPE_CURRENCY

    # 3. 百分比
    if RE_PERCENT.search(lower):
        return TYPE_PERCENT

    # 4. 标识符字段
    if RE_ID.search(lower):
        return TYPE_TEXT

    # 5. 数值推断
    numbers = [v for v in values if _is_number(v)]
    if numbers:
        # 唯一值比例 > 80% 且 name 不含指标关键词 → 可能是 ID
        unique_vals = set(numbers)
        unique_ratio = len(unique_vals) / len(numbers) if numbers else 0
        # 财务关键词（含这些字的字段名即使唯一值多也是数值）
        RE_FINANCE = re.compile(r"薪|工资|成本|利润|费用|营收|支出|wage|salary")
        if unique_ratio > 0.8 and not RE_METRIC_KEYWORD.search(name) and not RE_FINANCE.search(name):
            return TYPE_TEXT
        # 整数 → int，浮点 → float
        return TYPE_INT if all(isinstance(v, int) or (isinstance(v, float) and v.is_integer()) for v in numbers) else TYPE_FLOAT

    return TYPE_TEXT


def infer_field_info(columns: List[str], rows: List[List[Any]]) -> List[Dict[str, Any]]:
    """
    批量推断字段信息（移植前端 inferFieldInfo）。

    Args:
        columns: 列名列表
        rows: 二维数组（行 × 列），行为 [val1, val2, ...]

    Returns:
        字段信息数组，每项包含: {name, type, nullRate, sample}
    """
    if not columns or not rows:
        return []

    result = []
    total_rows = len(rows)

    for col_idx, col_name in enumerate(columns):
        # 收集该列所有非空值
        values = []
        for row in rows:
            if col_idx < len(row):
                v = row[col_idx]
                if v != "" and v is not None:
                    values.append(v)

        # 缺失率（保留 1 位小数 + %）
        null_count = total_rows - len(values)
        null_rate = "0.0%" if total_rows == 0 else f"{(null_count / total_rows * 100):.1f}%"

        # 样本值（截断 30 字符）
        sample = str(values[0])[:30] if values else "-"

        # 推断类型
        ftype = infer_field_type(col_name, values)

        result.append({
            "name": col_name,
            "type": ftype,
            "nullRate": null_rate,  # camelCase，与前端一致
            "sample": sample,
        })

    return result


def infer_field_info_from_records(columns: List[str], records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    批量推断字段信息（Dict 模式，与 Pandas DataFrame 配合使用）。

    Args:
        columns: 列名列表
        records: 行数组，每行是 {col_name: value}

    Returns:
        字段信息数组，格式与 infer_field_info 一致
    """
    if not columns or not records:
        return []

    result = []
    total_rows = len(records)

    for col_name in columns:
        values = []
        for r in records:
            v = r.get(col_name)
            if v is not None and v != "":
                # pandas NaN 检查
                try:
                    if isinstance(v, float) and v != v:  # NaN != NaN
                        continue
                except Exception:
                    pass
                values.append(v)

        null_count = total_rows - len(values)
        null_rate = "0.0%" if total_rows == 0 else f"{(null_count / total_rows * 100):.1f}%"

        sample = str(values[0])[:30] if values else "-"
        ftype = infer_field_type(col_name, values)

        result.append({
            "name": col_name,
            "type": ftype,
            "nullRate": null_rate,
            "sample": sample,
        })

    return result


def compute_type_distribution(field_info: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    统计字段类型分布（移植前端 computeTypeDistribution）。

    Returns:
        [{name: '整数', value: 5}, {name: '文本', value: 3}, ...]
    """
    if not field_info:
        return []

    TYPE_LABELS = {
        TYPE_DATE: "日期/时间",
        TYPE_TEXT: "文本",
        TYPE_INT: "整数",
        TYPE_FLOAT: "浮点数",
        TYPE_CURRENCY: "浮点数",
        TYPE_PERCENT: "浮点数",
    }

    counts: Dict[str, int] = {}
    for f in field_info:
        label = TYPE_LABELS.get(f.get("type"), "其他")
        counts[label] = counts.get(label, 0) + 1

    return [{"name": k, "value": v} for k, v in counts.items()]


# ===== 模块级单例便捷访问 =====
def get_numeric_fields(field_info: List[Dict[str, Any]]) -> List[str]:
    """从 field_info 中提取所有数值字段名"""
    return [f["name"] for f in field_info if f.get("type") in NUMERIC_TYPES]


def get_text_fields(field_info: List[Dict[str, Any]]) -> List[str]:
    """从 field_info 中提取所有文本字段名"""
    return [f["name"] for f in field_info if f.get("type") == TYPE_TEXT]


def get_date_fields(field_info: List[Dict[str, Any]]) -> List[str]:
    """从 field_info 中提取所有日期字段名"""
    return [f["name"] for f in field_info if f.get("type") == TYPE_DATE]