
from sqlalchemy import Column, Text
from sqlmodel import Field, SQLModel

from app.rule_constants import DEFAULT_RULE_INTERVAL_MINUTES


class WatchRule(SQLModel, table=True):
    __tablename__ = "watch_rules"
    __table_args__ = {"sqlite_autoincrement": True}

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(max_length=255)
    enabled: bool = Field(default=True)
    source: str = Field(max_length=32, default="nexusmods")
    interval_minutes: int = Field(default=DEFAULT_RULE_INTERVAL_MINUTES)
    source_config_json: str = Field(default="{}", sa_column=Column(Text))
    filters_json: str = Field(default="{}", sa_column=Column(Text))
    notification_json: str = Field(default="{}", sa_column=Column(Text))
    created_at: str
    updated_at: str
