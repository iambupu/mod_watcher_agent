from dataclasses import dataclass
from typing import Any

from app.services.agent.context.context_inference import (
    FollowupDecision,
    followup_decision,
    has_distinctive_keywords,
    semantic_continuity_score,
)
from app.services.agent.semantic_search import base_keywords


@dataclass(frozen=True)
class QueryContextSelection:
    selected_context: dict[str, Any]
    score: float
    quality_score: float
    current_keywords: list[str]
    followup: FollowupDecision


def should_inherit_active_constraints(current_text: str) -> bool:
    current_keywords = base_keywords(current_text)
    followup = followup_decision(current_text)
    return followup.is_followup or followup.low_signal or not has_distinctive_keywords(current_keywords)


def should_use_current_query_context(current_text: str, current_keywords: list[str]) -> bool:
    followup = followup_decision(current_text)
    has_relational_refinement = "has_relational_intent" in followup.reasons
    return bool(
        current_keywords
        and has_distinctive_keywords(current_keywords)
        and not followup.is_followup
        and not has_relational_refinement
    )


def select_history_query_context(
    *,
    current_text: str,
    current_keywords: list[str],
    candidates: list[dict[str, Any]],
) -> QueryContextSelection | None:
    followup = followup_decision(current_text)
    scored_candidates: list[tuple[float, int, dict[str, Any]]] = []
    for idx, context in enumerate(candidates):
        if not has_context_signal(context):
            continue
        candidate_keywords = _string_list(context.get("keywords"))
        continuity = semantic_continuity_score(current_text, current_keywords, candidate_keywords)
        quality = context_quality_score(context)
        structural_bonus = 0.0
        if context.get("game"):
            structural_bonus += 0.05
        if context.get("source_name"):
            structural_bonus += 0.05
        if context.get("category"):
            structural_bonus += 0.03
        if followup.low_signal and candidate_keywords:
            structural_bonus += 0.08
        structural_bonus += quality * 0.08
        recency_bonus = max(0.0, 0.06 - idx * 0.01)
        score = continuity + structural_bonus + recency_bonus
        enriched = dict(context)
        enriched["quality_score"] = quality
        scored_candidates.append((score, idx, enriched))
    if not scored_candidates:
        return None
    best_score, _best_idx, best_context = max(scored_candidates, key=lambda item: (item[0], -item[1]))
    best_quality = float(best_context.get("quality_score") or 0.0)
    if (best_score >= 0.18 and best_quality >= 0.2) or (followup.low_signal and best_quality >= 0.12):
        return QueryContextSelection(
            selected_context=best_context,
            score=round(float(best_score), 3),
            quality_score=round(float(best_quality), 3),
            current_keywords=list(current_keywords),
            followup=followup,
        )
    return None


def has_context_signal(context: dict[str, Any]) -> bool:
    return bool(context.get("keywords")) or any(
        context.get(key) is not None
        for key in ["game", "source_name", "category", "adult_content", "sort_field"]
    )


def context_quality_score(context: dict[str, Any]) -> float:
    keywords = _string_list(context.get("keywords"))
    semantic_anchors = _string_list(context.get("semantic_anchors"))
    score = 0.0
    if keywords:
        score += min(len(keywords), 4) * 0.18
    if semantic_anchors:
        score += min(len(semantic_anchors), 3) * 0.08
    if context.get("game"):
        score += 0.2
    if context.get("source_name"):
        score += 0.12
    if context.get("category"):
        score += 0.1
    if context.get("adult_content") is not None:
        score += 0.08
    if context.get("sort_field"):
        score += 0.08
    return round(min(score, 1.0), 3)


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]
