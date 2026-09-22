"""
semantic_cache.py — 两级语义缓存（L1 精确 + L2 FAISS）

设计要点（doc04 §3）：
- L1 精确匹配：MD5(question + dataset_id) → CacheEntry 表查询（< 5ms）
- L2 FAISS 语义匹配：余弦相似度 ≥ threshold → 命中（< 30ms）
- 写入：保存向量到 SQLite + 增量加入 FAISS 索引
- 失效：按 dataset_id 失效（重建该 dataset 的 FAISS 子索引）
- LRU 淘汰：超过 max_entries 时按 hit_count ASC + created_at ASC 淘汰
- 优雅降级：FAISS/Embedding 失败时仅用 L1 精确匹配

为什么是两级？
- L1（精确）：解决完全相同问题的快速命中（30-60% 命中率）
- L2（语义）：解决"问法不同但意图相同"的问题（目标 60%+ 总命中率）
- LLM 调用延迟 2-3s，缓存命中 < 50ms，加速 50x+

数据流：
  query(question, dataset_id)
    → L1 MD5 hash lookup
        → hit: return result
    → L2 encode + FAISS.search(k=1)
        → score ≥ threshold: load from SQLite, return
    → cache miss: caller invokes LLM, then store()
"""
import hashlib
import json
import logging
import os
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import numpy as np

from config import FAISS_CONFIG
from models.database import db_session_scope
from models.cache_entry import CacheEntry

from .embedding_model import get_embedding_model

logger = logging.getLogger(__name__)


# ===== 错误类型 =====
class CacheError(Exception):
    """缓存错误"""
    pass


class SemanticCache:
    """两级语义缓存（L1 + L2 FAISS）"""

    def __init__(self):
        self.threshold = FAISS_CONFIG["similarity_threshold"]
        self.max_entries = FAISS_CONFIG["max_entries"]
        self.index_path = FAISS_CONFIG["index_path"]
        self.mapping_path = FAISS_CONFIG["mapping_path"]

        # FAISS 索引（懒加载）
        self._index = None
        self._id_to_cache_id: Dict[int, int] = {}  # FAISS 内部 id → CacheEntry.id
        self._cache_id_to_faiss_id: Dict[int, int] = {}  # 反向映射
        self._next_faiss_id = 0

        # 锁（FAISS 索引非线程安全）
        self._lock = threading.RLock()

        # Embedding 模型（懒加载）
        self._embedding_model = None

    def _get_embedding_model(self):
        """懒加载 embedding 模型"""
        if self._embedding_model is None:
            self._embedding_model = get_embedding_model()
        return self._embedding_model

    def _ensure_index_loaded(self) -> bool:
        """懒加载 FAISS 索引（启动时从磁盘恢复）"""
        if self._index is not None:
            return True

        with self._lock:
            if self._index is not None:
                return True

            try:
                import faiss

                # 从磁盘加载（如有）
                if os.path.exists(self.index_path):
                    self._index = faiss.read_index(self.index_path)
                    self._next_faiss_id = self._index.ntotal
                    # 重建映射（从 SQLite 加载所有 CacheEntry 的 id 和向量）
                    self._rebuild_mapping_from_db()
                    logger.info(f"[SemanticCache] 从磁盘恢复 FAISS 索引: {self._next_faiss_id} 条")
                else:
                    # 新建空索引（IndexFlatIP = 内积 = 余弦相似度，因向量已归一化）
                    self._index = faiss.IndexFlatIP(self._get_embedding_model().vector_dim)
                    logger.info(f"[SemanticCache] 新建空 FAISS 索引")

                return True
            except ImportError:
                logger.error("[SemanticCache] faiss 未安装，L2 缓存不可用")
                return False
            except Exception as e:
                logger.error(f"[SemanticCache] 加载 FAISS 索引失败: {e}")
                self._index = None
                return False

    def _rebuild_mapping_from_db(self):
        """从 SQLite 重建 FAISS id ↔ CacheEntry.id 映射"""
        try:
            with db_session_scope() as session:
                entries = session.query(CacheEntry).order_by(CacheEntry.id.asc()).all()
                for i, entry in enumerate(entries):
                    self._id_to_cache_id[i] = entry.id
                    self._cache_id_to_faiss_id[entry.id] = i
                logger.info(f"[SemanticCache] 重建映射: {len(entries)} 条")
        except Exception as e:
            logger.warning(f"[SemanticCache] 重建映射失败: {e}")

    # ===== 查询 =====
    def lookup(self, question: str, dataset_id: str) -> Optional[Dict[str, Any]]:
        """查询缓存（L1 → L2）

        Args:
            question: 用户问题
            dataset_id: 数据集 ID

        Returns:
            缓存命中结果 dict（含 sql/data/chart_config/insight/cached/similarity）
            未命中返回 None
        """
        if not question or not dataset_id:
            return None

        question_hash = self._compute_hash(question, dataset_id)

        # ===== L1: 精确匹配 =====
        try:
            with db_session_scope() as session:
                entry = session.query(CacheEntry).filter_by(
                    dataset_id=dataset_id,
                    question_hash=question_hash,
                ).first()

                if entry:
                    entry.increment_hit(similarity=1.0)
                    session.flush()
                    logger.info(f"[SemanticCache] L1 命中: dataset={dataset_id}, hash={question_hash[:8]}")
                    result = entry.to_cache_result()
                    result["cache_level"] = "L1"
                    return result
        except Exception as e:
            logger.warning(f"[SemanticCache] L1 查询失败: {e}")

        # ===== L2: FAISS 语义匹配 =====
        return self._lookup_l2(question, dataset_id)

    def _lookup_l2(self, question: str, dataset_id: str) -> Optional[Dict[str, Any]]:
        """L2 FAISS 语义匹配"""
        model = self._get_embedding_model()
        if not model.is_loaded():
            if not model._ensure_loaded():
                logger.debug("[SemanticCache] Embedding 模型未加载，跳过 L2")
                return None

        # 1. 编码问题
        vector = model.encode(question)
        if vector is None:
            return None

        # 2. 加载索引
        if not self._ensure_index_loaded():
            return None

        # 3. FAISS 搜索 k=1
        try:
            with self._lock:
                if self._index is None or self._index.ntotal == 0:
                    return None

                # reshape 为 [1, dim]
                query_vec = vector.reshape(1, -1).astype(np.float32)
                scores, faiss_ids = self._index.search(query_vec, k=1)

                if len(scores) == 0 or len(faiss_ids) == 0:
                    return None

                top_score = float(scores[0][0])
                top_faiss_id = int(faiss_ids[0][0])

                # 4. 相似度阈值过滤
                if top_score < self.threshold:
                    logger.debug(f"[SemanticCache] L2 未命中: score={top_score:.4f} < threshold={self.threshold}")
                    return None

                # 5. FAISS id → CacheEntry.id
                cache_id = self._id_to_cache_id.get(top_faiss_id)
                if cache_id is None:
                    logger.warning(f"[SemanticCache] FAISS id {top_faiss_id} 无映射")
                    return None

                # 6. 从 SQLite 加载 CacheEntry，且 dataset_id 必须匹配（防跨数据集误命中）
                with db_session_scope() as session:
                    entry = session.query(CacheEntry).filter_by(id=cache_id).first()
                    if entry is None or entry.dataset_id != dataset_id:
                        return None

                    entry.increment_hit(similarity=top_score)
                    session.flush()
                    logger.info(
                        f"[SemanticCache] L2 命中: dataset={dataset_id}, "
                        f"score={top_score:.4f}, cache_id={cache_id}"
                    )
                    result = entry.to_cache_result()
                    result["cache_level"] = "L2"
                    return result

        except Exception as e:
            logger.warning(f"[SemanticCache] L2 查询失败: {e}")
            return None

    # ===== 写入 =====
    def store(
        self,
        question: str,
        dataset_id: str,
        sql: str,
        result: Dict[str, Any],
        chart_config: Optional[Dict[str, Any]] = None,
        insight: Optional[str] = None,
    ) -> bool:
        """写入缓存

        Args:
            question: 用户问题
            dataset_id: 数据集 ID
            sql: SQL 语句
            result: 查询结果 {columns, rows, row_count}
            chart_config: 图表配置（可选）
            insight: 洞察文字（可选）

        Returns:
            True if stored successfully
        """
        if not question or not dataset_id or not sql:
            logger.warning("[SemanticCache] store 跳过：缺少必要字段")
            return False

        # 1. 计算 hash + 向量
        question_hash = self._compute_hash(question, dataset_id)

        vector = None
        model = self._get_embedding_model()
        if model.is_loaded() or model._ensure_loaded():
            vector = model.encode(question)

        if vector is None:
            logger.warning("[SemanticCache] store 跳过：embedding 失败")
            return False

        # 2. 写入 SQLite
        try:
            vector_bytes = CacheEntry.encode_vector(vector.tolist())

            with db_session_scope() as session:
                # 检查是否已存在（避免重复）
                existing = session.query(CacheEntry).filter_by(
                    dataset_id=dataset_id,
                    question_hash=question_hash,
                ).first()

                if existing:
                    # 更新现有条目（不增加 hit_count）
                    existing.sql_text = sql
                    existing.result_json = json.dumps(result, ensure_ascii=False)
                    existing.chart_config_json = json.dumps(chart_config, ensure_ascii=False) if chart_config else None
                    existing.insight = insight
                    cache_id = existing.id
                    logger.info(f"[SemanticCache] 更新缓存: cache_id={cache_id}")
                else:
                    entry = CacheEntry(
                        dataset_id=dataset_id,
                        question=question,
                        question_hash=question_hash,
                        question_vector=vector_bytes,
                        sql_text=sql,
                        result_json=json.dumps(result, ensure_ascii=False),
                        chart_config_json=json.dumps(chart_config, ensure_ascii=False) if chart_config else None,
                        insight=insight,
                    )
                    session.add(entry)
                    session.flush()
                    cache_id = entry.id
                    logger.info(f"[SemanticCache] 新增缓存: cache_id={cache_id}")

                # 3. 加入 FAISS 索引（仅在 SQLite 成功提交后）
                self._add_to_faiss(vector, cache_id)

                # 4. 检查是否超过 max_entries（LRU 淘汰）
                self._maybe_evict(session)

                return True

        except Exception as e:
            logger.error(f"[SemanticCache] store 失败: {e}")
            return False

    def _add_to_faiss(self, vector: np.ndarray, cache_id: int):
        """添加向量到 FAISS 索引"""
        if not self._ensure_index_loaded():
            return

        try:
            with self._lock:
                if cache_id in self._cache_id_to_faiss_id:
                    # 已存在（重复 store），不重复添加
                    return

                vec = vector.reshape(1, -1).astype(np.float32)
                self._index.add(vec)

                faiss_id = self._next_faiss_id
                self._next_faiss_id += 1

                self._id_to_cache_id[faiss_id] = cache_id
                self._cache_id_to_faiss_id[cache_id] = faiss_id

                logger.debug(f"[SemanticCache] FAISS 添加: faiss_id={faiss_id}, cache_id={cache_id}, total={self._index.ntotal}")
        except Exception as e:
            logger.warning(f"[SemanticCache] FAISS add 失败: {e}")

    # ===== 失效 =====
    def invalidate_by_dataset(self, dataset_id: str) -> int:
        """失效指定数据集的所有缓存

        Args:
            dataset_id: 数据集 ID

        Returns:
            删除的条目数
        """
        try:
            with db_session_scope() as session:
                entries = session.query(CacheEntry).filter_by(dataset_id=dataset_id).all()
                deleted_count = len(entries)

                # 收集需要从 FAISS 移除的 cache_id
                cache_ids = [e.id for e in entries]

                # 从 SQLite 删除
                session.query(CacheEntry).filter_by(dataset_id=dataset_id).delete()

                # 从 FAISS 重建（FAISS 不支持单条删除）
                self._rebuild_faiss_index(session)

                logger.info(f"[SemanticCache] 失效 dataset={dataset_id}, 删除 {deleted_count} 条")
                return deleted_count
        except Exception as e:
            logger.error(f"[SemanticCache] 失效失败: {e}")
            return 0

    def _rebuild_faiss_index(self, session):
        """重建 FAISS 索引（失效后调用）"""
        try:
            import faiss

            with self._lock:
                # 1. 收集所有剩余 CacheEntry
                remaining = session.query(CacheEntry).order_by(CacheEntry.id.asc()).all()

                # 2. 重置索引
                self._index = faiss.IndexFlatIP(self._get_embedding_model().vector_dim)
                self._id_to_cache_id.clear()
                self._cache_id_to_faiss_id.clear()
                self._next_faiss_id = 0

                # 3. 重新添加所有向量
                for i, entry in enumerate(remaining):
                    vector = np.array(entry.get_vector(), dtype=np.float32)
                    self._index.add(vector.reshape(1, -1))
                    self._id_to_cache_id[i] = entry.id
                    self._cache_id_to_faiss_id[entry.id] = i
                    self._next_faiss_id += 1

                logger.info(f"[SemanticCache] FAISS 重建: {self._next_faiss_id} 条")
        except Exception as e:
            logger.error(f"[SemanticCache] FAISS 重建失败: {e}")

    # ===== LRU 淘汰 =====
    def _maybe_evict(self, session):
        """检查是否超过 max_entries，是则淘汰"""
        try:
            total = session.query(CacheEntry).count()
            if total <= self.max_entries:
                return

            # 按 hit_count ASC, created_at ASC 淘汰
            evict_count = total - self.max_entries
            evict_candidates = (
                session.query(CacheEntry)
                .order_by(CacheEntry.hit_count.asc(), CacheEntry.created_at.asc())
                .limit(evict_count)
                .all()
            )

            evict_ids = [e.id for e in evict_candidates]
            for e in evict_candidates:
                session.delete(e)

            logger.info(f"[SemanticCache] LRU 淘汰: 删除 {len(evict_ids)} 条（总 {total} → {self.max_entries}）")

            # 重建 FAISS
            self._rebuild_faiss_index(session)
        except Exception as e:
            logger.warning(f"[SemanticCache] LRU 淘汰失败: {e}")

    # ===== 统计 =====
    def stats(self) -> Dict[str, Any]:
        """获取缓存统计信息

        Returns:
            {total_entries, l1_hits, l2_hits, l1_hit_rate, l2_hit_rate,
             threshold, index_size, embedding_loaded}
        """
        try:
            with db_session_scope() as session:
                total = session.query(CacheEntry).count()

                # 按 hit_count 计算（简化：所有条目 hit_count 之和）
                total_hits = session.query(CacheEntry).with_entities(
                    CacheEntry.hit_count
                ).all()
                total_hits = sum(h[0] for h in total_hits)

                # FAISS 索引大小
                index_size = self._index.ntotal if self._index is not None else 0

                return {
                    "total_entries": total,
                    "max_entries": self.max_entries,
                    "total_hits": total_hits,
                    "threshold": self.threshold,
                    "index_size": index_size,
                    "embedding_loaded": self._embedding_model is not None and self._embedding_model.is_loaded(),
                }
        except Exception as e:
            logger.warning(f"[SemanticCache] stats 失败: {e}")
            return {
                "total_entries": 0,
                "max_entries": self.max_entries,
                "total_hits": 0,
                "threshold": self.threshold,
                "index_size": 0,
                "embedding_loaded": False,
                "error": str(e),
            }

    # ===== 工具 =====
    @staticmethod
    def _compute_hash(question: str, dataset_id: str) -> str:
        """计算 L1 精确匹配的 MD5 hash"""
        key = f"{dataset_id}::{question.strip().lower()}"
        return hashlib.md5(key.encode("utf-8")).hexdigest()

    def save_index(self):
        """手动保存 FAISS 索引到磁盘（可选，进程退出时会自动调）"""
        try:
            if self._index is not None:
                import faiss
                faiss.write_index(self._index, self.index_path)
                logger.info(f"[SemanticCache] FAISS 索引已保存: {self.index_path}")
        except Exception as e:
            logger.warning(f"[SemanticCache] 保存 FAISS 索引失败: {e}")


# ===== 模块单例 =====
_cache_instance: Optional[SemanticCache] = None
_cache_lock = threading.Lock()


def get_semantic_cache() -> SemanticCache:
    """获取 SemanticCache 单例"""
    global _cache_instance
    if _cache_instance is None:
        with _cache_lock:
            if _cache_instance is None:
                _cache_instance = SemanticCache()
    return _cache_instance


# ===== 模块暴露 =====
__all__ = [
    "SemanticCache",
    "CacheError",
    "get_semantic_cache",
]
