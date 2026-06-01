import re
from dataclasses import dataclass
from typing import Any

from app.services.agent.context.context_inference import followup_decision, has_distinctive_keywords
from app.services.agent.context.context_utils import (
    has_query_context_signal as has_query_context_signal_base,
)
from app.services.agent.list_utils import string_list
from app.services.agent.planning.context_result_reference import (
    is_contextual_query_followup,
    referenced_title_keywords,
)
from app.services.game_alias_service import DEFAULT_KNOWN_GAMES, alias_key, build_resolved_aliases
from app.utils.numeric import safe_float


@dataclass(frozen=True)
class QueryContextBackfill:
    context: dict[str, Any]
    keywords: list[str]


def backfill_query_context_for_planning(
    *,
    query: str,
    last_query_context: dict | None,
    history: list | None,
) -> QueryContextBackfill:
    context = last_query_context if isinstance(last_query_context, dict) else {}
    context_keywords = string_list(context.get("keywords"))
    history_context = history_context_for_diagnosis(history)
    if is_contextual_query_followup(query) and history_context:
        merged_context = dict(context)
        if not context_keywords and history_context.get("keywords"):
            merged_context["keywords"] = history_context["keywords"]
            context_keywords = string_list(history_context.get("keywords"))
        for key in ("game", "source_name", "category", "adult_content", "sort_field", "sort_order"):
            if merged_context.get(key) is None and history_context.get(key) is not None:
                merged_context[key] = history_context[key]
        if merged_context != context:
            merged_context["source"] = context.get("source") or history_context.get("source") or "history_backfill"
            context = merged_context

    context_quality = safe_float(context.get("quality_score"))
    if context.get("source") == "current" and (not context_keywords or context_quality < 0.2):
        recovered_keywords = history_keywords(history)
        if recovered_keywords:
            context = {**context, "keywords": recovered_keywords, "source": "history_backfill"}
            context_keywords = recovered_keywords
    return QueryContextBackfill(context=dict(context), keywords=list(context_keywords))


def has_query_context_signal(context: dict[str, Any], keywords: list[str]) -> bool:
    if str(context.get("source") or "").strip().lower() == "current":
        return False
    return bool(keywords) or has_query_context_signal_base(context, include_source_current=False)


def select_effective_last_query_context(query: str, short_context: dict | None, memory_context: dict | None) -> dict:
    short = short_context if isinstance(short_context, dict) else {}
    long = {}
    if isinstance(memory_context, dict):
        loaded = memory_context.get("long_term")
        if isinstance(loaded, dict) and isinstance(loaded.get("last_query_context"), dict):
            long = loaded["last_query_context"]
    if not long:
        return short
    short_keywords = string_list(short.get("keywords"))
    short_anchors = string_list(short.get("semantic_anchors"))
    short_quality = safe_float(short.get("quality_score"))
    followup = followup_decision(query)
    short_is_current = str(short.get("source") or "").strip().lower() == "current"
    if (
        (short_keywords or short_anchors)
        and short_quality >= 0.2
        and not (short_is_current and (followup.is_followup or followup.low_signal))
    ):
        return short
    long_keywords = string_list(long.get("keywords"))
    long_anchors = string_list(long.get("semantic_anchors"))
    long_quality = safe_float(long.get("quality_score"))
    if not (long_keywords or long_anchors) or long_quality < 0.45:
        return short
    if not followup.is_followup and not followup.low_signal:
        return short
    selected = dict(long)
    selected["source"] = "long_term_writeback"
    return selected


def diagnosis_context_from_last_query(last_query_context: dict | None, history: list | None) -> tuple[list[str], dict[str, Any]]:
    context = last_query_context if isinstance(last_query_context, dict) else {}
    keywords = string_list(context.get("keywords"))
    slots = dict(context)
    if str(context.get("source") or "").strip().lower() != "current":
        return keywords, slots
    history_context = history_context_for_diagnosis(history)
    if history_context.get("keywords"):
        keywords = string_list(history_context.get("keywords"))
        slots = history_context
    return keywords, slots


def history_keywords(history: list | None) -> list[str]:
    if not history:
        return []
    for item in reversed(history):
        if str(getattr(item, "role", "")).strip() != "user":
            continue
        text = str(getattr(item, "text", "") or "")
        if not text:
            continue
        if followup_decision(text).score >= 0.7:
            continue
        keywords = referenced_title_keywords(text)
        lexical = [keyword for keyword in keywords if re.fullmatch(r"[a-z0-9\u4e00-\u9fff_-]+", keyword)]
        if lexical and has_distinctive_keywords(lexical):
            return lexical[:5]
    return []


def history_context_for_diagnosis(history: list | None) -> dict[str, Any]:
    if not history:
        return {}
    for item in reversed(history):
        if str(getattr(item, "role", "")).strip() != "user":
            continue
        text = str(getattr(item, "text", "") or "")
        if not text or followup_decision(text).score >= 0.7:
            continue
        keywords = referenced_title_keywords(text)
        lexical = [keyword for keyword in keywords if re.fullmatch(r"[a-z0-9\u4e00-\u9fff_-]+", keyword)]
        if not lexical or not has_distinctive_keywords(lexical):
            continue
        context: dict[str, Any] = {"source": "recent_user", "keywords": lexical[:5]}
        game = _known_game_from_text(text)
        if game:
            context["game"] = game
        return context
    return {}


def _known_game_from_text(text: str) -> str | None:
    games = DEFAULT_KNOWN_GAMES
    lowered = str(text or "").lower()
    for game in games:
        if game.lower() in lowered:
            return game
    text_key = alias_key(str(text or ""))
    for key, targets in build_resolved_aliases(games).items():
        if key and key in text_key and targets:
            return targets[0]
    return None
