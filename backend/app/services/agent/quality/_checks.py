from pathlib import Path

import yaml


def exception_check(exc: Exception) -> dict[str, object]:
    return {
        "name": "case.exception",
        "passed": False,
        "actual": type(exc).__name__,
        "expected": "no exception",
    }


def load_case_objects(path: Path, *, label: str) -> list[dict[str, object]]:
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or []
    if not isinstance(data, list):
        raise ValueError(f"{label} cases must be a list")
    invalid_indexes = [index for index, item in enumerate(data) if not isinstance(item, dict)]
    if invalid_indexes:
        raise ValueError(f"{label} cases must be objects at indexes: {invalid_indexes}")
    return data


def expect_field_type_summary(field_types: dict[str, str]) -> dict[str, str]:
    return dict(sorted(field_types.items()))


def invalid_expect_field_types(expected: dict[str, object], field_types: dict[str, str]) -> dict[str, str]:
    invalid: dict[str, str] = {}
    for field in sorted(expected):
        value = expected[field]
        expected_type = field_types.get(field)
        if expected_type and not _matches_expect_type(value, expected_type):
            invalid[field] = _type_name(value)
    return invalid


def _matches_expect_type(value: object, expected_type: str) -> bool:
    if expected_type == "bool":
        return isinstance(value, bool)
    if expected_type == "list":
        return isinstance(value, list)
    if expected_type == "number":
        return isinstance(value, int | float) and not isinstance(value, bool)
    if expected_type == "object":
        return isinstance(value, dict)
    if expected_type == "string":
        return isinstance(value, str)
    if expected_type == "string_or_null":
        return value is None or isinstance(value, str)
    return False


def _type_name(value: object) -> str:
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, dict):
        return "object"
    if isinstance(value, list):
        return "list"
    if isinstance(value, str):
        return "string"
    if isinstance(value, int | float):
        return "number"
    if value is None:
        return "null"
    return type(value).__name__
