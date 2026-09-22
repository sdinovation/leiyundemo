"""
insight.py — POST /api/insight

数据集整体洞察报告
"""
import logging

from flask import Blueprint, request

from api.errors import error_response, success_response
from core.data_manager import DatasetNotFoundError, data_manager
from core.insight_generator import generate_dataset_overview

bp = Blueprint("insight", __name__, url_prefix="/api")
logger = logging.getLogger(__name__)


@bp.route("/insight", methods=["POST"])
def generate_insights():
    """生成数据集整体洞察报告"""
    payload = request.get_json(silent=True) or {}
    dataset_id = payload.get("dataset_id") or payload.get("datasetId")

    if not dataset_id:
        return error_response("缺少 'dataset_id' 字段", error_code="MISSING_DATASET_ID")

    try:
        dataset = data_manager.get_dataset(dataset_id)

        # 从 dataset 直接构造 profile_stats（避免字符串混淆）
        field_info = dataset.get_field_info()
        type_distribution = {}
        for f in field_info:
            t = f.get("type", "text")
            type_distribution[t] = type_distribution.get(t, 0) + 1

        profile_stats = {
            "total_rows": dataset.row_count,
            "total_columns": len(dataset.get_columns()),
            "numeric_summary": [
                {"name": f["name"], "type": f["type"]}
                for f in field_info if f.get("type") in ("int", "float", "currency", "percent")
            ],
            "type_distribution": type_distribution,
        }

        overview = generate_dataset_overview(
            dataset_name=dataset.original_name,
            profile_stats=profile_stats,
        )

        return success_response({
            "dataset_id": dataset_id,
            "dataset_name": dataset.original_name,
            **overview,
        })

    except DatasetNotFoundError as e:
        return error_response(str(e), status_code=404, error_code="DATASET_NOT_FOUND")
    except Exception as e:
        logger.exception("[Insight] 生成失败")
        return error_response(str(e), status_code=500)