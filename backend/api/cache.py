"""
cache.py — GET /api/cache/stats, POST /api/cache/invalidate

缓存管理端点
"""
import logging

from flask import Blueprint, request

from api.errors import error_response, success_response
from cache.semantic_cache import get_semantic_cache

bp = Blueprint("cache", __name__, url_prefix="/api")
logger = logging.getLogger(__name__)


@bp.route("/cache/stats", methods=["GET"])
def cache_stats():
    """获取缓存统计信息"""
    try:
        cache = get_semantic_cache()
        stats = cache.stats()
        return success_response(stats)
    except Exception as e:
        logger.exception("[Cache] 获取统计失败")
        return error_response(str(e), status_code=500)


@bp.route("/cache/invalidate", methods=["POST"])
def invalidate_cache():
    """失效指定数据集的所有缓存"""
    payload = request.get_json(silent=True) or {}
    dataset_id = payload.get("dataset_id") or payload.get("datasetId")

    if not dataset_id:
        return error_response("缺少 'dataset_id' 字段", error_code="MISSING_DATASET_ID")

    try:
        cache = get_semantic_cache()
        deleted = cache.invalidate_by_dataset(dataset_id)
        return success_response({
            "dataset_id": dataset_id,
            "deleted_entries": deleted,
        })
    except Exception as e:
        logger.exception("[Cache] 失效失败")
        return error_response(str(e), status_code=500)