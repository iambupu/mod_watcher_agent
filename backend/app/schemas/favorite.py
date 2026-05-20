
from pydantic import BaseModel

from app.schemas.mod import ModRead


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
