"""
cache_entry.py — CacheEntry 模型（FAISS 语义缓存条目）

约定（doc02 §3 + doc04 §3）：
- question_hash = MD5(question + dataset_id)，用于 L1 精确匹配（加索引）
- question_vector = 384 维 float32 的二进制 BLOB（struct.pack 1536 bytes）
- similarity_score 记录最近一次命中时的相似度
- hit_count + last_hit_at 用于 LRU 淘汰策略
"""
import json
import struct
from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Text, Float, LargeBinary, DateTime, Index

from .database import Base


class CacheEntry(Base):
    __tablename__ = "cache_entries"

    id = Column(Integer, primary_key=True, autoincrement=True)
    dataset_id = Column(String(64), nullable=False, index=True)
    question = Column(Text, nullable=False)
    # MD5(question + dataset_id)，用于 L1 精确匹配快速查找
    question_hash = Column(String(32), nullable=False, index=True)
    # 384 维 float32 向量的二进制 BLOB（1536 bytes）
    question_vector = Column(LargeBinary, nullable=False)
    # 缓存的 SQL 语句
    sql_text = Column(Text, nullable=False)
    # 缓存的查询结果 JSON
    result_json = Column(Text, nullable=True)
    # 缓存的图表配置 JSON
    chart_config_json = Column(Text, nullable=True)
    # 缓存的洞察文字
    insight = Column(Text, nullable=True)
    # 最近一次命中的相似度分数（0-1）
    similarity_score = Column(Float, nullable=True)
    # 命中次数（用于 LRU 淘汰）
    hit_count = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    last_hit_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False, index=True)

    __table_args__ = (
        Index("idx_cache_dataset_hash", "dataset_id", "question_hash"),
        Index("idx_cache_dataset_hit", "dataset_id", "hit_count"),
    )

    VECTOR_DIM = 384

    @classmethod
    def encode_vector(cls, vector: list) -> bytes:
        """将 384 维 float 列表编码为二进制 BLOB"""
        assert len(vector) == cls.VECTOR_DIM, f"vector length must be {cls.VECTOR_DIM}"
        return struct.pack(f"{cls.VECTOR_DIM}f", *vector)

    @classmethod
    def decode_vector(cls, blob: bytes) -> list:
        """将二进制 BLOB 解码为 384 维 float 列表"""
        return list(struct.unpack(f"{cls.VECTOR_DIM}f", blob))

    def get_vector(self) -> list:
        return self.decode_vector(self.question_vector)

    def get_result(self) -> dict:
        return json.loads(self.result_json) if self.result_json else None

    def get_chart_config(self) -> dict:
        return json.loads(self.chart_config_json) if self.chart_config_json else None

    def to_cache_result(self) -> dict:
        """序列化为缓存命中结果（用于 API 响应）"""
        return {
            "sql": self.sql_text,
            "data": self.get_result(),
            "chart_config": self.get_chart_config(),
            "insight": self.insight,
            "cached": True,
            "cache_similarity": self.similarity_score,
            "hit_count": self.hit_count,
        }

    def increment_hit(self, similarity: float = None):
        """增加命中计数并更新最后命中时间"""
        self.hit_count += 1
        if similarity is not None:
            self.similarity_score = similarity
        self.last_hit_at = datetime.now(timezone.utc)