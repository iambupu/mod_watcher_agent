# 中文注释：规范化 Agent 查询计划、槽位约束和语义信号。

from typing import Any

from sqlmodel import Session

from app.services.agent.planning.context_active_constraints import apply_active_constraints
from app.services.agent.planning.context_inheritance_application import (
    apply_followup_context,
    mark_current_context_not_inherited,
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
from app.services.agent.planning.executor_query_plan import build_executor_query_plan


def build_context_query_plan(
    query: str,
    active_constraints: dict | None,
    last_query_context: dict | None,
    shown_mod_titles: list[str] | None,
    history: list | None,
    session: Session | None,
) -> dict[str, Any]:
    raw = build_executor_query_plan(query)
    current_only_plan = _current_only_query_plan(raw)
    constraints = active_constraints or {}
    backfill = backfill_query_context_for_planning(
        query=query,
        last_query_context=last_query_context,
        history=history,
    )
    if has_query_context_signal(backfill.context, backfill.keywords):
        apply_followup_context(raw, backfill.context, query)
    elif str((backfill.context or {}).get("source") or "").strip().lower() == "current":
        mark_current_context_not_inherited(raw, backfill.context)
    effective_shown_titles = shown_mod_titles or shown_titles_from_history(history)
    apply_result_reference_context(raw, query, effective_shown_titles)
    apply_result_reference_context(current_only_plan, query, effective_shown_titles)
    apply_active_constraints(raw, constraints)
    apply_active_constraints(current_only_plan, constraints)
    raw["_agent_current_only_plan"] = _current_only_query_plan(current_only_plan)
    _apply_dual_retrieval_signal(raw)
    return normalize_context_query_plan(raw=raw, query=query, constraints=constraints, session=session)


_CURRENT_ONLY_PLAN_FIELDS = {
    "keywords",
    "excluded_keywords",
    "exclude_titles",
    "games",
    "game_domains",
    "sources",
    "excluded_sources",
    "categories",
    "category_hints",
    "tags",
    "summary_languages",
    "excluded_summary_languages",
    "requirement_terms",
    "compatibility_terms",
    "has_thumbnail",
    "author",
    "adult_content",
    "min_downloads",
    "min_endorsements",
    "min_views",
    "min_likes",
    "updated_since_days",
    "updated_after",
    "updated_before",
    "published_after",
    "published_before",
    "created_after",
    "created_before",
    "sort_field",
    "sort_order",
    "limit",
    "open_discovery",
    "retrieval_mode",
    "keyword_match_mode",
    "exact_title",
    "version",
    "external_id",
    "source_url",
    "evidence_id",
}


def _current_only_query_plan(raw: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in raw.items() if key in _CURRENT_ONLY_PLAN_FIELDS}


def _apply_dual_retrieval_signal(raw: dict[str, Any]) -> None:
    signal = raw.get("_agent_context_signal")
    if not isinstance(signal, dict):
        return
    inherit_mode = str(signal.get("inherit_mode") or "").strip()
    if inherit_mode not in {"fallback_keywords", "constraints_only"}:
        return
    raw["_agent_dual_retrieval"] = {
        "enabled": True,
        "reason": inherit_mode,
        "reserve_min": 3,
        "reserve_ratio": 0.5,
    }
