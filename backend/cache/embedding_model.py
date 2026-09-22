"""
embedding_model.py — Sentence Transformers 嵌入模型封装

设计要点（doc04 §2）：
- 单例模式（启动时预加载一次，避免每次调用都加载）
- 使用 paraphrase-multilingual-MiniLM-L12-v2（120MB，多语言，384 维）
- encode(text) → numpy 数组（384 维 float32，已 L2 归一化）
- 失败优雅降级：模型未下载/加载失败 → encode 返回 None

为什么选 MiniLM-L12-v2？
- 多语言支持（中文、英文混合）
- 模型体积小（120MB，本地 CPU 推理 < 20ms/句）
- 384 维输出，FAISS 索引效率高
- 与 doc02/04 设计一致

首次运行时会自动从 HuggingFace 下载模型到 ~/.cache/huggingface/
如果离线环境下载失败，encode() 返回 None，FAISS 缓存自动降级到 L1-only
"""
import logging
import threading
from typing import List, Optional, Union

import numpy as np

from config import EMBEDDING_CONFIG

logger = logging.getLogger(__name__)


class EmbeddingModel:
    """Sentence Transformer 单例封装"""

    def __init__(self):
        self.model_name = EMBEDDING_CONFIG["model_name"]
        self.device = EMBEDDING_CONFIG["device"]
        self.vector_dim = EMBEDDING_CONFIG["vector_dim"]
        self._model = None
        self._load_error: Optional[str] = None
        self._lock = threading.Lock()

    def _ensure_loaded(self) -> bool:
        """懒加载模型（线程安全）

        Returns:
            True if model loaded successfully, False otherwise
        """
        if self._model is not None:
            return True
        if self._load_error is not None:
            return False  # 之前加载失败过，不再重试

        with self._lock:
            # 双重检查（避免并发重复加载）
            if self._model is not None:
                return True
            if self._load_error is not None:
                return False

            try:
                logger.info(f"[EmbeddingModel] 加载模型: {self.model_name} (device={self.device})")
                from sentence_transformers import SentenceTransformer
                self._model = SentenceTransformer(self.model_name, device=self.device)
                logger.info(f"[EmbeddingModel] 加载成功: vector_dim={self.vector_dim}")
                return True
            except Exception as e:
                self._load_error = str(e)
                logger.error(f"[EmbeddingModel] 加载失败: {e}")
                return False

    def encode(self, text: Union[str, List[str]]) -> Optional[np.ndarray]:
        """将文本编码为向量

        Args:
            text: 单个字符串或字符串列表

        Returns:
            numpy.ndarray (shape: [384] or [N, 384], dtype=float32)，已 L2 归一化
            失败返回 None
        """
        if not text:
            return None

        if not self._ensure_loaded():
            return None

        try:
            # sentence-transformers 自动处理 list 输入
            is_single = isinstance(text, str)
            texts = [text] if is_single else text

            vectors = self._model.encode(
                texts,
                normalize_embeddings=True,  # L2 归一化，便于 cosine similarity
                convert_to_numpy=True,
                show_progress_bar=False,
                batch_size=32,
            )

            # 确保 float32
            vectors = vectors.astype(np.float32)

            return vectors[0] if is_single else vectors
        except Exception as e:
            logger.error(f"[EmbeddingModel] encode 失败: {e}")
            return None

    def is_loaded(self) -> bool:
        """模型是否已加载"""
        return self._model is not None

    def get_load_error(self) -> Optional[str]:
        """获取加载错误（用于 health 端点）"""
        return self._load_error

    def similarity(self, vec_a: np.ndarray, vec_b: np.ndarray) -> float:
        """计算两个向量的余弦相似度（已归一化 → 等价点积）"""
        if vec_a is None or vec_b is None:
            return 0.0
        # dot product of normalized vectors = cosine similarity
        return float(np.dot(vec_a, vec_b))


# ===== 模块单例 =====
_embedding_model_instance: Optional[EmbeddingModel] = None
_singleton_lock = threading.Lock()


def get_embedding_model() -> EmbeddingModel:
    """获取 EmbeddingModel 单例（懒加载）"""
    global _embedding_model_instance
    if _embedding_model_instance is None:
        with _singleton_lock:
            if _embedding_model_instance is None:
                _embedding_model_instance = EmbeddingModel()
    return _embedding_model_instance


# ===== 模块暴露 =====
__all__ = [
    "EmbeddingModel",
    "get_embedding_model",
]
