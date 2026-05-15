from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class ModItem:
    source_id: str
    source: str
    name: str
    game: str
    url: str
    summary: str = ""
    author: str = ""
    downloads: int = 0
    endorsements: int = 0
    likes: int = 0
    categories: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    thumbnail_url: str = ""
    updated_at: datetime | None = None
    is_adult: bool = False
    raw: dict | None = None
