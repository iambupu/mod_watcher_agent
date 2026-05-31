import re
from typing import Any

from app.services.agent.list_utils import string_list
from app.services.agent.planning.open_discovery_policy import apply_open_discovery_executor_policy
from app.services.agent.planning.semantic_signals import anchor_domains, extract_semantic_anchors
from app.services.agent.semantic_brain.semantic_strategy_schema import SemanticStrategyResult
from app.services.agent.semantic_inference import canonical_semantic_token
from app.services.agent.semantic_search import base_keywords, semantic_query_from_anchors
from app.utils.boolean import parse_bool


def attach_semantic_strategy_to_query_plan(
    query_plan: dict[str, Any],
    result: SemanticStrategyResult,
) -> dict[str, Any]:
    """把 SemanticStrategy 转成 executor 可消费的 query_plan 字段。"""
    merged = dict(query_plan or {})
    strategy = result.strategy.model_dump(mode="python")
    # SemanticStrategy 是主决策对象；query_plan 只作为 executor 输入承载检索字段。
    merged["_agent_query_plan_role"] = "executor_query"
    merged["_agent_semantic_strategy_primary"] = True
    _apply_strategy_core(merged, strategy, used_llm=result.used_llm)
    merged["_agent_semantic_strategy"] = result.strategy.model_dump(mode="python")
    merged["_agent_semantic_strategy_source"] = result.source
    merged["_agent_semantic_strategy_status"] = result.status
    merged["_agent_semantic_strategy_used_llm"] = result.used_llm
    if result.fallback_reason:
        merged["_agent_semantic_strategy_fallback_reason"] = result.fallback_reason
    return merged


def _apply_strategy_core(plan: dict[str, Any], strategy: dict[str, Any], *, used_llm: bool) -> None:
    task_type = str(strategy.get("task_type") or "").strip()
    retrieval_strategy = str(strategy.get("strategy") or "").strip()
    hard_filters = strategy.get("hard_filters") if isinstance(strategy.get("hard_filters"), dict) else {}
    core_terms = string_list(strategy.get("core_terms"), limit=20)
    soft_signals = string_list(strategy.get("soft_signals"), limit=20)

    if core_terms and (used_llm or not plan.get("keywords")):
        core_terms = _constrain_llm_terms(core_terms, strategy, plan) if used_llm else core_terms
        if not core_terms:
            # 避免覆盖为非法/脱离问题的关键词，保留原有可用关键词。
            core_terms = string_list(plan.get("keywords"))
        if not core_terms:
            return
        # core_terms 是 LLM 对当前任务主体的表达；旧 keywords 只作为 executor 兼容字段承载它。
        plan["keywords"] = core_terms
    if used_llm:
        soft_signals = _constrain_llm_terms(soft_signals, strategy, plan)
    if used_llm:
        _apply_hard_filter(plan, "game", "games", hard_filters)
        _apply_hard_filter(plan, "source", "sources", hard_filters)
    for field in ("adult_content", "exact_title", "external_id", "source_url"):
        if hard_filters.get(field) is not None and (used_llm or field in {"exact_title", "external_id", "source_url"}):
            plan[field] = hard_filters[field]
    for field in ("excluded_keywords", "excluded_sources"):
        values = string_list(hard_filters.get(field), limit=20)
        if field == "excluded_keywords":
            values = _drop_core_term_exclusions(values, core_terms)
        if values:
            plan[field] = values

    plan["_agent_semantic_task_type"] = task_type
    plan["_agent_semantic_retrieval_strategy"] = retrieval_strategy
    plan["_agent_semantic_soft_signals"] = soft_signals
    plan["_agent_semantic_ranking_goal"] = str(strategy.get("ranking_goal") or "").strip()
    plan["_agent_answer_shape"] = str(strategy.get("answer_shape") or "").strip()
    _attach_semantic_anchors(plan, strategy, core_terms)

    if task_type:
        plan["intent"] = _intent_for_task_type(task_type, fallback=str(plan.get("intent") or "search"))
    should_apply_open_discovery = (
        (task_type == "open_discovery" or retrieval_strategy == "broad_then_judge")
        and (used_llm or parse_bool(plan.get("open_discovery")))
    )
    if should_apply_open_discovery:
        apply_open_discovery_executor_policy(plan, soft_signals=soft_signals)
    elif task_type == "exact_lookup":
        plan["open_discovery"] = False
        plan["retrieval_mode"] = "filtered"
    elif task_type == "preference":
        plan.setdefault("open_discovery", False)


def _apply_hard_filter(
    plan: dict[str, Any],
    strategy_field: str,
    plan_field: str,
    hard_filters: dict[str, Any],
) -> None:
    value = str(hard_filters.get(strategy_field) or "").strip()
    if value:
        plan[plan_field] = [value]


def _attach_semantic_anchors(plan: dict[str, Any], strategy: dict[str, Any], core_terms: list[str]) -> None:
    if plan.get("_agent_ranking_semantic_anchors"):
        return
    user_goal = str(strategy.get("user_goal") or "").strip()
    anchors = extract_semantic_anchors(user_goal, core_terms or string_list(plan.get("keywords"), limit=20))
    if not anchors:
        return
    plan["_agent_ranking_semantic_anchors"] = anchors
    plan["_agent_ranking_semantic_domains"] = anchor_domains(anchors)


def _intent_for_task_type(task_type: str, *, fallback: str) -> str:
    if task_type == "comparative" and fallback in {"alternative", "comparison"}:
        return fallback
    mapping = {
        "exact_lookup": "search",
        "open_discovery": "search",
        "comparative": "comparison",
        "advisory": "install_risk",
        "preference": "preference_summary",
        "unknown": "unknown",
    }
    return mapping.get(task_type, fallback)


def _drop_core_term_exclusions(values: list[str], core_terms: list[str]) -> list[str]:
    core_keys = {value.lower() for value in core_terms}
    return [value for value in values if value.lower() not in core_keys]


def _constrain_llm_terms(
    terms: list[str],
    strategy: dict[str, Any],
    plan: dict[str, Any],
) -> list[str]:
    user_goal = str(strategy.get("user_goal") or "").strip()
    allowed = _grounded_terms_for_plan(plan, user_goal)
    if not allowed:
        return terms
    constrained = [term for term in string_list(terms) if _is_grounded_term(_normalize_term(term), allowed)]
    return constrained


def _is_grounded_term(term_norm: str, allowed_terms: set[str]) -> bool:
    if not term_norm:
        return False
    return term_norm in allowed_terms or canonical_semantic_term(term_norm) in allowed_terms


def canonical_semantic_term(term_norm: str) -> str:
    term = str(term_norm or "").strip().lower()
    if not term:
        return term
    mapped = canonical_semantic_token(term)
    if mapped:
        return mapped
    # 仅做低风险词形归一化，避免把普通词误切短（如 boss -> bos）。
    if re.fullmatch(r"[a-z0-9]+", term):
        if term.endswith("s") and len(term) > 4 and not term.endswith(("ss", "us", "is", "es")):
            return term[:-1]
        if term.endswith("ed") and len(term) > 4:
            return term[:-2]
    return term


def _grounded_terms_for_plan(plan: dict[str, Any], user_goal: str) -> set[str]:
    grounding: set[str] = {
        *_normalize_terms(string_list(plan.get("keywords"))),
        *_normalize_terms(base_keywords(user_goal)),
    }
    grounding.update(_normalize_terms(string_list(plan.get("_agent_ranking_semantic_anchors"))))
    grounding.update(_normalize_terms(string_list(plan.get("_agent_semantic_anchors"))))
    anchors = extract_semantic_anchors(user_goal, string_list(plan.get("keywords")))
    grounding.update(_normalize_terms(anchors))
    if anchors:
        signals = semantic_query_from_anchors("", anchors)
        grounding.update(_normalize_terms(signals.expanded_terms))
        grounding.update(_normalize_terms(signals.category_aliases))
        grounding.update(_normalize_terms(signals.matched_concepts))
    return grounding


def _normalize_terms(values: list[str]) -> set[str]:
    return {
        _normalize_term(value)
        for value in values
        if _normalize_term(value)
    }


def _normalize_term(value: str) -> str:
    return str(value or "").strip().lower()
