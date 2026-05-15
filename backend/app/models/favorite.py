from typing import Optional
from sqlmodel import SQLModel, Field


class Favorite(SQLModel, table=True):
    __tablename__ = "favorites"
    __table_args__ = {"sqlite_autoincrement": True}

    id: Optional[int] = Field(default=None, primary_key=True)
    mod_id: int = Field(foreign_key="mods.id", unique=True)
    tracking_enabled: bool = Field(default=True)
    notify_on_update: bool = Field(default=True)
    user_note: Optional[str] = Field(default=None)
    user_tags_json: str = Field(default="[]")
    last_known_version: Optional[str] = Field(default=None, max_length=64)
    last_known_updated_at: Optional[str] = Field(default=None)
    last_checked_at: Optional[str] = Field(default=None)
    created_at: str
    updated_at: str
