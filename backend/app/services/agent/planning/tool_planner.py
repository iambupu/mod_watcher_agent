from typing import Any, TypedDict

from app.services.agent.slot_aliases import normalize_source_alias
from app.utils.boolean import parse_bool
from app.utils.numeric import safe_float


class ToolPlan(TypedDict):
    steps: list[dict[str, Any]]
    online_steps: list[dict[str, Any]]
    parallel_groups: list[dict[str, Any]]
    degraded_reasons: list[str]
    tool_policy_evidence: dict[str, Any]


LOCAL_TOOLS = ["structured_sql", "sqlite_fts"]
ONLINE_TOOLS = ["nexusmods_search", "loverslab_google"]
ALLOWED_TOOLS = {*LOCAL_TOOLS, *ONLINE_TOOLS}
DEFAULT_TOOL_CAPABILITIES = {"nexusmods_search": True, "loverslab_google": True}


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
    diagnosis_confidence = safe_float(query_diagnosis.get("confidence")) if isinstance(query_diagnosis, dict) else 0.0
    should_clarify = parse_bool(query_diagnosis.get("should_clarify")) if isinstance(query_diagnosis, dict) else False
    known_slots = query_diagnosis.get("known_slots") if isinstance(query_diagnosis, dict) else {}
    known_slots = known_slots if isinstance(known_slots, dict) else {}
    semantic_strategy = _semantic_strategy(query_diagnosis)
    tool_policy = _tool_policy_for_semantic_strategy(semantic_strategy)
    semantic_anchors, semantic_domains = _semantic_signals(query_diagnosis)
    degraded_reasons: list[str] = []
    policy_recall_mode = str(tool_policy.get("online_recall_mode") or "").strip()
    if not policy_recall_mode:
        narrow_online_recall = _should_use_narrow_online_recall(
            diagnosis_confidence=diagnosis_confidence,
            should_clarify=should_clarify,
            known_slots=known_slots,
            semantic_domains=semantic_domains,
        )
    else:
        narrow_online_recall = policy_recall_mode == "narrow"

    steps = [
        {"tool": "structured_sql", "reason": "先用硬过滤查本地缓存"},
        {"tool": "sqlite_fts", "reason": "使用 SQLite FTS5 进行关键词召回"},
    ]
    local_group_tools = [*LOCAL_TOOLS]

    online_steps: list[dict[str, Any]] = []
    baseline_online_tools: list[str] = []
    if local_only:
        degraded_reasons.append("local-only 策略已启用，跳过在线工具。")
    else:
        preferred_online_tools = _preferred_online_tools(known_slots, preferences or {}, semantic_domains, tool_policy)
        baseline_online_tools = list(preferred_online_tools)
        if narrow_online_recall and not tool_policy.get("force_online"):
            preferred_online_tools = _apply_narrow_online_filter(
                preferred_online_tools,
                known_slots,
                semantic_anchors,
                semantic_domains,
                degraded_reasons,
            )
        for tool in preferred_online_tools:
            if capabilities.get(tool):
                online_steps.append({"tool": tool, "group": "online", "reason": "扩大在线候选池"})
            else:
                degraded_reasons.append(f"{tool} 不可用，已从工具计划降级。")

    steps = _whitelist(steps)
    online_steps = _whitelist(online_steps)
    local_group_tools = [tool for tool in local_group_tools if tool in ALLOWED_TOOLS]
    online_group_tools = [step["tool"] for step in online_steps]
    groups = _build_parallel_groups(local_group_tools, online_group_tools)
    tool_policy_evidence = _build_tool_policy_evidence(
        diagnosis_confidence=diagnosis_confidence,
        should_clarify=should_clarify,
        known_slots=known_slots,
        local_group_tools=local_group_tools,
        online_group_tools=online_group_tools,
        degraded_reasons=degraded_reasons,
        local_only=local_only,
        narrow_online_recall=narrow_online_recall,
        baseline_online_tools=baseline_online_tools,
        semantic_anchors=semantic_anchors,
        semantic_domains=semantic_domains,
        tool_policy=tool_policy,
    )
    return {
        "steps": steps,
        "online_steps": online_steps,
        "parallel_groups": groups,
        "degraded_reasons": degraded_reasons,
        "tool_policy_evidence": tool_policy_evidence,
    }


def _build_parallel_groups(local_group_tools: list[str], online_group_tools: list[str]) -> list[dict[str, Any]]:
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
    return groups


def _preferred_online_tools(
    known_slots: dict[str, Any],
    preferences: dict[str, Any],
    semantic_domains: list[str],
    tool_policy: dict[str, Any] | None = None,
) -> list[str]:
    tool_policy = tool_policy or {}
    if tool_policy.get("suppress_online"):
        return []
    policy_tools = [str(tool).strip() for tool in tool_policy.get("online_tools", []) if str(tool).strip()]
    if policy_tools:
        return policy_tools
    explicit_source = str(known_slots.get("source") or "").strip().lower()
    sources = []
    if explicit_source:
        sources.append(explicit_source)
    favorite_summary = preferences.get("favorite_summary") if isinstance(preferences, dict) else None
    if not explicit_source and isinstance(favorite_summary, dict):
        sources.extend(str(item).strip().lower() for item in favorite_summary.get("top_sources", []))
    tools = []
    if "nexusmods" in sources:
        tools.append("nexusmods_search")
    if "loverslab" in sources or known_slots.get("adult_content") is True:
        tools.append("loverslab_google")
    if explicit_source:
        return list(dict.fromkeys(tools))
    if "source_scope" in semantic_domains:
        tools.append("loverslab_google")
    if tools or "content_type" in semantic_domains or "mechanics" in semantic_domains:
        tools.extend(["nexusmods_search", "loverslab_google"])
    else:
        tools = ["nexusmods_search", "loverslab_google"]
    return list(dict.fromkeys(tools))


def _tool_policy_for_semantic_strategy(strategy: dict[str, Any]) -> dict[str, Any]:
    task_type = str(strategy.get("task_type") or "").strip()
    source = normalize_source_alias(
        ((strategy.get("hard_filters") or {}) if isinstance(strategy.get("hard_filters"), dict) else {}).get("source")
    )
    if source == "nexusmods":
        source_tools = ["nexusmods_search"]
    elif source == "loverslab":
        source_tools = ["loverslab_google"]
    else:
        source_tools = []
    # 这里是 SemanticStrategy 到工具能力的固定映射，不再重新解释用户语义。
    if task_type == "exact_lookup":
        return {"strategy": "exact_lookup_policy", "online_tools": source_tools, "online_recall_mode": "narrow"}
    if task_type == "open_discovery":
        return {
            "strategy": "open_discovery_broad_recall_policy",
            "online_tools": source_tools or ["nexusmods_search", "loverslab_google"],
            "online_recall_mode": "broad",
            "force_online": True,
        }
    if task_type == "comparative":
        return {"strategy": "comparative_fetch_missing_policy", "online_tools": source_tools or ["nexusmods_search", "loverslab_google"], "online_recall_mode": "broad"}
    if task_type == "advisory":
        return {"strategy": "advisory_evidence_policy", "online_tools": source_tools or ["nexusmods_search", "loverslab_google"], "online_recall_mode": "broad"}
    if task_type == "preference":
        return {"strategy": "preference_memory_policy", "online_tools": [], "online_recall_mode": "narrow", "suppress_online": True}
    if task_type == "unknown":
        return {"strategy": "clarify_first_policy", "online_tools": [], "online_recall_mode": "narrow", "suppress_online": True}
    return {"strategy": "semantic_default_policy", "online_tools": []}


def _whitelist(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [step for step in steps if step.get("tool") in ALLOWED_TOOLS]


def _build_tool_policy_evidence(
    *,
    diagnosis_confidence: float,
    should_clarify: bool,
    known_slots: dict[str, Any],
    local_group_tools: list[str],
    online_group_tools: list[str],
    degraded_reasons: list[str],
    local_only: bool,
    narrow_online_recall: bool,
    baseline_online_tools: list[str],
    semantic_anchors: list[str],
    semantic_domains: list[str],
    tool_policy: dict[str, Any],
) -> dict[str, Any]:
    score = _estimate_tool_policy_score(
        diagnosis_confidence=diagnosis_confidence,
        should_clarify=should_clarify,
        known_slots=known_slots,
        degraded_reasons=degraded_reasons,
    )
    if local_only:
        strategy = "local_only"
    else:
        execution_strategy = "local_first" if not online_group_tools else "local_first_with_online"
        strategy = str(tool_policy.get("strategy") or "")
        if not strategy or strategy == "semantic_default_policy":
            strategy = execution_strategy
    return {
        "score": score,
        "strategy": strategy,
        "execution_strategy": "local_only" if local_only else execution_strategy,
        "known_slot_count": len([k for k, v in known_slots.items() if v not in (None, "", [])]),
        "should_clarify": should_clarify,
        "local_tools": list(local_group_tools),
        "online_tools": list(online_group_tools),
        "degraded_reasons": list(degraded_reasons),
        "online_recall_mode": "narrow" if narrow_online_recall else "broad",
        "expand_online_candidates": [
            tool for tool in baseline_online_tools if tool not in set(online_group_tools)
        ],
        "semantic_anchors": list(semantic_anchors),
        "semantic_domains": list(semantic_domains),
        "tool_policy": str(tool_policy.get("strategy") or ""),
    }


def _estimate_tool_policy_score(
    *,
    diagnosis_confidence: float,
    should_clarify: bool,
    known_slots: dict[str, Any],
    degraded_reasons: list[str],
) -> float:
    score = 0.4
    score += min(max(diagnosis_confidence, 0.0), 1.0) * 0.35
    score += min(len([k for k, v in known_slots.items() if v not in (None, "", [])]), 4) * 0.06
    if should_clarify:
        score -= 0.12
    if degraded_reasons:
        score -= min(0.2, 0.08 * len(degraded_reasons))
    return round(min(max(score, 0.0), 1.0), 3)


def _should_use_narrow_online_recall(
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


def _apply_narrow_online_filter(
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
        degraded_reasons.append("工具策略置信度较低，在线阶段先收窄到 nexusmods_search。")
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


def _semantic_strategy(query_diagnosis: dict[str, Any]) -> dict[str, Any]:
    understanding = query_diagnosis.get("understanding") if isinstance(query_diagnosis, dict) else {}
    evidence = understanding.get("evidence") if isinstance(understanding, dict) else []
    if not isinstance(evidence, list):
        return {}
    for item in evidence:
        if not isinstance(item, dict):
            continue
        if item.get("field") == "semantic_strategy" and isinstance(item.get("value"), dict):
            return item["value"]
    return {}
