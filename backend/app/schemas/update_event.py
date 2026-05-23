
from pydantic import BaseModel

from app.schemas.mod import ModRead


class UpdateEventRead(BaseModel):
    id: int
    mod_id: int
    favorite_id: int | None = None
    old_version: str | None = None
    new_version: str | None = None
    old_updated_at: str | None = None
    new_updated_at: str | None = None
    raw_changelog: str | None = None
    change_summary: str | None = None
    detected_at: str
    seen: bool
    translated_summary: str | None = None
    mod: ModRead | None = None

    model_config = {"from_attributes": True}


class UpdateEventPatch(BaseModel):
    seen: bool


class UpdateEventList(BaseModel):
    items: list[UpdateEventRead]
    total: int
