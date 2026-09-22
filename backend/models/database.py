"""
database.py — SQLAlchemy 初始化（doc02/03 约定：plain declarative_base + scoped_session）

约定：
- 使用 plain SQLAlchemy（不依赖 Flask-SQLAlchemy），保持代码可独立测试
- 三个模型：Dataset / QueryHistory / CacheEntry
- 启动时 init_db(app) 自动创建表（若不存在）
"""
import logging
from contextlib import contextmanager
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, scoped_session, sessionmaker

from config import METADATA_DB_URI

logger = logging.getLogger(__name__)

# 单例 engine + session factory
_engine = None
_SessionFactory = None
Base = declarative_base()


def _get_engine():
    global _engine
    if _engine is None:
        _engine = create_engine(
            METADATA_DB_URI,
            pool_pre_ping=True,
            pool_recycle=3600,
            pool_size=10,
            max_overflow=20,
            echo=False,
        )
    return _engine


def _get_session_factory():
    global _SessionFactory
    if _SessionFactory is None:
        _SessionFactory = sessionmaker(bind=_get_engine(), autoflush=False, autocommit=False)
    return _SessionFactory


def init_db(app=None):
    """初始化数据库，创建所有表"""
    engine = _get_engine()
    # 延迟导入避免循环依赖
    from .dataset import Dataset  # noqa
    from .query_history import QueryHistory  # noqa
    from .cache_entry import CacheEntry  # noqa
    from .rule import Rule  # noqa  # 用户自定义业务规则（Layer 1）
    Base.metadata.create_all(engine)
    logger.info(f"[DB] 已初始化 metadata 数据库：{METADATA_DB_URI}")


def get_session():
    """获取一个新的 Session 实例（调用方负责 close）"""
    return _get_session_factory()()


@contextmanager
def db_session_scope():
    """
    带自动 commit/rollback 的 session 上下文管理器。
    用法：
        with db_session_scope() as session:
            session.add(obj)
            # 退出时自动 commit；异常时自动 rollback
    """
    session = get_session()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()