# 中文注释：定义AI 摘要相关的数据库持久化模型。

from sqlalchemy import Index
from sqlmodel import Field, SQLModel


class ModSummary(SQLModel, table=True):
    __tablename__ = "mod_summaries"
    __table_args__ = (
        Index("ix_mod_summaries_lookup", "mod_id", "language", "summary_type", "id"),
        Index("ix_mod_summaries_language_type_mod", "language", "summary_type", "mod_id"),
        {"sqlite_autoincrement": True},
    )

    id: int | None = Field(default=None, primary_key=True)
    mod_id: int = Field(foreign_key="mods.id")
    language: str = Field(max_length=10)
    summary_type: str = Field(max_length=32)
    content: str
    model: str | None = Field(default=None, max_length=64)
    generated_at: str
