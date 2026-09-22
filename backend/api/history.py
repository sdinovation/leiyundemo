"""
history.py — GET /api/history

分页查询指定数据集的查询历史
"""
import logging

from flask import Blueprint, request
from sqlalchemy import desc

from api.errors import error_response, success_response
from models import db_session_scope
from models.query_history import QueryHistory

bp = Blueprint("history", __name__, url_prefix="/api")
logger = logging.getLogger(__name__)


@bp.route("/history", methods=["GET"])
def get_history():
    """获取查询历史（分页）"""
    dataset_id = request.args.get("dataset_id") or request.args.get("datasetId")
    page = int(request.args.get("page", 1))
    per_page = min(int(request.args.get("per_page", 20)), 100)

    if not dataset_id:
        return error_response("缺少 'dataset_id' 参数", error_code="MISSING_DATASET_ID")

    if page < 1:
        page = 1
    if per_page < 1:
        per_page = 20

    try:
        with db_session_scope() as session:
            query_builder = session.query(QueryHistory).filter_by(dataset_id=dataset_id)
            total = query_builder.count()
            entries = (
                query_builder
                .order_by(desc(QueryHistory.created_at))
                .offset((page - 1) * per_page)
                .limit(per_page)
                .all()
            )

            history_list = [e.to_summary() for e in entries]
            total_pages = (total + per_page - 1) // per_page

            return success_response({
                "history": history_list,
                "total": total,
                "page": page,
                "per_page": per_page,
                "total_pages": total_pages,
            })
    except Exception as e:
        logger.exception("[History] 查询失败")
        return error_response(str(e), status_code=500)