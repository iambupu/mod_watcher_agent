# 中文注释：规范化 Agent 查询计划、槽位约束和语义信号。

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
        agent_metadata = _agent_metadata(raw)
        current_only_plan = agent_metadata.get("_agent_current_only_plan")
        if isinstance(current_only_plan, dict):
            agent_metadata["_agent_current_only_plan"] = normalize_query_plan(current_only_plan, query, slot_options)
        context_game = str((constraints or {}).get("game") or "").strip().lower()
        if context_game:
            query_only = normalize_query_plan(build_executor_query_plan(query), query, slot_options)
            query_only_games = _string_list(query_only.get("games"))
            if query_only_games and all(game.lower() != context_game for game in query_only_games):
                raw["games"] = query_only_games
        normalized = normalize_query_plan(raw, query, slot_options)
        normalized.update(agent_metadata)
        return normalized
    except Exception:
        return raw


def _agent_metadata(raw: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in raw.items() if key.startswith("_agent_")}
