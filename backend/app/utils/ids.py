# 中文注释：提供正整数 ID 清洗相关的纯函数工具。

from collections.abc import Iterable


def positive_integer_id(value: object, *, allow_string: bool = False) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        candidate = value
    elif allow_string and isinstance(value, str) and value.strip().isdigit():
        candidate = int(value.strip())
    else:
        return None
    return candidate if candidate > 0 else None


def positive_integer_ids(values: Iterable[object]) -> list[int]:
    ids: list[int] = []
    seen: set[int] = set()
    for value in values:
        candidate = positive_integer_id(value)
        if candidate is None:
            continue
        if candidate in seen:
            continue
        ids.append(candidate)
        seen.add(candidate)
    return ids
