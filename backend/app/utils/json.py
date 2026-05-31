import json
import re
from typing import Any, TypeVar

T = TypeVar("T")


def json_object(value: str | None) -> dict[str, Any]:
    try:
        parsed = json.loads(value or "{}")
    except (json.JSONDecodeError, TypeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def json_array(value: str | None) -> list[Any]:
    try:
        parsed = json.loads(value or "[]")
    except (json.JSONDecodeError, TypeError):
        return []
    return parsed if isinstance(parsed, list) else []


def json_text(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def strip_json_fence(value: str | None) -> str:
    return re.sub(r"^```(?:json)?\s*|\s*```$", "", str(value or "").strip(), flags=re.IGNORECASE | re.DOTALL).strip()


def json_object_from_text(value: str | None) -> dict[str, Any] | None:
    return _json_container_from_text(value, dict, "{")


def json_array_from_text(value: str | None) -> list[Any] | None:
    return _json_container_from_text(value, list, "[")


def _json_container_from_text(value: str | None, expected_type: type[T], start_marker: str) -> T | None:
    raw = strip_json_fence(value)
    if not raw:
        return None

    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        parsed = None
    else:
        return parsed if isinstance(parsed, expected_type) else None

    decoder = json.JSONDecoder()
    for index, char in enumerate(raw):
        if char != start_marker:
            continue
        try:
            parsed, _end = decoder.raw_decode(raw[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, expected_type):
            return parsed
    return None
