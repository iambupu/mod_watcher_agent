from typing import Any

from sqlmodel import Session

from app.services.agent.list_utils import string_list as _string_list
from app.services.agent.planning.executor_query_plan import build_executor_query_plan
from app.services.agent.query_planner import load_slot_options, normalize_query_plan


def normalize_context_query_plan(
    *,
    raw: dict[str, Any],
    query: str,
    constraints: dict[str, Any] | None,
    session: Session | None,
) -> dict[str, Any]:
    if session is None:
        return raw
    try:
        slot_options = load_slot_options(session)
        context_game = str((constraints or {}).get("game") or "").strip().lower()
        if context_game:
            query_only = normalize_query_plan(build_executor_query_plan(query), query, slot_options)
            query_only_games = _string_list(query_only.get("games"))
            if query_only_games and all(game.lower() != context_game for game in query_only_games):
                raw["games"] = query_only_games
        context_signal = raw.get("_agent_context_signal")
        normalized = normalize_query_plan(raw, query, slot_options)
        if isinstance(context_signal, dict):
            normalized["_agent_context_signal"] = context_signal
        return normalized
    except Exception:
        return raw
