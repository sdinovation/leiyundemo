"""
schema.py — GET /api/schema

获取数据集 schema（列名 + 字段信息 + 样本数据 + 行数）
"""
import logging

from flask import Blueprint, request

from api.errors import error_response, success_response
from core.data_manager import DatasetNotFoundError, data_manager

bp = Blueprint("schema", __name__, url_prefix="/api")
logger = logging.getLogger(__name__)


@bp.route("/schema", methods=["GET"])
def get_schema():
    """获取数据集 schema"""
    dataset_id = request.args.get("dataset_id") or request.args.get("datasetId")
    sample_size = int(request.args.get("sample_size", 5))

    if not dataset_id:
        return error_response("缺少 'dataset_id' 参数", error_code="MISSING_DATASET_ID")

    try:
        schema = data_manager.get_schema(dataset_id, sample_size=sample_size)
        return success_response(schema)
    except DatasetNotFoundError as e:
        return error_response(str(e), status_code=404, error_code="DATASET_NOT_FOUND")
    except Exception as e:
        logger.exception("[Schema] 获取失败")
        return error_response(str(e), status_code=500)