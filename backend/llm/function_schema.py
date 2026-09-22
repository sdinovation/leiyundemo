"""
function_schema.py — LLM Function Calling JSON Schema（doc03 §3 约定）

函数名：execute_data_query（替代 doc01 的 analyze_data_question）
设计：LLM 直接输出 SQL 字符串 + 图表类型 + 洞察文字（不要 query plan）

为什么 LLM 直接出 SQL？
- 减少一次"plan → SQL"映射，错误率更低
- LLM 更擅长写 SQL（训练数据中 SQL 占比高）
- 字段名/表名由 prompt 中的数据画像约束，不需要从结构化 plan 重构

Schema 字段（来自 doc03 §3.4 + 适当扩展）：
- sql (required): 完整 SQL 语句，单条 SELECT，目标表固定为 "data"
- chart_type (required): bar/line/pie/scatter/table/number
- insight (required): 1-2 句中文解读
- explanation: 一句话解释查询思路
- x_field: 分组维度（bar/line/pie 用）
- y_field: 指标字段
- aggregation: sum/avg/count/max/min/ratio
- intent: ranking/trend/comparison/distribution/summary/list/correlation/filter
- filters: [{field, op, value}] 过滤条件
- sort_order: desc/asc/null
- limit: 整数
"""
from typing import Any, Dict, List


# ===== OpenAI Function Calling 格式 =====
EXECUTE_DATA_QUERY_FUNCTION: Dict[str, Any] = {
    "name": "execute_data_query",
    "description": (
        "根据用户的数据分析问题和数据画像，直接生成 SQL 查询语句并调用此函数。"
        "SQL 必须只查询表名为 \"data\" 的表（数据已预加载至此表）。"
        "执行后会自动生成图表配置和详细解读。"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "sql": {
                "type": "string",
                "description": (
                    "完整的 SQL SELECT 语句，作用于表 \"data\"。"
                    "中文字段名必须用双引号包裹（如 SELECT \"城市\" FROM \"data\"）。"
                    "禁止使用 INSERT/UPDATE/DELETE/DROP 等写操作。"
                    "禁止使用 RATIO()/PERCENT() 等函数，系统会自动展开。"
                    "禁止使用多语句（不能用 ; 分隔）。"
                ),
            },
            "chart_type": {
                "type": "string",
                "enum": ["bar", "line", "pie", "scatter", "table", "number"],
                "description": (
                    "图表类型：bar(柱状-排名), line(折线-趋势), pie(饼图-分布), "
                    "scatter(散点-相关性), table(表格), number(数字卡片-标量)"
                ),
            },
            "insight": {
                "type": "string",
                "description": (
                    "1-2 句中文文字解读（不超过 150 字）。"
                    "必须基于查询结果的事实，禁止编造数据。"
                ),
            },
            "explanation": {
                "type": "string",
                "description": "一句话解释你要怎么分析这个问题（不超过 80 字）",
            },
            "x_field": {
                "type": ["string", "null"],
                "description": "X 轴字段名（用于 bar/line/pie/scatter）。必须是数据画像中的原始列名。",
            },
            "y_field": {
                "type": ["string", "null"],
                "description": "Y 轴字段名（用于 bar/line/scatter）。必须是数据画像中的原始列名。",
            },
            "aggregation": {
                "type": "string",
                "enum": ["sum", "avg", "count", "max", "min", "ratio"],
                "description": (
                    "聚合方式：sum求和, avg平均, count计数, max最大, min最小, ratio占比。"
                    "问人数/条数/订单数 → count。"
                ),
            },
            "intent": {
                "type": "string",
                "enum": [
                    "ranking", "trend", "comparison", "distribution",
                    "summary", "list", "correlation", "filter",
                ],
                "description": (
                    "查询意图：ranking排名, trend趋势, comparison对比, "
                    "distribution分布, summary汇总, list清单, "
                    "correlation相关性, filter筛选。"
                ),
            },
            "filters": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "field": {"type": "string", "description": "字段名"},
                        "op": {
                            "type": "string",
                            "enum": ["=", "!=", ">", "<", ">=", "<=", "LIKE", "NOT LIKE", "IN"],
                            "description": "比较运算符",
                        },
                        "value": {"type": "string", "description": "比较值"},
                    },
                    "required": ["field", "op", "value"],
                },
                "description": "WHERE 过滤条件数组",
            },
            "sort_order": {
                "type": ["string", "null"],
                "enum": ["desc", "asc", "null"],
                "description": "排序方向：desc降序, asc升序, null不排序",
            },
            "limit": {
                "type": "integer",
                "description": "返回行数限制（排名类默认 10，清单类可设 50-100）",
                "default": 10,
            },
        },
        "required": ["sql", "chart_type", "insight"],
    },
}


# ===== 验证工具 =====
VALID_CHART_TYPES = set(EXECUTE_DATA_QUERY_FUNCTION["parameters"]["properties"]["chart_type"]["enum"])
VALID_AGGREGATIONS = set(EXECUTE_DATA_QUERY_FUNCTION["parameters"]["properties"]["aggregation"]["enum"])
VALID_INTENTS = set(EXECUTE_DATA_QUERY_FUNCTION["parameters"]["properties"]["intent"]["enum"])
VALID_SORT_ORDERS = {"desc", "asc", "null", None}
VALID_OPS = {"=", "!=", ">", "<", ">=", "<=", "LIKE", "NOT LIKE", "IN", "NOT IN"}


def validate_function_call(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """校验并补全 LLM 返回的函数参数

    Args:
        arguments: LLM 返回的 dict（可能字段不全或枚举值非法）

    Returns:
        校验/补全后的 dict（缺失字段用默认值补全，非法枚举值用安全值替换）

    Raises:
        ValueError: 必填字段缺失
    """
    # 必填字段检查
    for required in ("sql", "chart_type", "insight"):
        if not arguments.get(required):
            raise ValueError(f"LLM 返回缺少必填字段: {required}")

    # ===== 类型校验 =====
    result = dict(arguments)

    # chart_type
    if result["chart_type"] not in VALID_CHART_TYPES:
        result["chart_type"] = "bar"  # 降级

    # aggregation（可选）
    agg = result.get("aggregation")
    if agg and agg not in VALID_AGGREGATIONS:
        result["aggregation"] = None

    # intent（可选）
    intent = result.get("intent")
    if intent and intent not in VALID_INTENTS:
        result["intent"] = "summary"

    # sort_order
    sort_order = result.get("sort_order")
    if sort_order not in VALID_SORT_ORDERS:
        result["sort_order"] = "desc" if intent in ("ranking", "trend") else None

    # limit
    if not isinstance(result.get("limit"), int):
        try:
            result["limit"] = int(result.get("limit") or 10)
        except (ValueError, TypeError):
            result["limit"] = 10

    # filters
    filters = result.get("filters") or []
    if not isinstance(filters, list):
        filters = []
    result["filters"] = [
        f for f in filters
        if isinstance(f, dict) and f.get("field") and f.get("op") in VALID_OPS and f.get("value") is not None
    ]

    # 默认值
    result.setdefault("explanation", "")
    result.setdefault("x_field", None)
    result.setdefault("y_field", None)
    result.setdefault("aggregation", None)
    result.setdefault("intent", "summary")

    return result


# ===== 模块暴露 =====
__all__ = [
    "EXECUTE_DATA_QUERY_FUNCTION",
    "VALID_CHART_TYPES",
    "VALID_AGGREGATIONS",
    "VALID_INTENTS",
    "VALID_SORT_ORDERS",
    "VALID_OPS",
    "validate_function_call",
]