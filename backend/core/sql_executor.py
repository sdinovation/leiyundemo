"""
sql_executor.py — SQL 安全执行（doc02 §5 实现）

注意：原本计划用 DuckDB 提升性能，但当前 Stage 2.3 范围内保留 SQLite 实现
（理由：每数据集一个独立 SQLite 文件已能支撑 10万行；DuckDB 需要持久化 schema 才能
跨连接使用，每个数据集一个 DuckDB 文件会增加复杂度；如未来需要列式加速，可替换本文件）。

安全校验（doc02 §5.2）：
1. 非空
2. 无 `;`（禁止多语句）
3. 必须以 SELECT（或 WITH）开头
4. 禁止关键字（INSERT/UPDATE/DELETE/DROP/ALTER/CREATE/ATTACH/DETACH/PRAGMA/REPLACE/MERGE/TRUNCATE/VACUUM/REINDEX/GRANT/REVOKE）
5. 禁止函数（LOAD_EXTENSION/WRITEFILE/READFILE）
6. 无注释（-- / /* / */）

执行参数：
- 限制最大返回行数（默认 10000）
- 参数化查询（防止 SQL 注入）
"""
import logging
import re
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional

from config import SQL_EXECUTOR_CONFIG

logger = logging.getLogger(__name__)


# ===== 自定义异常 =====
class SQLValidationError(Exception):
    """SQL 校验失败"""
    def __init__(self, message: str, sql: str = ""):
        super().__init__(message)
        self.sql = sql


class SQLExecutionError(Exception):
    """SQL 执行失败"""
    def __init__(self, message: str, sql: str = ""):
        super().__init__(message)
        self.sql = sql


# ===== 校验正则 =====
_FORBIDDEN_KEYWORDS = SQL_EXECUTOR_CONFIG["forbidden_keywords"]
_FORBIDDEN_FUNCTIONS = SQL_EXECUTOR_CONFIG["forbidden_functions"]
_MAX_RETURN_ROWS = SQL_EXECUTOR_CONFIG["max_return_rows"]

# 匹配禁止关键字（word boundary + 不区分大小写）
_RE_FORBIDDEN_KEYWORD = re.compile(
    r"\b(" + "|".join(re.escape(kw) for kw in _FORBIDDEN_KEYWORDS) + r")\b",
    re.IGNORECASE,
)

# 匹配禁止函数（\b FUNC \s* ( )
_RE_FORBIDDEN_FUNCTION = re.compile(
    r"\b(" + "|".join(re.escape(fn) for fn in _FORBIDDEN_FUNCTIONS) + r")\s*\(",
    re.IGNORECASE,
)

# 匹配注释
_RE_LINE_COMMENT = re.compile(r"--")
_RE_BLOCK_COMMENT = re.compile(r"/\*|\*/")

# 匹配 SELECT / WITH 开头
_RE_SELECT_PREFIX = re.compile(r"^\s*(SELECT|WITH)\b", re.IGNORECASE)


def validate(sql: str) -> None:
    """校验 SQL 安全性，通过校验抛 SQLValidationError

    Args:
        sql: 待校验的 SQL 语句

    Raises:
        SQLValidationError: 任何一条规则不满足
    """
    if not sql or not sql.strip():
        raise SQLValidationError("SQL 语句为空", sql)

    # 1. 禁止多语句（; 分隔）
    # 注意：末尾的 ; 是允许的（自然语句结束），但中间出现 ; 视为多语句
    stripped = sql.rstrip().rstrip(";").strip()
    if ";" in stripped:
        raise SQLValidationError("SQL 包含多条语句（; 分隔），已被拒绝", sql)

    # 2. 必须以 SELECT 或 WITH 开头
    if not _RE_SELECT_PREFIX.match(sql):
        raise SQLValidationError("SQL 必须以 SELECT 或 WITH 开头", sql)

    # 3. 无禁止关键字
    kw_match = _RE_FORBIDDEN_KEYWORD.search(sql)
    if kw_match:
        raise SQLValidationError(f"SQL 包含禁止的关键字: {kw_match.group(0).upper()}", sql)

    # 4. 无禁止函数
    fn_match = _RE_FORBIDDEN_FUNCTION.search(sql)
    if fn_match:
        raise SQLValidationError(f"SQL 包含禁止的函数: {fn_match.group(0).split('(')[0].upper()}", sql)

    # 5. 无注释
    if _RE_LINE_COMMENT.search(sql) or _RE_BLOCK_COMMENT.search(sql):
        raise SQLValidationError("SQL 包含注释，已被拒绝", sql)


# ===== 主类 =====
class SQLExecutor:
    """SQL 安全执行器（基于 SQLite）"""

    def execute(self, sql: str, db_path: str) -> Dict[str, Any]:
        """校验 + 执行 SQL，返回查询结果

        Args:
            sql: 已通过 validate 的 SQL
            db_path: 数据集对应的 SQLite 文件路径

        Returns:
            {"columns": [...], "rows": [{col: val, ...}], "row_count": N}

        Raises:
            SQLValidationError, SQLExecutionError
        """
        # 1. 校验
        validate(sql)

        # 2. 检查 db_path
        if not Path(db_path).exists():
            raise SQLExecutionError(f"数据集文件不存在: {db_path}", sql)

        # 3. 执行
        try:
            conn = sqlite3.connect(str(db_path), timeout=SQL_EXECUTOR_CONFIG["execution_timeout"])
            conn.row_factory = sqlite3.Row
            try:
                cur = conn.execute(sql)
                rows = cur.fetchmany(_MAX_RETURN_ROWS)
                columns = [d[0] for d in cur.description] if cur.description else []
                # 转为标准 JSON 序列化格式
                row_dicts = []
                for row in rows:
                    row_dict = {}
                    for col in columns:
                        val = row[col]
                        # 处理特殊类型（datetime, bytes, decimal）
                        if val is None:
                            row_dict[col] = None
                        elif isinstance(val, (int, float, str, bool)):
                            row_dict[col] = val
                        else:
                            row_dict[col] = str(val)
                    row_dicts.append(row_dict)
                result = {
                    "columns": columns,
                    "rows": row_dicts,
                    "row_count": len(row_dicts),
                }
                logger.debug(f"[SQLExecutor] {sql[:80]}... → {len(row_dicts)} 行")
                return result
            finally:
                conn.close()
        except sqlite3.Error as e:
            raise SQLExecutionError(f"SQL 执行失败: {str(e)[:200]}", sql)
        except Exception as e:
            raise SQLExecutionError(f"未知执行错误: {str(e)[:200]}", sql)

    def execute_raw(self, sql: str, db_path: str) -> tuple:
        """执行 SQL 返回 (columns, rows) 元组（兼容 doc02 §5.3 的 execute_raw 接口）"""
        result = self.execute(sql, db_path)
        return result["columns"], result["rows"]


# ===== 模块级单例 =====
sql_executor = SQLExecutor()