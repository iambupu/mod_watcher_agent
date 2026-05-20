
from sqlmodel import Field, SQLModel


class Favorite(SQLModel, table=True):
    __tablename__ = "favorites"
    __table_args__ = {"sqlite_autoincrement": True}

    id: int | None = Field(default=None, primary_key=True)
    mod_id: int = Field(foreign_key="mods.id", unique=True)
    tracking_enabled: bool = Field(default=True)
    notify_on_update: bool = Field(default=True)
    user_note: str | None = Field(default=None)
    user_tags_json: str = Field(default="[]")
    last_known_version: str | None = Field(default=None, max_length=64)
    last_known_updated_at: str | None = Field(default=None)
    last_checked_at: str | None = Field(default=None)
    created_at: str
    updated_at: str
