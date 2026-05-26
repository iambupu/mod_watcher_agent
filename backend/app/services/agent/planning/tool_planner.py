from typing import Any, TypedDict


class ToolPlan(TypedDict):
    steps: list[dict[str, Any]]
    fallback_steps: list[dict[str, Any]]
    parallel_groups: list[dict[str, Any]]
    degraded_reasons: list[str]
    planning_evidence: dict[str, Any]


LOCAL_TOOLS = ["structured_sql", "sqlite_fts"]
OPTIONAL_LOCAL_TOOLS = ["qdrant_vector"]
ONLINE_TOOLS = ["nexusmods_search", "loverslab_google"]
ALLOWED_TOOLS = {*LOCAL_TOOLS, *OPTIONAL_LOCAL_TOOLS, *ONLINE_TOOLS}
DEFAULT_TOOL_CAPABILITIES = {"qdrant_vector": False, "nexusmods_search": True, "loverslab_google": True}


def default_tool_capabilities() -> dict[str, bool]:
    return dict(DEFAULT_TOOL_CAPABILITIES)


def build_tool_plan(
    *,
    query_diagnosis: dict[str, Any],
    preferences: dict[str, Any] | None = None,
    capabilities: dict[str, bool] | None = None,
    local_only: bool = False,
) -> ToolPlan:
    capabilities = capabilities or {}
    diagnosis_confidence = float(query_diagnosis.get("confidence") or 0) if isinstance(query_diagnosis, dict) else 0.0
    should_clarify = bool(query_diagnosis.get("should_clarify")) if isinstance(query_diagnosis, dict) else False
    known_slots = query_diagnosis.get("known_slots") if isinstance(query_diagnosis, dict) else {}
    known_slots = known_slots if isinstance(known_slots, dict) else {}
    semantic_anchors, semantic_domains = _semantic_signals(query_diagnosis)
    degraded_reasons: list[str] = []
    conservative_mode = _should_use_conservative_online_mode(
        diagnosis_confidence=diagnosis_confidence,
        should_clarify=should_clarify,
        known_slots=known_slots,
        semantic_domains=semantic_domains,
    )

    steps = [
        {"tool": "structured_sql", "reason": "先用硬过滤查本地缓存"},
        {"tool": "sqlite_fts", "reason": "使用 SQLite FTS5 进行关键词召回"},
    ]
    local_group_tools = [*LOCAL_TOOLS]
    if capabilities.get("qdrant_vector"):
        steps.append({"tool": "qdrant_vector", "reason": "语义召回可用"})
        local_group_tools.append("qdrant_vector")

    fallback_steps: list[dict[str, Any]] = []
    baseline_online_tools: list[str] = []
    if local_only:
        degraded_reasons.append("local-only 策略已启用，跳过在线工具。")
    else:
        preferred_online_tools = _preferred_online_tools(known_slots, preferences or {}, semantic_domains)
        baseline_online_tools = list(preferred_online_tools)
        if conservative_mode:
            preferred_online_tools = _apply_conservative_online_filter(
                preferred_online_tools,
                known_slots,
                semantic_anchors,
                semantic_domains,
                degraded_reasons,
            )
        for tool in preferred_online_tools:
            if capabilities.get(tool):
                fallback_steps.append({"tool": tool, "group": "online", "reason": "本地结果不足时补查在线来源"})
            else:
                degraded_reasons.append(f"{tool} 不可用，已从工具计划降级。")

    online_group_tools = [step["tool"] for step in fallback_steps]
    groups = [
        {
            "name": "local_retrieval",
            "tools": local_group_tools,
            "max_concurrency": len(local_group_tools),
            "timeout_ms": 2500,
            "required_before": "fusion",
        }
    ]
    if online_group_tools:
        groups.append(
            {
                "name": "online_retrieval",
                "tools": online_group_tools,
                "max_concurrency": min(2, len(online_group_tools)),
                "timeout_ms": 6000,
                "run_when": "local_results_below_threshold",
            }
        )
    planning_evidence = _build_planning_evidence(
        diagnosis_confidence=diagnosis_confidence,
        should_clarify=should_clarify,
        known_slots=known_slots,
        local_group_tools=local_group_tools,
        online_group_tools=online_group_tools,
        degraded_reasons=degraded_reasons,
        capabilities=capabilities,
        local_only=local_only,
        conservative_mode=conservative_mode,
        baseline_online_tools=baseline_online_tools,
        semantic_anchors=semantic_anchors,
        semantic_domains=semantic_domains,
    )
    return {
        "steps": _whitelist(steps),
        "fallback_steps": _whitelist(fallback_steps),
        "parallel_groups": groups,
        "degraded_reasons": degraded_reasons,
        "planning_evidence": planning_evidence,
    }


def _preferred_online_tools(
    known_slots: dict[str, Any],
    preferences: dict[str, Any],
    semantic_domains: list[str],
) -> list[str]:
    sources = []
    source = str(known_slots.get("source") or "").strip().lower()
    if source:
        sources.append(source)
    favorite_summary = preferences.get("favorite_summary") if isinstance(preferences, dict) else None
    if isinstance(favorite_summary, dict):
        sources.extend(str(item).strip().lower() for item in favorite_summary.get("top_sources", []))
    tools = []
    if "nexusmods" in sources:
        tools.append("nexusmods_search")
    if "loverslab" in sources or known_slots.get("adult_content") is True:
        tools.append("loverslab_google")
    if "source_scope" in semantic_domains or "content_type" in semantic_domains:
        tools.append("loverslab_google")
    if not tools:
        tools = ["nexusmods_search", "loverslab_google"]
    return list(dict.fromkeys(tools))


def _whitelist(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [step for step in steps if step.get("tool") in ALLOWED_TOOLS]


def _build_planning_evidence(
    *,
    diagnosis_confidence: float,
    should_clarify: bool,
    known_slots: dict[str, Any],
    local_group_tools: list[str],
    online_group_tools: list[str],
    degraded_reasons: list[str],
    capabilities: dict[str, bool],
    local_only: bool,
    conservative_mode: bool,
    baseline_online_tools: list[str],
    semantic_anchors: list[str],
    semantic_domains: list[str],
) -> dict[str, Any]:
    score = _estimate_planning_score(
        diagnosis_confidence=diagnosis_confidence,
        should_clarify=should_clarify,
        known_slots=known_slots,
        degraded_reasons=degraded_reasons,
        capabilities=capabilities,
    )
    if local_only:
        strategy = "local_only"
    elif not online_group_tools:
        strategy = "local_first_no_online_fallback"
    else:
        strategy = "local_first_with_online_fallback"
    return {
        "score": score,
        "strategy": strategy,
        "known_slot_count": len([k for k, v in known_slots.items() if v not in (None, "", [])]),
        "should_clarify": should_clarify,
        "local_tools": list(local_group_tools),
        "online_tools": list(online_group_tools),
        "degraded_reasons": list(degraded_reasons),
        "conservative_mode": conservative_mode,
        "expand_online_candidates": [
            tool for tool in baseline_online_tools if tool not in set(online_group_tools)
        ],
        "semantic_anchors": list(semantic_anchors),
        "semantic_domains": list(semantic_domains),
    }


def _estimate_planning_score(
    *,
    diagnosis_confidence: float,
    should_clarify: bool,
    known_slots: dict[str, Any],
    degraded_reasons: list[str],
    capabilities: dict[str, bool],
) -> float:
    score = 0.4
    score += min(max(diagnosis_confidence, 0.0), 1.0) * 0.35
    score += min(len([k for k, v in known_slots.items() if v not in (None, "", [])]), 4) * 0.06
    if should_clarify:
        score -= 0.12
    if degraded_reasons:
        score -= min(0.2, 0.08 * len(degraded_reasons))
    if capabilities.get("qdrant_vector"):
        score += 0.05
    return round(min(max(score, 0.0), 1.0), 3)


def _should_use_conservative_online_mode(
    *,
    diagnosis_confidence: float,
    should_clarify: bool,
    known_slots: dict[str, Any],
    semantic_domains: list[str],
) -> bool:
    if "source_scope" in semantic_domains or "mechanics" in semantic_domains:
        return False
    if known_slots.get("source"):
        return False
    if known_slots.get("adult_content") is True:
        return False
    if should_clarify:
        return True
    if diagnosis_confidence < 0.5:
        return True
    known_slot_count = len([k for k, v in known_slots.items() if v not in (None, "", [])])
    return known_slot_count == 0


def _apply_conservative_online_filter(
    preferred_online_tools: list[str],
    known_slots: dict[str, Any],
    semantic_anchors: list[str],
    semantic_domains: list[str],
    degraded_reasons: list[str],
) -> list[str]:
    if not preferred_online_tools:
        return []
    if known_slots.get("adult_content") is True:
        return preferred_online_tools
    if "source_scope" in semantic_domains or "mechanics" in semantic_domains:
        return preferred_online_tools
    if "framework" in semantic_anchors and "loverslab_google" in preferred_online_tools:
        return preferred_online_tools
    if "nexusmods_search" in preferred_online_tools and "loverslab_google" in preferred_online_tools:
        degraded_reasons.append("规划置信度较低，在线阶段先收窄到 nexusmods_search。")
        return ["nexusmods_search"]
    return preferred_online_tools


def _semantic_signals(query_diagnosis: dict[str, Any]) -> tuple[list[str], list[str]]:
    understanding = query_diagnosis.get("understanding") if isinstance(query_diagnosis, dict) else {}
    evidence = understanding.get("evidence") if isinstance(understanding, dict) else []
    anchors: list[str] = []
    domains: list[str] = []
    if isinstance(evidence, list):
        for item in evidence:
            if not isinstance(item, dict):
                continue
            field = str(item.get("field") or "").strip()
            value = item.get("value")
            if field == "semantic_anchors" and isinstance(value, list):
                anchors.extend(str(v).strip() for v in value if str(v).strip())
            if field == "semantic_domains" and isinstance(value, list):
                domains.extend(str(v).strip() for v in value if str(v).strip())
    return list(dict.fromkeys(anchors)), list(dict.fromkeys(domains))
