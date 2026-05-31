import logging
import os
from dataclasses import dataclass, field
from typing import Any

from app.services.agent.list_utils import unique_text
from app.services.agent.planning.query_intent import (
    detect_adult_constraint,
    detect_query_intent,
    infer_source_constraints,
    is_open_discovery_query,
)
from app.services.agent.schemas import AgentHistoryItem
from app.services.agent.semantic_brain.semantic_strategy_prompt import (
    build_semantic_strategy_prompt,
    build_semantic_strategy_repair_prompt,
)
from app.services.agent.semantic_brain.semantic_strategy_schema import (
    SemanticHardFilters,
    SemanticStrategy,
    SemanticStrategyResult,
)
from app.services.agent.semantic_search import base_keywords
from app.services.llm_client import create_llm_client
from app.utils.json import json_object_from_text

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SemanticStrategyInput:
    query: str
    history: list[AgentHistoryItem] = field(default_factory=list)
    active_constraints: dict[str, Any] = field(default_factory=dict)
    last_query_context: dict[str, Any] = field(default_factory=dict)
    memory_context: dict[str, Any] = field(default_factory=dict)
    shown_mod_titles: list[str] = field(default_factory=list)
    llm_available: bool = False
    provider: str = ""
    api_key: str = ""
    base_url: str = ""
    model: str = ""
    evidence_id: str = ""


class SemanticStrategyTool:
    """让 LLM 先决定语义策略；规则 fallback 只提供低保，不重新扩展成复杂规划器。"""

    name = "semantic_strategy"

    async def run(self, tool_input: SemanticStrategyInput) -> SemanticStrategyResult:
        evidence_id = str(tool_input.evidence_id or "").strip()
        if not _enabled():
            result = SemanticStrategyResult(
                strategy=_fallback_strategy(tool_input),
                source="disabled",
                status="disabled",
                fallback_reason="feature_disabled",
            )
            result.evidence.append(_evidence(result, evidence_id=evidence_id))
            return result
        if tool_input.llm_available and tool_input.provider and tool_input.model:
            try:
                result = await _run_llm_strategy(tool_input)
            except Exception as exc:  # pragma: no cover - defensive degradation path
                logger.info(
                    "agent.semantic_strategy status=degraded reason=%s evidence_id=%s",
                    type(exc).__name__,
                    evidence_id,
                )
                result = None
            if result is not None:
                result.evidence.append(_evidence(result, evidence_id=evidence_id))
                return result
        fallback = SemanticStrategyResult(
            strategy=_fallback_strategy(tool_input),
            source="fallback",
            status="fallback",
            fallback_reason="llm_unavailable_or_invalid",
        )
        fallback.evidence.append(_evidence(fallback, evidence_id=evidence_id))
        return fallback


async def _run_llm_strategy(tool_input: SemanticStrategyInput) -> SemanticStrategyResult | None:
    prompt = build_semantic_strategy_prompt(
        query=tool_input.query,
        history=tool_input.history,
        active_constraints=tool_input.active_constraints,
        last_query_context=tool_input.last_query_context,
        memory_context=tool_input.memory_context,
        shown_mod_titles=tool_input.shown_mod_titles,
    )
    client = create_llm_client(
        provider=tool_input.provider,
        api_key=tool_input.api_key,
        base_url=tool_input.base_url,
    )
    content = await client.chat(prompt, model=tool_input.model, max_tokens=900, request_timeout=25.0)
    parsed = json_object_from_text(content)
    strategy = _strategy_from_json(parsed)
    if strategy is not None:
        logger.info(
            "agent.semantic_strategy status=succeeded source=llm task_type=%s strategy=%s evidence_id=%s",
            strategy.task_type,
            strategy.strategy,
            tool_input.evidence_id,
        )
        return SemanticStrategyResult(
            strategy=strategy,
            source="llm",
            used_llm=True,
            status="succeeded",
            raw_output=content,
        )
    repair_text = await client.chat(
        build_semantic_strategy_repair_prompt(original_prompt=prompt, invalid_output=content),
        model=tool_input.model,
        max_tokens=900,
        request_timeout=25.0,
    )
    repaired = _strategy_from_json(json_object_from_text(repair_text))
    if repaired is None:
        logger.info(
            "agent.semantic_strategy status=degraded reason=invalid_llm_json evidence_id=%s",
            tool_input.evidence_id,
        )
        return None
    logger.info(
        "agent.semantic_strategy status=succeeded source=llm_repair task_type=%s strategy=%s evidence_id=%s",
        repaired.task_type,
        repaired.strategy,
        tool_input.evidence_id,
    )
    return SemanticStrategyResult(
        strategy=repaired,
        source="llm",
        used_llm=True,
        status="succeeded",
        raw_output=repair_text,
    )


def _strategy_from_json(value: dict | None) -> SemanticStrategy | None:
    if not isinstance(value, dict):
        return None
    try:
        return SemanticStrategy.model_validate(value)
    except Exception:
        return None


def _fallback_strategy(tool_input: SemanticStrategyInput) -> SemanticStrategy:
    query = str(tool_input.query or "")
    intent = detect_query_intent(query)
    task_type = _task_type_from_intent(query, intent)
    strategy_map = {
        "exact_lookup": "exact_then_explain",
        "open_discovery": "broad_then_judge",
        "comparative": "compare_known_and_fetch_missing",
        "advisory": "evidence_then_advice",
        "preference": "memory_summary",
        "unknown": "clarify_first",
    }
    answer_shape_map = {
        "exact_lookup": "direct_lookup",
        "open_discovery": "grouped_recommendation",
        "comparative": "comparison_table",
        "advisory": "risk_advice",
        "preference": "memory_summary",
        "unknown": "clarify_first",
    }
    hard_filters = _fallback_hard_filters(tool_input)
    core_terms = base_keywords(query)[:6]
    soft_signals = _fallback_soft_signals(tool_input, core_terms)
    return SemanticStrategy(
        task_type=task_type,
        user_goal=query.strip()[:500],
        strategy=strategy_map[task_type],
        hard_filters=hard_filters,
        core_terms=core_terms,
        soft_signals=soft_signals,
        ranking_goal=_ranking_goal(task_type, query),
        answer_shape=answer_shape_map[task_type],
        confidence=0.55 if task_type != "unknown" else 0.25,
        reason="fallback_strategy",
    )


def _task_type_from_intent(query: str, intent: str) -> str:
    lowered = query.lower()
    if intent == "install_risk":
        return "advisory"
    if intent in {"comparison", "alternative"} or any(marker in lowered for marker in ["对比", "比较", "替代", "哪个", "第二个"]):
        return "comparative"
    if any(marker in lowered for marker in ["安装", "兼容", "依赖", "风险", "前置"]):
        return "advisory"
    if intent == "preference_summary" or any(marker in lowered for marker in ["偏好", "画像", "收藏"]):
        return "preference"
    if _looks_like_exact_lookup(query):
        return "exact_lookup"
    if is_open_discovery_query(query) or intent in {"search", "recent", "game", "author"}:
        return "open_discovery"
    return "unknown"


def _looks_like_exact_lookup(query: str) -> bool:
    lowered = query.lower()
    return "http://" in lowered or "https://" in lowered or "external_id" in lowered or "mod:" in lowered


def _fallback_hard_filters(tool_input: SemanticStrategyInput) -> SemanticHardFilters:
    constraints = tool_input.active_constraints or {}
    sources = infer_source_constraints(tool_input.query).get("sources") or []
    excluded_sources = infer_source_constraints(tool_input.query).get("excluded_sources") or []
    source = sources[0] if sources else str(constraints.get("source") or "").strip() or None
    return SemanticHardFilters(
        game=str(constraints.get("game") or "").strip() or None,
        source=source,
        adult_content=detect_adult_constraint(tool_input.query)
        if detect_adult_constraint(tool_input.query) is not None
        else constraints.get("adult_content"),
        excluded_sources=excluded_sources,
    )


def _fallback_soft_signals(tool_input: SemanticStrategyInput, core_terms: list[str]) -> list[str]:
    signals: list[str] = []
    for term in core_terms:
        signals.append(term)
    context = tool_input.last_query_context if isinstance(tool_input.last_query_context, dict) else {}
    for key in ("semantic_anchors", "semantic_domains", "keywords"):
        value = context.get(key)
        if isinstance(value, list):
            signals.extend(str(item).strip() for item in value if str(item).strip())
    if tool_input.shown_mod_titles:
        signals.extend(str(title).strip() for title in tool_input.shown_mod_titles[:5] if str(title).strip())
    return unique_text(signals, limit=16)


def _ranking_goal(task_type: str, query: str) -> str:
    if task_type == "open_discovery":
        return "优先保留能直接满足用户语义目标的候选，再按用途分组。"
    if task_type == "comparative":
        return "优先比较用户已指代或已展示的 MOD，并补充缺失证据。"
    if task_type == "advisory":
        return "优先保留能支持安装、兼容、依赖和风险判断的候选。"
    if task_type == "exact_lookup":
        return "优先精确命中用户指定标题、URL 或 ID。"
    if task_type == "preference":
        return "优先总结用户长期偏好和收藏画像。"
    return f"先澄清用户目标：{query[:120]}"


def _evidence(result: SemanticStrategyResult, *, evidence_id: str) -> dict[str, Any]:
    item: dict[str, Any] = {
        "fragment_id": "u_semantic_strategy",
        "field": "semantic_strategy",
        "source": result.source,
        "value": result.strategy.model_dump(mode="python"),
    }
    if evidence_id:
        item["evidence_id"] = evidence_id
    if result.fallback_reason:
        item["reason"] = result.fallback_reason
    return item


def _enabled() -> bool:
    raw = os.getenv("MW_AGENT_SEMANTIC_STRATEGY_ENABLED", "true").strip().lower()
    return raw not in {"0", "false", "no", "off"}
