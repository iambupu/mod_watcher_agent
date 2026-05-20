
from pydantic import BaseModel


class ModRead(BaseModel):
    id: int
    source: str
    external_id: str
    game: str
    game_domain: str | None = None
    title: str
    url: str
    author: str | None = None
    category: str | None = None
    tags_json: str = "[]"
    original_summary: str | None = None
    translated_summary: str | None = None
    ai_introduction: str | None = None
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
    ignored: bool = False
    first_seen_at: str
    last_seen_at: str

    model_config = {"from_attributes": True}


class ModList(BaseModel):
    items: list[ModRead]
    total: int


class ModGameOption(BaseModel):
    value: str
    label: str
    count: int


class ModIgnore(BaseModel):
    ignored: bool = True
