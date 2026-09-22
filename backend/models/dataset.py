"""
dataset.py — Dataset 模型（数据集元信息）

约定（doc02 §3）：
- id 格式：`ds-{timestamp}-{uuid_hex[:8]}`（例：`ds-1723294800-abc123`）
- columns_json / field_info_json 用 TEXT 存 JSON 字符串（SQLite 不支持 JSON 类型）
- file_size 单位字节；file_size_display 是格式化后的字符串（"245 KB"）
- db_path 指向该 dataset 自己的 SQLite 文件（每个数据集一个 DB）
"""
import json
from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Text, DateTime

from .database import Base


class Dataset(Base):
    __tablename__ = "datasets"

    id = Column(String(64), primary_key=True)
    # 磁盘上的文件名（带 dataset_id 前缀避免冲突）
    filename = Column(String(256), nullable=False)
    # 用户上传时的原始文件名
    original_name = Column(String(256), nullable=False)
    # 文件字节数
    file_size = Column(Integer, nullable=False)
    # 数据行数
    row_count = Column(Integer, nullable=False)
    # 该数据集的 SQLite 文件绝对路径（每数据集一个 DB，隔离数据）
    db_path = Column(String(512), nullable=False)
    # 列名 JSON 字符串
    columns_json = Column(Text, nullable=False, default="[]")
    # 字段信息数组 JSON 字符串
    field_info_json = Column(Text, nullable=False, default="[]")
    # 创建时间（UTC）
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    def get_columns(self) -> list:
        return json.loads(self.columns_json) if self.columns_json else []

    def get_field_info(self) -> list:
        return json.loads(self.field_info_json) if self.field_info_json else []

    def to_dict(self) -> dict:
        return {
            "dataset_id": self.id,
            "id": self.id,
            "filename": self.filename,
            "original_name": self.original_name,
            "file_size": self.file_size,
            "file_size_display": _format_size(self.file_size),
            "row_count": self.row_count,
            "columns": self.get_columns(),
            "field_info": self.get_field_info(),
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


def _format_size(size_bytes: int) -> str:
    """把字节数格式化为人类可读字符串（与前端一致）"""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    if size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"