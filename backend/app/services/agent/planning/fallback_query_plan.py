from typing import Any

from app.services.agent.identity_inference import infer_identity_constraints
from app.services.agent.planning.query_intent import (
    detect_adult_constraint,
    detect_query_intent,
    infer_sort_preference,
    infer_source_constraints,
    is_recent_query,
)
from app.services.agent.semantic_search import base_keywords
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

DEFAULT_FALLBACK_LIMIT = 8


def build_fallback_query_plan(query: str, *, limit: int = DEFAULT_FALLBACK_LIMIT) -> dict[str, Any]:
    """Build a deterministic query plan when LLM planning is unavailable."""
    clean_query = _clean_fallback_keyword_query(query)
    fallback_tokens = base_keywords(clean_query)
    plan: dict[str, Any] = {
        "intent": detect_query_intent(query),
        "keywords": fallback_tokens[:5],
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
    return plan


def _clean_fallback_keyword_query(query: str) -> str:
    scoped_query = query.split("[scope]", 1)[0].strip()
    return query_without_compatibility_terms(
        query_without_thumbnail_terms(
            query_without_metric_terms(
                query_without_adult_markers(query_without_absolute_date_terms(scoped_query))
            )
        )
    )
