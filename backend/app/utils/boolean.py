TRUE_STRINGS = {"1", "true", "yes", "on"}
FALSE_STRINGS = {"0", "false", "no", "off", ""}


def parse_bool(value: object, *, default: bool = False) -> bool:
    parsed = parse_optional_bool(value)
    return default if parsed is None else parsed


def parse_optional_bool(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    if isinstance(value, int | float):
        return value != 0
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in TRUE_STRINGS:
            return True
        if normalized in FALSE_STRINGS:
            return False
    return None
