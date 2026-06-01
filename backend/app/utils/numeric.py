from typing import Any


def _clean_number_text(value: Any) -> str:
    return str(value).replace(",", "").strip()


def safe_nonnegative_int(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    try:
        return max(0, int(_clean_number_text(value or 0)))
    except (TypeError, ValueError):
        return 0


def is_plain_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def optional_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        text = _clean_number_text(value)
        if not text:
            return None
        return int(text)
    except (TypeError, ValueError):
        return None


def optional_nonnegative_int(value: Any) -> int | None:
    parsed = optional_int(value)
    return max(0, parsed) if parsed is not None else None


def optional_bounded_int(value: Any, *, minimum: int, maximum: int) -> int | None:
    parsed = optional_int(value)
    if parsed is None:
        return None
    return max(minimum, min(maximum, parsed))


def bounded_int(
    value: Any,
    *,
    default: int,
    minimum: int,
    maximum: int,
    default_when_below_minimum: bool = False,
) -> int:
    try:
        parsed = int(_clean_number_text(value or default))
    except (TypeError, ValueError):
        parsed = default
    if parsed < minimum and default_when_below_minimum:
        return default
    return max(minimum, min(maximum, parsed))


def safe_float(
    value: Any,
    *,
    default: float = 0.0,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float:
    try:
        result = float(_clean_number_text(value))
    except (TypeError, ValueError):
        result = default
    if minimum is not None:
        result = max(minimum, result)
    if maximum is not None:
        result = min(maximum, result)
    return result


def safe_optional_float(value: Any) -> float | None:
    try:
        return float(_clean_number_text(value))
    except (TypeError, ValueError):
        return None
