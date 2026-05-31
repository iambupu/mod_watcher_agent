import logging
from dataclasses import dataclass, field
from typing import Any

from app.services.agent.result_merger import (
    filter_by_adult_content,
    filter_by_distinctive_terms,
    filter_by_exact_title,
    filter_excluded_keywords,
    filter_excluded_titles,
    filter_semantic_soft_rejects,
    merge_results,
    sort_results,
)
from app.services.agent.search_types import SearchPlan, SearchResult
from app.services.agent.semantic_search import strip_scope

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ResultFusionRankerInput:
    query: str
    query_plan: dict[str, Any]
    plan: SearchPlan
    staged_results: list[SearchResult] = field(default_factory=list)
    online_results: list[SearchResult] = field(default_factory=list)
    evidence_id: str = ""
    emit_evidence: bool = True
    apply_distinctive_filter: bool = True


@dataclass(frozen=True)
class ResultFusionRankerOutput:
    results: list[SearchResult]
    evidence: list[dict[str, object]]


class ResultFusionRankerTool:
    """融合多路检索候选，执行过滤、去重和排序。"""

    name = "result_fusion_ranker"

    def run(self, tool_input: ResultFusionRankerInput) -> ResultFusionRankerOutput:
        results = merge_results(tool_input.staged_results, tool_input.online_results)
        results = sort_results(results, tool_input.plan, tool_input.query_plan)
        if tool_input.apply_distinctive_filter:
            results = filter_by_distinctive_terms(
                results,
                _filter_query(tool_input.query, tool_input.plan, tool_input.query_plan),
                query_plan=tool_input.query_plan,
                plan=tool_input.plan,
                fallback_terms=_fallback_filter_terms(tool_input.query_plan, tool_input.plan),
            )
        results = filter_by_adult_content(results, tool_input.plan)
        results = filter_semantic_soft_rejects(results, tool_input.query_plan)
        results = filter_by_exact_title(results, tool_input.plan.exact_title)
        results = filter_excluded_titles(results, _excluded_titles(tool_input.query_plan))
        results = filter_excluded_keywords(results, tool_input.plan.excluded_keywords)
        logger.info("agent.search.final count=%s limit=%s evidence_id=%s", len(results), tool_input.plan.limit, tool_input.evidence_id)
        logger.info(
            "agent.tool name=result_fusion_ranker status=succeeded count=%s staged=%s online=%s sort=%s/%s evidence_id=%s",
            len(results),
            len(tool_input.staged_results),
            len(tool_input.online_results),
            tool_input.plan.sort_field,
            tool_input.plan.sort_order,
            tool_input.evidence_id,
        )
        evidence: list[dict[str, object]] = []
        if tool_input.emit_evidence:
            evidence.append(
                {
                    "fragment_id": "r_fusion_1",
                    "stage": "final_ranking",
                    "tool": self.name,
                    "status": "succeeded",
                    "count": len(results),
                    "evidence_id": tool_input.evidence_id,
                    "fields": ["sort_field", "sort_order", "limit"],
                }
            )
        return ResultFusionRankerOutput(results=results, evidence=evidence)


def _filter_query(query: str, plan: SearchPlan, query_plan: dict[str, Any] | None = None) -> str:
    if plan.exact_title:
        return plan.exact_title
    if plan.external_id or plan.source_url:
        return ""
    visible_query = strip_scope(query)
    if query_plan and query_plan.get("keyword_match_mode") == "all" and plan.keywords:
        return " ".join(plan.keywords)
    if (plan.summary_languages or isinstance(plan.has_thumbnail, bool)) and plan.keywords:
        return " ".join(plan.keywords)
    if _has_metric_constraints(plan) and plan.keywords:
        return " ".join(plan.keywords)
    if isinstance(plan.adult_content, bool) and plan.keywords:
        return " ".join(plan.keywords)
    if (
        query_plan
        and query_plan.get("intent") != "comparison"
        and (plan.sources or query_plan.get("excluded_sources"))
        and plan.keywords
    ):
        return " ".join(plan.keywords)
    if plan.excluded_keywords and plan.categories:
        return " ".join(plan.categories)
    if plan.excluded_keywords and plan.keywords:
        return " ".join(plan.keywords)
    return visible_query


def _has_metric_constraints(plan: SearchPlan) -> bool:
    return any(
        value is not None
        for value in [
            plan.min_downloads,
            plan.min_endorsements,
            plan.min_views,
            plan.min_likes,
        ]
    )


def _excluded_titles(query_plan: dict[str, Any]) -> list[str]:
    raw = query_plan.get("exclude_titles")
    if not isinstance(raw, list):
        return []
    return [str(value).strip() for value in raw if str(value).strip()]


def _fallback_filter_terms(query_plan: dict[str, Any], plan: SearchPlan) -> list[str]:
    if plan.external_id or plan.source_url:
        return []
    if query_plan.get("intent") == "comparison":
        return []
    return plan.keywords
