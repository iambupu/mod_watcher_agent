from typing import Optional
from sqlmodel import SQLModel, Field


class ModSummary(SQLModel, table=True):
    __tablename__ = "mod_summaries"
    __table_args__ = {"sqlite_autoincrement": True}

    id: Optional[int] = Field(default=None, primary_key=True)
    mod_id: int = Field(foreign_key="mods.id")
    language: str = Field(max_length=10)
    summary_type: str = Field(max_length=32)
    content: str
    model: Optional[str] = Field(default=None, max_length=64)
    generated_at: str
