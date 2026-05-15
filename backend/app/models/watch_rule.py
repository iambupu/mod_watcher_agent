from typing import Optional

from sqlalchemy import Column, Text
from sqlmodel import Field, SQLModel


class WatchRule(SQLModel, table=True):
    __tablename__ = "watch_rules"
    __table_args__ = {"sqlite_autoincrement": True}

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(max_length=255)
    enabled: bool = Field(default=True)
    source: str = Field(max_length=32, default="nexusmods")
    interval_minutes: int = Field(default=360)
    source_config_json: str = Field(default="{}", sa_column=Column(Text))
    filters_json: str = Field(default="{}", sa_column=Column(Text))
    notification_json: str = Field(default="{}", sa_column=Column(Text))
    created_at: str
    updated_at: str
