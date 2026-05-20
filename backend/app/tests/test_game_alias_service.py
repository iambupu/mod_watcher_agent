import json
from pathlib import Path
from uuid import uuid4

from app.services.game_alias_service import (
    add_game_alias_mappings,
    build_resolved_aliases,
    load_game_aliases,
)


def _alias_file(name: str) -> Path:
    root = Path("backend/.test_aliases")
    root.mkdir(parents=True, exist_ok=True)
    return (root / f"{name}-{uuid4().hex}.json").resolve()


def test_add_game_alias_mappings_writes_only_valid_targets():
    alias_file = _alias_file("service")

    try:
        aliases = add_game_alias_mappings(
            [
                {"alias": "星刃", "game": "Stellar Blade"},
                {"alias": "不存在", "game": "Unknown Game"},
            ],
            ["Stellar Blade"],
            path=alias_file,
        )

        assert aliases == {"星刃": ["Stellar Blade"]}
        assert load_game_aliases(alias_file) == {"星刃": ["Stellar Blade"]}
        payload = json.loads(alias_file.read_text(encoding="utf-8"))
        assert payload == {"aliases": {"星刃": ["Stellar Blade"]}}
    finally:
        alias_file.unlink(missing_ok=True)


def test_build_resolved_aliases_ignores_alias_targets_not_in_database():
    aliases = build_resolved_aliases(
        ["Stellar Blade"],
        aliases={"星刃": ["Stellar Blade"], "天际": ["Skyrim Special Edition"]},
    )

    assert aliases == {"星刃": ["Stellar Blade"]}
