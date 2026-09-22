"""
errors.py — 统一错误处理

为所有 API 路由提供：
- 标准 JSON 错误响应格式
- Flask 错误处理器注册
"""
import logging
import traceback
from typing import Any, Dict, Optional

from flask import jsonify
from werkzeug.exceptions import HTTPException

from core.data_manager import DataManagerError, DatasetNotFoundError
from core.query_processor import QueryProcessorError
from core.sql_executor import SQLExecutionError

logger = logging.getLogger(__name__)


def error_response(
    message: str,
    status_code: int = 400,
    error_code: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
):
    """构造标准 JSON 错误响应"""
    body = {
        "success": False,
        "error": {
            "code": error_code or _status_to_code(status_code),
            "message": message,
            "details": details or {},
        }
    }
    return jsonify(body), status_code


def success_response(data: Any, status_code: int = 200):
    """构造标准 JSON 成功响应"""
    body = {"success": True, "data": data}
    return jsonify(body), status_code


def _status_to_code(status_code: int) -> str:
    """HTTP 状态码 → 错误码字符串"""
    mapping = {
        400: "BAD_REQUEST",
        401: "UNAUTHORIZED",
        403: "FORBIDDEN",
        404: "NOT_FOUND",
        413: "PAYLOAD_TOO_LARGE",
        415: "UNSUPPORTED_MEDIA_TYPE",
        422: "UNPROCESSABLE_ENTITY",
        500: "INTERNAL_ERROR",
        503: "SERVICE_UNAVAILABLE",
    }
    return mapping.get(status_code, "UNKNOWN_ERROR")


def register_error_handlers(app):
    """注册全局错误处理器"""

    @app.errorhandler(DatasetNotFoundError)
    def handle_dataset_not_found(e):
        return error_response(str(e), status_code=404, error_code="DATASET_NOT_FOUND")

    @app.errorhandler(DataManagerError)
    def handle_data_manager_error(e):
        return error_response(str(e), status_code=400, error_code="DATA_MANAGER_ERROR")

    @app.errorhandler(QueryProcessorError)
    def handle_query_processor_error(e):
        return error_response(str(e), status_code=422, error_code="QUERY_PROCESSOR_ERROR")

    @app.errorhandler(SQLExecutionError)
    def handle_sql_execution_error(e):
        return error_response(str(e), status_code=422, error_code="SQL_EXECUTION_ERROR")

    @app.errorhandler(HTTPException)
    def handle_http_exception(e):
        return error_response(e.description or e.name, status_code=e.code)

    @app.errorhandler(Exception)
    def handle_unhandled_exception(e):
        logger.error(f"[API] 未捕获异常: {e}\n{traceback.format_exc()}")
        return error_response("服务器内部错误", status_code=500, error_code="INTERNAL_ERROR")


__all__ = [
    "error_response",
    "success_response",
    "register_error_handlers",
]