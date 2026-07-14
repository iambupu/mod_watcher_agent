import logging
from dataclasses import dataclass, field, replace
from typing import Any

from sqlmodel import Session

from app.services.agent.planning.open_discovery_policy import is_open_discovery_plan
from app.services.agent.planning.query_plan_hygiene import sanitize_query_plan_fields
from app.services.agent.planning.retrieval_policy import current_only_reserved
from app.services.agent.planning.tool_plan_policy import (
    allowed_online_tools as _allowed_online_tools,
)
from app.services.agent.planning.tool_plan_policy import (
    online_recall_mode as _online_recall_mode,
)
from app.services.agent.planning.tool_plan_policy import (
    planned_tools as _planned_tools,
)
from app.services.agent.retrieval_evidence import (
    active_query_plan_fields,
    append_retrieval_evidence,
)
from app.services.agent.search_types import SearchPlan, SearchResult
from app.services.agent.semantic_search import distinctive_query_terms, strip_scope
from app.services.agent.tools.local_db_search_tool import (
    LocalDbSearchTool,
    local_db_input_from_plan,
)
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
    """执行 graph 选出的检索工具，并把跳过、降级和命中情况写入 evidence。"""

    name = "tool_executor"

    def __init__(self, session: Session):
        self.session = session

    async def run(self, tool_input: ToolExecutorInput) -> ToolExecutorOutput:
        query_plan = sanitize_query_plan_fields(dict(tool_input.query_plan or {}), query=tool_input.query)
        evidence_id = tool_input.evidence_id or str(query_plan.get("evidence_id") or "").strip()
        plan = SearchPlan.from_query_plan(query_plan)
        plan_query = {**plan.to_query_plan(), "evidence_id": evidence_id}
        effective_query = _effective_search_query(tool_input.query, plan)
        evidence: list[dict[str, object]] = []
        allowed_tools = _planned_tools(tool_input.tool_plan)

        staged_results: list[SearchResult] = []
        if allowed_tools & {"structured_sql", "sqlite_fts", "local_db_search"}:
            # 本地检索承担硬过滤和本地缓存召回，是普通用户离线优先路径。
            if _dual_retrieval_enabled(query_plan):
                current_plan_query = _branch_plan_query(query_plan.get("_agent_current_only_plan"), evidence_id)
                current_results: list[SearchResult] = []
                if _plan_has_current_signal(current_plan_query):
                    current_plan = SearchPlan.from_query_plan(current_plan_query)
                    current_query = _effective_search_query(tool_input.query, current_plan)
                    current_results = await LocalDbSearchTool(self.session).run(
                        local_db_input_from_plan(current_query, current_plan_query)
                    )
                    current_results = _tag_retrieval_branch(current_results, "current_only")
                    _log_local_search(
                        count=len(current_results),
                        evidence_id=evidence_id,
                        query_plan=current_plan_query,
                        plan=current_plan,
                        retrieval_branch="current_only",
                    )
                    _append_branch_evidence(
                        evidence,
                        branch="current_only",
                        status="succeeded",
                        count=len(current_results),
                        query_plan=current_plan_query,
                        evidence_id=evidence_id,
                    )
                else:
                    _append_branch_evidence(
                        evidence,
                        branch="current_only",
                        status="skipped",
                        count=0,
                        query_plan=current_plan_query,
                        evidence_id=evidence_id,
                        reason="no_current_only_signal",
                    )

                context_results = await LocalDbSearchTool(self.session).run(
                    local_db_input_from_plan(effective_query, plan_query)
                )
                context_results = _tag_retrieval_branch(context_results, "context_scoped")
                staged_results.extend(current_results)
                staged_results.extend(context_results)
                _log_local_search(
                    count=len(context_results),
                    evidence_id=evidence_id,
                    query_plan=query_plan,
                    plan=plan,
                    retrieval_branch="context_scoped",
                )
                _append_branch_evidence(
                    evidence,
                    branch="context_scoped",
                    status="succeeded",
                    count=len(context_results),
                    query_plan=query_plan,
                    evidence_id=evidence_id,
                )
                evidence.append(
                    {
                        "fragment_id": f"r_exec_{len(evidence) + 1}",
                        "stage": "local_retrieval",
                        "tool": "local_db",
                        "status": "succeeded",
                        "retrieval_branch": "dual_summary",
                        "current_only_count": len(current_results),
                        "context_scoped_count": len(context_results),
                        "current_only_reserved": current_only_reserved(plan.limit, len(current_results)),
                        "evidence_id": evidence_id,
                    }
                )
            else:
                local_results = await LocalDbSearchTool(self.session).run(
                    local_db_input_from_plan(effective_query, plan_query)
                )
                staged_results.extend(local_results)
                _log_local_search(
                    count=len(local_results),
                    evidence_id=evidence_id,
                    query_plan=query_plan,
                    plan=plan,
                    retrieval_branch="",
                )
                append_retrieval_evidence(
                    evidence,
                    stage="local_retrieval",
                    tool="local_db",
                    status="succeeded",
                    count=len(local_results),
                    fields=active_query_plan_fields(query_plan),
                    query_plan=query_plan,
                    evidence_id=evidence_id,
                )
        else:
            append_retrieval_evidence(
                evidence,
                stage="local_retrieval",
                tool="local_db",
                status="skipped",
                count=0,
                reason="not_planned",
                fields=["tool_plan"],
                evidence_id=evidence_id,
            )

        online_results: list[SearchResult] = []
        online_allowed = bool(allowed_tools & {"nexusmods_search", "loverslab_google", "loverslab_scrape", "web_search"})
        online_decision = _online_retrieval_decision(
            query_plan=query_plan,
            query=effective_query,
            local_results=staged_results,
            online_allowed=online_allowed,
        )
        if online_decision.should_query:
            # 在线检索只在工具计划允许且本地质量/来源范围需要时触发。
            web_output = await WebSearchTool(self.session).run(
                query=effective_query,
                query_plan=plan_query,
                evidence_id=evidence_id,
                online_recall_mode=_online_recall_mode(tool_input.tool_plan),
                allowed_tools=_allowed_online_tools(allowed_tools),
            )
            online_results = web_output.results
            evidence.extend(web_output.evidence)
        else:
            reason = online_decision.reason
            logger.info(
                "agent.tool name=web_search status=skipped reason=%s results=0 decision_reasons=%s evidence_id=%s",
                reason,
                online_decision.reasons,
                evidence_id,
            )
            append_retrieval_evidence(
                evidence,
                stage="online_retrieval",
                tool="online_gate",
                status="skipped",
                count=0,
                reason=reason,
                fields=["keywords", "sources", "games", "categories", "category_hints"],
                query_plan=query_plan,
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


def _dual_retrieval_enabled(query_plan: dict[str, Any]) -> bool:
    config = query_plan.get("_agent_dual_retrieval")
    return isinstance(config, dict) and config.get("enabled") is True and isinstance(
        query_plan.get("_agent_current_only_plan"),
        dict,
    )


def _branch_plan_query(raw_plan: object, evidence_id: str) -> dict[str, Any]:
    plan = sanitize_query_plan_fields(dict(raw_plan or {})) if isinstance(raw_plan, dict) else {}
    if evidence_id:
        plan["evidence_id"] = evidence_id
    return plan


def _plan_has_current_signal(plan_query: dict[str, Any]) -> bool:
    signal_fields = [
        "keywords",
        "games",
        "game_domains",
        "sources",
        "categories",
        "category_hints",
        "tags",
        "requirement_terms",
        "compatibility_terms",
        "summary_languages",
        "excluded_summary_languages",
        "exact_title",
        "version",
        "external_id",
        "source_url",
        "author",
    ]
    if any(plan_query.get(field) not in (None, "", []) for field in signal_fields):
        return True
    return any(
        plan_query.get(field) is not None
        for field in [
            "adult_content",
            "has_thumbnail",
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
        ]
    )


def _tag_retrieval_branch(results: list[SearchResult], branch: str) -> list[SearchResult]:
    return [replace(item, retrieval_branch=branch) for item in results]


def _append_branch_evidence(
    evidence: list[dict[str, object]],
    *,
    branch: str,
    status: str,
    count: int,
    query_plan: dict[str, Any],
    evidence_id: str,
    reason: str | None = None,
) -> None:
    append_retrieval_evidence(
        evidence,
        stage="local_retrieval",
        tool="local_db",
        status=status,
        count=count,
        reason=reason,
        fields=active_query_plan_fields(query_plan),
        query_plan=query_plan,
        evidence_id=evidence_id,
    )
    evidence[-1]["retrieval_branch"] = branch


def _log_local_search(
    *,
    count: int,
    evidence_id: str,
    query_plan: dict[str, Any],
    plan: SearchPlan,
    retrieval_branch: str,
) -> None:
    logger.info(
        "agent.search.local count=%s evidence_id=%s retrieval_branch=%s open_discovery=%s retrieval_mode=%s keywords=%s excluded_keywords=%s excluded_sources=%s keyword_match_mode=%s exclude_titles=%s exact_title=%s version=%s external_id=%s source_url=%s games=%s game_domains=%s sources=%s categories=%s tags=%s summary_languages=%s excluded_summary_languages=%s requirement_terms=%s compatibility_terms=%s has_thumbnail=%s author=%s adult_content=%s min_downloads=%s min_endorsements=%s min_views=%s min_likes=%s updated_since_days=%s updated_after=%s updated_before=%s published_after=%s published_before=%s created_after=%s created_before=%s sort=%s/%s",
        count,
        evidence_id,
        retrieval_branch,
        query_plan.get("open_discovery"),
        query_plan.get("retrieval_mode"),
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


@dataclass(frozen=True)
class OnlineRetrievalDecision:
    should_query: bool
    reason: str
    reasons: list[str] = field(default_factory=list)


def _online_retrieval_decision(
    *,
    query_plan: dict[str, Any],
    query: str,
    local_results: list[SearchResult],
    online_allowed: bool,
) -> OnlineRetrievalDecision:
    if not online_allowed:
        return OnlineRetrievalDecision(False, "not_planned", ["online_tools_not_planned"])
    reasons: list[str] = []
    # 在线检索决策要解释“为什么查”或“为什么不查”，避免用户看到来源漂移。
    sources = {str(value).strip().lower() for value in (query_plan.get("sources") or []) if str(value).strip()}
    if sources & {"nexusmods", "loverslab"}:
        reasons.append("explicit_source_scope")
    if distinctive_query_terms(query):
        reasons.append("distinctive_query_terms")
    if is_open_discovery_plan(query_plan):
        reasons.append("open_discovery_query")
    if _is_ecosystem_query(query, query_plan):
        reasons.append("ecosystem_or_risk_query")
    quality_reasons = _local_quality_reasons(local_results)
    reasons.extend(quality_reasons)
    if reasons:
        return OnlineRetrievalDecision(True, "quality_or_scope_requires_online", list(dict.fromkeys(reasons)))
    return OnlineRetrievalDecision(False, "local_matches_sufficient", ["local_quality_sufficient"])


def _is_ecosystem_query(query: str, query_plan: dict[str, Any]) -> bool:
    text = str(query or "").lower()
    domains = {str(value).strip().lower() for value in (query_plan.get("_agent_semantic_domains") or []) if str(value).strip()}
    anchors = {str(value).strip().lower() for value in (query_plan.get("_agent_semantic_anchors") or []) if str(value).strip()}
    return (
        "mechanics" in domains
        or "source_scope" in domains
        or bool(anchors & {"framework", "roleplay", "pregnancy"})
        or any(marker in text for marker in ["前置", "依赖", "兼容", "风险", "替代", "生态", "framework", "requirements", "compat"])
    )


def _local_quality_reasons(local_results: list[SearchResult]) -> list[str]:
    if not local_results:
        return ["no_local_results"]
    reasons: list[str] = []
    if len(local_results) < 3:
        reasons.append("local_results_too_few")
    sources = {str(item.mod.source or "").strip().lower() for item in local_results if str(item.mod.source or "").strip()}
    if len(sources) <= 1:
        reasons.append("local_source_diversity_low")
    summaries = [item for item in local_results[:5] if item.mod.original_summary]
    if len(summaries) < min(2, len(local_results[:5])):
        reasons.append("local_summary_coverage_low")
    return reasons


def _effective_search_query(query: str, plan: SearchPlan) -> str:
    visible_query = strip_scope(query)
    parts = [visible_query]
    if not distinctive_query_terms(visible_query):
        # 用户输入缺少可区分词时，补入计划中的关键词和分类，提升本地/在线召回率。
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
