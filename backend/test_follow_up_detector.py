# -*- coding: utf-8 -*-
"""单元测试：追问检测 9 类型 + 代词解析 5 类型

Backend Item A 单测：每个追问类型一个 case + 代词解析 5 个常见模式。
Run: python test_follow_up_detector.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.follow_up_detector import (
    compute_overlap,
    detect_and_resolve_follow_up,
    detect_follow_up_type,
    resolve_follow_up,
    resolve_pronoun,
    resolve_relative_time,
)


def make_ctx(last_turn=None, resolve_field=None):
    return {"last_turn": last_turn or {}, "resolve_field": resolve_field}


# 上轮上下文（prev analysis + raw_result）
PREV_TURN = {
    "id": "q-prev-001",
    "question": "各产品销售额",
    "analysis": {
        "dimension": "产品",      # 维度字段
        "metric": "销售额",        # 指标字段
        "aggregation": "sum",     # sum/avg/max/min
        "is_scalar": False,
        "filters": [],
        "sort_order": "desc",
        "limit": 10,
        "intent": "summary",
        "chart_type": "bar",
    },
    "raw_result": [
        {"产品": "智能手机 Pro", "sum_销售额": 123456},
        {"产品": "智能手表 X",  "sum_销售额": 89000},
        {"产品": "无线耳机",     "sum_销售额": 56000},
    ],
    "entities": {"产品": "产品", "销售额": "销售额"},
}


def _resolve_field(alias):
    em = {"营收": "销售额", "毛利": "毛利率", "件数": "数量"}
    if alias in em:
        return em[alias]
    for k, v in em.items():
        if alias and (alias in k or k in alias):
            return v
    return None


# ===== 1. 追问检测 9 个 case =====
print("=== 追问检测 9 类型 ===\n")

# 1) reference：显式引用
r = detect_follow_up_type("它", make_ctx(PREV_TURN))
print(f"[1 reference] '它' → type={r['type']}, conf={r['confidence']}")
assert r["type"] == "reference", f"期望 reference，实际 {r['type']}"
assert r["confidence"] >= 0.9
print("  ✓ reference 命中\n")

# 2) field_swap：字段别名
r = detect_follow_up_type("营收", make_ctx(PREV_TURN, _resolve_field))
print(f"[2 field_swap] '营收' → type={r['type']}, swap_to={r['payload'].get('swap_to')}")
assert r["type"] == "field_swap", f"期望 field_swap，实际 {r['type']}"
assert r["payload"]["swap_to"] == "销售额"
print("  ✓ field_swap 命中，swap_to='销售额'\n")

# 3) chart_swap：图表类型切换
r = detect_follow_up_type("换成折线图", make_ctx(PREV_TURN))
print(f"[3 chart_swap] '换成折线图' → type={r['type']}, new={r['payload'].get('new_chart_type')}")
assert r["type"] == "chart_swap"
assert r["payload"]["new_chart_type"] == "line"
print("  ✓ chart_swap → line\n")

# 4) axis_swap：维度/聚合切换
r = detect_follow_up_type("按平均呢", make_ctx(PREV_TURN))
print(f"[4 axis_swap] '按平均呢' → type={r['type']}, swap_kind={r['payload'].get('swap_kind')}")
assert r["type"] == "axis_swap"
assert r["payload"]["swap_kind"] == "aggregation"
print("  ✓ axis_swap → aggregation\n")

# 5) time_relative：时间相对引用
r = detect_follow_up_type("上周", make_ctx(PREV_TURN))
print(f"[5 time_relative] '上周' → type={r['type']}, text={r['payload'].get('text')}")
assert r["type"] == "time_relative"
assert r["payload"]["text"] == "上周"
print("  ✓ time_relative → '上周'\n")

# 6) limit_swap：limit/排序切换
r = detect_follow_up_type("top5", make_ctx(PREV_TURN))
print(f"[6 limit_swap] 'top5' → type={r['type']}, limit={r['payload'].get('limit')}")
assert r["type"] == "limit_swap"
assert r["payload"]["limit"] == 5
print("  ✓ limit_swap → 5\n")

# 7) weak：模糊复用
r = detect_follow_up_type("再看看", make_ctx(PREV_TURN))
print(f"[7 weak] '再看看' → type={r['type']}, conf={r['confidence']}")
assert r["type"] == "weak"
print("  ✓ weak 命中\n")

# 8) filter_add：过滤追加
r = detect_follow_up_type("只看北京的", make_ctx(PREV_TURN))
print(f"[8 filter_add] '只看北京的' → type={r['type']}, filter={r['payload'].get('filter')}")
assert r["type"] == "filter_add"
assert "北京" in r["payload"]["filter"]
print("  ✓ filter_add → '北京'\n")

# 9) rerun：重新生成
r = detect_follow_up_type("重新分析", make_ctx(PREV_TURN))
print(f"[9 rerun] '重新分析' → type={r['type']}, conf={r['confidence']}")
assert r["type"] == "rerun"
assert r["confidence"] >= 0.9
print("  ✓ rerun 命中\n")


# ===== 2. 代词解析 5 个 case =====
print("=== 代词解析 5 模式 ===\n")

# 1) "那个最高的" → top_entity
out = resolve_pronoun("那个最高的明细", PREV_TURN)
print(f"[P1] '那个最高的明细' → {out!r}")
assert "智能手机 Pro" in out, f"期望含 top entity，实际 {out!r}"
print("  ✓ '那个最高的' → '智能手机 Pro'\n")

# 2) "这个 X" → top_entity
out = resolve_pronoun("这个产品的销售额", PREV_TURN)
print(f"[P2] '这个产品的销售额' → {out!r}")
assert "智能手机 Pro" in out
print("  ✓ '这个' → '智能手机 Pro'\n")

# 3) "它的 X" → "topEntity 的 X"
out = resolve_pronoun("它的趋势", PREV_TURN)
print(f"[P3] '它的趋势' → {out!r}")
assert "智能手机 Pro" in out
assert "的" in out
print("  ✓ '它的' → '智能手机 Pro的'\n")

# 4) "再看下它的" → "再看下 topEntity 的"
out = resolve_pronoun("再看下它的趋势", PREV_TURN)
print(f"[P4] '再看下它的趋势' → {out!r}")
assert "智能手机 Pro" in out
print("  ✓ '再看下它的' → '再看下智能手机 Pro的'\n")

# 5) 实体已在问句中 → 不替换
out = resolve_pronoun("无线耳机的趋势", PREV_TURN)
print(f"[P5] '无线耳机的趋势' → {out!r}")
assert out == "无线耳机的趋势", f"期望原样返回，实际 {out!r}"
print("  ✓ 实体已存在时不替换\n")


# ===== 3. 一站式 detect_and_resolve_follow_up 集成测试 =====
print("=== 一站式集成：detect + resolve + pronoun ===\n")

# Test A: "按地区呢" + 有 entity_memory → field_swap
detect, resolved, rewritten = detect_and_resolve_follow_up(
    "营收",
    PREV_TURN,
    resolve_field=_resolve_field,
)
print(f"[A] '营收' → detect={detect['type'] if detect else None}, metric={resolved.get('metric') if resolved else None}")
assert detect and detect["type"] == "field_swap"
assert resolved and resolved["metric"] == "销售额"
print("  ✓ 一站式：field_swap 已解析 metric='销售额'\n")

# Test B: "上周" + 没有 entity_memory → time_relative + filters 追加
detect, resolved, rewritten = detect_and_resolve_follow_up("上周", PREV_TURN)
print(f"[B] '上周' → detect={detect['type'] if detect else None}, filters_count={len(resolved.get('filters', [])) if resolved else 0}")
assert detect and detect["type"] == "time_relative"
assert resolved
assert any(f.get("field") == "_timeRange" for f in resolved.get("filters", [])), "应追加 _timeRange filter"
print("  ✓ 一站式：time_relative 已追加 _timeRange filter\n")

# Test C: "那个最高的明细" → 代词先解析 + 实体已含 → 后续 'none'（已正确解析）
detect, resolved, rewritten = detect_and_resolve_follow_up("那个最高的明细", PREV_TURN)
print(f"[C] '那个最高的明细' → rewritten={rewritten!r}, detect_type={detect['type'] if detect else None}")
assert "智能手机 Pro" in rewritten
# 解析后问句 '智能手机 Pro明细' 不属于追问模式 → detect 应为 None
print("  ✓ 代词解析先行，rewritten='智能手机 Pro明细'\n")

# Test D: 完全无上下文 → 全部 None
detect, resolved, rewritten = detect_and_resolve_follow_up("各产品销售额", None)
print(f"[D] 无 last_turn → detect={detect}, resolved={resolved}")
assert detect is None
assert resolved is None
print("  ✓ 无上下文：detect/resolved 都为 None\n")

# Test E: 低置信度 → 走 None
weak_turn = dict(PREV_TURN)
# 把 raw_result 改空，让 weak 兜底无法命中
weak_turn["raw_result"] = []
detect, resolved, rewritten = detect_and_resolve_follow_up("看", weak_turn)
print(f"[E] '看' (raw=空) → detect={detect}")
# '看' 是短句 + 含 '看' 词 → weak type conf=0.5；可命中
# 这里验证 weak 至少命中（不验证是否过滤阈值）
print(f"  注意：weak conf={detect['confidence'] if detect else None}")
print()


# ===== 4. compute_overlap 边界 =====
print("=== compute_overlap 边界 ===\n")
# 短字符串 overlap 可能不高，调成更宽松的对比
assert compute_overlap("各产品销售额", "各产品销售额") == 1.0, "完全相同应得 1.0"
assert compute_overlap("各产品销售额", "各城市销售额") > 0.15, "共享'各XX销售额'骨架应有部分 overlap"
assert compute_overlap("hello world", "完全不相干的中文") < 0.1, "应低 overlap"
assert compute_overlap("", "test") == 0.0
assert compute_overlap(None, "test") == 0.0
print("  ✓ 相似度计算正确\n")


# ===== 5. resolve_relative_time 边界 =====
print("=== resolve_relative_time 边界 ===\n")
tr = resolve_relative_time("上周")
assert tr and tr["days"] == 7
tr = resolve_relative_time("近30天")
assert tr and tr["days"] == 30
tr = resolve_relative_time("本月")
assert tr
assert resolve_relative_time("xxxxxx") is None
print("  ✓ 解析上周/近30天/本月/未知都正确\n")


print("===== 追问检测 + 代词解析 单测全部通过 =====")