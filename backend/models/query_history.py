"""
query_history.py — QueryHistory 模型（查询历史记录）

约定（doc02 §3）：
- id 用 Integer autoincrement（与 doc01 String(64) 不同，采用 doc02 最新约定）
- result_json / chart_config_json 用 TEXT 存 JSON 字符串
- cached 标记是否命中缓存（用于缓存命中率统计）
- response_time_ms 记录端到端延迟（性能分析）
"""
import json
from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, Index

from .database import Base


class QueryHistory(Base):
    __tablename__ = "query_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    dataset_id = Column(String(64), nullable=False, index=True)
    question = Column(Text, nullable=False)
    sql_text = Column(Text, nullable=False)
    # 查询结果 JSON 字符串（包含 columns + rows）
    result_json = Column(Text, nullable=True)
    # 图表配置 JSON 字符串（chartType / categories / values 等）
    chart_config_json = Column(Text, nullable=True)
    # 文字解读
    insight = Column(Text, nullable=True)
    # 是否命中缓存
    cached = Column(Boolean, default=False, nullable=False)
    # 端到端响应延迟（毫秒）
    response_time_ms = Column(Integer, nullable=False, default=0)
    # LLM 调用次数（0 表示走规则引擎或缓存命中）
    llm_calls = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False, index=True)

    __table_args__ = (
        Index("idx_query_history_dataset_created", "dataset_id", "created_at"),
    )

    def get_result(self) -> dict:
        return json.loads(self.result_json) if self.result_json else None

    def get_chart_config(self) -> dict:
        return json.loads(self.chart_config_json) if self.chart_config_json else None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "dataset_id": self.dataset_id,
            "question": self.question,
            "sql_text": self.sql_text,
            "result": self.get_result(),
            "chart_config": self.get_chart_config(),
            "insight": self.insight,
            "cached": self.cached,
            "response_time_ms": self.response_time_ms,
            "llm_calls": self.llm_calls,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def to_summary(self) -> dict:
        """历史列表用的摘要（不含完整 result 数据，节省带宽）"""
        chart_config = self.get_chart_config()
        result = self.get_result()
        return {
            "id": self.id,
            "question": self.question,
            "sql_text": self.sql_text,
            "chart_type": chart_config.get("chartType") or chart_config.get("type") if chart_config else None,
            "intent": chart_config.get("intent") if chart_config else None,
            "cached": self.cached,
            "response_time_ms": self.response_time_ms,
            "row_count": len(result.get("rows", [])) if result else 0,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }