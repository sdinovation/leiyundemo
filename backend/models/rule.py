"""
rule.py — 用户自定义业务规则（Layer 1：规则学习能力）

设计目标：
- 用户在对话中说"以后记住 X=Y"或"下次 TOP 5 排除自己" → 自动写入本表
- 后续分析时由 rules_store.retrieve_relevant_rules() 检索 top-K 注入 prompt
- 与 entity_memory 并存：前者存字段别名，本表存业务规则

字段：
- id: 自增主键
- scope: 规则作用域（'global' / dataset_id）
- category: 规则分类（'alias' / 'filter' / 'aggregation' / 'ranking' / 'format' / 'other'）
- text: 规则原文（如 "TOP 5 排除自己"）
- pattern_keywords: 触发关键词（JSON list，用于检索）
- enabled: 是否启用
- hit_count / miss_count: 命中率统计（Layer 4 用）
- created_at / updated_at: 时间戳

约定：
- 单条 text 长度 ≤ 200 字
- 单数据集最多 100 条规则（超出按 LRU 淘汰）
"""
import json
import logging
from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, Index

from .database import Base

logger = logging.getLogger(__name__)


class Rule(Base):
    __tablename__ = "rules"

    id = Column(Integer, primary_key=True, autoincrement=True)
    # 规则作用域：'global' 表示所有数据集共享，否则存具体 dataset_id
    scope = Column(String(64), nullable=False, default="global", index=True)
    # 规则分类
    category = Column(String(32), nullable=False, default="other", index=True)
    # 规则原文
    text = Column(Text, nullable=False)
    # 触发关键词（JSON 字符串数组），用于检索匹配
    pattern_keywords = Column(Text, nullable=True)
    # 是否启用
    enabled = Column(Boolean, default=True, nullable=False)
    # 命中 / 未命中次数（Layer 4 用）
    hit_count = Column(Integer, default=0, nullable=False)
    miss_count = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    __table_args__ = (
        Index("idx_rules_scope_enabled", "scope", "enabled"),
    )

    def get_keywords(self) -> list:
        """解析 pattern_keywords JSON → list[str]"""
        if not self.pattern_keywords:
            return []
        try:
            kws = json.loads(self.pattern_keywords)
            return [str(k) for k in kws] if isinstance(kws, list) else []
        except (json.JSONDecodeError, TypeError):
            return []

    def set_keywords(self, kws: list) -> None:
        """设置关键词列表（序列化为 JSON）"""
        self.pattern_keywords = json.dumps(list(kws), ensure_ascii=False)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "scope": self.scope,
            "category": self.category,
            "text": self.text,
            "pattern_keywords": self.get_keywords(),
            "enabled": self.enabled,
            "hit_count": self.hit_count,
            "miss_count": self.miss_count,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }