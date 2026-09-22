"""
dataset.py — GET /api/dataset, DELETE /api/dataset/{id}

数据集管理端点
"""
import logging

from flask import Blueprint, request
from sqlalchemy import desc

from api.errors import error_response, success_response
from core.data_manager import DatasetNotFoundError, data_manager
from models import db_session_scope
from models.dataset import Dataset

bp = Blueprint("dataset", __name__, url_prefix="/api")
logger = logging.getLogger(__name__)


@bp.route("/dataset", methods=["GET"])
def list_datasets():
    """列出所有数据集"""
    try:
        with db_session_scope() as session:
            datasets = session.query(Dataset).order_by(desc(Dataset.created_at)).all()
            return success_response({
                "datasets": [d.to_dict() for d in datasets],
                "total": len(datasets),
            })
    except Exception as e:
        logger.exception("[Dataset] 列表查询失败")
        return error_response(str(e), status_code=500)


@bp.route("/dataset/<dataset_id>", methods=["DELETE"])
def delete_dataset(dataset_id: str):
    """删除数据集（级联清理 SQLite 文件 + 缓存 + 历史）"""
    if not dataset_id:
        return error_response("缺少 dataset_id", error_code="MISSING_DATASET_ID")

    try:
        data_manager.delete_dataset(dataset_id)
        return success_response({
            "dataset_id": dataset_id,
            "deleted": True,
        })
    except DatasetNotFoundError as e:
        return error_response(str(e), status_code=404, error_code="DATASET_NOT_FOUND")
    except Exception as e:
        logger.exception("[Dataset] 删除失败")
        return error_response(str(e), status_code=500)