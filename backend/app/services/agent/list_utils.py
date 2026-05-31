from collections.abc import Callable, Iterable


def string_list(value: object, *, limit: int | None = None) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        values = [value]
    elif isinstance(value, list | tuple | set):
        values = list(value)
    else:
        return []
    items = [str(item).strip() for item in values if str(item).strip()]
    return items[:limit] if limit is not None else items


def unique_text(
    values: Iterable[object],
    *,
    limit: int | None = None,
    key_func: Callable[[str], str] | None = None,
) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for item in values:
        text = str(item or "").strip()
        key = key_func(text) if key_func else text.lower()
        if not text or not key or key in seen:
            continue
        result.append(text)
        seen.add(key)
        if limit is not None and len(result) >= limit:
            break
    return result


def merge_unique_text(
    values: Iterable[object],
    additions: Iterable[object],
    *,
    limit: int | None = None,
    key_func: Callable[[str], str] | None = None,
) -> list[str]:
    return unique_text([*values, *additions], limit=limit, key_func=key_func)
