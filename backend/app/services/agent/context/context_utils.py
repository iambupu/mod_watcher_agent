from typing import Any

from app.services.agent.list_utils import unique_text

QUERY_CONTEXT_SIGNAL_FIELDS = ("game", "source_name", "category", "adult_content", "sort_field", "sort_order")


def has_query_context_signal(context: dict[str, Any], *, include_source_current: bool = True) -> bool:
    if not include_source_current and str(context.get("source") or "").strip().lower() == "current":
        return False
    return bool(context.get("keywords") or context.get("semantic_anchors")) or any(
        context.get(key) is not None for key in QUERY_CONTEXT_SIGNAL_FIELDS
    )


def merge_context_terms(primary: list[str], secondary: list[str], *, limit: int | None = None) -> list[str]:
    return unique_text((str(value).strip().lower() for value in [*primary, *secondary]), limit=limit)
