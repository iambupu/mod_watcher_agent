import logging
from typing import Any

from app.services.agent.context.context_inference import decide_context_inheritance
from app.services.agent.list_utils import string_list
from app.utils.numeric import safe_float

logger = logging.getLogger(__name__)


def apply_followup_context(raw: dict[str, Any], context: dict[str, Any], query: str) -> None:
    context_keywords = string_list(context.get("keywords"))
    context_semantic_anchors = string_list(context.get("semantic_anchors"))
    effective_context_keywords = context_keywords or context_semantic_anchors
    current_keywords = string_list(raw.get("keywords"))
    context_quality = safe_float(context.get("quality_score"))
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
    llm_selected_context = context.get("source") == "llm_context_selection" and context.get("llm_should_inherit") is True
    inherited_fields: list[str] = []
    skipped_reason = ""
    overridden_by_current_signal = False
    if llm_selected_context:
        # LLM context selector 已结合完整上下文判断是否继承；这里仍保留显式当前槽位优先。
        inherit_keywords = True
        topic_shift = False
    if not inherit_keywords:
        if topic_shift:
            skipped_reason = "topic_shift"
            overridden_by_current_signal = True
        elif current_keywords and not inherit_decision.low_signal:
            skipped_reason = "strong_current_signal"
            overridden_by_current_signal = True
        else:
            skipped_reason = "low_inherit_score"
    if inherit_keywords:
        raw["keywords"] = merge_context_keywords(
            current_keywords=current_keywords,
            context_keywords=effective_context_keywords,
        )
        inherited_fields.append("keywords")
        # memory 默认是提示，不是命令；只有低信息追问且连续性足够高时才升级成 executor 字段。
        if _allow_context_field_promotion(
            current_keywords=current_keywords,
            inherit_score=inherit_score,
            inherit_threshold=inherit_threshold,
            topic_shift=topic_shift,
            context_quality=context_quality,
            low_signal=inherit_decision.low_signal,
            raw=raw,
        ):
            _copy_context_value(raw, "game", "games", context, inherited_fields=inherited_fields)
            _copy_context_value(raw, "source_name", "sources", context, inherited_fields=inherited_fields)
            _copy_context_value(raw, "category", "categories", context, inherited_fields=inherited_fields)
            for key in ["adult_content", "sort_field", "sort_order"]:
                if raw.get(key) is None and context.get(key) is not None:
                    raw[key] = context[key]
                    inherited_fields.append(key)
        raw["_agent_context_hint"] = _context_hint(context)
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
        "inherited_fields": list(inherited_fields),
        "skipped_reason": skipped_reason,
        "overridden_by_current_signal": overridden_by_current_signal,
        "reasons": list(inherit_decision.reasons),
        "policy_reasons": list(inherit_decision.policy_reasons),
    }
    if llm_selected_context:
        raw["_agent_context_signal"]["llm_selected"] = True
        raw["_agent_context_signal"]["llm_confidence"] = context.get("llm_confidence")
        raw["_agent_context_signal"]["llm_reason"] = context.get("llm_reason")
    logger.info(
        "agent.context_inherit source=%s inherited=%s inherited_fields=%s skipped_reason=%s overridden_by_current_signal=%s inherit_keywords=%s followup_score=%.2f continuity_score=%.2f inherit_score=%.2f inherit_threshold=%.2f topic_shift=%s low_signal=%s quality_score=%.2f reasons=%s policy_reasons=%s current_keywords=%s context_keywords=%s context_semantic_anchors=%s",
        context.get("source"),
        bool(inherit_keywords),
        inherited_fields,
        skipped_reason,
        overridden_by_current_signal,
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


def mark_current_context_not_inherited(raw: dict[str, Any], context: dict[str, Any]) -> None:
    raw["_agent_context_signal"] = {
        "source": "current",
        "quality_score": safe_float((context or {}).get("quality_score")),
        "followup_score": 0.0,
        "continuity_score": 0.0,
        "inherit_score": 0.0,
        "inherit_threshold": 0.0,
        "inherited": False,
        "topic_shift": False,
        "low_signal": False,
        "inherited_fields": [],
        "skipped_reason": "current_input_not_context",
        "overridden_by_current_signal": True,
        "reasons": [],
        "policy_reasons": [],
    }


def _allow_context_field_promotion(
    *,
    current_keywords: list[str],
    inherit_score: float,
    inherit_threshold: float,
    topic_shift: bool,
    context_quality: float,
    low_signal: bool,
    raw: dict[str, Any],
) -> bool:
    weak_current = _only_weak_current_keywords(current_keywords)
    if topic_shift and not weak_current and not low_signal:
        return False
    if current_keywords and not weak_current and not low_signal:
        return False
    if low_signal and context_quality >= 0.75:
        return True
    if has_refinement_constraints(raw):
        return False
    if (weak_current or len(current_keywords) <= 2) and context_quality >= 0.75:
        return True
    return inherit_score >= inherit_threshold


def _context_hint(context: dict[str, Any]) -> dict[str, Any]:
    return {
        "keywords": string_list(context.get("keywords")),
        "semantic_anchors": string_list(context.get("semantic_anchors")),
        "semantic_domains": string_list(context.get("semantic_domains")),
        "game": context.get("game"),
        "source_name": context.get("source_name"),
        "category": context.get("category"),
        "adult_content": context.get("adult_content"),
        "sort_field": context.get("sort_field"),
        "sort_order": context.get("sort_order"),
        "source": context.get("source"),
        "quality_score": context.get("quality_score"),
    }


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


def _copy_context_value(
    raw: dict[str, Any],
    context_key: str,
    plan_key: str,
    context: dict[str, Any],
    *,
    inherited_fields: list[str],
) -> None:
    if raw.get(plan_key) or context.get(context_key) is None:
        return
    raw[plan_key] = [context[context_key]]
    inherited_fields.append(plan_key)


def _is_weak_keyword(token: str) -> bool:
    if len(token) <= 1:
        return True
    return token in {
        "mod",
        "mods",
        "style",
        "related",
        "similar",
        "same",
        "continue",
        "more",
        "another",
        "result",
        "results",
        "ll",
        "loverslab",
        "nexus",
        "nexusmods",
        "继续",
        "相关",
        "类似",
        "同类",
        "结果",
        "的结果",
        "风格",
        "相关风格",
        "相关结果",
        "类似结果",
        "同类结果",
    }


def _only_weak_current_keywords(values: list[str]) -> bool:
    return all(_is_weak_keyword(str(value).strip().lower()) for value in values if str(value).strip())
