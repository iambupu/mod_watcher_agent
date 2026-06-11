# 中文注释：管理 Agent 长期记忆、偏好和证据记录。

import json
from datetime import UTC, datetime
from typing import Any

from sqlmodel import Session

from app.services.agent.list_utils import string_list
from app.services.settings_service import SettingsService
from app.utils.boolean import parse_bool
from app.utils.json import json_object

PREFERENCES_KEY = "agent_preferences_json"
PREFERENCES_DIRTY_KEY = "agent_preferences_dirty"


class AgentPreferenceService:
    def __init__(self, session: Session):
        self.settings = SettingsService(session)

    def load_preferences(self) -> dict[str, Any]:
        data = json_object(self.settings.get(PREFERENCES_KEY))
        if not data:
            return _empty_preferences()
        return {**_empty_preferences(), **data}

    def save_preferences(self, preferences: dict[str, Any]) -> dict[str, Any]:
        data = {**self.load_preferences(), **preferences}
        data["updated_at"] = datetime.now(UTC).isoformat()
        self.settings.set_batch(
            {
                PREFERENCES_KEY: json.dumps(data, ensure_ascii=False),
                PREFERENCES_DIRTY_KEY: "false",
            }
        )
        return data

    def save_last_query_context(self, context: dict[str, Any]) -> dict[str, Any]:
        cleaned = _clean_context(context)
        if not cleaned:
            return self.load_preferences()
        return self.save_preferences({"last_query_context": cleaned})

    def mark_dirty(self, *, commit: bool = True) -> None:
        self.settings.set(PREFERENCES_DIRTY_KEY, "true", commit=commit)

    def is_dirty(self) -> bool:
        return parse_bool(self.settings.get(PREFERENCES_DIRTY_KEY))


def _empty_preferences() -> dict[str, Any]:
    return {
        "last_query_context": {},
        "favorite_summary": {},
        "updated_at": None,
    }


def _clean_context(context: dict[str, Any]) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    for key, value in context.items():
        name = str(key or "").strip()
        if not name:
            continue
        if isinstance(value, list):
            values = string_list(value, limit=12)
            if values:
                cleaned[name] = values
            continue
        if isinstance(value, bool):
            cleaned[name] = value
            continue
        if isinstance(value, int | float):
            cleaned[name] = value
            continue
        text = str(value or "").strip()
        if text:
            cleaned[name] = text
    return cleaned
