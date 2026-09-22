"""
diagnostics.py — GET /api/diagnostics（运维诊断端点）

Backend Item B：暴露 LLMClient 健康状态、累计调用/失败次数、错误分类统计。
供前端 dashboard / pushErrorLog 使用，也可被运维脚本 curl 巡检。

注意：本端点暴露的是内部统计，不含敏感凭据；如需鉴权请在 app 层加白名单。
"""
import logging

from flask import Blueprint

from api.errors import success_response
from llm.llm_client import get_llm_client

bp = Blueprint("diagnostics", __name__, url_prefix="/api")

logger = logging.getLogger(__name__)


@bp.route("/diagnostics", methods=["GET"])
def diagnostics():
    """返回 LLM 健康状态 + 累计错误统计

    Returns:
        success({
            "llm": LLMClient.get_health(),
        })
    """
    llm_client = get_llm_client()
    payload = {
        "llm": llm_client.get_health(),
    }
    return success_response(payload)