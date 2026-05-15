from typing import Optional
from pydantic import BaseModel


class ModRead(BaseModel):
    id: int
    source: str
    external_id: str
    game: str
    game_domain: Optional[str] = None
    title: str
    url: str
    author: Optional[str] = None
    category: Optional[str] = None
    tags_json: str = "[]"
    original_summary: Optional[str] = None
    translated_summary: Optional[str] = None
    ai_introduction: Optional[str] = None
    version: Optional[str] = None
    created_at_remote: Optional[str] = None
    updated_at_remote: Optional[str] = None
    published_at_remote: Optional[str] = None
    downloads: Optional[int] = None
    unique_downloads: Optional[int] = None
    endorsements: Optional[int] = None
    views: Optional[int] = None
    likes: Optional[int] = None
    adult_content: Optional[bool] = None
    thumbnail_url: Optional[str] = None
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
