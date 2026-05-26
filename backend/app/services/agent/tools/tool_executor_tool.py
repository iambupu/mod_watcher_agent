import logging
from dataclasses import dataclass, field
from typing import Any

from sqlmodel import Session

from app.services.agent.search_types import SearchPlan, SearchResult
from app.services.agent.semantic_search import distinctive_query_terms
from app.services.agent.tools.local_db_search_tool import (
    LocalDbSearchTool,
    local_db_input_from_plan,
)
from app.services.agent.tools.vector_search_tool import VectorSearchInput, VectorSearchTool
from app.services.agent.tools.web_search_tool import WebSearchTool

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ToolExecutorInput:
    query: str
    query_plan: dict[str, Any]
    tool_plan: dict[str, Any]
    evidence_id: str = ""


@dataclass(frozen=True)
class ToolExecutorOutput:
    staged_results: list[SearchResult] = field(default_factory=list)
    online_results: list[SearchResult] = field(default_factory=list)
    evidence: list[dict[str, object]] = field(default_factory=list)
    effective_query: str = ""


class ToolExecutorTool:
    """Agent tool for executing retrieval tools selected by the graph planner."""

    name = "tool_executor"

    def __init__(self, session: Session):
        self.session = session

    async def run(self, tool_input: ToolExecutorInput) -> ToolExecutorOutput:
        query_plan = dict(tool_input.query_plan or {})
        evidence_id = tool_input.evidence_id or str(query_plan.get("evidence_id") or "").strip()
        plan = SearchPlan.from_query_plan(query_plan)
        plan_query = {**plan.to_query_plan(), "evidence_id": evidence_id}
        effective_query = _effective_search_query(tool_input.query, plan)
        evidence: list[dict[str, object]] = []
        allowed_tools = _planned_tools(tool_input.tool_plan)

        staged_results: list[SearchResult] = []
        if allowed_tools & {"structured_sql", "sqlite_fts", "local_db_search"}:
            local_results = await LocalDbSearchTool(self.session).run(local_db_input_from_plan(effective_query, plan_query))
            staged_results.extend(local_results)
            logger.info(
                "agent.search.local count=%s evidence_id=%s keywords=%s excluded_keywords=%s excluded_sources=%s keyword_match_mode=%s exclude_titles=%s exact_title=%s version=%s external_id=%s source_url=%s games=%s game_domains=%s sources=%s categories=%s tags=%s summary_languages=%s excluded_summary_languages=%s requirement_terms=%s compatibility_terms=%s has_thumbnail=%s author=%s adult_content=%s min_downloads=%s min_endorsements=%s min_views=%s min_likes=%s updated_since_days=%s updated_after=%s updated_before=%s published_after=%s published_before=%s created_after=%s created_before=%s sort=%s/%s",
                len(local_results),
                evidence_id,
                plan.keywords,
                plan.excluded_keywords,
                query_plan.get("excluded_sources", []),
                query_plan.get("keyword_match_mode"),
                query_plan.get("exclude_titles", []),
                plan.exact_title,
                plan.version,
                plan.external_id,
                plan.source_url,
                plan.games,
                plan.game_domains,
                plan.sources,
                plan.categories,
                plan.tags,
                plan.summary_languages,
                plan.excluded_summary_languages,
                plan.requirement_terms,
                plan.compatibility_terms,
                plan.has_thumbnail,
                plan.author,
                plan.adult_content,
                plan.min_downloads,
                plan.min_endorsements,
                plan.min_views,
                plan.min_likes,
                plan.updated_since_days,
                plan.updated_after,
                plan.updated_before,
                plan.published_after,
                plan.published_before,
                plan.created_after,
                plan.created_before,
                plan.sort_field,
                plan.sort_order,
            )
            _append_evidence(
                evidence,
                stage="local_retrieval",
                tool="local_db",
                status="succeeded",
                count=len(local_results),
                fields=_query_plan_fields(query_plan),
                evidence_id=evidence_id,
            )
        else:
            _append_evidence(
                evidence,
                stage="local_retrieval",
                tool="local_db",
                status="skipped",
                count=0,
                reason="not_planned",
                fields=["tool_plan"],
                evidence_id=evidence_id,
            )

        vector_output = VectorSearchTool(enabled=False).run(
            VectorSearchInput(
                query=effective_query,
                filters=plan.to_query_plan(),
                limit=plan.limit,
                evidence_id=evidence_id,
            )
        )
        staged_results.extend(vector_output.results)
        evidence.extend(vector_output.evidence)

        online_results: list[SearchResult] = []
        online_allowed = bool(allowed_tools & {"nexusmods_search", "loverslab_google", "loverslab_scrape", "web_search"})
        should_query_online = online_allowed and (
            not any(item.score > 1 for item in staged_results) or _should_query_online(query_plan, effective_query)
        )
        if should_query_online:
            web_output = await WebSearchTool(self.session).run(
                query=effective_query,
                query_plan=plan_query,
                evidence_id=evidence_id,
                conservative_mode=bool(query_plan.get("_agent_conservative_mode")),
                allowed_tools=_allowed_online_tools(allowed_tools),
            )
            online_results = web_output.results
            evidence.extend(web_output.evidence)
        else:
            reason = "not_planned" if not online_allowed else "local_matches_sufficient"
            logger.info(
                "agent.tool name=web_search status=skipped reason=%s results=0 evidence_id=%s",
                reason,
                evidence_id,
            )
            _append_evidence(
                evidence,
                stage="online_retrieval",
                tool="online_gate",
                status="skipped",
                count=0,
                reason=reason,
                fields=["keywords", "sources", "games", "categories"],
                evidence_id=evidence_id,
            )

        logger.info(
            "agent.tool name=tool_executor status=succeeded staged=%s online=%s evidence=%s evidence_id=%s",
            len(staged_results),
            len(online_results),
            len(evidence),
            evidence_id,
        )
        return ToolExecutorOutput(
            staged_results=staged_results,
            online_results=online_results,
            evidence=evidence,
            effective_query=effective_query,
        )


def _planned_tools(tool_plan: dict[str, Any]) -> set[str]:
    tools: set[str] = set()
    for group in tool_plan.get("parallel_groups") or []:
        if not isinstance(group, dict):
            continue
        tools.update(str(tool).strip() for tool in (group.get("tools") or []) if str(tool).strip())
    for step in tool_plan.get("fallback_steps") or []:
        if isinstance(step, dict) and str(step.get("tool") or "").strip():
            tools.add(str(step.get("tool")).strip())
    return tools


def _allowed_online_tools(planned_tools: set[str]) -> set[str]:
    allowed = planned_tools & {"nexusmods_search", "loverslab_google", "loverslab_scrape", "web_search"}
    if "web_search" in allowed:
        return {"nexusmods_search", "loverslab_google", "loverslab_scrape"}
    if "loverslab_google" in allowed:
        allowed.add("loverslab_scrape")
    return allowed


def _append_evidence(
    evidence: list[dict[str, object]],
    *,
    stage: str,
    tool: str,
    status: str,
    count: int,
    reason: str | None = None,
    fields: list[str] | None = None,
    evidence_id: str = "",
) -> None:
    item: dict[str, object] = {
        "fragment_id": f"r_exec_{len(evidence) + 1}",
        "stage": stage,
        "tool": tool,
        "status": status,
        "count": count,
    }
    if evidence_id:
        item["evidence_id"] = evidence_id
    if reason:
        item["reason"] = reason
    if fields:
        item["fields"] = fields
    evidence.append(item)


def _query_plan_fields(query_plan: dict[str, Any]) -> list[str]:
    field_keys = [
        "keywords",
        "games",
        "game_domains",
        "sources",
        "categories",
        "tags",
        "adult_content",
        "has_thumbnail",
        "summary_languages",
        "excluded_summary_languages",
        "requirement_terms",
        "compatibility_terms",
        "author",
        "sort_field",
        "sort_order",
        "exact_title",
        "version",
        "external_id",
        "source_url",
    ]
    return [key for key in field_keys if query_plan.get(key) not in (None, "", [])]


def _should_query_online(query_plan: dict[str, Any], query: str) -> bool:
    sources = {str(value).strip().lower() for value in (query_plan.get("sources") or []) if str(value).strip()}
    return bool(sources & {"nexusmods", "loverslab"}) or bool(distinctive_query_terms(query))


def _effective_search_query(query: str, plan: SearchPlan) -> str:
    visible_query = query.split("[scope]", 1)[0].strip()
    parts = [visible_query]
    if not distinctive_query_terms(visible_query):
        parts.extend([*plan.keywords, *plan.categories])
    seen: set[str] = set()
    values: list[str] = []
    for part in parts:
        value = str(part or "").strip()
        key = value.lower()
        if value and key not in seen:
            values.append(value)
            seen.add(key)
    return " ".join(values) or visible_query
