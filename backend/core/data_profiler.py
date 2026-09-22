"""
data_profiler.py — 数据画像构建（doc02 §4.3）

输出 Markdown 文本，作为 LLM system prompt 的数据上下文。

格式：
【数据概况】
数据集：xxx.csv (共 N 条记录, M 个字段)

【字段详情】
─ 字段名 (type): 取值/统计/范围（≤20 个唯一值 → 全部列出；>20 → Top10）

【样本数据(前5行)】
行1: k=v, k=v, ...
"""
import logging
from typing import Any, Dict, List, Optional

from models.dataset import Dataset

from .field_inference import (
    TYPE_DATE,
    TYPE_TEXT,
    TYPE_INT,
    TYPE_FLOAT,
    TYPE_CURRENCY,
    TYPE_PERCENT,
    NUMERIC_TYPES,
)

logger = logging.getLogger(__name__)


def _format_number(v: float) -> str:
    """格式化数值为 2 位小数（避免过长）"""
    if v is None:
        return "-"
    try:
        return f"{float(v):.2f}"
    except (ValueError, TypeError):
        return str(v)


def _format_sample_value(v: Any) -> str:
    """格式化样本值字符串（截断 20 字符）"""
    if v is None:
        return "-"
    s = str(v)
    return s if len(s) <= 20 else s[:20] + "..."


def _build_field_summary(field_name: str, ftype: str, values: List[Any]) -> str:
    """构建单个字段的画像摘要"""
    label = f"─ {field_name} ({ftype})"

    if ftype == TYPE_TEXT:
        unique = list(dict.fromkeys([v for v in values if v is not None]))
        if len(unique) <= 20:
            sample_str = ", ".join(_format_sample_value(v) for v in unique[:20])
            return f"{label}: 取值({len(unique)}个), 全部: {sample_str}"
        else:
            top5 = unique[:5]
            sample_str = ", ".join(_format_sample_value(v) for v in top5)
            return f"{label}: 取值({len(unique)}个), Top5: {sample_str}"

    elif ftype == TYPE_DATE:
        valid = [v for v in values if v is not None]
        if not valid:
            return f"{label}: 无有效值"
        try:
            sorted_vals = sorted(valid)
            return f"{label}: 范围 {sorted_vals[0]} ~ {sorted_vals[-1]}"
        except Exception:
            return f"{label}: 含 {len(valid)} 个日期值"

    elif ftype in NUMERIC_TYPES:
        nums = []
        for v in values:
            try:
                if v is not None:
                    nums.append(float(v))
            except (ValueError, TypeError):
                continue
        if not nums:
            return f"{label}: 无有效数值"
        return (
            f"{label}: 统计: "
            f"总和={_format_number(sum(nums))} / "
            f"平均={_format_number(sum(nums) / len(nums))} / "
            f"最大={_format_number(max(nums))} / "
            f"最小={_format_number(min(nums))}"
        )

    return f"{label}: -"


def _build_sample_rows_str(rows: List[Dict[str, Any]], limit: int = 5) -> str:
    """构建样本数据字符串"""
    if not rows:
        return "（无样本数据）"

    lines = []
    for i, row in enumerate(rows[:limit], start=1):
        parts = [f"{k}={_format_sample_value(v)}" for k, v in row.items()]
        lines.append(f"行{i}: {', '.join(parts)}")
    return "\n".join(lines)


def build_data_profile(dataset: Dataset) -> str:
    """构建数据画像文本（喂给 LLM 当 system prompt 上下文）

    Args:
        dataset: Dataset SQLAlchemy 模型实例

    Returns:
        Markdown 格式的中文画像文本
    """
    from .data_manager import data_manager

    field_info = dataset.get_field_info()
    columns = dataset.get_columns()

    # 拉取所有行（一次，limit 由 DataManager 控制）
    try:
        all_rows = data_manager.get_all_rows(dataset)
    except Exception as e:
        logger.warning(f"[DataProfiler] 拉取数据失败: {e}")
        all_rows = []

    # 按字段分组取值
    field_values: Dict[str, List[Any]] = {col: [] for col in columns}
    for row in all_rows:
        for col in columns:
            v = row.get(col)
            if v is not None and v != "":
                field_values[col].append(v)

    # 第一部分：概况
    summary = (
        f"【数据概况】\n"
        f"数据集：{dataset.original_name} (共 {dataset.row_count} 条记录, {len(columns)} 个字段)"
    )

    # 第二部分：字段详情
    field_summaries = ["【字段详情】"]
    for f in field_info:
        fname = f["name"]
        ftype = f.get("type", "text")
        values = field_values.get(fname, [])
        field_summaries.append(_build_field_summary(fname, ftype, values))

    # 第三部分：样本数据
    sample_section = f"【样本数据(前5行)】\n{_build_sample_rows_str(all_rows, limit=5)}"

    # 组合
    profile = "\n\n".join([summary, "\n".join(field_summaries), sample_section])

    logger.debug(f"[DataProfiler] 构建画像: {dataset.id} ({len(profile)} 字符)")
    return profile


# ===== 便捷函数 =====
def estimate_tokens(text: str) -> int:
    """粗略估算文本的 token 数（中文约 1.5 字符/token，英文约 4 字符/token）"""
    if not text:
        return 0
    chinese_chars = sum(1 for c in text if "一" <= c <= "鿿")
    other_chars = len(text) - chinese_chars
    return int(chinese_chars / 1.5 + other_chars / 4)