from typing import Optional
from pydantic import BaseModel


class UpdateEventRead(BaseModel):
    id: int
    mod_id: int
    favorite_id: Optional[int] = None
    old_version: Optional[str] = None
    new_version: Optional[str] = None
    old_updated_at: Optional[str] = None
    new_updated_at: Optional[str] = None
    raw_changelog: Optional[str] = None
    change_summary: Optional[str] = None
    detected_at: str
    seen: bool
    translated_summary: Optional[str] = None

    model_config = {"from_attributes": True}


class UpdateEventPatch(BaseModel):
    seen: bool


class UpdateEventList(BaseModel):
    items: list[UpdateEventRead]
    total: int
