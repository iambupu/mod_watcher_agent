from typing import Optional
from pydantic import BaseModel


class SettingsRead(BaseModel):
    settings: dict[str, str]


class SettingsUpdate(BaseModel):
    settings: dict[str, Optional[str]]
