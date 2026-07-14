import logging
from dataclasses import dataclass, field
from typing import Any

from app.services.agent.planning.retrieval_policy import current_only_reserved
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
        results = _apply_context_pollution_guard(results, tool_input.query_plan, tool_input.plan)
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
            guard = tool_input.query_plan.get("_agent_context_pollution_guard")
            evidence.append(
                {
                    "fragment_id": "r_fusion_1",
                    "stage": "final_ranking",
                    "tool": self.name,
                    "status": "succeeded",
                    "count": len(results),
                    "evidence_id": tool_input.evidence_id,
                    "fields": ["sort_field", "sort_order", "limit"],
                    **(_guard_evidence_fields(guard) if isinstance(guard, dict) else {}),
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


def _apply_context_pollution_guard(
    results: list[SearchResult],
    query_plan: dict[str, Any],
    plan: SearchPlan,
) -> list[SearchResult]:
    if not _dual_retrieval_enabled(query_plan):
        return results
    current_only = [item for item in results if item.retrieval_branch == "current_only"]
    context_scoped = [item for item in results if item.retrieval_branch == "context_scoped"]
    reserved = current_only_reserved(plan.limit, len(current_only))
    blocked_terms = _context_signal_terms(query_plan, "blocked_terms")
    guard = {
        "triggered": False,
        "reason": "not_triggered",
        "blocked_terms": blocked_terms,
        "current_only_count": len(current_only),
        "context_scoped_count": len(context_scoped),
        "current_only_reserved": reserved,
    }
    if not reserved:
        query_plan["_agent_context_pollution_guard"] = guard
        return results

    selected = current_only[:reserved]
    selected_ids = {id(item) for item in selected}
    leading_ids = {id(item) for item in results[:reserved]}
    if selected_ids.issubset(leading_ids):
        query_plan["_agent_context_pollution_guard"] = guard
        return results

    leading_context = [item for item in results[:reserved] if item.retrieval_branch == "context_scoped"]
    context_hints = _context_signal_terms(query_plan, "context_hints")
    reason = "current_only_reserved"
    if leading_context and _results_mention_terms(leading_context, context_hints):
        reason = "context_hints_displaced_current_only"
    remaining = [item for item in results if id(item) not in selected_ids]
    guard["triggered"] = True
    guard["reason"] = reason
    query_plan["_agent_context_pollution_guard"] = guard
    return [*selected, *remaining]


def _dual_retrieval_enabled(query_plan: dict[str, Any]) -> bool:
    config = query_plan.get("_agent_dual_retrieval")
    return isinstance(config, dict) and config.get("enabled") is True


def _context_signal_terms(query_plan: dict[str, Any], field: str) -> list[str]:
    signal = query_plan.get("_agent_context_signal")
    if not isinstance(signal, dict):
        return []
    values = signal.get(field)
    if not isinstance(values, list):
        return []
    terms: list[str] = []
    seen: set[str] = set()
    for value in values:
        term = str(value or "").strip().lower()
        if term and term not in seen:
            terms.append(term)
            seen.add(term)
    return terms


def _results_mention_terms(results: list[SearchResult], terms: list[str]) -> bool:
    if not results or not terms:
        return False
    return any(_result_mentions_terms(item, terms) for item in results)


def _result_mentions_terms(result: SearchResult, terms: list[str]) -> bool:
    haystack = " ".join(
        str(value or "")
        for value in [
            result.mod.title,
            result.mod.translated_title_zh,
            result.mod.category,
            result.mod.tags_json,
            result.mod.original_summary,
        ]
    ).lower()
    return any(term in haystack for term in terms)


def _guard_evidence_fields(guard: dict[str, Any]) -> dict[str, object]:
    return {
        "context_pollution_guard": {
            "triggered": bool(guard.get("triggered")),
            "reason": str(guard.get("reason") or ""),
            "blocked_terms": guard.get("blocked_terms") if isinstance(guard.get("blocked_terms"), list) else [],
            "current_only_count": int(guard.get("current_only_count") or 0),
            "context_scoped_count": int(guard.get("context_scoped_count") or 0),
            "current_only_reserved": int(guard.get("current_only_reserved") or 0),
        }
    }
