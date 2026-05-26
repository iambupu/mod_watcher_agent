from app.services.agent.schemas import (
    AgentAnalysisEvidenceCoverage,
    AgentAudit,
    AgentAuditAnalysis,
    AgentAuditConclusion,
    AgentAuditEvidence,
    AgentChatResponse,
    AgentContextSignalEvidence,
    AgentMemoryContextAlignmentEvidence,
    AgentToolPlanningEvidence,
)

_RECOMMENDED_ACTION_REASON_MAP = {
    "collect_more_evidence": "insufficient_analysis_evidence",
    "review_memory_signals": "memory_signal_conflicts_detected",
    "clarify_memory_conflict": "high_consistency_risk_memory_conflict",
    "expand_online_sources_and_narrow_scope": "conservative_online_zero_result_expand_sources",
    "narrow_query_scope_and_review_memory": "low_planning_confidence_with_medium_risk",
    "narrow_query_scope": "low_planning_confidence",
}


def build_standard_audit(response: AgentChatResponse, tool_plan: object | None = None) -> AgentAudit:
    understanding = response.understanding if isinstance(response.understanding, dict) else {}
    slots = understanding.get("slots") if isinstance(understanding.get("slots"), dict) else {}
    intent = str(understanding.get("intent") or "")
    confidence = understanding.get("confidence")
    understanding_evidence = understanding.get("evidence") if isinstance(understanding.get("evidence"), list) else []
    evidence_ids: list[str] = []
    for item in understanding_evidence:
        if not isinstance(item, dict):
            continue
        fragment_id = str(item.get("fragment_id") or "").strip()
        if fragment_id:
            evidence_ids.append(fragment_id)
        for related in item.get("related_fragments") or []:
            related_id = str(related or "").strip()
            if related_id:
                evidence_ids.append(related_id)
    for item in response.memory_evidence or []:
        if isinstance(item, dict):
            fragment_id = str(item.get("fragment_id") or "").strip()
            if fragment_id:
                evidence_ids.append(fragment_id)
    for item in response.retrieval_evidence or []:
        if isinstance(item, dict):
            fragment_id = str(item.get("fragment_id") or "").strip()
            if fragment_id:
                evidence_ids.append(fragment_id)
    unique_evidence_ids = sorted(set(evidence_ids))
    context_source = _understanding_evidence_value(understanding_evidence, "context_source")
    context_quality_score = _as_float(_understanding_evidence_value(understanding_evidence, "context_quality_score"))
    context_inherit_score = _as_float(_understanding_evidence_value(understanding_evidence, "context_inherit_score"))
    context_inherit_threshold = _as_float(_understanding_evidence_value(understanding_evidence, "context_inherit_threshold"))
    context_followup_score = _as_float(_understanding_evidence_value(understanding_evidence, "context_followup_score"))
    context_policy_reasons = _string_list(_understanding_evidence_value(understanding_evidence, "context_policy_reasons"))
    context_inherited = _as_bool(_understanding_evidence_value(understanding_evidence, "context_inherited"))
    topic_shift_detected = _as_bool(_understanding_evidence_value(understanding_evidence, "topic_shift_detected"))
    conflict_fields: list[str] = []
    hard_conflict_count = 0
    soft_conflict_count = 0
    for item in response.memory_evidence or []:
        if not isinstance(item, dict):
            continue
        if str(item.get("source") or "").strip() != "memory_conflict":
            continue
        field = str(item.get("field") or "").strip()
        severity = str(item.get("severity") or "").strip()
        if field:
            conflict_fields.append(field)
        if severity == "hard_conflict":
            hard_conflict_count += 1
        elif severity == "soft_conflict":
            soft_conflict_count += 1
    preference_stale = any(
        isinstance(item, dict)
        and str(item.get("field") or "").strip() == "preference_stale"
        and bool(item.get("value"))
        for item in (response.memory_evidence or [])
    )
    alignment = _memory_context_alignment(
        hard_conflict_count=hard_conflict_count,
        soft_conflict_count=soft_conflict_count,
        context_source=str(context_source or ""),
        context_quality_score=context_quality_score,
        context_inherit_score=context_inherit_score,
        context_inherited=context_inherited,
        topic_shift_detected=topic_shift_detected,
        preference_stale=preference_stale,
    )
    analysis_payload = {
        "intent": intent,
        "confidence": confidence,
        "slots": slots,
        "semantic_anchors": _string_list(_understanding_evidence_value(understanding_evidence, "semantic_anchors")),
        "semantic_domains": _string_list(_understanding_evidence_value(understanding_evidence, "semantic_domains")),
        "evidence_id": response.evidence_id,
    }
    analysis = AgentAuditAnalysis.model_validate(analysis_payload)
    coverage = AgentAnalysisEvidenceCoverage.model_validate(
        _build_analysis_evidence_coverage(analysis_payload, understanding_evidence)
    )
    context_signal = AgentContextSignalEvidence.model_validate(
        {
            "source": str(context_source or ""),
            "quality_score": context_quality_score,
            "inherit_score": context_inherit_score,
            "inherit_threshold": context_inherit_threshold,
            "followup_score": context_followup_score,
            "inherited": context_inherited,
            "topic_shift_detected": topic_shift_detected,
            "policy_reasons": context_policy_reasons,
        }
    )
    alignment_model = AgentMemoryContextAlignmentEvidence.model_validate(alignment)
    evidence = {
        "fragments": unique_evidence_ids,
        "memory_count": len(response.memory_evidence or []),
        "retrieval_count": len(response.retrieval_evidence or []),
        "conflict_count": len(conflict_fields),
        "conflict_fields": sorted(set(conflict_fields)),
        "hard_conflict_count": hard_conflict_count,
        "soft_conflict_count": soft_conflict_count,
        "analysis_evidence_coverage": coverage.model_dump(mode="python"),
        "context_signal": context_signal.model_dump(mode="python"),
        "memory_context_alignment": alignment_model.model_dump(mode="python"),
    }
    web_search_evidence = _build_web_search_evidence(response.retrieval_evidence or [])
    if web_search_evidence:
        evidence["web_search"] = web_search_evidence
    evidence["retrieval_decision"] = _build_retrieval_decision_evidence(
        context_signal=evidence.get("context_signal") if isinstance(evidence.get("context_signal"), dict) else {},
        memory_alignment=evidence.get("memory_context_alignment")
        if isinstance(evidence.get("memory_context_alignment"), dict)
        else {},
        web_search=web_search_evidence,
        understanding_evidence=understanding_evidence,
    )
    evidence["semantic_trace"] = _build_semantic_trace_evidence(understanding_evidence)
    planning_evidence = _extract_planning_evidence(tool_plan)
    if planning_evidence:
        evidence["tool_planning"] = AgentToolPlanningEvidence.model_validate(planning_evidence).model_dump(mode="python")
    conclusion_payload = {
        "used_llm": response.used_llm,
        "match_count": len(response.matches),
        "consistency_risk": _consistency_risk(
            hard_conflict_count,
            soft_conflict_count,
            memory_context_alignment_score=_as_float(alignment_model.score),
            context_quality_score=context_quality_score,
            context_inherit_score=context_inherit_score,
            context_source=str(context_source or ""),
            topic_shift_detected=topic_shift_detected,
        ),
        "planning_confidence": _planning_confidence((planning_evidence or {}).get("score")),
    }
    conclusion_payload["evidence_sufficiency"] = _conclusion_evidence_sufficiency(
        analysis=analysis_payload, evidence=evidence
    )
    return AgentAudit(
        analysis=analysis,
        evidence=AgentAuditEvidence.model_validate(evidence),
        conclusion=AgentAuditConclusion.model_validate(conclusion_payload),
    )


def apply_consistency_guard(response: AgentChatResponse) -> None:
    audit = _audit_as_dict(response.audit)
    conclusion = audit.get("conclusion") if isinstance(audit.get("conclusion"), dict) else {}
    evidence = audit.get("evidence") if isinstance(audit.get("evidence"), dict) else {}
    coverage = (
        evidence.get("analysis_evidence_coverage")
        if isinstance(evidence.get("analysis_evidence_coverage"), dict)
        else {}
    )
    tool_planning = evidence.get("tool_planning") if isinstance(evidence.get("tool_planning"), dict) else {}
    planning_score = tool_planning.get("score")
    try:
        planning_score_value = float(planning_score)
    except (TypeError, ValueError):
        planning_score_value = None
    risk = str(conclusion.get("consistency_risk") or "").strip().lower()
    evidence_sufficiency = str(conclusion.get("evidence_sufficiency") or "").strip().lower()
    conflict_count = int(evidence.get("conflict_count") or 0)
    has_online_adaptation_signal = any(
        isinstance(item, dict)
        and str(item.get("stage") or "").strip() == "online_adaptation"
        and str(item.get("reason") or "").strip() == "conservative_online_zero_result_expand_sources"
        for item in (response.retrieval_evidence or [])
    )
    conclusion["action_payload"] = {}
    conclusion["requires_clarification"] = risk == "high" and conflict_count > 0
    conclusion["recommended_action_reason"] = ""
    coverage_missing_fields = [str(value).strip() for value in (coverage.get("missing_fields") or []) if str(value).strip()]
    try:
        if (
            risk == "low"
            and evidence_sufficiency == "insufficient"
            and (planning_score_value is None or planning_score_value >= 0.45)
            and not has_online_adaptation_signal
        ):
            _set_recommended_action(conclusion, "collect_more_evidence")
            conclusion["action_payload"] = {"review_targets": ["analysis_evidence", *coverage_missing_fields]}
            cards = response.response_cards if isinstance(response.response_cards, dict) else {}
            next_steps = cards.get("next_steps")
            if isinstance(next_steps, list):
                hint = "当前任务理解证据不足，建议先补充目标游戏/关键词或上下文后再检索。"
                if hint not in next_steps:
                    cards["next_steps"] = [hint, *next_steps]
                    response.response_cards = cards
            return
        if risk == "medium":
            _set_recommended_action(conclusion, "review_memory_signals")
            conclusion["action_payload"] = {"review_targets": ["memory_signals", "context_slots"]}
        if risk == "high":
            if conflict_count <= 0:
                _set_recommended_action(conclusion, "review_memory_signals")
                conclusion["action_payload"] = {"review_targets": ["memory_signals", "context_slots", "alignment_score"]}
                return
            _set_recommended_action(conclusion, "clarify_memory_conflict")
            conclusion["action_payload"] = {
                "conflict_fields": list(evidence.get("conflict_fields") or []),
                "requires_user_confirmation": True,
            }
            response.clarifying_question = response.clarifying_question or "当前上下文存在冲突。你要继续查找哪个游戏、哪个来源？"
            cards = response.response_cards if isinstance(response.response_cards, dict) else {}
            next_steps = cards.get("next_steps")
            if isinstance(next_steps, list):
                hint = "存在上下文冲突，请先确认目标游戏/来源后再继续检索。"
                if hint not in next_steps:
                    cards["next_steps"] = [hint, *next_steps]
                    response.response_cards = cards
            return
        if planning_score_value is None or planning_score_value >= 0.45:
            return
        if has_online_adaptation_signal:
            _set_recommended_action(conclusion, "expand_online_sources_and_narrow_scope")
            cards = response.response_cards if isinstance(response.response_cards, dict) else {}
            next_steps = cards.get("next_steps")
            if isinstance(next_steps, list):
                candidates = [str(item).strip() for item in (tool_planning.get("expand_online_candidates") or []) if str(item).strip()]
                if not candidates:
                    online_tools = {str(item).strip() for item in (tool_planning.get("online_tools") or []) if str(item).strip()}
                    candidates = [tool for tool in ["nexusmods_search", "loverslab_google"] if tool and tool not in online_tools]
                conclusion["expand_online_candidates"] = candidates
                candidate_details = [
                    {"id": candidate, "label": _source_candidate_label(candidate)} for candidate in candidates
                ]
                conclusion["expand_online_candidates_detail"] = candidate_details
                conclusion["action_payload"] = {
                    "expand_online_candidates": candidate_details,
                    "narrow_scope_fields": ["game", "source", "keywords"],
                }
                if candidates:
                    hint = (
                        "当前在线来源召回不足，建议补充来源或放宽来源限制，并明确游戏/关键词后重试。"
                        f"可扩展来源：{', '.join(candidates)}。"
                    )
                else:
                    hint = "当前在线来源召回不足，建议补充来源或放宽来源限制，并明确游戏/关键词后重试。"
                if hint not in next_steps:
                    cards["next_steps"] = [hint, *next_steps]
                    response.response_cards = cards
            return
        if risk == "medium":
            _set_recommended_action(conclusion, "narrow_query_scope_and_review_memory")
            conclusion["action_payload"] = {
                "narrow_scope_fields": ["game", "source", "keywords"],
                "review_targets": ["memory_signals"],
            }
        else:
            _set_recommended_action(conclusion, "narrow_query_scope")
            conclusion["action_payload"] = {"narrow_scope_fields": ["game", "source", "keywords"]}
        cards = response.response_cards if isinstance(response.response_cards, dict) else {}
        next_steps = cards.get("next_steps")
        if isinstance(next_steps, list):
            hint = "当前需求范围较宽或证据不足，建议补充游戏/来源/关键词后再检索。"
            if response.used_llm:
                return
            if hint not in next_steps:
                cards["next_steps"] = [hint, *next_steps]
                response.response_cards = cards
    finally:
        _set_response_audit(response, audit, conclusion=conclusion, evidence=evidence)


def annotate_action_evidence_consistency(response: AgentChatResponse) -> None:
    audit = _audit_as_dict(response.audit)
    conclusion = audit.get("conclusion") if isinstance(audit.get("conclusion"), dict) else {}
    evidence = audit.get("evidence") if isinstance(audit.get("evidence"), dict) else {}
    recommended_action = str(conclusion.get("recommended_action") or "").strip()
    evidence_sufficiency = str(conclusion.get("evidence_sufficiency") or "").strip()
    consistency_risk = str(conclusion.get("consistency_risk") or "").strip()
    valid = True
    reason = "ok"
    if recommended_action == "collect_more_evidence" and evidence_sufficiency != "insufficient":
        valid = False
        reason = "collect_more_evidence_requires_insufficient_evidence"
    if recommended_action == "clarify_memory_conflict" and consistency_risk != "high":
        valid = False
        reason = "clarify_memory_conflict_requires_high_risk"
    evidence["action_evidence_consistent"] = valid
    evidence["action_evidence_consistency_reason"] = reason
    violations = audit_contract_violations(conclusion=conclusion, evidence=evidence)
    evidence["audit_contract_passed"] = not violations
    evidence["audit_contract_violations"] = violations
    conclusion["contract_status"] = "ok" if not violations else "violated"
    conclusion["contract_violations_count"] = len(violations)
    _set_response_audit(response, audit, conclusion=conclusion, evidence=evidence)


def audit_contract_violations(*, conclusion: dict[str, object], evidence: dict[str, object]) -> list[str]:
    violations: list[str] = []
    recommended_action = str(conclusion.get("recommended_action") or "").strip()
    recommended_action_reason = str(conclusion.get("recommended_action_reason") or "").strip()
    evidence_sufficiency = str(conclusion.get("evidence_sufficiency") or "").strip()
    consistency_risk = str(conclusion.get("consistency_risk") or "").strip()
    if recommended_action == "collect_more_evidence" and evidence_sufficiency != "insufficient":
        violations.append("collect_more_evidence_requires_insufficient_evidence")
    expected_reason = expected_reason_for_action(recommended_action)
    if recommended_action and not recommended_action_reason:
        violations.append("recommended_action_requires_non_empty_reason")
    if recommended_action and expected_reason is None:
        violations.append("recommended_action_reason_mapping_missing")
    if expected_reason is not None and recommended_action_reason != expected_reason:
        violations.append(f"recommended_action_reason_mismatch:{recommended_action}")
    if recommended_action == "clarify_memory_conflict" and consistency_risk != "high":
        violations.append("clarify_memory_conflict_requires_high_risk")
    if not isinstance(evidence.get("analysis_evidence_coverage"), dict):
        violations.append("analysis_evidence_coverage_missing")
    semantic_trace = evidence.get("semantic_trace") if isinstance(evidence.get("semantic_trace"), dict) else None
    retrieval_decision = evidence.get("retrieval_decision") if isinstance(evidence.get("retrieval_decision"), dict) else {}
    semantic_anchors = retrieval_decision.get("semantic_anchors") if isinstance(retrieval_decision.get("semantic_anchors"), list) else []
    if semantic_anchors:
        if not semantic_trace:
            violations.append("semantic_trace_missing_for_semantic_query")
        else:
            if not isinstance(semantic_trace.get("anchors"), list):
                violations.append("semantic_trace_anchors_invalid")
            if not isinstance(semantic_trace.get("domains"), list):
                violations.append("semantic_trace_domains_invalid")
            if not isinstance(semantic_trace.get("memory_fragment_count"), int):
                violations.append("semantic_trace_memory_fragment_count_invalid")
    return violations


def expected_reason_for_action(action: str) -> str | None:
    return _RECOMMENDED_ACTION_REASON_MAP.get(str(action or "").strip())


def classify_retrieval_reason_group(reason: str) -> str:
    token = str(reason or "").strip().lower()
    if not token:
        return "web"
    if token.startswith("memory_"):
        return "memory"
    if token.startswith("context_") or "context" in token:
        return "context"
    if token.startswith("low_quality_context"):
        return "context"
    if token.startswith("conservative_online_") or "online" in token:
        return "web"
    if token.startswith("semantic_") or "semantic" in token:
        return "semantic"
    return "web"


def _consistency_risk(
    hard_conflict_count: int,
    soft_conflict_count: int,
    *,
    memory_context_alignment_score: float | None = None,
    context_quality_score: float | None = None,
    context_inherit_score: float | None = None,
    context_source: str | None = None,
    topic_shift_detected: bool | None = None,
) -> str:
    if hard_conflict_count >= 1:
        return "high"
    if memory_context_alignment_score is not None and memory_context_alignment_score < 0.35:
        return "high"
    if soft_conflict_count >= 2:
        return "medium"
    if memory_context_alignment_score is not None and memory_context_alignment_score < 0.55:
        return "medium"
    if bool(topic_shift_detected) and (context_inherit_score is not None and context_inherit_score >= 0.45):
        return "medium"
    if (
        str(context_source or "").strip().lower() in {"recent_user", "history_backfill"}
        and context_inherit_score is not None
        and context_inherit_score >= 0.55
        and context_quality_score is not None
        and context_quality_score < 0.2
    ):
        return "medium"
    return "low"


def _memory_context_alignment(
    *,
    hard_conflict_count: int,
    soft_conflict_count: int,
    context_source: str,
    context_quality_score: float | None,
    context_inherit_score: float | None,
    context_inherited: bool | None,
    topic_shift_detected: bool | None,
    preference_stale: bool,
) -> dict[str, object]:
    score = 1.0
    reasons: list[str] = []
    if hard_conflict_count >= 1:
        score -= 0.6
        reasons.append("hard_memory_conflict")
    elif soft_conflict_count >= 1:
        score -= min(0.35, 0.12 * soft_conflict_count)
        reasons.append("soft_memory_conflict")
    if preference_stale:
        score -= 0.2
        reasons.append("stale_preference_memory")
    if (
        bool(context_inherited)
        and context_inherit_score is not None
        and context_inherit_score >= 0.55
        and context_quality_score is not None
        and context_quality_score < 0.2
    ):
        score -= 0.5
        reasons.append("low_quality_context_inherited")
    if bool(topic_shift_detected) and bool(context_inherited):
        score -= 0.2
        reasons.append("topic_shift_with_inheritance")
    if (
        str(context_source).strip().lower() in {"recent_user", "history_backfill"}
        and context_quality_score is not None
        and context_quality_score < 0.12
    ):
        score -= 0.15
        reasons.append("very_low_context_quality")
    bounded = max(0.0, min(score, 1.0))
    if bounded < 0.35:
        decision = "realign_before_retrieval"
    elif bounded < 0.55:
        decision = "review_memory_and_context"
    else:
        decision = "aligned"
    return {
        "score": round(bounded, 3),
        "decision": decision,
        "reasons": reasons,
    }


def _planning_confidence(score: object) -> str:
    try:
        value = float(score)
    except (TypeError, ValueError):
        return "unknown"
    if value < 0.45:
        return "low"
    if value < 0.7:
        return "medium"
    return "high"


def _build_web_search_evidence(retrieval_evidence: list[dict[str, object]]) -> dict[str, object]:
    online_items = [
        item
        for item in retrieval_evidence
        if isinstance(item, dict) and str(item.get("stage") or "").strip() == "online_retrieval"
    ]
    adaptation_items = [
        item
        for item in retrieval_evidence
        if isinstance(item, dict) and str(item.get("stage") or "").strip() == "online_adaptation"
    ]
    if not online_items and not adaptation_items:
        return {}
    tools: set[str] = set()
    tool_statuses: dict[str, str] = {}
    tool_result_counts: dict[str, int] = {}
    succeeded = 0
    skipped = 0
    degraded = 0
    online_count = 0
    for item in online_items:
        tool = str(item.get("tool") or "").strip()
        if tool:
            tools.add(tool)
        status = str(item.get("status") or "").strip().lower()
        try:
            count = int(item.get("count") or 0)
        except (TypeError, ValueError):
            count = 0
        if tool:
            tool_statuses[tool] = status or "unknown"
            tool_result_counts[tool] = count
        if status == "succeeded":
            succeeded += 1
            online_count += count
        elif status == "skipped":
            skipped += 1
        elif status == "degraded":
            degraded += 1
    reasons: list[str] = []
    for item in online_items:
        reason = str(item.get("reason") or "").strip()
        tool = str(item.get("tool") or "").strip()
        status = str(item.get("status") or "").strip().lower()
        if reason:
            reasons.append(reason)
        if tool == "online_gate" and status == "skipped" and not reason:
            reasons.append("online_gate_skipped")
    for item in adaptation_items:
        reason = str(item.get("reason") or "").strip()
        if reason:
            reasons.append(reason)
    if adaptation_items and not online_items:
        tool_statuses["online_gate"] = "skipped"
        tool_result_counts["online_gate"] = 0
        skipped += 1
    unique_reasons = sorted({value for value in reasons if value})
    queried = any(str(item.get("tool") or "").strip() != "online_gate" for item in online_items)
    return {
        "enabled": bool(online_items or adaptation_items),
        "tools": sorted(tools),
        "tool_statuses": tool_statuses,
        "tool_result_counts": tool_result_counts,
        "succeeded_count": succeeded,
        "skipped_count": skipped,
        "degraded_count": degraded,
        "online_result_count": online_count,
        "adaptation_triggered": bool(adaptation_items),
        "queried": queried,
        "trigger_reasons": unique_reasons,
    }


def _build_retrieval_decision_evidence(
    *,
    context_signal: dict[str, object],
    memory_alignment: dict[str, object],
    web_search: dict[str, object],
    understanding_evidence: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    alignment_score = _as_float(memory_alignment.get("score"))
    context_quality = _as_float(context_signal.get("quality_score"))
    context_inherit = _as_float(context_signal.get("inherit_score"))
    web_enabled = bool(web_search.get("enabled"))
    web_queried = bool(web_search.get("queried"))
    reasons: list[str] = []
    reason_groups: dict[str, list[str]] = {"context": [], "memory": [], "web": [], "semantic": []}
    semantic_anchors = _string_list(_understanding_evidence_value(understanding_evidence or [], "semantic_anchors"))
    semantic_domains = _string_list(_understanding_evidence_value(understanding_evidence or [], "semantic_domains"))
    if alignment_score is not None and alignment_score < 0.55:
        reasons.append("memory_context_alignment_low")
        reason_groups["memory"].append("memory_context_alignment_low")
    if context_quality is not None and context_quality < 0.2 and (context_inherit or 0.0) >= 0.55:
        reasons.append("low_quality_context_with_high_inherit")
        reason_groups["context"].append("low_quality_context_with_high_inherit")
    for item in web_search.get("trigger_reasons") or []:
        text = str(item).strip()
        if text:
            reasons.append(text)
            group = classify_retrieval_reason_group(text)
            reason_groups[group].append(text)
    if semantic_anchors:
        reasons.append("semantic_anchors_detected")
        reason_groups["semantic"].append("semantic_anchors_detected")
    for domain in semantic_domains:
        token = str(domain).strip().lower()
        if not token:
            continue
        reason = f"semantic_domain_{token}"
        reasons.append(reason)
        reason_groups["semantic"].append(reason)
    mode = "local_only"
    if web_enabled and web_queried:
        mode = "local_plus_web"
    elif web_enabled:
        mode = "web_adaptation_only"
    return {
        "mode": mode,
        "web_enabled": web_enabled,
        "web_queried": web_queried,
        "alignment_score": alignment_score,
        "context_quality_score": context_quality,
        "context_inherit_score": context_inherit,
        "semantic_anchors": semantic_anchors,
        "semantic_domains": semantic_domains,
        "reasons": sorted(set(reasons)),
        "reason_groups": {
            "context": sorted(set(reason_groups["context"])),
            "memory": sorted(set(reason_groups["memory"])),
            "web": sorted(set(reason_groups["web"])),
            "semantic": sorted(set(reason_groups["semantic"])),
        },
    }


def _build_semantic_trace_evidence(understanding_evidence: list[dict[str, object]]) -> dict[str, object]:
    anchors = _string_list(_understanding_evidence_value(understanding_evidence, "semantic_anchors"))
    context_anchors = _string_list(_understanding_evidence_value(understanding_evidence, "context_semantic_anchors"))
    domains = _string_list(_understanding_evidence_value(understanding_evidence, "semantic_domains"))
    memory_related_fragments: list[str] = []
    for field in ("semantic_anchors", "semantic_domains"):
        for item in understanding_evidence:
            if not isinstance(item, dict):
                continue
            if str(item.get("field") or "").strip() != field:
                continue
            for fragment in item.get("related_fragments") or []:
                token = str(fragment or "").strip()
                if token.startswith("m_"):
                    memory_related_fragments.append(token)
    overlap = {item.lower() for item in anchors} & {item.lower() for item in context_anchors}
    return {
        "anchors": anchors,
        "context_anchors": context_anchors,
        "domains": domains,
        "inherited_anchor_overlap": len(overlap),
        "memory_fragment_count": len(sorted(set(memory_related_fragments))),
    }


def _build_analysis_evidence_coverage(
    analysis: dict[str, object],
    understanding_evidence: list[dict[str, object]],
) -> dict[str, object]:
    field_fragments: dict[str, list[str]] = {}
    for item in understanding_evidence:
        if not isinstance(item, dict):
            continue
        field = str(item.get("field") or "").strip()
        fragment_id = str(item.get("fragment_id") or "").strip()
        if not field or not fragment_id:
            continue
        field_fragments.setdefault(field, []).append(fragment_id)
    required_fields = ["intent", "confidence", "slots"]
    if analysis.get("semantic_anchors") not in (None, "", [], {}):
        required_fields.append("semantic_anchors")
    if analysis.get("semantic_domains") not in (None, "", [], {}):
        required_fields.append("semantic_domains")
    missing_fields: list[str] = []
    field_map: dict[str, list[str]] = {}
    for field in required_fields:
        fragments = []
        if field == "slots":
            for slot_name in (analysis.get("slots") or {}):
                fragments.extend(field_fragments.get(str(slot_name), []))
        else:
            fragments.extend(field_fragments.get(field, []))
        unique_fragments = sorted({str(value).strip() for value in fragments if str(value).strip()})
        if analysis.get(field) not in (None, "", {}, []) and not unique_fragments:
            missing_fields.append(field)
        field_map[field] = unique_fragments
    covered = len(
        [field for field in required_fields if not (analysis.get(field) not in (None, "", {}, []) and field in missing_fields)]
    )
    coverage_ratio = covered / len(required_fields) if required_fields else 1.0
    return {
        "required_fields": required_fields,
        "covered_fields": covered,
        "coverage_ratio": round(coverage_ratio, 3),
        "missing_fields": missing_fields,
        "field_fragments": field_map,
    }


def _extract_planning_evidence(tool_plan: object | None) -> dict[str, object]:
    if not isinstance(tool_plan, dict):
        return {}
    planning = tool_plan.get("planning_evidence")
    if not isinstance(planning, dict):
        return {}
    return {
        "score": planning.get("score"),
        "strategy": planning.get("strategy"),
        "known_slot_count": planning.get("known_slot_count"),
        "should_clarify": planning.get("should_clarify"),
        "conservative_mode": planning.get("conservative_mode"),
        "semantic_anchors": list(planning.get("semantic_anchors") or []),
        "semantic_domains": list(planning.get("semantic_domains") or []),
        "expand_online_candidates": list(planning.get("expand_online_candidates") or []),
        "local_tools": list(planning.get("local_tools") or []),
        "online_tools": list(planning.get("online_tools") or []),
        "degraded_reasons": list(planning.get("degraded_reasons") or []),
    }


def _audit_as_dict(value: object) -> dict[str, object]:
    if isinstance(value, AgentAudit):
        return value.model_dump(mode="python")
    if isinstance(value, dict):
        return dict(value)
    return {}


def _set_response_audit(
    response: AgentChatResponse,
    audit: dict[str, object],
    *,
    conclusion: dict[str, object],
    evidence: dict[str, object],
) -> None:
    audit["conclusion"] = conclusion
    audit["evidence"] = evidence
    response.audit = AgentAudit.model_validate(audit)


def _source_candidate_label(candidate: str) -> str:
    key = str(candidate or "").strip().lower()
    if "nexus" in key:
        return "NexusMods"
    if "lovers" in key:
        return "LoversLab"
    return str(candidate or "").strip()


def _conclusion_evidence_sufficiency(*, analysis: dict[str, object], evidence: dict[str, object]) -> str:
    coverage = evidence.get("analysis_evidence_coverage") if isinstance(evidence.get("analysis_evidence_coverage"), dict) else {}
    try:
        coverage_ratio = float(coverage.get("coverage_ratio") or 0.0)
    except (TypeError, ValueError):
        coverage_ratio = 0.0
    memory_count = int(evidence.get("memory_count") or 0)
    retrieval_count = int(evidence.get("retrieval_count") or 0)
    slots = analysis.get("slots") if isinstance(analysis.get("slots"), dict) else {}
    slot_count = len(slots)
    if coverage_ratio < 0.67:
        return "insufficient"
    if slot_count == 0 and retrieval_count == 0:
        return "insufficient"
    if memory_count > 0 or retrieval_count > 0:
        return "sufficient"
    return "partial"


def _set_recommended_action(conclusion: dict[str, object], action: str) -> None:
    conclusion["recommended_action"] = action
    conclusion["recommended_action_reason"] = expected_reason_for_action(action) or ""


def _understanding_evidence_value(understanding_evidence: list[dict[str, object]], field: str) -> object:
    key = str(field or "").strip()
    for item in understanding_evidence:
        if not isinstance(item, dict):
            continue
        if str(item.get("field") or "").strip() == key:
            return item.get("value")
    return None


def _string_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def _as_float(value: object) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_bool(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes"}:
            return True
        if lowered in {"false", "0", "no"}:
            return False
    return None
