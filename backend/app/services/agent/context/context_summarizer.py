import logging
import re
from datetime import UTC, datetime

from app.services.agent.context.context_inference import has_distinctive_keywords
from app.services.agent.context.context_selection import (
    context_quality_score,
    select_history_query_context,
    should_inherit_active_constraints,
    should_use_current_query_context,
)
from app.services.agent.context.context_store import AgentContextSnapshot
from app.services.agent.context.context_window import split_context_window
from app.services.agent.planning.query_intent import (
    detect_adult_constraint,
    infer_source_constraints,
    is_recent_query,
)
from app.services.agent.planning.semantic_signals import anchor_domains, extract_semantic_anchors
from app.services.agent.schemas import AgentChatRequest, AgentHistoryItem, AgentModDetailRequest
from app.services.agent.semantic_search import base_keywords
from app.services.game_alias_service import DEFAULT_KNOWN_GAMES, alias_key, build_resolved_aliases

logger = logging.getLogger(__name__)

_KNOWN_GAMES = DEFAULT_KNOWN_GAMES
_CATEGORY_HINTS = {
    "服装": "outfit",
    "outfit": "outfit",
    "clothing": "outfit",
    "dress": "outfit",
    "画质": "visual",
    "visual": "visual",
}


def summarize_agent_context(
    request: AgentChatRequest | AgentModDetailRequest,
    *,
    recent_message_count: int = 5,
) -> AgentContextSnapshot:
    older, recent = split_context_window(request.history, recent_message_count=recent_message_count)
    current_text = _request_text(request)
    all_context_text = "\n".join([*(item.text for item in request.history), current_text])
    running_summary = _build_running_summary(older, current_text)
    return {
        "running_summary": running_summary,
        "recent_messages": recent,
        "active_constraints": _extract_constraints(all_context_text, current_text),
        "last_query_context": _extract_last_query_context(request.history, current_text),
        "shown_mod_titles": _extract_shown_mod_titles(request.history),
        "tool_traces": [],
        "reflection_notes": [],
        "summary_updated_at": datetime.now(UTC).isoformat(),
    }


def _build_running_summary(older: list[AgentHistoryItem], current_text: str) -> str:
    lines: list[str] = []
    if older:
        for item in older[-8:]:
            prefix = "用户" if item.role == "user" else "助手"
            lines.append(f"{prefix}: {item.text}")
    if current_text:
        lines.append(f"本轮用户: {current_text}")
    return "上下文摘要:\n" + "\n".join(lines) if lines else ""


def _extract_constraints(all_context_text: str, current_text: str) -> dict[str, object]:
    constraints: dict[str, object] = {}
    inherit_history = should_inherit_active_constraints(current_text)
    history_text = all_context_text if inherit_history else current_text
    game = _find_known_value(current_text, _KNOWN_GAMES) or _find_known_value(history_text, _KNOWN_GAMES)
    if game:
        constraints["game"] = game
    current_source_constraints = infer_source_constraints(current_text)
    all_source_constraints = infer_source_constraints(history_text)
    source = None
    if current_source_constraints.get("sources"):
        source = current_source_constraints["sources"][0]
    elif not current_source_constraints.get("excluded_sources") and all_source_constraints.get("sources"):
        source = all_source_constraints["sources"][0]
    if source:
        constraints["source"] = source
    category = _find_category(current_text) or _find_category(history_text)
    if category:
        constraints["category"] = category
    current_adult_content = detect_adult_constraint(current_text)
    adult_content = current_adult_content
    if adult_content is None and inherit_history:
        adult_content = detect_adult_constraint(all_context_text)
    if adult_content is not None:
        constraints["adult_content"] = adult_content
    has_recent_signal = is_recent_query(current_text) or _contains_any(
        current_text,
        ["最近", "最新", "更新", "recent", "latest"],
    )
    inherited_recent_signal = inherit_history and (
        is_recent_query(all_context_text) or _contains_any(all_context_text, ["最近", "最新", "更新", "recent", "latest"])
    )
    if has_recent_signal or inherited_recent_signal:
        constraints["sort_field"] = "updated_at_remote"
        constraints["sort_order"] = "desc"
    return constraints


def _request_text(request: AgentChatRequest | AgentModDetailRequest) -> str:
    if isinstance(request, AgentChatRequest):
        return request.message.strip()
    return (request.question or "").strip()


def _find_known_value(text: str, values: list[str]) -> str | None:
    lowered = text.lower()
    for value in values:
        if value.lower() in lowered:
            return value
    text_key = alias_key(text)
    if not text_key:
        return None
    for key, targets in build_resolved_aliases(values).items():
        if key and key in text_key and targets:
            return targets[0]
    return None


def _find_category(text: str) -> str | None:
    lowered = text.lower()
    for marker, category in _CATEGORY_HINTS.items():
        if marker in lowered:
            return category
    return None


def _contains_any(text: str, markers: list[str]) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in markers)


def _extract_last_query_context(history: list[AgentHistoryItem], current_text: str) -> dict[str, object]:
    current_keywords = base_keywords(current_text)
    if should_use_current_query_context(current_text, current_keywords):
        return _query_context_from_text(current_text, source="current")
    candidates: list[dict[str, object]] = []
    for item in reversed(history):
        if item.role != "user":
            continue
        context = _query_context_from_text(item.text, source="recent_user")
        candidates.append(context)
    selection = select_history_query_context(
        current_text=current_text,
        current_keywords=current_keywords,
        candidates=candidates,
    )
    if selection is not None:
        logger.info(
            "agent.context.select source=%s score=%.3f quality=%.3f followup=%s low_signal=%s current_keywords=%s selected_keywords=%s",
            selection.selected_context.get("source"),
            selection.score,
            selection.quality_score,
            selection.followup.is_followup,
            selection.followup.low_signal,
            selection.current_keywords,
            selection.selected_context.get("keywords", []),
        )
        return selection.selected_context
    return {}


def _query_context_from_text(text: str, *, source: str) -> dict[str, object]:
    context: dict[str, object] = {"source": source}
    keywords = _context_keywords(text)
    semantic_anchors = extract_semantic_anchors(text, keywords)
    semantic_domains = anchor_domains(semantic_anchors)
    if keywords and has_distinctive_keywords(keywords):
        context["keywords"] = keywords
    if semantic_anchors:
        context["semantic_anchors"] = semantic_anchors
    if semantic_domains:
        context["semantic_domains"] = semantic_domains
    game = _find_known_value(text, _KNOWN_GAMES)
    if game:
        context["game"] = game
    source_constraints = infer_source_constraints(text)
    source_name = (source_constraints.get("sources") or [None])[0]
    if source_name:
        context["source_name"] = source_name
    category = _find_category(text)
    if category:
        context["category"] = category
    adult_content = detect_adult_constraint(text)
    if adult_content is not None:
        context["adult_content"] = adult_content
    if is_recent_query(text) or _contains_any(text, ["最近", "最新", "更新", "recent", "latest"]):
        context["sort_field"] = "updated_at_remote"
        context["sort_order"] = "desc"
    context["quality_score"] = context_quality_score(context)
    return context


def _context_keywords(text: str) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for keyword in [
        *base_keywords(text),
        *re.findall(r"[a-z][a-z0-9_-]{2,}", str(text or "").lower()),
    ]:
        token = str(keyword or "").strip().lower()
        if not token or token in seen:
            continue
        if re.fullmatch(r"[a-z0-9\u4e00-\u9fff_-]+", token) is None:
            continue
        if _is_noisy_context_token(token):
            continue
        if not has_distinctive_keywords([token]):
            continue
        merged.append(token)
        seen.add(token)
    return merged[:5]


def _is_noisy_context_token(token: str) -> bool:
    # Drop mojibake/placeholder-like fragments that pollute context inheritance.
    if "\ufffd" in token or "�" in token:
        return True
    if re.search(r"[^\x00-\x7f]", token) and not re.search(r"[\u4e00-\u9fff]", token):
        return True
    # Require a minimum signal for pure ASCII fragments.
    if re.fullmatch(r"[a-z0-9_-]+", token) and len(token) <= 1:
        return True
    weak_english = {
        "only",
        "ones",
        "show",
        "find",
        "add",
        "with",
        "preview",
        "images",
    }
    return token in weak_english


def _extract_shown_mod_titles(history: list[AgentHistoryItem]) -> list[str]:
    titles: list[str] = []
    for item in reversed(history):
        if item.role != "assistant":
            continue
        titles.extend(_shown_titles_from_text(item.text))
        if len(titles) >= 30:
            break
    return _unique_titles(titles)[:30]


def _shown_titles_from_text(text: str) -> list[str]:
    block = text.split("[shown_mods]", 1)[1] if "[shown_mods]" in text else text
    titles: list[str] = []
    for line in block.splitlines():
        title_match = re.search(r"\btitle=([^;\n]+)", line)
        if title_match:
            titles.append(title_match.group(1).strip())
            continue
        fallback_match = re.match(r"^\s*[-*]\s+(.+?)\s+\((?:nexusmods|loverslab)\)\s*$", line, re.IGNORECASE)
        if fallback_match:
            titles.append(fallback_match.group(1).strip())
    return titles


def _unique_titles(values: list[str]) -> list[str]:
    seen: set[str] = set()
    titles: list[str] = []
    for value in values:
        title = re.sub(r"\s+", " ", str(value or "").strip())
        key = title.lower()
        if title and key not in seen:
            titles.append(title)
            seen.add(key)
    return titles
