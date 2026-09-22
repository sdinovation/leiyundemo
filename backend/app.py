"""
app.py — Flask 应用工厂

Stage 5 完成：
- 7 个业务蓝图全部注册（upload/query/schema/history/insight/cache/dataset）
- 统一错误处理（api/errors.py）
- /api/health 端点（前后端契约对齐：{ok, message, ...}）
- / 根路径返回端点索引
"""
import json
import logging
import os
import traceback
from logging.handlers import RotatingFileHandler
from pathlib import Path

from flask import Flask, jsonify, request
from flask_cors import CORS

from config import (
    FLASK_CONFIG,
    CORS_CONFIG,
    LOG_DIR,
    BASE_DIR,
    get_config_summary,
    is_llm_configured,
)


def _setup_logging():
    """配置日志：控制台 + 滚动文件"""
    log_file = LOG_DIR / "app.log"
    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # 文件 handler（10 MB × 5 备份）
    file_handler = RotatingFileHandler(
        log_file, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.INFO)

    # 控制台 handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    console_handler.setLevel(logging.INFO)

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)

    return root_logger


def create_app(config_name="default") -> Flask:
    """Flask 应用工厂"""
    app = Flask(__name__)
    app.config["JSON_AS_ASCII"] = FLASK_CONFIG["json_as_ascii"]
    app.config["MAX_CONTENT_LENGTH"] = FLASK_CONFIG["max_content_length"]
    app.config["SECRET_KEY"] = FLASK_CONFIG["secret_key"]

    _setup_logging()
    logger = logging.getLogger(__name__)
    logger.info(f"[App] 启动 backend (config={config_name}, debug={FLASK_CONFIG['debug']})")

    # CORS
    CORS(
        app,
        origins=CORS_CONFIG["origins"],
        methods=CORS_CONFIG["methods"],
        allow_headers=CORS_CONFIG["headers"],
        supports_credentials=False,
    )

    # ===== 初始化数据库 =====
    from models import init_db
    init_db(app)

    # ===== 注册错误处理器（统一 JSON 响应）=====
    _register_error_handlers(app)

    # ===== 注册 Stage 5 业务蓝图（占位）=====
    _register_blueprints(app)

    # ===== 核心端点 =====
    @app.route("/")
    def index():
        """根路径 — 返回端点索引，方便调试"""
        return jsonify({
            "service": "shufen-backend",
            "version": "1.0.0",
            "stage": 5,
            "endpoints": {
                "GET /": "本响应",
                "GET /api/health": "健康检查（含 LLM / DuckDB / FAISS 状态）",
                "POST /api/upload": "文件上传 → 创建数据集",
                "POST /api/query": "自然语言查询（核心端点）",
                "GET /api/schema": "获取数据集 schema",
                "GET /api/history": "查询历史（分页）",
                "POST /api/insight": "数据集整体洞察报告",
                "GET /api/cache/stats": "缓存统计信息",
                "POST /api/cache/invalidate": "失效指定数据集缓存",
                "GET /api/dataset": "列出所有数据集",
                "DELETE /api/dataset/<id>": "删除数据集",
            },
        })

    @app.route("/api/health")
    def health():
        """健康检查端点

        返回形状（与前端 QueryService.healthCheck() 对齐）：
        {ok: true, message: "...", ...}
        """
        llm_ok = is_llm_configured()
        config_summary = get_config_summary()

        # 检查各组件状态
        components = {
            "llm_configured": llm_ok,
            "flask": True,
        }
        try:
            from cache.semantic_cache import get_semantic_cache
            cache = get_semantic_cache()
            components["semantic_cache"] = True
            from cache.embedding_model import get_embedding_model
            model = get_embedding_model()
            components["embedding_loaded"] = model.is_loaded()
        except Exception as e:
            components["semantic_cache"] = False
            components["embedding_loaded"] = False

        all_ok = all(components.values())
        return jsonify({
            "ok": all_ok,
            "message": "OK" if all_ok else "Backend up but degraded",
            "service": "shufen-backend",
            "version": "1.0.0",
            "stage": 5,
            "llm_configured": llm_ok,
            "components": components,
            "config": config_summary,
        })

    logger.info("[App] 初始化完成")
    return app


def _register_error_handlers(app: Flask):
    """统一错误响应（与前端契约对齐：{success, error}）"""

    @app.errorhandler(400)
    def bad_request(e):
        return jsonify({"success": False, "error": f"请求格式错误: {str(e)[:200]}"}), 400

    @app.errorhandler(404)
    def not_found(e):
        return jsonify({"success": False, "error": f"资源不存在: {request.path}"}), 404

    @app.errorhandler(405)
    def method_not_allowed(e):
        return jsonify({"success": False, "error": f"HTTP 方法不允许: {request.method} {request.path}"}), 405

    @app.errorhandler(413)
    def payload_too_large(e):
        return jsonify({"success": False, "error": "文件过大，请压缩后重试"}), 413

    @app.errorhandler(500)
    def internal_error(e):
        logging.getLogger(__name__).exception("[500] 内部错误")
        return jsonify({"success": False, "error": "服务器内部错误，请稍后重试"}), 500

    @app.errorhandler(Exception)
    def all_other_exceptions(e):
        logging.getLogger(__name__).exception("[Exception] 未捕获异常")
        return jsonify({"success": False, "error": f"未处理异常: {str(e)[:200]}"}), 500


def _register_blueprints(app: Flask):
    """注册业务蓝图"""
    from api.errors import register_error_handlers
    register_error_handlers(app)

    from api.upload import bp as upload_bp
    from api.query import bp as query_bp
    from api.schema import bp as schema_bp
    from api.history import bp as history_bp
    from api.insight import bp as insight_bp
    from api.cache import bp as cache_bp
    from api.dataset import bp as dataset_bp
    from api.diagnostics import bp as diagnostics_bp
    from api.rules import bp as rules_bp

    for bp in (upload_bp, query_bp, schema_bp, history_bp,
               insight_bp, cache_bp, dataset_bp, diagnostics_bp,
               rules_bp):
        app.register_blueprint(bp)

    logger = logging.getLogger(__name__)
    logger.info("[App] 注册 8 个业务蓝图完成")


# ===== WSGI 入口（生产部署用）=====
# gunicorn -w 4 -b 0.0.0.0:5000 wsgi:application
application = None  # 在 wsgi.py 中赋值


if __name__ == "__main__":
    app = create_app("development")
    app.run(
        host=FLASK_CONFIG["host"],
        port=FLASK_CONFIG["port"],
        debug=FLASK_CONFIG["debug"],
    )