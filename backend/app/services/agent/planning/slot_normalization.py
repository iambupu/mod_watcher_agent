import re
from typing import Any

from app.services.game_alias_service import alias_key


def normalize_allowed_list(
    raw: Any,
    allowed_values: list[str],
    aliases: dict[str, list[str]] | None = None,
) -> list[str]:
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list):
        return []
    aliases = aliases or {}
    allowed_by_key = {alias_key(value): value for value in allowed_values}
    normalized = []
    seen = set()
    for item in raw:
        key = alias_key(str(item or ""))
        value = allowed_by_key.get(key)
        if value and value not in seen:
            normalized.append(value)
            seen.add(value)
            continue
        for aliased_value in aliases.get(key, []):
            if aliased_value not in seen:
                normalized.append(aliased_value)
                seen.add(aliased_value)
    return normalized


def normalize_optional_bool(raw: Any) -> bool | None:
    if isinstance(raw, bool):
        return raw
    value = str(raw or "").strip().lower()
    if value in {"true", "1", "yes", "y"}:
        return True
    if value in {"false", "0", "no", "n"}:
        return False
    return None


def normalize_limit(raw: dict[str, Any], *, default: int, maximum: int) -> int:
    try:
        limit = int(raw.get("limit") or default)
    except (TypeError, ValueError):
        limit = default
    return max(1, min(maximum, limit))


def normalize_min_metric(raw: Any) -> int | None:
    try:
        value = int(str(raw or "").replace(",", "").strip())
    except (TypeError, ValueError):
        return None
    return max(0, value)


def normalize_time_window(raw: Any) -> int | None:
    try:
        value = int(str(raw or "").replace(",", "").strip())
    except (TypeError, ValueError):
        return None
    return max(1, min(365, value))


def normalize_absolute_date(raw: Any) -> str | None:
    if not isinstance(raw, str | int | float):
        return None
    value = str(raw or "").strip()
    if not value:
        return None
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+00:00", value):
        return value
    if re.fullmatch(r"\d{4}-\d{1,2}-\d{1,2}", value):
        year, month, day = value.split("-")
        return f"{year}-{int(month):02d}-{int(day):02d}T00:00:00+00:00"
    if re.fullmatch(r"\d{4}", value):
        return f"{value}-01-01T00:00:00+00:00"
    return None


def normalize_exclude_titles(raw: Any) -> list[str]:
    if isinstance(raw, str):
        values = [raw]
    elif isinstance(raw, list | tuple | set):
        values = list(raw)
    else:
        return []
    normalized: list[str] = []
    seen: set[str] = set()
    for item in values:
        title = re.sub(r"\s+", " ", str(item or "").strip())
        key = title.lower()
        if title and key not in seen:
            normalized.append(title)
            seen.add(key)
    return normalized[:50]


def normalize_external_id(raw: Any) -> str | None:
    if isinstance(raw, str | int | float):
        value = re.sub(r"\s+", "", str(raw or "").strip()).strip(" #")
        return value or None
    return None
