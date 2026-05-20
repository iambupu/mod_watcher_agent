import json
from pathlib import Path
from uuid import uuid4

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.api.routes_agent import _normalize_query_plan, _query_mods_with_plan
from app.models.mod import Mod


def _make_engine():
    return create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


def _alias_file(name: str) -> Path:
    root = Path("backend/.test_aliases")
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{name}-{uuid4().hex}.json"
    return path.resolve()


def test_chinese_game_alias_maps_to_database_game_and_does_not_remain_keyword(monkeypatch):
    alias_file = _alias_file("existing")
    alias_file.write_text(json.dumps({"aliases": {"剑星": ["Stellar Blade"]}}, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr("app.services.game_alias_service.settings.GAME_ALIAS_FILE", str(alias_file))
    slot_options = {
        "games": ["Skyrim Special Edition", "Stellar Blade"],
        "game_domains": [],
        "categories": [],
        "sources": ["nexusmods"],
    }

    try:
        plan = _normalize_query_plan(
            {"intent": "recent", "keywords": ["剑星"], "sort_field": "updated_at_remote"},
            "最近有什么剑星的成人 mod 更新吗",
            slot_options,
        )
    finally:
        alias_file.unlink(missing_ok=True)

    assert plan["games"] == ["Stellar Blade"]
    assert "剑星" not in plan["keywords"]


def test_llm_discovered_game_alias_is_persisted_and_used(monkeypatch):
    alias_file = _alias_file("learned")
    monkeypatch.setattr("app.services.game_alias_service.settings.GAME_ALIAS_FILE", str(alias_file))
    slot_options = {
        "games": ["Skyrim Special Edition", "Stellar Blade"],
        "game_domains": [],
        "categories": [],
        "sources": ["nexusmods"],
    }

    try:
        plan = _normalize_query_plan(
            {
                "intent": "recent",
                "keywords": ["星刃"],
                "game_aliases": [{"alias": "星刃", "game": "Stellar Blade"}],
            },
            "最近有什么星刃 mod 更新吗",
            slot_options,
        )
        stored = json.loads(alias_file.read_text(encoding="utf-8"))
    finally:
        alias_file.unlink(missing_ok=True)

    assert stored["aliases"]["星刃"] == ["Stellar Blade"]
    assert plan["games"] == ["Stellar Blade"]
    assert "星刃" not in plan["keywords"]


def test_chinese_game_alias_query_returns_stellar_blade_mods(monkeypatch):
    alias_file = _alias_file("query")
    alias_file.write_text(json.dumps({"aliases": {"剑星": ["Stellar Blade"]}}, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr("app.services.game_alias_service.settings.GAME_ALIAS_FILE", str(alias_file))
    engine = _make_engine()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        session.add_all(
            [
                Mod(
                    source="nexusmods",
                    external_id="stellar-1",
                    game="Stellar Blade",
                    title="Twinkie NSFW",
                    url="https://example.com/stellar",
                    adult_content=True,
                    updated_at_remote="2026-05-20T00:00:00",
                    first_seen_at="2026-05-20T00:00:00",
                    last_seen_at="2026-05-20T00:00:00",
                ),
                Mod(
                    source="nexusmods",
                    external_id="skyrim-1",
                    game="Skyrim Special Edition",
                    title="Skyrim NSFW",
                    url="https://example.com/skyrim",
                    adult_content=True,
                    updated_at_remote="2026-05-20T00:00:00",
                    first_seen_at="2026-05-20T00:00:00",
                    last_seen_at="2026-05-20T00:00:00",
                ),
            ]
        )
        session.commit()

        slot_options = {
            "games": ["Skyrim Special Edition", "Stellar Blade"],
            "game_domains": [],
            "categories": [],
            "sources": ["nexusmods"],
        }
        try:
            plan = _normalize_query_plan(
                {"intent": "recent", "keywords": ["剑星"], "adult_content": True, "sort_field": "updated_at_remote"},
                "最近有什么剑星的成人 mod 更新吗",
                slot_options,
            )
            results = _query_mods_with_plan(session, "最近有什么剑星的成人 mod 更新吗", plan)
        finally:
            alias_file.unlink(missing_ok=True)

    assert [mod.game for _, mod in results] == ["Stellar Blade"]
