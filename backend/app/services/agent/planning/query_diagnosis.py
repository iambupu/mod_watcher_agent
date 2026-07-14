from typing import Any, NotRequired, TypedDict

from app.services.agent.context.context_inference import is_contextual_followup
from app.services.agent.list_utils import string_list as _string_list
from app.services.agent.planning.context_diagnosis import (
    ContextDiagnosisSignal,
    PreferenceMemoryGate,
    decide_preference_memory_gate,
    evaluate_context_diagnosis,
)
from app.services.agent.planning.query_intent import detect_query_intent
from app.services.agent.planning.query_plan_contract import (
    semantic_strategy as get_semantic_strategy,
)
from app.services.agent.planning.semantic_signals import anchor_domains
from app.services.agent.tools.semantic_signal_tool import SemanticSignalInput, SemanticSignalTool
from app.utils.boolean import parse_bool, parse_optional_bool
from app.utils.numeric import safe_float, safe_nonnegative_int


class UnderstandingEvidence(TypedDict):
    fragment_id: str
    field: str
    source: str
    value: Any
    evidence_id: NotRequired[str]
    related_fragments: NotRequired[list[str]]


class TaskUnderstanding(TypedDict):
    intent: str
    slots: dict[str, Any]
    confidence: float
    evidence: list[UnderstandingEvidence]
    followup: bool


class QueryDiagnosis(TypedDict):
    intent: str
    confidence: float
    missing_slots: list[str]
    known_slots: dict[str, Any]
    should_clarify: bool
    clarifying_question: NotRequired[str | None]
    understanding: NotRequired[TaskUnderstanding]


def diagnosis_log_fields(diagnosis: dict[str, Any]) -> dict[str, Any]:
    """从诊断结果中提取稳定日志字段。"""
    return {
        "context_continuity_score": _evidence_value(diagnosis, "context_continuity_score", None),
        "semantic_anchors": _evidence_value(diagnosis, "semantic_anchors", []),
        "semantic_domains": _evidence_value(diagnosis, "semantic_domains", []),
    }


def diagnose_query(
    *,
    query: str,
    query_plan: dict[str, Any],
    active_constraints: dict[str, Any] | None = None,
    preferences: dict[str, Any] | None = None,
    context_keywords: list[str] | None = None,
    context_slots: dict[str, Any] | None = None,
) -> QueryDiagnosis:
    constraints = active_constraints or {}
    plan_keywords = _string_list((query_plan or {}).get("keywords"))
    evidence_id = str((query_plan or {}).get("evidence_id") or "").strip()
    semantic_strategy = get_semantic_strategy(query_plan)
    semantic_anchors, semantic_domains, semantic_source = _semantic_signals(
        query=query,
        query_plan=query_plan,
        keywords=plan_keywords,
        evidence_id=evidence_id,
    )
    preference_gate = decide_preference_memory_gate(
        query=query,
        query_plan=query_plan,
        context_keywords=context_keywords or [],
        context_slots=context_slots or {},
        preferences=preferences or {},
        semantic_anchors=semantic_anchors,
    )
    known_slots, slot_sources = _merge_known_slots(
        query_plan,
        constraints,
    )
    if semantic_strategy:
        _merge_semantic_strategy_slots(known_slots, slot_sources, semantic_strategy)
    _merge_inherited_context_slots(known_slots, slot_sources, context_slots or {})
    intent = _diagnosed_intent(query, query_plan, semantic_strategy=semantic_strategy)
    missing_slots = _missing_slots(query, query_plan, known_slots, intent, semantic_strategy=semantic_strategy)
    should_clarify = bool(missing_slots)
    confidence = _confidence(known_slots, missing_slots, semantic_strategy=semantic_strategy)
    context_signal = evaluate_context_diagnosis(
        query=query,
        known_slots=known_slots,
        context_keywords=context_keywords or [],
        context_slots=context_slots or {},
    )
    diagnosis: QueryDiagnosis = {
        "intent": intent,
        "confidence": confidence,
        "missing_slots": missing_slots,
        "known_slots": known_slots,
        "should_clarify": should_clarify,
        "clarifying_question": _clarifying_question(missing_slots) if should_clarify else None,
        "understanding": _build_understanding(
            query=query,
            intent=intent,
            known_slots=known_slots,
            slot_sources=slot_sources,
            confidence=confidence,
            missing_slots=missing_slots,
            context_keywords=context_keywords or [],
            context_slots=context_slots or {},
            preference_gate=preference_gate,
            preferences=preferences or {},
            query_plan=query_plan,
            plan_keywords=plan_keywords,
            semantic_anchors=semantic_anchors,
            semantic_domains=semantic_domains,
            semantic_source=semantic_source,
            context_signal=context_signal,
            semantic_strategy=semantic_strategy,
        ),
    }
    return diagnosis


def _evidence_value(diagnosis: dict[str, Any], field: str, default: Any) -> Any:
    evidence = ((diagnosis.get("understanding") or {}).get("evidence") or [])
    item = next((item for item in evidence if isinstance(item, dict) and item.get("field") == field), None)
    if not isinstance(item, dict):
        return default
    return item.get("value", default)


def _build_understanding(
    *,
    query: str,
    intent: str,
    known_slots: dict[str, Any],
    slot_sources: dict[str, str],
    confidence: float,
    missing_slots: list[str],
    context_keywords: list[str],
    context_slots: dict[str, Any],
    preference_gate: PreferenceMemoryGate,
    preferences: dict[str, Any],
    query_plan: dict[str, Any] | None = None,
    plan_keywords: list[str] | None = None,
    semantic_anchors: list[str] | None = None,
    semantic_domains: list[str] | None = None,
    semantic_source: str = "analysis",
    context_signal: ContextDiagnosisSignal | None = None,
    semantic_strategy: dict[str, Any] | None = None,
) -> TaskUnderstanding:
    evidence_id = str((query_plan or {}).get("evidence_id") or "").strip()
    plan_keywords = list(plan_keywords or [])
    semantic_anchors = list(semantic_anchors or [])
    semantic_domains = list(semantic_domains or [])
    context_signal = context_signal or evaluate_context_diagnosis(
        query=query,
        known_slots=known_slots,
        context_keywords=context_keywords,
        context_slots=context_slots,
    )
    followup_meta = context_signal.followup
    followup = followup_meta.is_followup
    evidence: list[UnderstandingEvidence] = [
        {
            "fragment_id": _understanding_fragment_id("intent", "query_plan"),
            "field": "intent",
            "source": "query_plan",
            "value": intent,
        },
        {
            "fragment_id": _understanding_fragment_id("confidence", "diagnosis"),
            "field": "confidence",
            "source": "diagnosis",
            "value": confidence,
        },
    ]
    if isinstance(semantic_strategy, dict):
        # diagnosis 服务前端和 audit，只解释 SemanticStrategy；检索策略已在兼容 query_plan 中确定。
        evidence.append(
            {
                "fragment_id": _understanding_fragment_id("semantic_strategy", "semantic_strategy"),
                "field": "semantic_strategy",
                "source": str((query_plan or {}).get("_agent_semantic_strategy_source") or "semantic_strategy"),
                "value": semantic_strategy,
            }
            )
        for field, value in _semantic_strategy_evidence_fields(semantic_strategy).items():
            evidence.append(
                {
                    "fragment_id": _understanding_fragment_id(field, "semantic_strategy"),
                    "field": field,
                    "source": "semantic_strategy",
                    "value": value,
                }
            )
        evidence.append(
            {
                "fragment_id": _understanding_fragment_id("semantic_strategy_used_llm", "semantic_strategy"),
                "field": "semantic_strategy_used_llm",
                "source": "semantic_strategy",
                "value": bool((query_plan or {}).get("_agent_semantic_strategy_used_llm")),
            }
        )
        fallback_reason = str((query_plan or {}).get("_agent_semantic_strategy_fallback_reason") or "").strip()
        if fallback_reason:
            evidence.append(
                {
                    "fragment_id": _understanding_fragment_id("semantic_strategy_fallback_reason", "semantic_strategy"),
                    "field": "semantic_strategy_fallback_reason",
                    "source": "semantic_strategy",
                    "value": fallback_reason,
                }
            )
    if followup:
        evidence.append({"fragment_id": _understanding_fragment_id("followup", "query_text"), "field": "followup", "source": "query_text", "value": True})
        evidence.append(
            {
                "fragment_id": _understanding_fragment_id("followup_score", "query_text"),
                "field": "followup_score",
                "source": "query_text",
                "value": followup_meta.score,
            }
        )
        evidence.append(
            {
                "fragment_id": _understanding_fragment_id("followup_reasons", "query_text"),
                "field": "followup_reasons",
                "source": "query_text",
                "value": list(followup_meta.reasons),
            }
        )
    topic_shift = context_signal.topic_shift
    if context_signal.effective_context_terms:
        evidence.append(
            {
                "fragment_id": _understanding_fragment_id("context_continuity_score", "short_term_memory"),
                "field": "context_continuity_score",
                "source": "short_term_memory",
                "value": context_signal.continuity_score,
            }
        )
        evidence.append(
            {
                "fragment_id": _understanding_fragment_id("context_inherit_score", "short_term_memory"),
                "field": "context_inherit_score",
                "source": "short_term_memory",
                "value": context_signal.inherit_score,
            }
        )
        evidence.append(
            {
                "fragment_id": _understanding_fragment_id("topic_shift_detected", "diagnosis"),
                "field": "topic_shift_detected",
                "source": "diagnosis",
                "value": topic_shift,
            }
        )
        evidence.append(
            {
                "fragment_id": _understanding_fragment_id("context_source", "short_term_memory"),
                "field": "context_source",
                "source": "short_term_memory",
                "value": context_signal.context_source,
            }
        )
        evidence.append(
            {
                "fragment_id": _understanding_fragment_id("context_semantic_anchors", "short_term_memory"),
                "field": "context_semantic_anchors",
                "source": "short_term_memory",
                "value": context_signal.context_semantic_anchors,
            }
        )
        evidence.append(
            {
                "fragment_id": _understanding_fragment_id("context_quality_score", "short_term_memory"),
                "field": "context_quality_score",
                "source": "short_term_memory",
                "value": context_signal.context_quality_score,
            }
        )
    if context_signal.promote_followup_from_context:
        followup = True
        evidence.append(
            {
                "fragment_id": _understanding_fragment_id("followup", "short_term_memory"),
                "field": "followup",
                "source": "short_term_memory",
                "value": True,
            }
        )
    if isinstance(context_signal.context_signal, dict):
        raw_context_signal = context_signal.context_signal
        evidence.append(
            {
                "fragment_id": _understanding_fragment_id("context_inherited", "diagnosis"),
                "field": "context_inherited",
                "source": "diagnosis",
                "value": bool(raw_context_signal.get("inherited")),
            }
        )
        evidence.append(
            {
                "fragment_id": _understanding_fragment_id("context_inherited_fields", "diagnosis"),
                "field": "context_inherited_fields",
                "source": "diagnosis",
                "value": [
                    str(item).strip()
                    for item in (raw_context_signal.get("inherited_fields") or [])
                    if str(item).strip()
                ],
            }
        )
        evidence.append(
            {
                "fragment_id": _understanding_fragment_id("context_skipped_reason", "diagnosis"),
                "field": "context_skipped_reason",
                "source": "diagnosis",
                "value": str(raw_context_signal.get("skipped_reason") or ""),
            }
        )
        evidence.append(
            {
                "fragment_id": _understanding_fragment_id("context_overridden_by_current_signal", "diagnosis"),
                "field": "context_overridden_by_current_signal",
                "source": "diagnosis",
                "value": bool(raw_context_signal.get("overridden_by_current_signal")),
            }
        )
        evidence.append(
            {
                "fragment_id": _understanding_fragment_id("context_inherit_threshold", "diagnosis"),
                "field": "context_inherit_threshold",
                "source": "diagnosis",
                "value": safe_float(raw_context_signal.get("inherit_threshold")),
            }
        )
        evidence.append(
            {
                "fragment_id": _understanding_fragment_id("context_followup_score", "diagnosis"),
                "field": "context_followup_score",
                "source": "diagnosis",
                "value": safe_float(raw_context_signal.get("followup_score")),
            }
        )
        evidence.append(
            {
                "fragment_id": _understanding_fragment_id("context_policy_reasons", "diagnosis"),
                "field": "context_policy_reasons",
                "source": "diagnosis",
                "value": [
                    str(item).strip()
                    for item in (raw_context_signal.get("policy_reasons") or [])
                    if str(item).strip()
                ],
            }
        )
    evidence.append(
        {
            "fragment_id": _understanding_fragment_id("preference_memory_applied", "diagnosis"),
            "field": "preference_memory_applied",
            "source": "diagnosis",
            "value": False,
        }
    )
    evidence.append(
        {
            "fragment_id": _understanding_fragment_id("preference_memory_available", "diagnosis"),
            "field": "preference_memory_available",
            "source": "diagnosis",
            "value": bool(preference_gate.allow),
        }
    )
    evidence.append(
        {
            "fragment_id": _understanding_fragment_id("preference_memory_stale", "diagnosis"),
            "field": "preference_memory_stale",
            "source": "diagnosis",
            "value": bool(preference_gate.reason == "stale_preference_memory"),
        }
    )
    evidence.append(
        {
            "fragment_id": _understanding_fragment_id("preference_memory_reason", "diagnosis"),
            "field": "preference_memory_reason",
            "source": "diagnosis",
            "value": str(preference_gate.reason or ""),
        }
    )
    if semantic_anchors:
        evidence.append(
            {
                "fragment_id": _understanding_fragment_id("semantic_anchors", "analysis"),
                "field": "semantic_anchors",
                "source": semantic_source,
                "value": semantic_anchors,
            }
        )
    if semantic_domains:
        evidence.append(
            {
                "fragment_id": _understanding_fragment_id("semantic_domains", "analysis"),
                "field": "semantic_domains",
                "source": semantic_source,
                "value": semantic_domains,
            }
        )
    understanding_slots = dict(known_slots)
    if isinstance(semantic_strategy, dict):
        understanding_slots["semantic_task_type"] = str(semantic_strategy.get("task_type") or "")
        understanding_slots["semantic_strategy"] = str(semantic_strategy.get("strategy") or "")
        understanding_slots["soft_signals"] = _string_list(semantic_strategy.get("soft_signals"))
    if not understanding_slots.get("game") and context_slots.get("game") and not topic_shift:
        understanding_slots["game"] = context_slots["game"]
    if plan_keywords:
        understanding_slots["keywords"] = plan_keywords
        evidence.append(
            {
                "fragment_id": _understanding_fragment_id("keywords", "query_plan"),
                "field": "keywords",
                "source": "query_plan",
                "value": list(plan_keywords),
            }
        )
    if "open_discovery" in query_plan:
        open_discovery = parse_bool(query_plan.get("open_discovery"))
        understanding_slots["open_discovery"] = open_discovery
        evidence.append(
            {
                "fragment_id": _understanding_fragment_id("open_discovery", "query_plan"),
                "field": "open_discovery",
                "source": "query_plan",
                "value": open_discovery,
            }
        )
    if query_plan.get("retrieval_mode"):
        understanding_slots["retrieval_mode"] = str(query_plan.get("retrieval_mode"))
        evidence.append(
            {
                "fragment_id": _understanding_fragment_id("retrieval_mode", "query_plan"),
                "field": "retrieval_mode",
                "source": "query_plan",
                "value": str(query_plan.get("retrieval_mode")),
            }
        )
    memory_meta = preferences.get("memory_meta") if isinstance(preferences, dict) else None
    if isinstance(memory_meta, dict) and memory_meta.get("preferences_age_days") is not None:
        evidence.append(
            {
                "fragment_id": _understanding_fragment_id("preference_memory_age_days", "diagnosis"),
                "field": "preference_memory_age_days",
                "source": "diagnosis",
                "value": safe_nonnegative_int(memory_meta.get("preferences_age_days")),
            }
        )
    for field in ["game", "source", "category", "adult_content", "sort_field", "sort_order", "adult_content_allowed"]:
        if field in known_slots:
            item = {
                "fragment_id": _understanding_fragment_id(field, slot_sources.get(field, "query_plan")),
                "field": field,
                "source": slot_sources.get(field, "query_plan"),
                "value": known_slots.get(field),
            }
            if field == "game":
                item["related_fragments"] = ["u_query_plan_keywords", "m_writeback_game"]
            evidence.append(item)
    if missing_slots:
        evidence.append(
            {
                "fragment_id": _understanding_fragment_id("missing_slots", "diagnosis"),
                "field": "missing_slots",
                "source": "diagnosis",
                "value": list(missing_slots),
            }
        )
    if evidence_id:
        for item in evidence:
            item["evidence_id"] = evidence_id
    return {
        "intent": intent,
        "slots": understanding_slots,
        "confidence": confidence,
        "evidence": evidence,
        "followup": followup,
    }


def _diagnosed_intent(query: str, query_plan: dict[str, Any], *, semantic_strategy: dict[str, Any] | None = None) -> str:
    planned = str(query_plan.get("intent") or "unknown")
    if isinstance(semantic_strategy, dict) and semantic_strategy.get("task_type"):
        if semantic_strategy.get("task_type") == "comparative" and planned in {"alternative", "comparison"}:
            return planned
        return {
            "exact_lookup": "search",
            "open_discovery": "search",
            "comparative": "comparison",
            "advisory": "install_risk",
            "preference": "preference_summary",
            "unknown": "unknown",
        }.get(str(semantic_strategy.get("task_type")), planned)
    detected = detect_query_intent(query)
    if detected in {"comparison", "alternative", "install_risk", "preference_summary"}:
        return detected
    return planned


def _merge_known_slots(
    query_plan: dict[str, Any],
    constraints: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, str]]:
    known: dict[str, Any] = {}
    slot_sources: dict[str, str] = {}
    _copy_first_list_value(known, "game", query_plan.get("games"), slot_sources=slot_sources, source="query_plan")
    _copy_first_list_value(known, "source", query_plan.get("sources"), slot_sources=slot_sources, source="query_plan")
    _copy_first_list_value(
        known,
        "category",
        query_plan.get("categories"),
        slot_sources=slot_sources,
        source="query_plan",
    )

    for key in ["game", "source", "category", "sort_field", "sort_order"]:
        if key not in known and constraints.get(key) is not None:
            known[key] = constraints[key]
            slot_sources[key] = "short_term_memory"

    adult_content = query_plan.get("adult_content")
    if adult_content is None:
        adult_content = constraints.get("adult_content")
        if adult_content is not None:
            slot_sources["adult_content"] = "short_term_memory"
    else:
        slot_sources["adult_content"] = "query_plan"
    if adult_content is not None:
        known["adult_content"] = adult_content
    return known, slot_sources


def _merge_semantic_strategy_slots(
    known: dict[str, Any],
    slot_sources: dict[str, str],
    semantic_strategy: dict[str, Any],
) -> None:
    hard_filters = semantic_strategy.get("hard_filters") if isinstance(semantic_strategy.get("hard_filters"), dict) else {}
    mapping = {
        "game": "game",
        "source": "source",
        "adult_content": "adult_content",
        "exact_title": "exact_title",
        "external_id": "external_id",
        "source_url": "source_url",
    }
    for source_key, slot_key in mapping.items():
        value = hard_filters.get(source_key)
        if value not in (None, "", []):
            known[slot_key] = _normalize_slot_value(slot_key, value)
            slot_sources[slot_key] = "semantic_strategy"


def _merge_inherited_context_slots(
    known: dict[str, Any],
    slot_sources: dict[str, str],
    context_slots: dict[str, Any],
) -> None:
    context_signal = context_slots.get("_agent_context_signal") if isinstance(context_slots, dict) else None
    if not isinstance(context_signal, dict):
        return
    if not context_signal.get("inherited") or context_signal.get("topic_shift"):
        return
    for key in ["game", "source", "category", "sort_field", "sort_order"]:
        if key not in known and context_slots.get(key) is not None:
            known[key] = context_slots[key]
            slot_sources[key] = "short_term_memory"
    if "adult_content" not in known and context_slots.get("adult_content") is not None:
        known["adult_content"] = context_slots["adult_content"]
        slot_sources["adult_content"] = "short_term_memory"


def _copy_first_list_value(
    target: dict[str, Any],
    key: str,
    value: Any,
    *,
    slot_sources: dict[str, str] | None = None,
    source: str | None = None,
) -> None:
    values = _string_list(value, limit=1)
    if values:
        target[key] = _normalize_slot_value(key, values[0])
        if slot_sources is not None and source:
            slot_sources[key] = source


def _normalize_slot_value(key: str, value: object) -> object:
    if key == "adult_content":
        parsed = parse_optional_bool(value)
        if parsed is not None:
            return parsed
        return value
    text = str(value or "").strip()
    if key == "category":
        labels = {
            "outfit": "Outfit",
            "body": "Body",
            "gameplay": "Gameplay",
            "armor": "Armor",
            "weapon": "Weapon",
        }
        return labels.get(text.lower(), text)
    return text


def _missing_slots(
    query: str,
    query_plan: dict[str, Any],
    known_slots: dict[str, Any],
    intent: str | None = None,
    semantic_strategy: dict[str, Any] | None = None,
) -> list[str]:
    task_type = semantic_strategy.get("task_type") if isinstance(semantic_strategy, dict) else None
    if task_type in {"open_discovery", "preference"}:
        return []
    if task_type == "unknown":
        return ["query_scope"]
    intent = intent or str(query_plan.get("intent") or "unknown")
    if intent not in {"search", "recent", "game", "comparison", "alternative"}:
        return []
    if "game" in known_slots:
        return []
    if _is_contextual_followup(query):
        return ["game"]
    if known_slots.get("adult_content") is True or known_slots.get("category"):
        return ["game"]
    return []


def _confidence(
    known_slots: dict[str, Any],
    missing_slots: list[str],
    *,
    semantic_strategy: dict[str, Any] | None = None,
) -> float:
    if isinstance(semantic_strategy, dict):
        semantic_confidence = safe_float(semantic_strategy.get("confidence"))
        if semantic_confidence > 0:
            return round(max(0.0, min(semantic_confidence, 0.98)), 3)
    if missing_slots:
        return 0.45
    score = 0.55
    if known_slots.get("game"):
        score += 0.2
    if known_slots.get("source"):
        score += 0.08
    if "adult_content" in known_slots:
        score += 0.08
    if known_slots.get("sort_field"):
        score += 0.04
    return min(score, 0.95)


def _clarifying_question(missing_slots: list[str]) -> str | None:
    if "game" in missing_slots:
        return "你想看哪个游戏的 Mod？"
    if "query_scope" in missing_slots:
        return "你想查找哪类 Mod，或希望我按哪个游戏、来源、关键词来缩小范围？"
    return None


def _semantic_strategy_evidence_fields(strategy: dict[str, Any]) -> dict[str, Any]:
    hard_filters = strategy.get("hard_filters") if isinstance(strategy.get("hard_filters"), dict) else {}
    return {
        "semantic_task_type": str(strategy.get("task_type") or ""),
        "semantic_user_goal": str(strategy.get("user_goal") or ""),
        "semantic_retrieval_strategy": str(strategy.get("strategy") or ""),
        "semantic_hard_filters": hard_filters,
        "semantic_soft_signals": _string_list(strategy.get("soft_signals")),
        "semantic_missing_info": _string_list(strategy.get("missing_info")),
        "semantic_strategy_reason": str(strategy.get("reason") or ""),
    }


def _is_contextual_followup(query: str) -> bool:
    return is_contextual_followup(query)


def _understanding_fragment_id(field: str, source: str) -> str:
    return f"u_{source}_{field}"


def _semantic_signals(
    *,
    query: str,
    keywords: list[str],
    query_plan: dict[str, Any],
    evidence_id: str,
) -> tuple[list[str], list[str], str]:
    plan_anchors = _string_list((query_plan or {}).get("_agent_semantic_anchors"))
    if plan_anchors:
        plan_domains = _string_list((query_plan or {}).get("_agent_semantic_domains")) or anchor_domains(plan_anchors)
        semantic_source = str((query_plan or {}).get("_agent_semantic_source") or "").strip()
        source = "semantic_strategy" if semantic_source == "llm" else "query_plan"
        return plan_anchors, plan_domains, source
    semantic_signal = SemanticSignalTool().run(
        SemanticSignalInput(query=query, keywords=keywords, evidence_id=evidence_id)
    )
    return semantic_signal.anchors, semantic_signal.domains, "analysis"
