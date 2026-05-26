from typing import Any

from sqlmodel import Session

from app.services.agent.planning.context_active_constraints import apply_active_constraints
from app.services.agent.planning.context_inheritance_application import (
    apply_followup_context,
)
from app.services.agent.planning.context_memory_selection import (
    backfill_query_context_for_planning,
    has_query_context_signal,
)
from app.services.agent.planning.context_plan_normalization import normalize_context_query_plan
from app.services.agent.planning.context_result_reference import (
    apply_result_reference_context,
    shown_titles_from_history,
)
from app.services.agent.planning.fallback_query_plan import build_fallback_query_plan


def build_context_query_plan(
    query: str,
    active_constraints: dict | None,
    last_query_context: dict | None,
    shown_mod_titles: list[str] | None,
    history: list | None,
    session: Session | None,
) -> dict[str, Any]:
    raw = build_fallback_query_plan(query)
    constraints = active_constraints or {}
    backfill = backfill_query_context_for_planning(
        query=query,
        last_query_context=last_query_context,
        history=history,
    )
    if has_query_context_signal(backfill.context, backfill.keywords):
        apply_followup_context(raw, backfill.context, query)
    elif str((backfill.context or {}).get("source") or "").strip().lower() == "current":
        raw["_agent_context_signal"] = {
            "source": "current",
            "quality_score": float((backfill.context or {}).get("quality_score") or 0.0),
            "followup_score": 0.0,
            "continuity_score": 0.0,
            "inherit_score": 0.0,
            "inherit_threshold": 0.0,
            "inherited": False,
            "topic_shift": False,
            "low_signal": False,
            "inherited_fields": [],
            "skipped_reason": "current_input_not_context",
            "overridden_by_current_signal": True,
            "reasons": [],
            "policy_reasons": [],
        }
    effective_shown_titles = shown_mod_titles or shown_titles_from_history(history)
    apply_result_reference_context(raw, query, effective_shown_titles)
    apply_active_constraints(raw, constraints)
    return normalize_context_query_plan(raw=raw, query=query, constraints=constraints, session=session)
