from dataclasses import dataclass
from typing import Any

from app.services.agent.context.context_inference import (
    FollowupDecision,
    context_keyword_inherit_score,
    decide_context_inheritance,
    followup_decision,
    has_distinctive_keywords,
    semantic_continuity_score,
)
from app.services.agent.context.context_utils import merge_context_terms
from app.services.agent.list_utils import string_list
from app.utils.numeric import safe_float


@dataclass(frozen=True)
class ContextDiagnosisSignal:
    followup: FollowupDecision
    context_semantic_anchors: list[str]
    effective_context_terms: list[str]
    continuity_score: float
    inherit_score: float
    topic_shift: bool
    context_source: str
    context_quality_score: float
    promote_followup_from_context: bool
    context_signal: dict[str, Any] | None


@dataclass(frozen=True)
class PreferenceMemoryGate:
    allow: bool
    reason: str


def evaluate_context_diagnosis(
    *,
    query: str,
    known_slots: dict[str, Any],
    context_keywords: list[str],
    context_slots: dict[str, Any],
) -> ContextDiagnosisSignal:
    followup = followup_decision(query)
    context_semantic_anchors = string_list(context_slots.get("semantic_anchors"), limit=12)
    effective_context_terms = merge_context_terms(context_keywords, context_semantic_anchors)
    continuity = 0.0
    inherit_score = 0.0
    topic_shift = False
    if effective_context_terms:
        continuity = semantic_continuity_score(query, None, effective_context_terms)
        inherit_score = context_keyword_inherit_score(query, None, effective_context_terms)
        topic_shift = continuity < 0.22 and inherit_score < 0.2
        context_game = str(context_slots.get("game") or "").strip().lower()
        current_game = str(known_slots.get("game") or "").strip().lower()
        if context_game and current_game and context_game != current_game:
            topic_shift = True
            continuity = min(continuity, 0.15)
            inherit_score = min(inherit_score, 0.15)
    return ContextDiagnosisSignal(
        followup=followup,
        context_semantic_anchors=context_semantic_anchors,
        effective_context_terms=effective_context_terms,
        continuity_score=float(continuity),
        inherit_score=float(inherit_score),
        topic_shift=bool(topic_shift),
        context_source=str(context_slots.get("source") or "unknown"),
        context_quality_score=safe_float(context_slots.get("quality_score")),
        promote_followup_from_context=(
            (not followup.is_followup)
            and bool(context_semantic_anchors)
            and float(inherit_score) >= 0.32
        ),
        context_signal=context_slots.get("_agent_context_signal")
        if isinstance(context_slots.get("_agent_context_signal"), dict)
        else None,
    )


def decide_preference_memory_gate(
    *,
    query: str,
    query_plan: dict[str, Any],
    context_keywords: list[str],
    context_slots: dict[str, Any],
    preferences: dict[str, Any],
    semantic_anchors: list[str],
) -> PreferenceMemoryGate:
    memory_meta = preferences.get("memory_meta") if isinstance(preferences, dict) else None
    if isinstance(memory_meta, dict) and bool(memory_meta.get("preference_stale")):
        return PreferenceMemoryGate(allow=False, reason="stale_preference_memory")
    followup = followup_decision(query)
    plan_keywords = string_list(query_plan.get("keywords"), limit=12)
    context_semantic_anchors = string_list(context_slots.get("semantic_anchors"), limit=12)
    effective_context_terms = merge_context_terms(context_keywords, context_semantic_anchors)
    inherit_decision = decide_context_inheritance(
        query=query,
        current_keywords=plan_keywords,
        context_keywords=effective_context_terms,
        context_quality=safe_float(context_slots.get("quality_score")),
        has_refinement_constraints=False,
        context_has_semantic_anchors=bool(context_semantic_anchors),
    )
    continuity = inherit_decision.continuity_score
    inherit_score = inherit_decision.inherit_score
    distinctive_count = len([keyword for keyword in plan_keywords if has_distinctive_keywords([keyword])])
    has_explicit_scope = bool((query_plan.get("games") or []) or (query_plan.get("sources") or []))
    has_strong_current_signal = has_explicit_scope or distinctive_count >= 2 or len(semantic_anchors) >= 2
    if context_semantic_anchors and str(context_slots.get("source") or "").strip() in {
        "recent_user",
        "history_backfill",
    }:
        return PreferenceMemoryGate(allow=False, reason="context_locked")
    if effective_context_terms and inherit_decision.inherit_keywords:
        return PreferenceMemoryGate(allow=False, reason="context_locked")
    if followup.is_followup and (followup.low_signal or inherit_score >= 0.5):
        return PreferenceMemoryGate(allow=True, reason="followup_query")
    if inherit_score >= 0.45 or continuity >= 0.45:
        return PreferenceMemoryGate(allow=True, reason="context_continuity")
    if has_strong_current_signal:
        return PreferenceMemoryGate(allow=False, reason="strong_current_signal")
    return PreferenceMemoryGate(allow=True, reason="weak_current_signal")
