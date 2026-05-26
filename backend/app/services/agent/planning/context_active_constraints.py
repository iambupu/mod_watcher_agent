from typing import Any


def apply_active_constraints(raw: dict[str, Any], constraints: dict[str, Any] | None) -> None:
    active_constraints = constraints or {}
    for source_key, target_key in [
        ("game", "games"),
        ("source", "sources"),
        ("category", "categories"),
    ]:
        if active_constraints.get(source_key) and not raw.get(target_key):
            raw[target_key] = [active_constraints[source_key]]
    for key in ["adult_content", "sort_field", "sort_order"]:
        if raw.get(key) is None and active_constraints.get(key) is not None:
            raw[key] = active_constraints[key]
