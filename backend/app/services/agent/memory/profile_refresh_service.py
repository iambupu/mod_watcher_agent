import json
from collections import Counter
from typing import Any

from sqlmodel import Session, select

from app.models.agent_message import AgentMessage
from app.models.mod import Mod
from app.services.agent.memory.favorite_preference_summarizer import summarize_favorite_preferences
from app.services.agent.memory.preference_service import AgentPreferenceService
from app.services.agent.planning.query_intent import detect_adult_constraint

CONVERSATION_MESSAGE_LIMIT = 200


def refresh_agent_preferences(session: Session) -> dict[str, Any]:
    """Refresh the persisted user profile from favorites and agent conversation history."""
    favorite_summary = summarize_favorite_preferences(session)
    conversation_summary = summarize_conversation_preferences(session)
    preferences = AgentPreferenceService(session).save_preferences(
        {
            "favorite_summary": favorite_summary,
            "last_query_context": conversation_summary,
            "conversation_summary": conversation_summary,
        }
    )
    return {
        "favorite_summary": favorite_summary,
        "conversation_summary": conversation_summary,
        "updated_at": preferences.get("updated_at"),
    }


def summarize_conversation_preferences(session: Session) -> dict[str, Any]:
    """Build deterministic preference signals from recent agent messages."""
    messages = session.exec(
        select(AgentMessage)
        .order_by(AgentMessage.id.desc())
        .limit(CONVERSATION_MESSAGE_LIMIT)
    ).all()
    messages.reverse()

    slot_values = _load_slot_values(session)
    game_counter: Counter[str] = Counter()
    source_counter: Counter[str] = Counter()
    category_counter: Counter[str] = Counter()
    adult_requests = 0
    sfw_requests = 0
    matched_mod_count = 0

    for message in messages:
        if message.role == "user":
            text = message.text or ""
            _count_text_mentions(text, slot_values["games"], game_counter)
            _count_text_mentions(text, slot_values["game_domains"], game_counter)
            _count_text_mentions(text, slot_values["categories"], category_counter)
            _count_text_mentions(text, slot_values["sources"], source_counter)
            adult_constraint = detect_adult_constraint(text)
            if adult_constraint is True:
                adult_requests += 1
            elif adult_constraint is False:
                sfw_requests += 1

        matches = _safe_json_list(message.matches_json)
        matched_mod_count += len(matches)
        for item in matches:
            _count_match_value(item.get("game"), game_counter)
            _count_match_value(item.get("game_domain"), game_counter)
            _count_match_value(item.get("source"), source_counter)
            _count_match_value(item.get("category"), category_counter)
            if item.get("adult_content") is True:
                adult_requests += 1

    top_games = _top_values(game_counter)
    top_sources = _top_values(source_counter)
    top_categories = _top_values(category_counter)
    adult_content_preference = None
    if adult_requests or sfw_requests:
        adult_content_preference = adult_requests >= sfw_requests

    return {
        "message_count": len(messages),
        "matched_mod_count": matched_mod_count,
        "top_games": top_games,
        "top_sources": top_sources,
        "top_categories": top_categories,
        "adult_content_requests": adult_requests,
        "sfw_requests": sfw_requests,
        "adult_content_preference": adult_content_preference,
        "summary": _summary_text(top_games, top_categories, top_sources, adult_content_preference),
    }


def _load_slot_values(session: Session) -> dict[str, list[str]]:
    def values(column) -> list[str]:
        rows = session.exec(
            select(column)
            .where(column.is_not(None), column != "")
            .distinct()
            .limit(500)
        ).all()
        return [str(row).strip() for row in rows if str(row or "").strip()]

    return {
        "games": values(Mod.game),
        "game_domains": values(Mod.game_domain),
        "categories": values(Mod.category),
        "sources": ["nexusmods", "nexus mods", "loverslab", *values(Mod.source)],
    }


def _safe_json_list(raw: str | None) -> list[dict[str, Any]]:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [item for item in parsed if isinstance(item, dict)]


def _count_text_mentions(text: str, values: list[str], counter: Counter[str]) -> None:
    haystack = text.lower()
    for value in values:
        if value and value.lower() in haystack:
            counter[_canonical_source(value)] += 1


def _count_match_value(value: object, counter: Counter[str]) -> None:
    normalized = str(value or "").strip()
    if normalized:
        counter[_canonical_source(normalized)] += 1


def _canonical_source(value: str) -> str:
    normalized = value.strip()
    if normalized.lower() == "nexus mods":
        return "nexusmods"
    return normalized


def _top_values(counter: Counter[str]) -> list[str]:
    return [value for value, _count in counter.most_common(5)]


def _summary_text(
    top_games: list[str],
    top_categories: list[str],
    top_sources: list[str],
    adult_content_preference: bool | None,
) -> str:
    parts = []
    if top_games:
        parts.append(f"对话偏向 {', '.join(top_games[:3])}")
    if top_categories:
        parts.append(f"对话常见分类为 {', '.join(top_categories[:3])}")
    if top_sources:
        parts.append(f"对话常见来源为 {', '.join(top_sources[:3])}")
    if adult_content_preference is True:
        parts.append("对话中成人内容倾向较明显")
    elif adult_content_preference is False:
        parts.append("对话中更偏向排除成人内容")
    return "；".join(parts) + ("。" if parts else "")
