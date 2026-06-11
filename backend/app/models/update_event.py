# 中文注释：定义更新事件相关的数据库持久化模型。

from sqlmodel import Field, SQLModel


class ModUpdateEvent(SQLModel, table=True):
    __tablename__ = "mod_update_events"
    __table_args__ = {"sqlite_autoincrement": True}

    id: int | None = Field(default=None, primary_key=True)
    mod_id: int = Field(foreign_key="mods.id")
    favorite_id: int | None = Field(default=None, foreign_key="favorites.id")
    old_version: str | None = Field(default=None, max_length=64)
    new_version: str | None = Field(default=None, max_length=64)
    old_updated_at: str | None = Field(default=None)
    new_updated_at: str | None = Field(default=None)
    raw_changelog: str | None = Field(default=None)
    change_summary: str | None = Field(default=None)
    detected_at: str
    seen: bool = Field(default=False)
