# 中文注释：定义收藏 API请求和响应的数据契约。

from pydantic import BaseModel

from app.schemas.mod import ModRead


class FavoriteImportCreate(BaseModel):
    source: str
    external_id: str
    game: str = ""
    game_domain: str | None = None
    title: str
    translated_title_zh: str | None = None
    url: str
    author: str | None = None
    category: str | None = None
    tags_json: str = "[]"
    original_summary: str | None = None
    version: str | None = None
    created_at_remote: str | None = None
    updated_at_remote: str | None = None
    published_at_remote: str | None = None
    downloads: int | None = None
    unique_downloads: int | None = None
    endorsements: int | None = None
    views: int | None = None
    likes: int | None = None
    adult_content: bool | None = None
    thumbnail_url: str | None = None
    raw_json: str | None = None
    tracking_enabled: bool = True
    notify_on_update: bool = True
    user_note: str | None = None
    user_tags_json: str = "[]"


class FavoriteCreate(BaseModel):
    mod_id: int
    tracking_enabled: bool = True
    notify_on_update: bool = True
    user_note: str | None = None
    user_tags_json: str = "[]"


class FavoriteUpdate(BaseModel):
    tracking_enabled: bool | None = None
    notify_on_update: bool | None = None
    user_note: str | None = None
    user_tags_json: str | None = None


class FavoriteRead(BaseModel):
    id: int
    mod_id: int
    tracking_enabled: bool
    notify_on_update: bool
    user_note: str | None = None
    user_tags_json: str
    last_known_version: str | None = None
    last_known_updated_at: str | None = None
    last_checked_at: str | None = None
    created_at: str
    updated_at: str
    translated_summary: str | None = None
    mod: ModRead | None = None

    model_config = {"from_attributes": True}
