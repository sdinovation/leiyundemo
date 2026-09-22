"""
rules.py — 用户自定义业务规则 REST API（Layer 1）

端点：
- POST /api/rules            新增规则（"以后记住 X"）
- GET  /api/rules            列表（按 dataset_id，可选 scope=global）
- DELETE /api/rules/<id>     删除规则
- PATCH /api/rules/<id>      启用/禁用规则
- POST /api/rules/retrieve   检索相关规则（调试用，平时由 QueryProcessor 内部调用）
"""
import logging

from flask import Blueprint, request

from api.errors import error_response, success_response
from core.rules_store import (
    RulesStore,
    _classify_rule,
    _extract_keywords,
    rules_store,
)

bp = Blueprint("rules", __name__, url_prefix="/api/rules")
logger = logging.getLogger(__name__)


@bp.route("", methods=["POST"])
def add_rule():
    """新增规则

    Body:
        {
            "text": "TOP 5 排除自己",
            "dataset_id": "ds-xxx",       # optional, 缺省='global'
            "category": "ranking",         # optional, 自动推断
            "keywords": ["TOP", "5"],     # optional, 自动提取
            "auto_dedup": true             # optional, default True
        }
    """
    data = request.get_json(silent=True) or {}
    text = (data.get("text") or "").strip()
    if not text:
        return error_response("规则文本不能为空", 400)
    if len(text) > 200:
        return error_response("规则文本超过 200 字限制", 400)

    dataset_id = (data.get("dataset_id") or "global").strip()
    category = data.get("category")
    keywords = data.get("keywords")
    auto_dedup = data.get("auto_dedup", True)

    try:
        result = rules_store.add_rule(
            text=text,
            scope=dataset_id,
            category=category,
            keywords=keywords,
            auto_dedup=auto_dedup,
        )
    except ValueError as e:
        return error_response(str(e), 400)
    except Exception as e:
        logger.exception("[Rules] add_rule 失败")
        return error_response(f"保存失败: {e}", 500)

    return success_response({
        "rule": result["rule"].to_dict() if hasattr(result["rule"], "to_dict") else {
            "id": result["rule"].id,
            "text": result["rule"].text,
            "category": result["rule"].category,
        },
        "created": result["created"],
        "merged_into": result["merged_into"],
    })


@bp.route("", methods=["GET"])
def list_rules():
    """列出规则

    Query:
        dataset_id:  数据集 ID（默认 'global'）
        scope:       'global' | 'dataset' | 'all'（默认 'dataset'）
        enabled_only: bool（默认 true）
    """
    dataset_id = (request.args.get("dataset_id") or "global").strip()
    scope = request.args.get("scope", "dataset")
    enabled_only = request.args.get("enabled_only", "true").lower() == "true"

    scopes = []
    if scope in ("all", "dataset"):
        scopes.append(dataset_id)
    if scope in ("all", "global"):
        scopes.append("global")

    out = []
    for sc in scopes:
        try:
            rules = rules_store.list_rules(sc, enabled_only=enabled_only)
        except Exception as e:
            logger.warning(f"[Rules] list_rules scope={sc} 失败: {e}")
            continue
        for r in rules:
            d = r.to_dict() if hasattr(r, "to_dict") else {"id": r.id, "text": r.text}
            d["scope"] = sc
            out.append(d)
    return success_response({"rules": out, "count": len(out)})


@bp.route("/<int:rule_id>", methods=["DELETE"])
def delete_rule(rule_id: int):
    try:
        ok = rules_store.delete_rule(rule_id)
    except Exception as e:
        logger.exception("[Rules] delete_rule 失败")
        return error_response(f"删除失败: {e}", 500)
    if not ok:
        return error_response("规则不存在", 404)
    return success_response({"deleted": rule_id})


@bp.route("/<int:rule_id>", methods=["PATCH"])
def toggle_rule(rule_id: int):
    data = request.get_json(silent=True) or {}
    enabled = data.get("enabled", True)
    if not isinstance(enabled, bool):
        return error_response("enabled 必须是 bool", 400)
    try:
        ok = rules_store.toggle_rule(rule_id, enabled)
    except Exception as e:
        logger.exception("[Rules] toggle_rule 失败")
        return error_response(f"更新失败: {e}", 500)
    if not ok:
        return error_response("规则不存在", 404)
    return success_response({"id": rule_id, "enabled": enabled})


@bp.route("/retrieve", methods=["POST"])
def retrieve_rules():
    """检索相关规则（调试 / 预览，给前端用）

    Body:
        { "question": "...", "dataset_id": "ds-xxx", "k": 3 }
    """
    data = request.get_json(silent=True) or {}
    question = (data.get("question") or "").strip()
    dataset_id = (data.get("dataset_id") or "global").strip()
    k = int(data.get("k", 3))

    if not question:
        return error_response("question 不能为空", 400)

    out = []
    seen = set()
    for sc in (dataset_id, "global"):
        try:
            rules = rules_store.retrieve_relevant_rules(question, scope=sc, k=k)
        except Exception as e:
            logger.warning(f"[Rules] retrieve scope={sc} 失败: {e}")
            continue
        for r in rules:
            if r.id in seen:
                continue
            seen.add(r.id)
            d = r.to_dict() if hasattr(r, "to_dict") else {"id": r.id, "text": r.text}
            d["scope"] = sc
            out.append(d)
        if len(out) >= k:
            break
    return success_response({"rules": out[:k], "count": len(out[:k])})
