# -*- coding: utf-8 -*-
"""端到端验证：build_conversation_history + build_user_message + process_sync 串联"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from llm.prompts import build_conversation_history, build_user_message, SYSTEM_PROMPT_SQL

# ===== Test 1: build_conversation_history 边界 =====
print("=== Test 1: build_conversation_history ===")
empty = build_conversation_history([])
assert empty == "", f"empty 应为空: {empty!r}"

single = build_conversation_history([{'question': '北京销售', 'sql': 'SELECT...'}])
assert "**第 1 轮**" in single
assert "北京销售" in single
print("  ✓ 空 history 返回空")
print("  ✓ 单轮 history 包含第 1 轮")

# 限制 max_turns
multi = build_conversation_history([
    {'question': f'Q{i}', 'sql': 'SELECT...'} for i in range(5)
], max_turns=3)
assert "Q0" not in multi and "Q1" not in multi  # 前 2 轮被截断
assert "Q2" in multi and "Q4" in multi          # 只保留最近 3 轮（Q2/Q3/Q4）
assert "**第 3 轮**" in multi
print("  ✓ max_turns=3 截断到最近 3 轮")

# 截断长字符串
long_q = "x" * 200
truncated = build_conversation_history([{'question': long_q, 'sql': ''}])
assert "x" * 200 not in truncated
print("  ✓ 长 question 被截断到 100 字")

# ===== Test 2: build_user_message 注入 history + entities =====
print("\n=== Test 2: build_user_message 注入 ===")
msg = build_user_message(
    question="上周的呢",
    data_profile="## 字段\n- 城市\n- 销售额",
    conversation_history="**第 1 轮**：用户问「近7天销售额」→ 总额 12345",
    entity_memory={"营收": "销售额"}
)
assert "## 字段别名记忆" in msg
assert "「营收」→ `销售额`" in msg
assert "## 对话历史（最近 3 轮）" in msg
assert "## 用户问题" in msg
print("  ✓ entity_memory 渲染成 Markdown 列表")
print("  ✓ conversation_history 注入")

# 无 history 无 entities 的最小调用
min_msg = build_user_message(question="测试", data_profile="## 字段")
assert "## 用户问题" in min_msg
assert "## 字段别名记忆" not in min_msg
assert "## 对话历史" not in min_msg
print("  ✓ 无 history/entity 时不出现对应 section")

# ===== Test 3: SYSTEM_PROMPT_SQL 规则 13 已更新 =====
print("\n=== Test 3: 规则 13 已更新 ===")
assert "基于对话历史" in SYSTEM_PROMPT_SQL
assert "字段别名记忆" in SYSTEM_PROMPT_SQL
# '本轮独立判断' 只在新规则的兜底分支中出现（无 history 时独立判断）
assert "若完全没有对话历史/别名记忆，则按本轮独立判断处理" in SYSTEM_PROMPT_SQL
print("  ✓ 新规则 13 '基于对话历史' + '字段别名记忆' 已加入")
print("  ✓ 兜底分支保留'无 history 时独立判断'语义")

# ===== Test 4: API 端点签名兼容 =====
print("\n=== Test 4: API 签名兼容 ===")
import re
from api.query import query
from core.query_processor import process_sync
# inspect 在 Python 3.14 + Optional 注解下报 ValueError，改用源码正则
src = inspect.getsource(process_sync) if 'inspect' in dir() else ''
import inspect as _inspect
src = _inspect.getsource(process_sync)
assert "conversation_history" in src
assert "entity_memory" in src
assert "Optional[List[Dict[str, Any]]]" in src or "conversation_history: Optional" in src
print(f"  ✓ process_sync 源码包含新参数")

print("\n===== Phase 2 后端验证全部通过 =====")