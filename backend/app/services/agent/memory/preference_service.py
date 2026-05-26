import json
from datetime import UTC, datetime
from typing import Any

from sqlmodel import Session

from app.services.settings_service import SettingsService

PREFERENCES_KEY = "agent_preferences_json"
PREFERENCES_DIRTY_KEY = "agent_preferences_dirty"


class AgentPreferenceService:
    def __init__(self, session: Session):
        self.settings = SettingsService(session)

    def load_preferences(self) -> dict[str, Any]:
        raw = self.settings.get(PREFERENCES_KEY)
        if not raw:
            return _empty_preferences()
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return _empty_preferences()
        if not isinstance(data, dict):
            return _empty_preferences()
        return {**_empty_preferences(), **data}

    def save_preferences(self, preferences: dict[str, Any]) -> dict[str, Any]:
        data = {**self.load_preferences(), **preferences}
        data["updated_at"] = datetime.now(UTC).isoformat()
        self.settings.set(PREFERENCES_KEY, json.dumps(data, ensure_ascii=False))
        self.settings.set(PREFERENCES_DIRTY_KEY, "false")
        return data

    def save_last_query_context(self, context: dict[str, Any]) -> dict[str, Any]:
        cleaned = _clean_context(context)
        if not cleaned:
            return self.load_preferences()
        return self.save_preferences({"last_query_context": cleaned})

    def mark_dirty(self) -> None:
        self.settings.set(PREFERENCES_DIRTY_KEY, "true")

    def is_dirty(self) -> bool:
        return (self.settings.get(PREFERENCES_DIRTY_KEY) or "false").strip().lower() == "true"


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
            values = [str(item).strip() for item in value if str(item).strip()]
            if values:
                cleaned[name] = values[:12]
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
