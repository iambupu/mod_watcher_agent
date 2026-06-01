import re
from typing import Any

from app.services.agent.list_utils import string_list, unique_text
from app.services.agent.planning.query_intent import infer_source_constraints
from app.services.agent.semantic_search import distinctive_query_terms, unique_terms
from app.services.agent.slot_aliases import normalize_source_alias
from app.utils.boolean import parse_bool
from app.utils.numeric import bounded_int

OPEN_DISCOVERY_DISPLAY_LIMIT = 12
OPEN_DISCOVERY_POOL_LIMIT = 60
OPEN_DISCOVERY_MAX_POOL_LIMIT = 80
JUDGE_CANDIDATE_LIMIT = 60
SOFT_OPEN_DISCOVERY_FIELDS = ("categories", "tags", "requirement_terms", "compatibility_terms")


def is_open_discovery_plan(plan: dict[str, Any]) -> bool:
    return parse_bool(plan.get("open_discovery")) and str(plan.get("retrieval_mode") or "").strip().lower() == "fuzzy"


def apply_open_discovery_executor_policy(plan: dict[str, Any], *, soft_signals: list[str] | None = None) -> None:
    """统一开放发现的 executor 兼容策略，避免 adapter、检索和排序各自维护一套规则。"""
    plan["open_discovery"] = True
    plan["retrieval_mode"] = "fuzzy"
    plan["limit"] = max(_positive_int_or_default(plan.get("limit"), 1), OPEN_DISCOVERY_DISPLAY_LIMIT)
    plan["candidate_pool_limit"] = max(
        _nonnegative_int_or_default(plan.get("candidate_pool_limit"), 0),
        OPEN_DISCOVERY_POOL_LIMIT,
    )
    category_hints = string_list(plan.get("category_hints"), limit=20)
    for field in SOFT_OPEN_DISCOVERY_FIELDS:
        values = string_list(plan.get(field), limit=20)
        if values:
            category_hints.extend(values)
            plan[field] = []
    category_hints.extend(soft_signals or [])
    plan["category_hints"] = unique_text(category_hints, limit=16)


def build_open_discovery_retrieval_plan(plan: dict[str, Any], query: str) -> dict[str, Any]:
    """检索阶段只保留明确硬约束，把容易误杀的槽位转成软提示或召回词。"""
    if not (parse_bool(plan.get("open_discovery")) or str(plan.get("retrieval_mode") or "").strip().lower() == "fuzzy"):
        return plan
    if plan.get("exact_title") or plan.get("external_id") or plan.get("source_url"):
        return plan
    relaxed = dict(plan)
    keywords = _focused_fuzzy_keywords(query, relaxed)
    soft_terms: list[str] = []
    for key in SOFT_OPEN_DISCOVERY_FIELDS:
        soft_terms.extend(str(value).strip() for value in (relaxed.get(key) or []) if str(value).strip())
    relaxed["keywords"] = unique_terms([*keywords, *soft_terms])[:10]
    relaxed["category_hints"] = unique_terms(
        [
            *(str(value).strip() for value in (relaxed.get("category_hints") or []) if str(value).strip()),
            *(str(value).strip() for value in (relaxed.get("categories") or []) if str(value).strip()),
        ]
    )
    relaxed["categories"] = []
    relaxed["sources"] = explicit_source_filters(relaxed, query)
    relaxed["tags"] = []
    relaxed["requirement_terms"] = []
    relaxed["compatibility_terms"] = []
    relaxed.pop("keyword_match_mode", None)
    relaxed["retrieval_mode"] = "fuzzy"
    return relaxed


def explicit_source_filters(plan: dict[str, Any], query: str) -> list[str]:
    query_sources = infer_source_constraints(query).get("sources") or []
    if query_sources:
        return unique_terms([str(value).strip() for value in query_sources if str(value).strip()])
    strategy = plan.get("_agent_semantic_strategy")
    hard_filters = strategy.get("hard_filters") if isinstance(strategy, dict) and isinstance(strategy.get("hard_filters"), dict) else {}
    source = str(hard_filters.get("source") or "").strip()
    # SemanticStrategy.hard_filters 约定只来自本轮显式约束；这里保留来源，避免开放发现突破用户“只看某来源”的限制。
    if not source:
        return []
    normalized_plan_sources = unique_terms([str(value).strip() for value in (plan.get("sources") or []) if str(value).strip()])
    return normalized_plan_sources or [normalize_source_alias(source)]


def open_discovery_result_limit(plan: dict[str, Any], *, default_limit: int) -> int:
    display_limit = _positive_int_or_default(plan.get("limit"), default_limit)
    if not is_open_discovery_plan(plan):
        return display_limit
    pool_limit = _nonnegative_int_or_default(plan.get("candidate_pool_limit"), 0)
    return max(display_limit, min(pool_limit, OPEN_DISCOVERY_MAX_POOL_LIMIT))


def judge_candidate_pool_limit(plan: dict[str, Any], *, display_limit: int) -> int:
    requested = _nonnegative_int_or_default(plan.get("candidate_pool_limit"), 0)
    return max(display_limit, min(requested or max(display_limit * 4, 20), JUDGE_CANDIDATE_LIMIT))


def _focused_fuzzy_keywords(query: str, plan: dict[str, Any]) -> list[str]:
    keywords = [str(value).strip() for value in (plan.get("keywords") or []) if str(value).strip()]
    core_terms = distinctive_query_terms(query)
    if not core_terms:
        return keywords
    query_text = str(query or "").lower()
    focused: list[str] = []
    for keyword in keywords:
        key = keyword.lower()
        if key in query_text or any(term in key or key in term for term in core_terms):
            focused.append(keyword)
    for term in core_terms:
        focused.extend(_keyword_variants(term))
    return unique_terms(focused)[:10] or keywords


def _keyword_variants(term: str) -> list[str]:
    value = str(term or "").strip().lower()
    if not value:
        return []
    variants = [value]
    if re.fullmatch(r"[a-z0-9][a-z0-9_-]{2,}", value) and not value.endswith("s"):
        variants.append(f"{value}s")
    if value == "bimbo":
        variants.extend(["bimbofication", "bimbofied"])
    return variants


def _positive_int_or_default(value: object, default: int) -> int:
    return bounded_int(value, default=default, minimum=1, maximum=OPEN_DISCOVERY_MAX_POOL_LIMIT)


def _nonnegative_int_or_default(value: object, default: int) -> int:
    return bounded_int(value, default=default, minimum=0, maximum=OPEN_DISCOVERY_MAX_POOL_LIMIT)
