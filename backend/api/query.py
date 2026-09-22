"""
query.py — POST /api/query（核心端点）

接收用户问题 + dataset_id，调用 QueryProcessor.process()
返回完整分析结果（含 sql/data/chart_config/insight/...）

Backend Item B：在 500 兜底响应里附带 LLMClient.last_error 详情，
供前端 pushErrorLog / toast 区分错误类型（网络超时 vs SQL 失败 vs 解析）。
"""
import logging

from flask import Blueprint, request

from api.errors import error_response, success_response
from core.data_manager import DataManagerError, DatasetNotFoundError
from core.query_processor import process_sync
from llm.llm_client import get_llm_client

bp = Blueprint("query", __name__, url_prefix="/api")

logger = logging.getLogger(__name__)


@bp.route("/query", methods=["POST"])
def query():
    """自然语言查询（核心端点）

    Body:
        question: 用户问题
        dataset_id: 数据集 ID
        conversation_history: 可选，对话历史 list[{question, sql, interpretation_summary}]
        entity_memory: 可选，字段别名记忆 dict{alias: realField}
    """
    payload = request.get_json(silent=True) or {}

    question = payload.get("question") or payload.get("query")
    dataset_id = payload.get("dataset_id") or payload.get("datasetId")
    # Phase 2 新增字段（向后兼容：缺省视为无历史）
    conversation_history = payload.get("conversation_history") or None
    entity_memory = payload.get("entity_memory") or None

    if not question:
        return error_response("缺少 'question' 字段", error_code="MISSING_QUESTION")
    if not dataset_id:
        return error_response("缺少 'dataset_id' 字段", error_code="MISSING_DATASET_ID")

    try:
        result = process_sync(
            question, dataset_id,
            conversation_history=conversation_history,
            entity_memory=entity_memory,
        )
        return success_response(result)
    except (DatasetNotFoundError, DataManagerError):
        # 已知错误 → 让全局错误处理器处理（返回 404/400）
        raise
    except Exception as e:
        # 未知错误 → 兜底 500，附带 LLMClient.last_error 供前端诊断
        logger.exception("[Query] 处理失败")
        llm_client = get_llm_client()
        details = {"llm_last_error": llm_client.last_error} if llm_client.last_error else {}
        return error_response(
            f"查询失败: {str(e)}",
            status_code=500,
            details=details,
        )