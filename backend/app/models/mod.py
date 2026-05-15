from typing import Optional
from sqlalchemy import UniqueConstraint
from sqlmodel import SQLModel, Field


class Mod(SQLModel, table=True):
    __tablename__ = "mods"
    __table_args__ = (
        UniqueConstraint("source", "external_id", name="uq_mod_source_external_id"),
        {"sqlite_autoincrement": True},
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    source: str = Field(max_length=255)
    external_id: str = Field(max_length=255)
    game: str = Field(max_length=255)
    game_domain: Optional[str] = Field(default=None, max_length=255)
    title: str = Field(max_length=512)
    url: str = Field(max_length=1024)
    author: Optional[str] = Field(default=None, max_length=255)
    category: Optional[str] = Field(default=None, max_length=255)
    tags_json: str = Field(default="[]")
    original_summary: Optional[str] = Field(default=None)
    version: Optional[str] = Field(default=None, max_length=64)
    created_at_remote: Optional[str] = Field(default=None)
    updated_at_remote: Optional[str] = Field(default=None)
    published_at_remote: Optional[str] = Field(default=None)
    downloads: Optional[int] = Field(default=None)
    unique_downloads: Optional[int] = Field(default=None)
    endorsements: Optional[int] = Field(default=None)
    views: Optional[int] = Field(default=None)
    likes: Optional[int] = Field(default=None)
    adult_content: Optional[bool] = Field(default=None)
    thumbnail_url: Optional[str] = Field(default=None, max_length=1024)
    raw_json: Optional[str] = Field(default=None)
    ignored: bool = Field(default=False)
    first_seen_at: str
    last_seen_at: str
