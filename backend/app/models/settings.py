from typing import Optional
from sqlmodel import SQLModel, Field


class Setting(SQLModel, table=True):
    __tablename__ = "settings"
    __table_args__ = {"sqlite_autoincrement": True}

    id: Optional[int] = Field(default=None, primary_key=True)
    key: str = Field(max_length=255, unique=True)
    value: str
    updated_at: str
