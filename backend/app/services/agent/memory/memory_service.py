# 中文注释：管理 Agent 长期记忆、偏好和证据记录。

from datetime import UTC, datetime
from typing import Any, TypedDict

from sqlmodel import Session

from app.services.agent.list_utils import string_list, unique_text
from app.services.agent.memory.preference_service import AgentPreferenceService
from app.services.agent.semantic_search import canonical_semantic_terms
from app.utils.time import parse_utc_datetime


class AgentMemoryContext(TypedDict):
    short_term: dict[str, Any]
    long_term: dict[str, Any]
    merged: dict[str, Any]


class AgentMemoryService:
    _LONG_TERM_STALE_DAYS = 90

    def __init__(self, session: Session | None):
        self.session = session

    def load_memory_context(self, *, short_term: dict[str, Any] | None = None) -> AgentMemoryContext:
        short = short_term if isinstance(short_term, dict) else {}
        long = self._load_long_term_preferences()
        merged = self._merge_memory(short, long)
        return {
            "short_term": short,
            "long_term": long,
            "merged": merged,
        }

    def _load_long_term_preferences(self) -> dict[str, Any]:
        if self.session is None:
            return {}
        try:
            data = AgentPreferenceService(self.session).load_preferences()
        except Exception:
            return {}
        if not isinstance(data, dict):
            return {}
        return {
            "favorite_summary": data.get("favorite_summary") if isinstance(data.get("favorite_summary"), dict) else {},
            "conversation_summary": (
                data.get("conversation_summary") if isinstance(data.get("conversation_summary"), dict) else {}
            ),
            "last_query_context": (
                data.get("last_query_context") if isinstance(data.get("last_query_context"), dict) else {}
            ),
            "updated_at": data.get("updated_at"),
        }

    def _merge_memory(self, short: dict[str, Any], long: dict[str, Any]) -> dict[str, Any]:
        short_query = short.get("last_query_context") if isinstance(short.get("last_query_context"), dict) else {}
        long_query = long.get("last_query_context") if isinstance(long.get("last_query_context"), dict) else {}
        favorite = long.get("favorite_summary") if isinstance(long.get("favorite_summary"), dict) else {}
        conversation = long.get("conversation_summary") if isinstance(long.get("conversation_summary"), dict) else {}
        merged_query = {**long_query, **short_query}
        for key in ("keywords", "semantic_anchors", "semantic_domains"):
            merged_values = [*string_list(long_query.get(key)), *string_list(short_query.get(key))]
            if key in {"keywords", "semantic_anchors"}:
                merged_values = canonical_semantic_terms(merged_values)
            merged_values = unique_text(merged_values)
            if merged_values:
                merged_query[key] = merged_values
        updated_at = parse_utc_datetime(long.get("updated_at"))
        age_days = _age_days(updated_at)
        preference_stale = _is_stale(updated_at, max_age_days=self._LONG_TERM_STALE_DAYS)
        return {
            "last_query_context": merged_query,
            "favorite_summary": favorite,
            "conversation_summary": conversation,
            "memory_meta": {
                "preferences_updated_at": updated_at.isoformat() if updated_at else None,
                "preferences_age_days": age_days,
                "preference_stale": preference_stale,
            },
        }


def _is_stale(value: datetime | None, *, max_age_days: int) -> bool:
    if value is None:
        return False
    age_seconds = (datetime.now(UTC) - value).total_seconds()
    return age_seconds > max_age_days * 24 * 3600


def _age_days(value: datetime | None) -> int | None:
    if value is None:
        return None
    age_seconds = max(0.0, (datetime.now(UTC) - value).total_seconds())
    return int(age_seconds // 86400)
