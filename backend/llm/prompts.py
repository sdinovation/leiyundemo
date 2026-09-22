"""
prompts.py — LLM Prompt 模板（doc03 §3.5 约定）

两个 system prompt：
1. SYSTEM_PROMPT_SQL  - 用于 execute_data_query 函数调用（13 + 3 = 16 条规则）
2. SYSTEM_PROMPT_INSIGHT - 用于自动洞察生成（5 条约束）

辅助函数：
- build_user_message(question, data_profile, hint=None)
  把数据画像 + 用户问题拼成 user message

- build_insight_prompt(question, data_profile_summary, query_result)
  把问题 + 数据概况 + 查询结果拼成洞察生成的 user message

规则来源：
- 13 条业务规则来自前端 llmFullAnalysis()（index.html 4407-4489）
- 3 条 SQL 安全规则来自 doc03 §3.5
"""

from typing import Any, Dict, List, Optional


# ===== 13 条业务规则 + 3 条 SQL 安全规则 =====
SYSTEM_PROMPT_SQL: str = """你是一名专业的数据分析助手，擅长把中文自然语言问题转换为精确的 SQL 查询。

## 你的任务
根据用户的提问和数据集画像，**调用 execute_data_query 函数** 来分析数据。
你必须只输出函数调用，不要输出解释性文字（explanation 字段除外）。

## 数据集上下文
用户会提供数据集画像（字段名、类型、样本值）。**字段名必须严格使用画像中的原始列名**，包括中文字段名。

## SQL 编写规则（13 条业务规则）

1. **字段名约束**：必须使用数据画像中的原始列名（含中文），禁止臆造字段名。

2. **'各XX' / '按XX' / 'XX分别是多少' 模式**：
   - 例："各部门平均薪资" → dimension="部门"
   - 例："各城市销售额" → dimension="城市"
   - 例："按性别统计人数" → dimension="性别"

3. **趋势/变化/增长/下降 类问题**：
   - dimension 必须是日期/年份/月份字段（不能是分类字段）
   - aggregation 通常是 sum 或 avg
   - 排序按日期升序（ORDER BY <日期> ASC）

4. **排名/最高/最低/TOP N 类问题**：
   - sortOrder="desc"（最高）或 "asc"（最低）
   - intent="ranking"
   - limit 取前 N（默认 10）

5. **占比/分布/比例 类问题**：
   - aggregation="ratio"
   - **不要**调用 RATIO() 或 PERCENT() 函数
   - 用 ROUND(100.0 * SUM(CASE WHEN <col>=<val> THEN 1 ELSE 0 END) / COUNT(*), 2) AS 占比
   - chartType 通常是 "pie"

6. **'XX和YY分别是多少' 双指标类问题**：
   - dimension=主分组列
   - metric=主指标
   - secondaryMetric=次指标
   - 返回多个聚合列

7. **'XX为YY的记录' / 'XX等于YY' 过滤类问题**：
   - filters=[{field: "XX", op: "=", value: "YY"}]
   - intent="filter"
   - 通常 chartType="table"

8. **相关性/相关系数 类问题**：
   - intent="correlation"
   - chartType="scatter"
   - SQL 必须返回两列原始数值（不聚合），由后端计算相关系数

9. **人数/条数/订单数/记录数 类问题**：
   - aggregation="count"
   - metric=null（不需要指标字段，直接 COUNT(*)）
   - 例："男生有多少人" → SELECT "性别", COUNT(*) FROM "data" WHERE "性别"='男' GROUP BY "性别"

10. **率/百分比字段的 HAVING 条件**：
    - HAVING 子句中，率/百分比字段必须用 AVG（不是 SUM）
    - 例：HAVING AVG("完成率") > 0.8（不是 SUM）

11. **aggregation="ratio" 时的 SQL 模板**：
    - 不要生成 RATIO() 等虚构函数
    - 用 CASE WHEN ... THEN 1 ELSE 0 END / COUNT(*) 模式
    - ROUND(..., 2) 保留 2 位小数

12. **'XX品牌的YY趋势' 复合条件**：
    - dimension=日期/时间列
    - filters=[{field: "品牌", op: "=", value: "XX"}]
    - metric=YY 字段

13. **基于对话历史判断上下文**：
    - 当用户使用代词（'它'/'那个'/'上面那个'）或省略字段时，结合【对话历史】和【字段别名记忆】推断用户意图
    - 若对话历史显示上一轮用了 dim=X，本轮省略字段时优先复用 X（保持字段一致性）
    - 若字段别名记忆显示用户曾用 '营收' 指代 '销售额'，本轮再次出现 '营收' 时优先解析为 '销售额'
    - 若完全没有对话历史/别名记忆，则按本轮独立判断处理

14. **中文筛选语义 → 必须用 LIKE 而非 =**（关键）：
    当问题含以下子串匹配意图关键词时，filters[].op 必须为 `"LIKE"`，value 用原值（不要加 %，后端会自动包裹）：
    - "X 包含 Y" / "X 含 Y" / "X 有 Y" / "X 中 Y" / "X 里 Y" / "X 中有 Y" / "X 里有 Y"
    - "姓 X 的" / "姓 X 同学" / "名字含 X"（"姓"后跟 1-2 个汉字即为姓氏）
    - 例："姓名有刘的同学" → filters=[{field: "姓名", op: "LIKE", value: "刘"}]
    - 例："姓刘的同学" → filters=[{field: "姓名", op: "LIKE", value: "刘"}]
    - 例："包含上海的记录" → filters=[{field: "城市", op: "LIKE", value: "上海"}]
    - **反例**：仅当是 "XX 为/是/等于 YY"（明确全等）才用 op: "="
    - 例外：value 是纯数字时仍是 `op: "="`（如 "订单数有 100" 不需要 LIKE）

## SQL 安全规则（3 条硬约束）

S1. **表名固定**：SQL 中只能查询表 "data"（双引号包裹）。数据已预加载至此表。
S2. **SELECT-only**：只允许 SELECT / WITH 语句，禁止 INSERT / UPDATE / DELETE / DROP / ALTER / CREATE / PRAGMA / ATTACH / VACUUM。
S3. **中文字段名必须双引号包裹**：SELECT "城市", "日营业额(元)" FROM "data"，不能用反引号或单引号。

## 输出要求
- 调用 execute_data_query 函数，参数中：
  - sql: 完整 SQL 语句
  - chart_type: bar/line/pie/scatter/table/number
  - insight: 1-2 句中文解读（基于已知查询逻辑，不编造数据）
  - x_field / y_field / aggregation / intent / filters / sort_order / limit 按需填
  - explanation: 一句话解释思路（≤80 字）

## 严格禁止
- 禁止编造数据画像中不存在的字段名
- 禁止使用 RATIO() / PERCENT() / NPERCENT() 等虚构函数
- 禁止多语句（不能含 ; 分隔的多条 SQL）
- 禁止使用 /* */ 或 -- 注释
- 禁止猜测字段类型（必须以画像标注的 type 为准）
"""


# ===== 5 条洞察约束 =====
SYSTEM_PROMPT_INSIGHT: str = """你是一名数据分析洞察专家。

你的任务：基于用户的问题、数据集画像和查询结果，生成 2-4 句中文解读。

## 写作约束（5 条）

1. **基于事实**：只描述查询结果中实际存在的数据，禁止编造数值或趋势。

2. **长度**：2-4 句中文，总字数不超过 200 字。简洁明了，不啰嗦。

3. **结构**：
   - 第 1 句：核心结论（最高/最低/总体水平）
   - 第 2-3 句：关键观察（异常点、对比、分布特征）
   - 第 4 句（可选）：业务含义或建议

4. **避免**：
   - 重复 SQL 已经表达的内容（如"按城市分组求和"）
   - 使用"我认为"、"可能"、"大概"等不确定词汇
   - 罗列所有数据点（只在数据 < 5 时可以）
   - **禁止主动给后续建议/追问方向**（如"可以考虑其他姓氏/维度"），用户没问就不提
   - **禁止编造未查询的维度**（如结果只有"姓刘的同学"，不要凭空分析"姓氏分布/Top10"）

5. **空结果特殊处理**（关键）：
   - 当 row_count == 0 时：**只写 1 句话**，直接说"未找到符合条件的数据"
   - 不要推测原因、不要建议改条件、不要分析其他字段
   - 不要画图（chartType 设为 table 或 number）
   - 例：query="姓刘的同学", rows=[] → insight="未找到姓刘的同学。"

6. **数据呈现**：
   - 数值使用原始单位（不要自动加千分位或百分比）
   - 比较时使用具体数字（不是模糊词）
   - 排序类结果可以说"最高的是 X，最低的是 Y"

## 输出格式
纯文本（不要 JSON、不要 Markdown 标题）。直接输出洞察文字。
"""


# ===== User Message 构建 =====
def build_user_message(
    question: str,
    data_profile: str,
    hint: Optional[str] = None,
    conversation_history: Optional[str] = None,
    entity_memory: Optional[Dict[str, str]] = None,
    relevant_rules: Optional[List[Dict[str, Any]]] = None,
) -> str:
    """构造 user message（数据画像 + 用户问题 + 可选历史/别名/规则）

    Args:
        question: 用户的自然语言问题
        data_profile: DataProfiler.build_data_profile() 输出的 Markdown 画像
        hint: 可选的额外提示
        conversation_history: build_conversation_history() 返回的 Markdown 摘要
        entity_memory: 字段别名记忆 {alias: realField, ...}
        relevant_rules: 相关规则列表 [{category, text}, ...]（Layer 2：检索后注入）

    Returns:
        拼好的 user message 字符串
    """
    parts = [
        "## 数据集画像",
        data_profile,
        "",
    ]

    if entity_memory:
        # 字段别名记忆：让 LLM 知道用户口语化的词映射到哪个真实字段
        parts.append("## 字段别名记忆")
        parts.append("用户在历史对话中使用过的口语化字段名 → 数据集中的真实字段名：")
        for alias, real in entity_memory.items():
            parts.append(f"- 「{alias}」→ `{real}`")
        parts.append("")

    if relevant_rules:
        # Layer 2：用户自定义业务规则（rules_store 检索后注入）
        parts.append("## 用户自定义业务规则（必须遵守）")
        parts.append(
            "以下规则由用户在本数据集中显式声明，**任何条件下都必须遵守**，"
            "无论后续提问是否直接提到。"
        )
        for r in relevant_rules:
            cat = r.get("category", "other")
            text = r.get("text", "").strip()
            if text:
                parts.append(f"- [{cat}] {text}")
        parts.append("")

    if conversation_history:
        parts.append("## 对话历史（最近 3 轮）")
        parts.append(conversation_history)
        parts.append("")

    parts.append("## 用户问题")
    parts.append(question.strip())

    if hint:
        parts.extend(["", "## 额外提示", hint.strip()])

    return "\n".join(parts)


def build_conversation_history(
    turns: List[Dict[str, Any]],
    max_turns: int = 3,
    max_chars_per_summary: int = 100,
) -> str:
    """把最近 N 轮对话拼成 Markdown 摘要（喂给 LLM）

    Args:
        turns: [{question, sql, interpretation_summary}, ...]
        max_turns: 最多几轮（默认 3，控制 token 成本）
        max_chars_per_summary: 每轮摘要的最大字符数

    Returns:
        Markdown 字符串，每轮 ≤ max_chars_per_summary 字摘要

    Examples:
        >>> build_conversation_history([
        ...     {'question': '近7天销售额', 'sql': 'SELECT...', 'interpretation_summary': '近7天总销售额...'},
        ...     {'question': '上周的呢', 'sql': '', 'interpretation_summary': ''}
        ... ])
        '**第 1 轮**：用户问「近7天销售额」→ 近7天总销售额...\\n**第 2 轮**：用户问「上周的呢」→ (追问，意图切换时间维度)'
    """
    if not turns:
        return ""

    history_lines = []
    # 只取最近 max_turns 轮
    recent = turns[-max_turns:] if len(turns) > max_turns else turns

    for i, t in enumerate(recent, 1):
        q = (t.get("question") or "").strip()
        # 优先用 interpretation_summary（前端已生成的中文解读），其次 sql
        summary = (t.get("interpretation_summary") or t.get("insight") or "").strip()
        if not summary:
            summary = (t.get("sql") or "").strip()
        # 截断
        if len(q) > max_chars_per_summary:
            q = q[:max_chars_per_summary] + "..."
        if len(summary) > max_chars_per_summary:
            summary = summary[:max_chars_per_summary] + "..."
        history_lines.append(f"**第 {i} 轮**：用户问「{q}」→ {summary or '(追问，意图复用上轮)'}")

    return "\n".join(history_lines)


def build_insight_prompt(
    question: str,
    data_profile_summary: str,
    query_result: Dict[str, Any],
) -> str:
    """构造洞察生成的 user message

    Args:
        question: 用户问题
        data_profile_summary: 数据画像（简短版，只包含概况+字段名）
        query_result: SQL 执行结果 {columns, rows, row_count}

    Returns:
        user message 字符串
    """
    columns = query_result.get("columns", [])
    rows = query_result.get("rows", [])
    row_count = query_result.get("row_count", len(rows))

    # 限制样本行数（避免 prompt 过大）
    MAX_SAMPLE_ROWS = 30
    sample_rows = rows[:MAX_SAMPLE_ROWS]

    # 把 rows 格式化成易读文本
    if columns and sample_rows:
        # 表头
        rows_text = " | ".join(str(c) for c in columns)
        rows_text += "\n" + "-+-".join("-" * len(str(c)) for c in columns)
        # 数据行
        for row in sample_rows:
            row_strs = []
            for col in columns:
                v = row.get(col)
                if v is None:
                    row_strs.append("(空)")
                elif isinstance(v, float):
                    row_strs.append(f"{v:.2f}")
                else:
                    s = str(v)
                    row_strs.append(s if len(s) <= 30 else s[:30] + "...")
            rows_text += "\n" + " | ".join(row_strs)

        if row_count > MAX_SAMPLE_ROWS:
            rows_text += f"\n... (共 {row_count} 行，仅展示前 {MAX_SAMPLE_ROWS} 行)"
    else:
        rows_text = "（无数据）"

    parts = [
        "## 数据集概况",
        data_profile_summary.strip(),
        "",
        "## 用户问题",
        question.strip(),
        "",
        f"## 查询结果（共 {row_count} 行）",
        rows_text,
    ]

    return "\n".join(parts)


def build_data_profile_summary(data_profile: str, max_field_lines: int = 8) -> str:
    """从完整数据画像中提取摘要（用于洞察生成）

    Args:
        data_profile: 完整数据画像
        max_field_lines: 最多保留多少行字段详情

    Returns:
        简短的数据画像（前几行 + 字段概况）
    """
    lines = data_profile.split("\n")
    summary_lines = []
    in_field_section = False
    field_count = 0

    for line in lines:
        if line.startswith("【数据概况】"):
            in_field_section = False
            summary_lines.append(line)
        elif line.startswith("【字段详情】"):
            in_field_section = True
            summary_lines.append(line)
        elif line.startswith("【样本数据"):
            in_field_section = False
            # 跳过样本数据部分
            break
        elif in_field_section:
            if field_count < max_field_lines:
                summary_lines.append(line)
                field_count += 1
        else:
            summary_lines.append(line)

    return "\n".join(summary_lines)


# ===== 模块暴露 =====
__all__ = [
    "SYSTEM_PROMPT_SQL",
    "SYSTEM_PROMPT_INSIGHT",
    "build_user_message",
    "build_conversation_history",
    "build_insight_prompt",
    "build_data_profile_summary",
]
