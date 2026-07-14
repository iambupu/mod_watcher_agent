"""Shared policies for local retrieval result allocation."""


def current_only_reserved(limit: int, current_only_count: int) -> int:
    """Return the result slots reserved for the current query branch."""
    if current_only_count <= 0:
        return 0
    half_limit = max(1, limit // 2)
    return min(current_only_count, min(3, half_limit))
