# 中文注释：定义Mod 主表相关的数据库持久化模型。

from sqlalchemy import Index, UniqueConstraint
from sqlmodel import Field, SQLModel


class Mod(SQLModel, table=True):
    __tablename__ = "mods"
    __table_args__ = (
        UniqueConstraint("source", "external_id", name="uq_mod_source_external_id"),
        Index("ix_mods_ignored_first_seen_at", "ignored", "first_seen_at"),
        Index("ix_mods_ignored_downloads", "ignored", "downloads"),
        Index("ix_mods_ignored_endorsements", "ignored", "endorsements"),
        Index("ix_mods_ignored_updated_at_remote", "ignored", "updated_at_remote"),
        Index(
            "ix_mods_ignored_downloads_endorsements_first_seen_at",
            "ignored",
            "downloads",
            "endorsements",
            "first_seen_at",
        ),
        Index("ix_mods_game_ignored", "game", "ignored"),
        Index("ix_mods_game_domain_ignored", "game_domain", "ignored"),
        Index("ix_mods_source_ignored", "source", "ignored"),
        Index("ix_mods_category_ignored", "category", "ignored"),
        {"sqlite_autoincrement": True},
    )

    id: int | None = Field(default=None, primary_key=True)
    source: str = Field(max_length=255)
    external_id: str = Field(max_length=255)
    game: str = Field(max_length=255)
    game_domain: str | None = Field(default=None, max_length=255)
    title: str = Field(max_length=512)
    translated_title_zh: str | None = Field(default=None, max_length=512)
    url: str = Field(max_length=1024)
    author: str | None = Field(default=None, max_length=255)
    category: str | None = Field(default=None, max_length=255)
    tags_json: str = Field(default="[]")
    original_summary: str | None = Field(default=None)
    version: str | None = Field(default=None, max_length=64)
    created_at_remote: str | None = Field(default=None)
    updated_at_remote: str | None = Field(default=None)
    published_at_remote: str | None = Field(default=None)
    downloads: int | None = Field(default=None)
    unique_downloads: int | None = Field(default=None)
    endorsements: int | None = Field(default=None)
    views: int | None = Field(default=None)
    likes: int | None = Field(default=None)
    adult_content: bool | None = Field(default=None)
    thumbnail_url: str | None = Field(default=None, max_length=1024)
    raw_json: str | None = Field(default=None)
    ignored: bool = Field(default=False)
    first_seen_at: str
    last_seen_at: str
