from typing import Any

from app.services.agent.identity_inference import infer_identity_constraints
from app.services.agent.list_utils import unique_text
from app.services.agent.planning.query_intent import (
    detect_adult_constraint,
    detect_query_intent,
    infer_sort_preference,
    infer_source_constraints,
    is_open_discovery_query,
    is_recent_query,
)
from app.services.agent.semantic_search import base_keywords, strip_scope
from app.services.agent.slot_attribute_inference import (
    infer_summary_language_constraints,
    infer_tag_constraints,
    infer_thumbnail_constraint,
    query_without_thumbnail_terms,
)
from app.services.agent.slot_constraint_inference import (
    infer_absolute_date_constraints,
    infer_numeric_constraints,
    infer_time_window,
    query_without_absolute_date_terms,
    query_without_metric_terms,
)
from app.services.agent.slot_text_inference import (
    infer_author_constraint,
    infer_compatibility_terms,
    infer_excluded_keywords,
    infer_requirement_terms,
    infer_title_constraint,
    infer_version_constraint,
    query_without_adult_markers,
    query_without_compatibility_terms,
)

DEFAULT_EXECUTOR_QUERY_LIMIT = 8


def build_executor_query_plan(query: str, *, limit: int = DEFAULT_EXECUTOR_QUERY_LIMIT) -> dict[str, Any]:
    """生成 executor 所需的确定性 query_plan 种子。"""
    clean_query = _clean_executor_keyword_query(query)
    executor_tokens = base_keywords(clean_query)
    open_discovery = is_open_discovery_query(query)
    plan: dict[str, Any] = {
        "intent": detect_query_intent(query),
        "keywords": executor_tokens[:5],
        "open_discovery": open_discovery,
        "retrieval_mode": "fuzzy" if open_discovery else "filtered",
        "adult_content": detect_adult_constraint(query),
        "sort_field": "updated_at_remote" if is_recent_query(query) else "relevance",
        "sort_order": "desc",
        "limit": limit,
    }
    plan.update(infer_source_constraints(query))
    plan.update(infer_sort_preference(query))
    plan.update(infer_numeric_constraints(query))
    plan.update(infer_time_window(query))
    plan.update(infer_absolute_date_constraints(query))
    plan.update(infer_tag_constraints(query))
    plan.update(infer_summary_language_constraints(query))
    plan.update(infer_thumbnail_constraint(query))
    plan.update(infer_title_constraint(query))
    plan.update(infer_version_constraint(query))
    plan.update(infer_identity_constraints(query))
    plan.update(infer_requirement_terms(query))
    plan.update(infer_compatibility_terms(query))
    plan.update(infer_author_constraint(query))
    plan.update(infer_excluded_keywords(query))
    if open_discovery:
        _soften_open_discovery_slots(plan)
    return plan


def _clean_executor_keyword_query(query: str) -> str:
    scoped_query = strip_scope(query)
    return query_without_compatibility_terms(
        query_without_thumbnail_terms(
            query_without_metric_terms(
                query_without_adult_markers(query_without_absolute_date_terms(scoped_query))
            )
        )
    )


def _soften_open_discovery_slots(plan: dict[str, Any]) -> None:
    # slot_* 在开放发现里只是语义信号来源；除明确排除/身份字段外，不再主导硬过滤。
    hints: list[str] = []
    for field in ("categories", "tags", "requirement_terms", "compatibility_terms"):
        values = plan.get(field)
        if isinstance(values, list) and values:
            hints.extend(str(item).strip() for item in values if str(item).strip())
            plan[field] = []
    if hints:
        existing = plan.get("category_hints") if isinstance(plan.get("category_hints"), list) else []
        plan["category_hints"] = unique_text([*existing, *hints], limit=16)
