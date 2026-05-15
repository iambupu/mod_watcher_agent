from typing import Optional
from sqlmodel import SQLModel, Field


class ModUpdateEvent(SQLModel, table=True):
    __tablename__ = "mod_update_events"
    __table_args__ = {"sqlite_autoincrement": True}

    id: Optional[int] = Field(default=None, primary_key=True)
    mod_id: int = Field(foreign_key="mods.id")
    favorite_id: Optional[int] = Field(default=None, foreign_key="favorites.id")
    old_version: Optional[str] = Field(default=None, max_length=64)
    new_version: Optional[str] = Field(default=None, max_length=64)
    old_updated_at: Optional[str] = Field(default=None)
    new_updated_at: Optional[str] = Field(default=None)
    raw_changelog: Optional[str] = Field(default=None)
    change_summary: Optional[str] = Field(default=None)
    detected_at: str
    seen: bool = Field(default=False)
