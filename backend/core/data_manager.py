"""
data_manager.py — 数据集管理（doc02 §4 实现）

职责：
- 文件上传：保存到 data/uploads/，解析 CSV/Excel
- 字段类型推断：调用 field_inference
- 数据入库：每个数据集一个独立的 SQLite 文件 + DuckDB 视图表
- 数据画像：调用 data_profiler.build
- 查询：get_dataset / get_schema / get_sample_rows
- 删除：级联清理 DuckDB 视图表 + 元数据 + 缓存条目

约定（doc02 §4）：
- dataset_id = f'ds-{utc_timestamp}-{uuid_hex[:8]}'
- 文件存到 data/uploads/{dataset_id}.{ext}
- 数据存到 data/sqlite/{dataset_id}.db
"""
import io
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from config import (
    SQLITE_DIR,
    UPLOAD_DIR,
    UPLOAD_CONFIG,
)
from models import Dataset, db_session_scope, get_session
from models.database import _get_engine
from sqlalchemy.exc import SQLAlchemyError

from .field_inference import (
    infer_field_info_from_records,
    compute_type_distribution,
    get_numeric_fields,
    get_text_fields,
    get_date_fields,
)

logger = logging.getLogger(__name__)


# ===== 自定义异常 =====
class DataManagerError(Exception):
    """数据集管理错误基类"""
    pass


class FileTooLargeError(DataManagerError):
    pass


class InvalidFileFormatError(DataManagerError):
    pass


class DatasetNotFoundError(DataManagerError):
    pass


# ===== 工具函数 =====
def _generate_dataset_id() -> str:
    """生成 dataset_id: ds-{utc_timestamp}-{uuid4_hex[:8]}"""
    return f"ds-{int(datetime.now(timezone.utc).timestamp())}-{uuid.uuid4().hex[:8]}"


def _detect_encoding(file_bytes: bytes) -> str:
    """检测文件编码（UTF-8 / GBK 优先），与前端一致"""
    for encoding in ("utf-8", "utf-8-sig", "gbk", "gb18030", "latin-1"):
        try:
            file_bytes.decode(encoding)
            return encoding
        except (UnicodeDecodeError, LookupError):
            continue
    return "utf-8"


def _sniff_header(df_no_header: pd.DataFrame, max_rows: int = 5) -> int:
    """智能表头检测：找第一行作为表头（启发式：列值类型多变 → 可能是表头）

    简化策略：始终把第 0 行当表头（前端默认行为）。如需更智能，可在此扩展。
    """
    return 0


def _dedupe_columns(columns: List[str]) -> List[str]:
    """去重列名（与前端一致：_2 / _3 后缀）"""
    seen: Dict[str, int] = {}
    result = []
    for c in columns:
        c = str(c).strip() if c is not None else ""
        if not c:
            c = "字段"
        if c in seen:
            seen[c] += 1
            result.append(f"{c}_{seen[c]}")
        else:
            seen[c] = 0
            result.append(c)
    return result


def _clean_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """数据清洗：去除完全空行/空列、规范化列名"""
    # 去除完全空白的行
    df = df.dropna(how="all")
    # 去除完全空白的列
    df = df.dropna(axis=1, how="all")
    # 列名去重
    df.columns = _dedupe_columns(list(df.columns))
    # 字符串列去除首尾空格
    for col in df.select_dtypes(include=["object"]).columns:
        df[col] = df[col].astype(str).str.strip().replace({"nan": None, "": None})
    return df.reset_index(drop=True)


def _file_size_mb(file_bytes: bytes) -> float:
    return len(file_bytes) / (1024 * 1024)


# ===== DataManager 主类 =====
class DataManager:
    """数据集管理单例（基于 doc02 §4.2）"""

    def __init__(self):
        self._sqlite_dir = SQLITE_DIR
        self._upload_dir = UPLOAD_DIR

    # ===== 上传 =====
    def upload_file(self, file_bytes: bytes, original_filename: str) -> Dataset:
        """保存文件 + 解析 + 入库 + 插入 Dataset 记录

        Args:
            file_bytes: 文件二进制内容
            original_filename: 原始文件名（用于保留扩展名）

        Returns:
            Dataset 实例

        Raises:
            FileTooLargeError, InvalidFileFormatError, DataManagerError
        """
        # 1. 大小校验
        size_mb = _file_size_mb(file_bytes)
        if size_mb > UPLOAD_CONFIG["max_size_mb"]:
            raise FileTooLargeError(
                f"文件过大：{size_mb:.1f}MB > {UPLOAD_CONFIG['max_size_mb']}MB"
            )

        # 2. 扩展名校验
        ext = Path(original_filename).suffix.lower().lstrip(".")
        if not ext:
            raise InvalidFileFormatError(f"无法识别文件类型: {original_filename}")
        if ext not in UPLOAD_CONFIG["allowed_extensions"]:
            raise InvalidFileFormatError(
                f"不支持的文件格式: .{ext}（仅支持 {UPLOAD_CONFIG['allowed_extensions']}）"
            )

        # 3. 生成 dataset_id
        dataset_id = _generate_dataset_id()
        logger.info(f"[DataManager] 开始上传: {original_filename} → {dataset_id}")

        # 4. 保存原文件
        saved_filename = f"{dataset_id}.{ext}"
        saved_path = self._upload_dir / saved_filename
        saved_path.write_bytes(file_bytes)

        # 5. 解析文件
        try:
            df = self._parse_file(file_bytes, ext)
        except Exception as e:
            saved_path.unlink(missing_ok=True)
            raise InvalidFileFormatError(f"文件解析失败: {str(e)[:200]}")

        df = _clean_dataframe(df)
        if df.empty:
            saved_path.unlink(missing_ok=True)
            raise InvalidFileFormatError("文件为空或无有效数据")

        columns = list(df.columns)

        # 6. 字段推断
        records = df.to_dict(orient="records")
        field_info = infer_field_info_from_records(columns, records)

        # 7. 样本数据（前 5 行）
        sample_rows = records[:5]

        # 8. 写入 SQLite（每数据集一个独立 DB）
        db_path = self._sqlite_dir / f"{dataset_id}.db"
        try:
            self._load_to_sqlite(df, db_path)
        except Exception as e:
            saved_path.unlink(missing_ok=True)
            if db_path.exists():
                db_path.unlink(missing_ok=True)
            raise DataManagerError(f"数据入库失败: {str(e)[:200]}")

        # 9. 插入 Dataset 元数据
        try:
            with db_session_scope() as session:
                dataset = Dataset(
                    id=dataset_id,
                    filename=saved_filename,
                    original_name=original_filename,
                    file_size=len(file_bytes),
                    row_count=len(df),
                    db_path=str(db_path),
                    columns_json=_to_json_str(columns),
                    field_info_json=_to_json_str(field_info),
                    created_at=datetime.now(timezone.utc),
                )
                session.add(dataset)
                session.flush()
                session.refresh(dataset)
                # 拷贝关键字段（session 关闭后仍可用）
                result = Dataset(
                    id=dataset.id,
                    filename=dataset.filename,
                    original_name=dataset.original_name,
                    file_size=dataset.file_size,
                    row_count=dataset.row_count,
                    db_path=dataset.db_path,
                    columns_json=dataset.columns_json,
                    field_info_json=dataset.field_info_json,
                    created_at=dataset.created_at,
                )
        except SQLAlchemyError as e:
            saved_path.unlink(missing_ok=True)
            if db_path.exists():
                db_path.unlink(missing_ok=True)
            raise DataManagerError(f"元数据写入失败: {str(e)[:200]}")

        logger.info(
            f"[DataManager] 上传成功: {dataset_id} ({len(df)} 行 × {len(columns)} 列, "
            f"{len(file_bytes) / 1024:.1f} KB)"
        )
        return result

    def _parse_file(self, file_bytes: bytes, ext: str) -> pd.DataFrame:
        """根据扩展名解析 CSV/Excel"""
        if ext == "csv":
            encoding = _detect_encoding(file_bytes)
            return pd.read_csv(io.BytesIO(file_bytes), encoding=encoding, header=0)
        elif ext in ("xlsx", "xls"):
            return pd.read_excel(io.BytesIO(file_bytes), header=0, engine="openpyxl" if ext == "xlsx" else None)
        else:
            raise InvalidFileFormatError(f"不支持的扩展名: .{ext}")

    def _load_to_sqlite(self, df: pd.DataFrame, db_path: Path):
        """把 DataFrame 写入 SQLite（每个数据集一个 DB）"""
        import sqlite3
        conn = sqlite3.connect(str(db_path))
        try:
            # 用 dataset_id 作为表名（如果存在重复则加序号）
            table_name = "data"
            df.to_sql(table_name, conn, if_exists="replace", index=False)
        finally:
            conn.close()

    # ===== 查询 =====
    def get_dataset(self, dataset_id: str) -> Dataset:
        """获取 Dataset 实例（不存在抛 DatasetNotFoundError）"""
        with db_session_scope() as session:
            ds = session.query(Dataset).filter_by(id=dataset_id).first()
            if not ds:
                raise DatasetNotFoundError(f"数据集不存在: {dataset_id}")
            return Dataset(
                id=ds.id,
                filename=ds.filename,
                original_name=ds.original_name,
                file_size=ds.file_size,
                row_count=ds.row_count,
                db_path=ds.db_path,
                columns_json=ds.columns_json,
                field_info_json=ds.field_info_json,
                created_at=ds.created_at,
            )

    def get_schema(self, dataset_id: str, sample_size: int = 5) -> Dict[str, Any]:
        """获取数据集 schema（包括列、字段信息、样本、类型分布）"""
        ds = self.get_dataset(dataset_id)
        field_info = ds.get_field_info()
        sample_rows = self._get_sample_rows(ds, limit=5)
        type_distribution = compute_type_distribution(field_info)

        return {
            "dataset_id": ds.id,
            "filename": ds.original_name,
            "row_count": ds.row_count,
            "column_count": len(field_info),
            "columns": ds.get_columns(),
            "field_info": field_info,
            "sample_rows": sample_rows,
            "type_distribution": type_distribution,
            "created_at": ds.created_at.isoformat() if ds.created_at else None,
        }

    def _get_sample_rows(self, dataset: Dataset, limit: int = 5) -> List[Dict[str, Any]]:
        """从 SQLite 读取样本数据"""
        import sqlite3
        if not Path(dataset.db_path).exists():
            return []
        conn = sqlite3.connect(str(dataset.db_path))
        try:
            conn.row_factory = sqlite3.Row
            cur = conn.execute('SELECT * FROM "data" LIMIT ?', (limit,))
            rows = [dict(row) for row in cur.fetchall()]
        finally:
            conn.close()
        return rows

    def get_all_rows(self, dataset: Dataset) -> List[Dict[str, Any]]:
        """获取该数据集的所有行（用于 data_profiler / insight_generator）"""
        import sqlite3
        if not Path(dataset.db_path).exists():
            return []
        conn = sqlite3.connect(str(dataset.db_path))
        try:
            conn.row_factory = sqlite3.Row
            cur = conn.execute('SELECT * FROM "data"')
            return [dict(row) for row in cur.fetchall()]
        finally:
            conn.close()

    def load_dataframe(self, dataset_id: str) -> pd.DataFrame:
        """加载数据集为 Pandas DataFrame（InsightGenerator 需要此函数）"""
        ds = self.get_dataset(dataset_id)
        import sqlite3
        if not Path(ds.db_path).exists():
            raise DatasetNotFoundError(f"数据集文件不存在: {dataset.db_path}")
        conn = sqlite3.connect(str(ds.db_path))
        try:
            return pd.read_sql_query('SELECT * FROM "data"', conn)
        finally:
            conn.close()

    def build_data_profile(self, dataset: Dataset) -> str:
        """构建数据画像文本（喂给 LLM 当 system prompt 上下文）

        实际实现委托给 data_profiler.build（避免循环依赖）
        """
        from .data_profiler import build_data_profile as _build
        return _build(dataset)

    # ===== 删除 =====
    def delete_dataset(self, dataset_id: str) -> Dict[str, Any]:
        """删除数据集 + 关联文件 + 缓存条目

        Returns:
            {dataset_id, deleted_files: {upload, sqlite}, cache_entries_deleted}
        """
        ds = self.get_dataset(dataset_id)

        # 1. 删除 SQLite 文件
        sqlite_path = Path(ds.db_path)
        sqlite_deleted = False
        if sqlite_path.exists():
            sqlite_path.unlink()
            sqlite_deleted = True

        # 2. 删除上传的原文件
        upload_path = self._upload_dir / ds.filename
        upload_deleted = False
        if upload_path.exists():
            upload_path.unlink()
            upload_deleted = True

        # 3. 删除 cache_entries + query_history（cascade）
        with db_session_scope() as session:
            from models import CacheEntry, QueryHistory
            cache_count = session.query(CacheEntry).filter_by(dataset_id=dataset_id).delete()
            history_count = session.query(QueryHistory).filter_by(dataset_id=dataset_id).delete()
            session.query(Dataset).filter_by(id=dataset_id).delete()

        logger.info(
            f"[DataManager] 删除数据集: {dataset_id} "
            f"(upload={upload_deleted}, sqlite={sqlite_deleted}, "
            f"cache={cache_count}, history={history_count})"
        )

        return {
            "dataset_id": dataset_id,
            "deleted_files": {
                "upload": upload_deleted,
                "sqlite": sqlite_deleted,
            },
            "cache_entries_deleted": cache_count,
            "query_history_deleted": history_count,
        }


# ===== 工具函数 =====
def _to_json_str(obj: Any) -> str:
    """序列化对象为 JSON 字符串"""
    import json
    return json.dumps(obj, ensure_ascii=False, default=str)


# ===== 模块级单例 =====
data_manager = DataManager()