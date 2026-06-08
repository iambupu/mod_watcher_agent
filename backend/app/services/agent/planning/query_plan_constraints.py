from typing import Any

from app.services.agent.list_utils import unique_text

_MISSING = object()

FIELD_ALIASES = {
    "game": "games",
    "source": "sources",
}
LIST_CONSTRAINT_FIELDS = {
    "games",
    "game_domains",
    "sources",
    "categories",
    "excluded_sources",
    "excluded_keywords",
}

CANONICAL_HARD_CONSTRAINT_FIELDS = (
    "games",
    "game_domains",
    "sources",
    "adult_content",
    "excluded_sources",
    "excluded_keywords",
    "updated_since_days",
    "updated_after",
    "updated_before",
    "published_after",
    "published_before",
    "created_after",
    "created_before",
    "time_range",
    "exact_title",
    "author",
    "external_id",
    "source_url",
)

HARD_CONSTRAINT_FIELDS = (
    *CANONICAL_HARD_CONSTRAINT_FIELDS,
    *FIELD_ALIASES.keys(),
)


def canonical_constraint_field(field_name: str) -> str:
    return FIELD_ALIASES.get(str(field_name or "").strip(), str(field_name or "").strip())


def collect_hard_constraints(
    query_plan: dict[str, Any],
    hard_filters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return hard constraints using the SearchPlan field vocabulary."""

    hard_filters = hard_filters if isinstance(hard_filters, dict) else {}
    constraints: dict[str, Any] = {}
    for field_name in _candidate_hard_fields(hard_filters):
        canonical = canonical_constraint_field(field_name)
        if canonical in constraints:
            continue
        value = constraint_value_from_mapping(canonical, query_plan, hard_filters)
        if value is _MISSING or _is_empty_constraint_value(value):
            continue
        constraints[canonical] = _normalize_constraint_value(canonical, value)
    return constraints


def protected_constraint_field_names(hard_constraints: dict[str, Any]) -> set[str]:
    protected = set(hard_constraints)
    for alias, canonical in FIELD_ALIASES.items():
        if canonical in hard_constraints:
            protected.add(alias)
    return protected


def constraint_value_from_mapping(field_name: str, *mappings: dict[str, Any]) -> object:
    canonical = canonical_constraint_field(field_name)
    names = [canonical, *[alias for alias, target in FIELD_ALIASES.items() if target == canonical]]
    for mapping in mappings:
        if not isinstance(mapping, dict):
            continue
        for name in names:
            if name in mapping:
                return mapping[name]
    return _MISSING


def has_constraint_value(mapping: dict[str, Any], field_name: str) -> bool:
    value = constraint_value_from_mapping(field_name, mapping)
    return value is not _MISSING


def constraint_values_equal(first: object, second: object) -> bool:
    if isinstance(first, list) or isinstance(second, list):
        return _normalized_sequence(first) == _normalized_sequence(second)
    return first == second


def is_empty_constraint_value(value: object) -> bool:
    return _is_empty_constraint_value(value)


def _candidate_hard_fields(hard_filters: dict[str, Any]) -> list[str]:
    return unique_text([*CANONICAL_HARD_CONSTRAINT_FIELDS, *FIELD_ALIASES.keys(), *hard_filters.keys()], limit=64)


def _normalized_sequence(value: object) -> list[str]:
    items = value if isinstance(value, list) else [value]
    return [str(item).strip() for item in items if str(item or "").strip()]


def _normalize_constraint_value(field_name: str, value: object) -> object:
    if field_name in LIST_CONSTRAINT_FIELDS:
        return _normalized_sequence(value)
    return value


def _is_empty_constraint_value(value: object) -> bool:
    return value is None or value == "" or value == []
