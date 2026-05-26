import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from sqlmodel import Session

from app.services.agent import query_planner as query_planner_module
from app.services.agent.planning.context_plan_merge import (
    merge_context_query_plan,
    merge_llm_context_query_plan,
)
from app.services.agent.planning.fallback_query_plan import build_fallback_query_plan
from app.services.agent.query_planner import (
    build_database_schema_text,
    load_slot_options,
    normalize_query_plan,
)
from app.services.agent.schemas import AgentHistoryItem

logger = logging.getLogger(__name__)

QueryPlanner = Callable[..., Awaitable[dict[str, Any] | None]]


@dataclass(frozen=True)
class QueryPlanningInput:
    query: str
    history: list[AgentHistoryItem] = field(default_factory=list)
    context_query_plan: dict[str, Any] | None = None
    evidence_id: str = ""
    llm_available: bool = False
    provider: str = ""
    api_key: str = ""
    base_url: str = ""
    model: str = ""


@dataclass(frozen=True)
class QueryPlanningOutput:
    query_plan: dict[str, Any]
    raw_query_plan: dict[str, Any]
    evidence_id: str | None
    source: str


class QueryPlanningTool:
    """Agent tool for task understanding and normalized query planning."""

    name = "query_planning"

    def __init__(self, session: Session, *, planner: QueryPlanner | None = None):
        self.session = session
        self.planner = planner or query_planner_module.plan_query_with_llm

    async def run(self, tool_input: QueryPlanningInput) -> QueryPlanningOutput:
        slot_options = load_slot_options(self.session)
        source = "fallback"
        raw_query_plan = None
        llm_error_type = ""
        if tool_input.llm_available:
            try:
                raw_query_plan = await self.planner(
                    query=tool_input.query,
                    provider=tool_input.provider,
                    api_key=tool_input.api_key,
                    base_url=tool_input.base_url,
                    model=tool_input.model,
                    history=tool_input.history,
                    database_schema=build_database_schema_text(self.session),
                    slot_options=slot_options,
                )
            except Exception as exc:
                llm_error_type = type(exc).__name__
                logger.info(
                    "agent.tool name=query_planning status=degraded source=llm reason=planner_error error_type=%s evidence_id=%s",
                    llm_error_type,
                    tool_input.evidence_id,
                )
            if raw_query_plan is not None:
                source = "llm"
        if raw_query_plan is None:
            raw_query_plan = build_fallback_query_plan(tool_input.query)

        if source == "llm":
            raw_query_plan = merge_llm_context_query_plan(raw_query_plan, tool_input.context_query_plan)
        else:
            raw_query_plan = merge_context_query_plan(raw_query_plan, tool_input.context_query_plan)
        raw_evidence_id = str((raw_query_plan or {}).get("evidence_id") or "").strip()
        evidence_id = str(tool_input.evidence_id or raw_evidence_id).strip() or None
        query_plan = normalize_query_plan(
            raw_query_plan,
            tool_input.query,
            slot_options,
            planning_source=source,
        )
        context_used = bool(tool_input.context_query_plan)
        if evidence_id:
            query_plan["evidence_id"] = evidence_id
        if raw_evidence_id and raw_evidence_id != evidence_id:
            query_plan["_agent_raw_planning_evidence_id"] = raw_evidence_id
        semantic_anchors = _string_list(raw_query_plan.get("semantic_anchors"))
        semantic_domains = _string_list(raw_query_plan.get("semantic_domains"))
        if semantic_anchors:
            query_plan["_agent_semantic_anchors"] = semantic_anchors
            query_plan["_agent_semantic_source"] = source
        if semantic_domains:
            query_plan["_agent_semantic_domains"] = semantic_domains
        query_plan["_agent_planning_source"] = source
        query_plan["_agent_llm_planning_used"] = source == "llm"
        query_plan["_agent_fallback_planning_used"] = source == "fallback"
        query_plan["_agent_context_plan_used"] = context_used
        if llm_error_type:
            query_plan["_agent_llm_planning_error_type"] = llm_error_type
        _log_query_plan(query_plan, evidence_id=evidence_id, context_used=bool(tool_input.context_query_plan))
        logger.info(
            "agent.tool name=query_planning status=succeeded source=%s intent=%s keywords=%s evidence_id=%s context_used=%s llm_error_type=%s",
            source,
            query_plan.get("intent"),
            query_plan.get("keywords", []),
            evidence_id,
            bool(tool_input.context_query_plan),
            llm_error_type,
        )
        return QueryPlanningOutput(
            query_plan=query_plan,
            raw_query_plan=raw_query_plan,
            evidence_id=evidence_id,
            source=source,
        )


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()][:12]


def _log_query_plan(query_plan: dict[str, Any], *, evidence_id: str | None, context_used: bool) -> None:
    logger.info(
        "agent.chat.plan evidence_id=%s planning_source=%s llm_planning_used=%s fallback_planning_used=%s intent=%s keywords=%s excluded_keywords=%s exclude_titles=%s excluded_sources=%s keyword_match_mode=%s exact_title=%s version=%s external_id=%s source_url=%s games=%s sources=%s categories=%s tags=%s summary_languages=%s excluded_summary_languages=%s requirement_terms=%s compatibility_terms=%s has_thumbnail=%s author=%s adult_content=%s min_downloads=%s min_endorsements=%s min_views=%s min_likes=%s updated_since_days=%s updated_after=%s updated_before=%s published_after=%s published_before=%s created_after=%s created_before=%s sort=%s/%s context_used=%s",
        evidence_id,
        query_plan.get("_agent_planning_source"),
        query_plan.get("_agent_llm_planning_used"),
        query_plan.get("_agent_fallback_planning_used"),
        query_plan.get("intent"),
        query_plan.get("keywords", []),
        query_plan.get("excluded_keywords", []),
        query_plan.get("exclude_titles", []),
        query_plan.get("excluded_sources", []),
        query_plan.get("keyword_match_mode"),
        query_plan.get("exact_title"),
        query_plan.get("version"),
        query_plan.get("external_id"),
        query_plan.get("source_url"),
        query_plan.get("games", []),
        query_plan.get("sources", []),
        query_plan.get("categories", []),
        query_plan.get("tags", []),
        query_plan.get("summary_languages", []),
        query_plan.get("excluded_summary_languages", []),
        query_plan.get("requirement_terms", []),
        query_plan.get("compatibility_terms", []),
        query_plan.get("has_thumbnail"),
        query_plan.get("author"),
        query_plan.get("adult_content"),
        query_plan.get("min_downloads"),
        query_plan.get("min_endorsements"),
        query_plan.get("min_views"),
        query_plan.get("min_likes"),
        query_plan.get("updated_since_days"),
        query_plan.get("updated_after"),
        query_plan.get("updated_before"),
        query_plan.get("published_after"),
        query_plan.get("published_before"),
        query_plan.get("created_after"),
        query_plan.get("created_before"),
        query_plan.get("sort_field"),
        query_plan.get("sort_order"),
        context_used,
    )
    logger.info(
        "agent.chat.plan intent=%s evidence_id=%s",
        query_plan.get("intent"),
        evidence_id,
    )
