"""
config.py — 全局配置管理

约定（与 doc02/03 一致）：
- 路径常量基于 BASE_DIR 解析，所有相对路径都从 backend/ 目录开始
- 所有配置从 .env 读取（python-dotenv），未设置时使用安全默认值
- LLM 配置缺失时返回 None，由上层决定是否降级到纯规则引擎
"""
import os
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv

# 加载 .env 文件（位于 backend/ 同级目录）
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


def _bool(key: str, default: bool = False) -> bool:
    """读取布尔型环境变量"""
    raw = os.getenv(key)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "y", "on")


def _int(key: str, default: int) -> int:
    """读取整型环境变量，解析失败时使用默认值"""
    raw = os.getenv(key)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _float(key: str, default: float) -> float:
    """读取浮点型环境变量，解析失败时使用默认值"""
    raw = os.getenv(key)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


# ===== 路径常量 =====
DATA_DIR = BASE_DIR / "data"
UPLOAD_DIR = DATA_DIR / "uploads"
SQLITE_DIR = DATA_DIR / "sqlite"
FAISS_DIR = DATA_DIR / "faiss"
LOG_DIR = BASE_DIR / "logs"
METADATA_DB_PATH = DATA_DIR / "metadata.db"
METADATA_DB_URI = f"sqlite:///{METADATA_DB_PATH.as_posix()}"

# 自动创建所有目录
for _dir in (DATA_DIR, UPLOAD_DIR, SQLITE_DIR, FAISS_DIR, LOG_DIR):
    _dir.mkdir(parents=True, exist_ok=True)


# ===== LLM 配置 =====
LLM_CONFIG = {
    "api_key": os.getenv("LLM_API_KEY") or None,
    "base_url": os.getenv("LLM_BASE_URL", "https://api.deepseek.com/v1"),
    "model": os.getenv("LLM_MODEL", "deepseek-chat"),
    "timeout": _int("LLM_TIMEOUT", 30),
    "temperature_analysis": 0.0,
    "temperature_interpretation": 0.3,
    "max_tokens_analysis": 1024,
    "max_tokens_interpretation": 400,
}


# ===== Embedding 模型配置 =====
EMBEDDING_CONFIG = {
    "model_name": os.getenv("EMBEDDING_MODEL_NAME", "paraphrase-multilingual-MiniLM-L12-v2"),
    "device": os.getenv("EMBEDDING_DEVICE", "cpu"),
    "vector_dim": 384,  # MiniLM-L12 输出维度
}


# ===== FAISS 缓存配置 =====
FAISS_CONFIG = {
    "similarity_threshold": _float("FAISS_SIMILARITY_THRESHOLD", 0.92),
    "max_entries": _int("FAISS_MAX_ENTRIES", 10000),
    "index_path": str(FAISS_DIR / "semantic_cache.index"),
    "mapping_path": str(FAISS_DIR / "cache_mapping.json"),
}


# ===== 上传配置 =====
UPLOAD_CONFIG = {
    "max_size_mb": _int("MAX_UPLOAD_MB", 50),
    "allowed_extensions": [ext.strip().lower() for ext in os.getenv("ALLOWED_EXTENSIONS", "csv,xlsx,xls").split(",") if ext.strip()],
}


# ===== SQL 执行器配置 =====
SQL_EXECUTOR_CONFIG = {
    "max_return_rows": 10000,
    "execution_timeout": 30,
    # 禁止的关键字（防止 SQL 注入）
    "forbidden_keywords": [
        "INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE",
        "ATTACH", "DETACH", "PRAGMA", "REPLACE", "MERGE",
        "TRUNCATE", "VACUUM", "REINDEX", "GRANT", "REVOKE",
    ],
    # 禁止的函数
    "forbidden_functions": [
        "LOAD_EXTENSION", "WRITEFILE", "READFILE",
    ],
}


# ===== Flask 配置 =====
FLASK_CONFIG = {
    "host": os.getenv("FLASK_HOST", "0.0.0.0"),
    "port": _int("FLASK_PORT", 5000),
    "debug": _bool("FLASK_DEBUG", False),
    "secret_key": os.getenv("FLASK_SECRET_KEY", "shufen-dev-secret-change-in-prod"),
    "json_as_ascii": False,  # 支持中文响应不被转义为 \uXXXX
    "max_content_length": _int("MAX_UPLOAD_MB", 50) * 1024 * 1024,
}


# ===== CORS 配置 =====
CORS_CONFIG = {
    "origins": os.getenv("CORS_ORIGINS", "*"),
    "methods": ["GET", "POST", "DELETE", "OPTIONS"],
    "headers": ["Content-Type", "Authorization"],
}


def get_config_summary() -> dict:
    """返回所有配置的摘要（用于 /api/health 端点）"""
    return {
        "llm": {
            "configured": bool(LLM_CONFIG["api_key"]),
            "base_url": LLM_CONFIG["base_url"],
            "model": LLM_CONFIG["model"],
        },
        "embedding": {
            "model_name": EMBEDDING_CONFIG["model_name"],
            "vector_dim": EMBEDDING_CONFIG["vector_dim"],
        },
        "faiss": {
            "threshold": FAISS_CONFIG["similarity_threshold"],
            "max_entries": FAISS_CONFIG["max_entries"],
        },
        "upload": {
            "max_size_mb": UPLOAD_CONFIG["max_size_mb"],
            "allowed_extensions": UPLOAD_CONFIG["allowed_extensions"],
        },
        "flask": {
            "host": FLASK_CONFIG["host"],
            "port": FLASK_CONFIG["port"],
            "debug": FLASK_CONFIG["debug"],
        },
    }


# 模块级单例快捷访问
def get_llm_api_key() -> Optional[str]:
    return LLM_CONFIG["api_key"]


def is_llm_configured() -> bool:
    return bool(LLM_CONFIG["api_key"] and LLM_CONFIG["api_key"].strip())