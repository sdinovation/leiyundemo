"""
rules_store.py — 规则存储与检索（Layer 1 + Layer 2 + Layer 4）

职责：
- add_rule(text, scope, category, keywords): 写入规则
- list_rules(scope): 列出某作用域下的所有启用规则
- retrieve_relevant_rules(question, scope, k=3): 基于问题检索 top-K 规则
- record_hit(rule_id) / record_miss(rule_id): 命中率统计（Layer 4）
- deduplicate(text): 同义规则去重（Layer 4）

性能约束：
- 单数据集最多 100 条规则（超出按 hit_count LRU 淘汰）
- 检索走内存缓存 + 关键词匹配（O(n)，n ≤ 100）

示例：
    store = RulesStore()
    store.add_rule("TOP 5 排除自己", scope="ds-001", category="ranking",
                   keywords=["TOP", "前 5", "排除"])
    rules = store.retrieve_relevant_rules("前 5 名销售额", scope="ds-001", k=3)
"""
import json
import logging
import re
from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import Dict, List, Optional, Set, Tuple

from models.database import db_session_scope as session_scope
from models.rule import Rule

logger = logging.getLogger(__name__)


# ===== 关键词提取 =====
# 中文停用词（不作为关键词）
_CN_STOPWORDS = {
    "的", "了", "和", "是", "在", "我", "有", "就", "不", "也", "都", "而",
    "及", "与", "或", "把", "被", "从", "到", "给", "让", "但", "而且",
    "所以", "因为", "如果", "虽然", "然后", "可以", "应该", "需要",
    "以后", "下次", "记住", "以后都", "以后请", "下次请",
}

# 触发短语（用于规则捕获的二次确认）
_RULE_TRIGGERS = (
    "以后记住", "下次记住", "以后", "下次", "记住", "请记",
    "以后都", "以后请", "下次请", "永远", "以后一律", "一律",
    "记住这个", "记住这条", "记住一下", "记一下",
)


# ===== LRU 上限 =====
_MAX_RULES_PER_SCOPE = 100


def _extract_keywords(text: str, max_keywords: int = 8) -> List[str]:
    """从规则文本里提取关键词

    策略：
    - 中文 2-gram 切分 + 英文单词
    - 过滤停用词
    - 按出现频次排序
    """
    if not text:
        return []

    text = str(text).strip()
    keywords: Dict[str, int] = {}

    # 1) 英文 / 数字单词（直接保留）
    for m in re.finditer(r"[A-Za-z]+|\d+", text):
        w = m.group(0)
        if len(w) >= 2:
            keywords[w.lower()] = keywords.get(w.lower(), 0) + 1

    # 2) 中文 2-gram
    cn_chars = re.sub(r"[^一-鿿]", " ", text)
    for i in range(len(cn_chars) - 1):
        c1, c2 = cn_chars[i], cn_chars[i + 1]
        if c1 == " " or c2 == " ":
            continue
        gram = c1 + c2
        if gram in _CN_STOPWORDS:
            continue
        keywords[gram] = keywords.get(gram, 0) + 1

    # 3) 中文 3-gram（更精确的短语）
    for i in range(len(cn_chars) - 2):
        c1, c2, c3 = cn_chars[i], cn_chars[i + 1], cn_chars[i + 2]
        if c1 == " " or c2 == " " or c3 == " ":
            continue
        gram = c1 + c2 + c3
        if gram in _CN_STOPWORDS:
            continue
        # 3-gram 权重更高
        keywords[gram] = keywords.get(gram, 0) + 2

    # 排序后取 top N
    sorted_kws = sorted(keywords.items(), key=lambda x: (-x[1], x[0]))
    return [k for k, _ in sorted_kws[:max_keywords]]


def _classify_rule(text: str) -> str:
    """根据规则文本推断 category"""
    t = text.lower()
    if any(kw in t for kw in ("top", "前", "排名", "排除", "包含")):
        return "ranking"
    if any(kw in t for kw in ("= ", "等于", "视为", "当作", "也叫", "别名")):
        return "alias"
    if any(kw in t for kw in ("过滤", "筛选", "只看", "排除", "不要")):
        return "filter"
    if any(kw in t for kw in ("聚合", "求和", "求平均", "按…计算")):
        return "aggregation"
    if any(kw in t for kw in ("图表", "画成", "用…显示", "格式")):
        return "format"
    return "other"


def _text_similarity(a: str, b: str) -> float:
    """两条规则文本的相似度（用于去重）

    策略：综合以下 3 项的最大值，避免单一指标漏判：
    1) 关键词 Jaccard（中文 2/3-gram + 英文）
    2) 原始文本 SequenceMatcher 比例（捕捉"等于"vs"="、"本周"vs"上周"）
    3) 字符级 Jaccard（短文本兜底）
    """
    if not a or not b:
        return 0.0
    a = str(a).strip()
    b = str(b).strip()
    if a == b:
        return 1.0

    # 1) 关键词 Jaccard
    kws_a = set(_extract_keywords(a))
    kws_b = set(_extract_keywords(b))
    kw_jaccard = 0.0
    if kws_a and kws_b:
        kw_jaccard = len(kws_a & kws_b) / len(kws_a | kws_b)

    # 2) 原始文本 SequenceMatcher
    sm = SequenceMatcher(None, a, b)
    seq_ratio = sm.ratio()

    # 3) 字符级 Jaccard（去停用词前）
    chars_a = set(c for c in a if not c.isspace())
    chars_b = set(c for c in b if not c.isspace())
    char_jaccard = 0.0
    if chars_a and chars_b:
        char_jaccard = len(chars_a & chars_b) / len(chars_a | chars_b)

    # 取三者最大值
    return max(kw_jaccard, seq_ratio, char_jaccard)


class RulesStore:
    """规则存储管理器（单例模式）"""

    _instance: Optional["RulesStore"] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._cache = {}  # {scope: [Rule, ...]}
            cls._instance._cache_ts = {}  # {scope: timestamp}
        return cls._instance

    # ===== Layer 1: 写入规则 =====
    def add_rule(
        self,
        text: str,
        scope: str = "global",
        category: Optional[str] = None,
        keywords: Optional[List[str]] = None,
        auto_dedup: bool = True,
    ) -> Dict[str, any]:
        """添加一条规则（自动去重 + 关键词提取 + LRU 淘汰）

        Args:
            text: 规则原文
            scope: 'global' 或具体 dataset_id
            category: 规则分类（None 自动推断）
            keywords: 触发关键词（None 自动提取）
            auto_dedup: 是否自动去重（同义规则会合并）

        Returns:
            {'rule': Rule, 'created': bool, 'merged_into': Optional[int]}
        """
        if not text or not str(text).strip():
            raise ValueError("规则文本不能为空")
        text = str(text).strip()
        if len(text) > 200:
            raise ValueError("规则文本超过 200 字限制")

        if category is None:
            category = _classify_rule(text)
        if keywords is None:
            keywords = _extract_keywords(text)

        with session_scope() as session:
            # 去重：scope 下找相似度 > 0.7 的同 category 规则
            if auto_dedup:
                existing = session.query(Rule).filter(
                    Rule.scope == scope,
                    Rule.enabled == True,
                ).all()
                for r in existing:
                    if r.category != category:
                        continue
                    sim = _text_similarity(text, r.text)
                    if sim > 0.6:
                        # 合并：把新文本 append 到老文本（保持历史）
                        merged_text = r.text + " | " + text
                        if len(merged_text) <= 200:
                            r.text = merged_text
                            # 合并关键词
                            old_kws = set(r.get_keywords())
                            new_kws = set(keywords)
                            r.set_keywords(list(old_kws | new_kws))
                            r.updated_at = datetime.now(timezone.utc)
                            session.commit()
                            logger.info(f"[RulesStore] 同义规则合并: id={r.id}, sim={sim:.2f}")
                            # 返回 dict 避免 detached
                            merged_rule = Rule(
                                id=r.id, scope=r.scope, category=r.category,
                                text=r.text, enabled=r.enabled,
                                hit_count=r.hit_count, miss_count=r.miss_count,
                                created_at=r.created_at, updated_at=r.updated_at,
                            )
                            merged_rule.pattern_keywords = r.pattern_keywords
                            return {
                                "rule": merged_rule,
                                "created": False,
                                "merged_into": r.id,
                            }

            # 新建规则
            rule = Rule(
                scope=scope,
                category=category,
                text=text,
                enabled=True,
                hit_count=0,
                miss_count=0,
            )
            rule.set_keywords(keywords)
            session.add(rule)
            session.commit()
            new_id = rule.id
            logger.info(f"[RulesStore] 新增规则: id={new_id}, scope={scope}, category={category}, text={text[:50]}")

            # 清理缓存
            self._cache.pop(scope, None)
            self._cache_ts.pop(scope, None)

            # LRU 淘汰
            self._evict_if_needed(scope, session)

            # 返回 dict（避免 detached instance 问题）
            new_rule = Rule(
                id=rule.id,
                scope=rule.scope,
                category=rule.category,
                text=rule.text,
                enabled=rule.enabled,
                hit_count=rule.hit_count,
                miss_count=rule.miss_count,
                created_at=rule.created_at,
                updated_at=rule.updated_at,
            )
            new_rule.pattern_keywords = rule.pattern_keywords
            return {
                "rule": new_rule,
                "created": True,
                "merged_into": None,
            }

    def _evict_if_needed(self, scope: str, session) -> None:
        """超上限时按 hit_count LRU 淘汰"""
        count = session.query(Rule).filter(
            Rule.scope == scope,
            Rule.enabled == True,
        ).count()
        if count <= _MAX_RULES_PER_SCOPE:
            return
        # 删除 hit_count 最低 + 最近最少更新的
        to_delete = count - _MAX_RULES_PER_SCOPE
        victims = session.query(Rule).filter(
            Rule.scope == scope,
            Rule.enabled == True,
        ).order_by(
            Rule.hit_count.asc(),
            Rule.updated_at.asc(),
        ).limit(to_delete).all()
        for v in victims:
            logger.info(f"[RulesStore] LRU 淘汰: id={v.id}, hit={v.hit_count}, text={v.text[:30]}")
            session.delete(v)
        session.commit()

    def delete_rule(self, rule_id: int) -> bool:
        """删除一条规则"""
        with session_scope() as session:
            rule = session.query(Rule).filter(Rule.id == rule_id).first()
            if not rule:
                return False
            scope = rule.scope
            session.delete(rule)
            session.commit()
            self._cache.pop(scope, None)
            return True

    def toggle_rule(self, rule_id: int, enabled: bool) -> bool:
        """启用 / 禁用规则"""
        with session_scope() as session:
            rule = session.query(Rule).filter(Rule.id == rule_id).first()
            if not rule:
                return False
            rule.enabled = enabled
            scope = rule.scope
            session.commit()
            self._cache.pop(scope, None)
            return True

    # ===== Layer 2: 检索相关规则 =====
    def list_rules(
        self,
        scope: str = "global",
        enabled_only: bool = True,
        max_age_seconds: int = 30,
    ) -> List[Rule]:
        """列出某作用域下的规则（带内存缓存）"""
        cache_key = f"{scope}:{enabled_only}"
        now = datetime.now(timezone.utc)
        if (
            cache_key in self._cache
            and cache_key in self._cache_ts
            and (now - self._cache_ts[cache_key]).total_seconds() < max_age_seconds
        ):
            return self._cache[cache_key]

        with session_scope() as session:
            q = session.query(Rule).filter(Rule.scope == scope)
            if enabled_only:
                q = q.filter(Rule.enabled == True)
            rules = q.order_by(Rule.hit_count.desc(), Rule.created_at.desc()).all()
            # 复制到缓存（session detach 后失效）
            cached = [
                Rule(
                    id=r.id, scope=r.scope, category=r.category,
                    text=r.text, enabled=r.enabled,
                    hit_count=r.hit_count, miss_count=r.miss_count,
                    created_at=r.created_at, updated_at=r.updated_at,
                )
                for r in rules
            ]
            # pattern_keywords 也需要单独存
            for c, r in zip(cached, rules):
                c.pattern_keywords = r.pattern_keywords

        self._cache[cache_key] = cached
        self._cache_ts[cache_key] = now
        return cached

    def retrieve_relevant_rules(
        self,
        question: str,
        scope: str = "global",
        k: int = 3,
    ) -> List[Rule]:
        """根据问题检索 top-K 相关规则

        匹配策略：
        1) 关键词命中：question 与 rule.pattern_keywords 的交集数
        2) 全文相似度：question 与 rule.text 的 SequenceMatcher 相似度
        3) 综合得分 = 关键词命中数 * 2 + 相似度 * 1
        """
        if not question:
            return []
        rules = self.list_rules(scope, enabled_only=True)
        if not rules:
            return []

        q_keywords = set(_extract_keywords(question, max_keywords=12))

        scored: List[Tuple[int, float, Rule]] = []
        for r in rules:
            r_keywords = set(r.get_keywords())
            # 关键词命中数
            keyword_hits = len(q_keywords & r_keywords)
            # 全文相似度
            sim = _text_similarity(question, r.text)
            score = keyword_hits * 2 + sim
            if score > 0:
                scored.append((score, sim, r))

        scored.sort(key=lambda x: (-x[0], -x[1]))
        return [r for _, _, r in scored[:k]]

    # ===== Layer 4: 命中率统计 =====
    def record_hit(self, rule_id: int) -> None:
        with session_scope() as session:
            rule = session.query(Rule).filter(Rule.id == rule_id).first()
            if rule:
                rule.hit_count += 1
                session.commit()

    def record_miss(self, rule_id: int) -> None:
        with session_scope() as session:
            rule = session.query(Rule).filter(Rule.id == rule_id).first()
            if rule:
                rule.miss_count += 1
                session.commit()

    # ===== 工具函数 =====
    @staticmethod
    def looks_like_rule_capture(text: str) -> bool:
        """判断用户输入是否包含「规则捕获」意图

        触发短语：以后记住 / 下次记住 / 记住 / 请记 / 永远 / 一律 ...
        """
        if not text:
            return False
        return any(trig in text for trig in _RULE_TRIGGERS)

    @staticmethod
    def extract_rule_text(text: str) -> str:
        """从用户输入中提取规则正文（去掉触发短语前缀）"""
        if not text:
            return ""
        t = str(text).strip()
        # 依次去掉触发短语前缀
        for trig in _RULE_TRIGGERS:
            if t.startswith(trig):
                t = t[len(trig):].lstrip("：:，,。 ").strip()
                break
        # 去掉尾部礼貌词
        t = re.sub(r"[。！？]+$", "", t).strip()
        return t or str(text).strip()


# 单例
rules_store = RulesStore()


__all__ = [
    "RulesStore",
    "rules_store",
    "Rule",
]