from typing import Optional
from pydantic import BaseModel

from app.schemas.mod import ModRead


class FavoriteCreate(BaseModel):
    mod_id: int
    tracking_enabled: bool = True
    notify_on_update: bool = True
    user_note: Optional[str] = None
    user_tags_json: str = "[]"


class FavoriteUpdate(BaseModel):
    tracking_enabled: Optional[bool] = None
    notify_on_update: Optional[bool] = None
    user_note: Optional[str] = None
    user_tags_json: Optional[str] = None


class FavoriteRead(BaseModel):
    id: int
    mod_id: int
    tracking_enabled: bool
    notify_on_update: bool
    user_note: Optional[str] = None
    user_tags_json: str
    last_known_version: Optional[str] = None
    last_known_updated_at: Optional[str] = None
    last_checked_at: Optional[str] = None
    created_at: str
    updated_at: str
    translated_summary: Optional[str] = None
    mod: Optional[ModRead] = None

    model_config = {"from_attributes": True}
