from __future__ import annotations

import logging
from typing import Any

from sqlmodel import Session

from app.services.agent.planning.refined_retrieval_planner import (
    RefinedRetrievalInput,
    build_refined_retrieval_plan,
)
from app.services.agent.self_correction.hard_constraint_guard import guard_self_correction_plan
from app.services.agent.self_correction.self_correction_evidence import (
    SelfCorrectionEvidence,
    build_self_correction_evidence,
)
from app.services.agent.self_correction.self_correction_schema import (
    LLMSelfCorrectionReviewResult,
    SelfCorrectionConfig,
    default_self_correction_config,
)
from app.services.agent.tools.llm_self_correction_review_tool import (
    LLMSelfCorrectionReviewInput,
    LLMSelfCorrectionReviewTool,
)
from app.services.agent.tools.query_plan_repair_tool import (
    QueryPlanRepairInput,
    QueryPlanRepairTool,
)
from app.services.agent.workflows.search_stages import (
    execute_retrieval_stage,
    rank_candidates_stage,
)

logger = logging.getLogger(__name__)

_CORRECTION_ACTIONS = {"repair_query_plan", "refine_retrieval", "rejudge_candidates"}


async def self_correction_review_stage(
    session: Session,
    *,
    query: str,
    query_plan: dict[str, Any],
    matches: list,
    staged_results: list,
    online_results: list,
    retrieval_summary: dict[str, Any],
    retrieval_evidence: list[dict[str, object]],
    tool_plan: dict[str, Any],
    llm: dict[str, Any],
    evidence_id: str,
) -> dict[str, Any]:
    """Run mandatory LLM self-review and bounded correction before answer generation."""

    current_plan = dict(query_plan or {})
    config = _self_correction_config(current_plan)
    if not config.enabled:
        trace = _initial_trace(config, final_status="not_started")
        current_plan["_agent_self_correction_trace"] = trace
        return _stage_update(
            query_plan=current_plan,
            matches=matches,
            staged_results=staged_results,
            online_results=online_results,
            retrieval_evidence=retrieval_evidence,
            trace=trace,
        )

    current_matches = list(matches or [])
    current_staged = list(staged_results or [])
    current_online = list(online_results or [])
    current_evidence = list(retrieval_evidence or [])
    current_retrieval_summary = dict(retrieval_summary or {})
    original_evidence = list(current_evidence)
    review_evidence: list[dict[str, object]] = []
    trace = _initial_trace(config, final_status="not_started")

    for round_index in range(1, config.max_rounds + 1):
        phase = "round_review" if round_index == 1 else "post_correction_review"
        evidence = build_self_correction_evidence(
            original_query=query,
            query_plan=current_plan,
            matches=current_matches,
            retrieval_evidence=current_retrieval_summary,
        )
        review = await LLMSelfCorrectionReviewTool().run(
            LLMSelfCorrectionReviewInput(
                evidence=evidence,
                round_index=round_index,
                max_rounds=config.max_rounds,
                phase=phase,
                llm_available=bool(llm.get("available")),
                provider=str(llm.get("provider") or ""),
                api_key=str(llm.get("api_key") or ""),
                base_url=str(llm.get("base_url") or ""),
                model=str(llm.get("model") or ""),
                evidence_id=evidence_id,
            )
        )
        guard = guard_self_correction_plan(evidence=evidence, review_result=review)
        effective_action = review.action if guard.passed else "fallback_no_direct_match"
        effective_plan = guard.safe_correction_plan if guard.passed else {}
        round_summary = _round_summary(
            round_index=round_index,
            phase=phase,
            evidence=evidence,
            review=review,
            action=effective_action,
            correction_plan=effective_plan,
            guard_allowed=guard.passed,
            guard_violations=guard.rejected_changes,
        )
        trace["rounds"].append(round_summary)
        trace["final_status"] = _final_status(
            review,
            effective_action,
            round_index=round_index,
            config=config,
        )
        review_evidence.append(
            _review_evidence(
                round_index=round_index,
                phase=phase,
                evidence=evidence,
                review=review,
                action=effective_action,
                guard_allowed=guard.passed,
                guard_violations=guard.rejected_changes,
                evidence_id=evidence_id,
            )
        )
        current_plan["_agent_self_correction_trace"] = trace

        if not _should_run_correction(review, effective_action, round_index=round_index, config=config):
            break

        correction = _repair_query_plan(
            query=query,
            query_plan=current_plan,
            correction_plan=effective_plan,
            evidence=evidence,
        )
        current_plan = correction["query_plan"]
        trace["rounds"][-1]["repair"] = {
            "changed_fields": correction["changed_fields"],
            "removed_pollution": correction["removed_pollution"],
            "preserved_constraints": correction["preserved_constraints"],
        }

        if effective_action in {"repair_query_plan", "refine_retrieval"}:
            refined = build_refined_retrieval_plan(
                RefinedRetrievalInput(
                    original_query=query,
                    query_plan=current_plan,
                    semantic_strategy=_semantic_strategy(current_plan),
                    correction_plan=effective_plan,
                    detected_errors=_review_gaps(review),
                    round_index=round_index + 1,
                )
            )
            current_plan = refined.query_plan
            trace["rounds"][-1]["refined_retrieval"] = {
                "queries": refined.retrieval_queries,
                "removed_pollution": refined.removed_pollution,
                "preserved_constraints": refined.preserved_constraints,
            }
            retrieval_update = await execute_retrieval_stage(
                session,
                query=query,
                query_plan=current_plan,
                tool_plan=tool_plan,
                evidence_id=evidence_id,
            )
            current_retrieval_summary = dict(retrieval_update.get("retrieval_summary") or current_retrieval_summary)
            current_staged = list(retrieval_update.get("staged_results") or [])
            current_online = list(retrieval_update.get("online_results") or [])
            current_evidence = [
                *original_evidence,
                *list(retrieval_update.get("retrieval_evidence") or []),
            ]

        rank_update = await rank_candidates_stage(
            session,
            query=query,
            query_plan=current_plan,
            staged_results=current_staged,
            online_results=current_online,
            retrieval_evidence=current_evidence,
            llm=llm,
            evidence_id=evidence_id,
        )
        current_plan = dict(rank_update.get("query_plan") or current_plan)
        current_matches = list(rank_update.get("matches") or [])
        current_evidence = list(rank_update.get("retrieval_evidence") or current_evidence)
        trace["rounds"][-1]["post_correction_match_count"] = len(current_matches)
        current_plan["_agent_self_correction_trace"] = trace

    current_plan["_agent_self_correction_trace"] = trace
    logger.info(
        "agent.stage name=self_correction_review status=%s rounds=%s matches=%s evidence_id=%s",
        trace.get("final_status"),
        len(trace.get("rounds") or []),
        len(current_matches),
        evidence_id,
    )
    return _stage_update(
        query_plan=current_plan,
        matches=current_matches,
        staged_results=current_staged,
        online_results=current_online,
        retrieval_evidence=[*current_evidence, *review_evidence],
        trace=trace,
    )


def _self_correction_config(query_plan: dict[str, Any]) -> SelfCorrectionConfig:
    raw = query_plan.get("_agent_self_correction_config")
    if isinstance(raw, dict):
        try:
            return SelfCorrectionConfig.model_validate(raw)
        except ValueError:
            return SelfCorrectionConfig.model_validate(default_self_correction_config())
    return SelfCorrectionConfig.model_validate(default_self_correction_config())


def _semantic_strategy(query_plan: dict[str, Any]) -> dict[str, Any]:
    value = query_plan.get("_agent_semantic_strategy")
    return value if isinstance(value, dict) else {}


def _initial_trace(config: SelfCorrectionConfig, *, final_status: str) -> dict[str, Any]:
    return {
        "enabled": config.enabled,
        "llm_review_required": config.llm_review_required,
        "max_rounds": config.max_rounds,
        "min_direct_matches": config.min_direct_matches,
        "allow_hard_constraint_relaxation": config.allow_hard_constraint_relaxation,
        "allow_rule_only_review": config.allow_rule_only_review,
        "rounds": [],
        "final_status": final_status,
    }


def _round_summary(
    *,
    round_index: int,
    phase: str,
    evidence: SelfCorrectionEvidence,
    review: LLMSelfCorrectionReviewResult,
    action: str,
    correction_plan: dict[str, Any],
    guard_allowed: bool,
    guard_violations: list[str],
) -> dict[str, Any]:
    fit_counts = dict(getattr(evidence, "fit_counts", {}) or {})
    return {
        "round_index": round_index,
        "phase": phase,
        "review_status": _review_status(review),
        "used_llm": review.used_llm,
        "action": action,
        "direct_match_count": fit_counts.get("direct_match", 0),
        "support_context_count": fit_counts.get("support_context", 0),
        "off_scope_count": fit_counts.get("off_scope", 0),
        "uncertain_count": fit_counts.get("uncertain", 0),
        "reason_summary": review.reason_summary,
        "gaps": [*_review_gaps(review)[:8], *guard_violations[:8]],
        "guard_allowed": guard_allowed,
        "correction_plan_keys": sorted(correction_plan.keys()),
    }


def _review_evidence(
    *,
    round_index: int,
    phase: str,
    evidence: SelfCorrectionEvidence,
    review: LLMSelfCorrectionReviewResult,
    action: str,
    guard_allowed: bool,
    guard_violations: list[str],
    evidence_id: str,
) -> dict[str, object]:
    return {
        "fragment_id": f"r_self_correction_review_{round_index}",
        "stage": "final_ranking",
        "tool": "self_correction_review",
        "source": "agent_self_correction",
        "status": _review_status(review),
        "used_llm": review.used_llm,
        "round": round_index,
        "phase": phase,
        "action": action,
        "guard_allowed": guard_allowed,
        "guard_violations": guard_violations[:8],
        "reason": review.reason_summary,
        "gaps": _review_gaps(review)[:8],
        "fit_counts": dict(getattr(evidence, "fit_counts", {}) or {}),
        "evidence_id": evidence_id,
    }


def _should_run_correction(
    review: LLMSelfCorrectionReviewResult,
    action: str,
    *,
    round_index: int,
    config: SelfCorrectionConfig,
) -> bool:
    if round_index >= config.max_rounds:
        return False
    if config.llm_review_required and _review_status(review) in {"unavailable", "invalid", "blocked"}:
        return False
    return action in _CORRECTION_ACTIONS


def _repair_query_plan(
    *,
    query: str,
    query_plan: dict[str, Any],
    correction_plan: dict[str, Any],
    evidence: SelfCorrectionEvidence,
) -> dict[str, Any]:
    result = QueryPlanRepairTool().run(
        QueryPlanRepairInput(
            original_query=query,
            query_plan=query_plan,
            correction_plan=correction_plan,
            evidence=evidence,
        )
    )
    return {
        "query_plan": result.query_plan,
        "changed_fields": result.changed_fields,
        "removed_pollution": result.removed_pollution,
        "preserved_constraints": result.preserved_constraints,
    }


def _final_status(
    review: LLMSelfCorrectionReviewResult,
    action: str,
    *,
    round_index: int,
    config: SelfCorrectionConfig,
) -> str:
    if _review_status(review) == "unavailable":
        return "llm_review_unavailable"
    if action == "ask_clarification":
        return "clarification_needed"
    if action == "fallback_no_direct_match":
        return "fallback"
    if round_index >= config.max_rounds and action in _CORRECTION_ACTIONS:
        return "fallback"
    return "answered"


def _review_status(review: LLMSelfCorrectionReviewResult) -> str:
    return str(getattr(review, "llm_review_status", "") or getattr(review, "status", "") or "unknown")


def _review_gaps(review: LLMSelfCorrectionReviewResult) -> list[str]:
    raw = (
        getattr(review, "gaps", None)
        or getattr(review, "detected_errors", None)
        or getattr(review, "rejected_changes", None)
        or []
    )
    if not isinstance(raw, list):
        return []
    values: list[str] = []
    for item in raw:
        text = str(item or "").strip()
        if text and text not in values:
            values.append(text)
    return values


def _stage_update(
    *,
    query_plan: dict[str, Any],
    matches: list,
    staged_results: list,
    online_results: list,
    retrieval_evidence: list[dict[str, object]],
    trace: dict[str, Any],
) -> dict[str, Any]:
    return {
        "query_plan": query_plan,
        "matches": matches,
        "staged_results": staged_results,
        "online_results": online_results,
        "retrieval_evidence": retrieval_evidence,
        "self_correction_summary": {
            "status": trace.get("final_status"),
            "round_count": len(trace.get("rounds") or []),
            "llm_review_required": trace.get("llm_review_required"),
        },
        "self_correction_trace": trace,
    }
