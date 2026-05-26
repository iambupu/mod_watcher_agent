import logging
from typing import Any

from app.services.agent.context.context_inference import decide_context_inheritance

logger = logging.getLogger(__name__)


def apply_followup_context(raw: dict[str, Any], context: dict[str, Any], query: str) -> None:
    context_keywords = _string_list(context.get("keywords"))
    context_semantic_anchors = _string_list(context.get("semantic_anchors"))
    effective_context_keywords = context_keywords or context_semantic_anchors
    current_keywords = _string_list(raw.get("keywords"))
    context_quality = _as_float(context.get("quality_score"))
    inherit_decision = decide_context_inheritance(
        query=query,
        current_keywords=current_keywords,
        context_keywords=effective_context_keywords,
        context_quality=context_quality,
        has_refinement_constraints=has_refinement_constraints(raw),
        context_has_semantic_anchors=bool(context_semantic_anchors),
    )
    inherit_keywords = inherit_decision.inherit_keywords
    continuity = inherit_decision.continuity_score
    inherit_score = inherit_decision.inherit_score
    inherit_threshold = inherit_decision.inherit_threshold
    topic_shift = inherit_decision.topic_shift
    logger.info(
        "agent.context_inherit source=%s inherit_keywords=%s followup_score=%.2f continuity_score=%.2f inherit_score=%.2f inherit_threshold=%.2f topic_shift=%s low_signal=%s quality_score=%.2f reasons=%s policy_reasons=%s current_keywords=%s context_keywords=%s context_semantic_anchors=%s",
        context.get("source"),
        inherit_keywords,
        inherit_decision.followup_score,
        continuity,
        inherit_score,
        inherit_threshold,
        topic_shift,
        inherit_decision.low_signal,
        context_quality,
        list(inherit_decision.reasons),
        list(inherit_decision.policy_reasons),
        current_keywords,
        context_keywords,
        context_semantic_anchors,
    )
    raw["_agent_context_signal"] = {
        "source": context.get("source"),
        "quality_score": round(context_quality, 3),
        "followup_score": round(float(inherit_decision.followup_score), 3),
        "continuity_score": round(float(continuity), 3),
        "inherit_score": round(float(inherit_score), 3),
        "inherit_threshold": round(float(inherit_threshold), 3),
        "inherited": bool(inherit_keywords),
        "topic_shift": bool(topic_shift),
        "low_signal": bool(inherit_decision.low_signal),
        "reasons": list(inherit_decision.reasons),
        "policy_reasons": list(inherit_decision.policy_reasons),
    }
    if inherit_keywords:
        raw["keywords"] = merge_context_keywords(
            current_keywords=current_keywords,
            context_keywords=effective_context_keywords,
        )
    _copy_context_value(raw, "game", "games", context)
    _copy_context_value(raw, "source_name", "sources", context)
    _copy_context_value(raw, "category", "categories", context)
    for key in ["adult_content", "sort_field", "sort_order"]:
        if raw.get(key) is None and context.get(key) is not None:
            raw[key] = context[key]


def merge_context_keywords(*, current_keywords: list[str], context_keywords: list[str]) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()

    def _push(values: list[str]) -> None:
        for value in values:
            token = str(value or "").strip().lower()
            if not token or token in seen:
                continue
            if _is_weak_keyword(token):
                continue
            merged.append(token)
            seen.add(token)

    _push(context_keywords)
    _push(current_keywords)
    return merged[:6]


def has_refinement_constraints(raw: dict[str, Any]) -> bool:
    slots = [
        "adult_content",
        "has_thumbnail",
        "sort_field",
        "updated_since_days",
        "min_downloads",
        "min_endorsements",
        "min_views",
        "min_likes",
        "sources",
        "excluded_sources",
        "categories",
        "tags",
        "summary_languages",
        "excluded_summary_languages",
        "requirement_terms",
        "compatibility_terms",
        "author",
        "version",
        "exact_title",
        "external_id",
        "source_url",
    ]
    return any(raw.get(slot) not in (None, [], "") for slot in slots)


def _copy_context_value(raw: dict[str, Any], context_key: str, plan_key: str, context: dict[str, Any]) -> None:
    if raw.get(plan_key) or context.get(context_key) is None:
        return
    raw[plan_key] = [context[context_key]]


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _as_float(value: object) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _is_weak_keyword(token: str) -> bool:
    if len(token) <= 1:
        return True
    return token in {"mod", "mods", "style", "related", "similar", "continue", "继续", "相关", "类似"}
