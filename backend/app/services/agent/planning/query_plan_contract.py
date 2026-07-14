"""Shared field groups for the dictionary query-plan compatibility boundary."""

from typing import Any

METRIC_FIELDS = (
    "min_downloads",
    "min_endorsements",
    "min_views",
    "min_likes",
)

DATE_RANGE_FIELDS = (
    "updated_after",
    "updated_before",
    "published_after",
    "published_before",
    "created_after",
    "created_before",
)

LOOSE_TERM_FIELDS = frozenset(
    {
        "keywords",
        "category_hints",
        "requirement_terms",
        "compatibility_terms",
        "tags",
        "summary_languages",
        "excluded_summary_languages",
        "excluded_keywords",
    }
)

CURRENT_ONLY_QUERY_PLAN_FIELDS = frozenset(
    {
        "keywords",
        "excluded_keywords",
        "exclude_titles",
        "games",
        "game_domains",
        "sources",
        "excluded_sources",
        "categories",
        "category_hints",
        "tags",
        "summary_languages",
        "excluded_summary_languages",
        "requirement_terms",
        "compatibility_terms",
        "has_thumbnail",
        "author",
        "adult_content",
        *METRIC_FIELDS,
        "updated_since_days",
        *DATE_RANGE_FIELDS,
        "sort_field",
        "sort_order",
        "limit",
        "open_discovery",
        "retrieval_mode",
        "keyword_match_mode",
        "exact_title",
        "version",
        "external_id",
        "source_url",
        "evidence_id",
    }
)


def semantic_strategy(query_plan: dict[str, Any] | None) -> dict[str, Any]:
    """Return the semantic strategy carried by a compatible query plan."""
    value = (query_plan or {}).get("_agent_semantic_strategy")
    return value if isinstance(value, dict) else {}
