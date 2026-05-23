import json
from pathlib import Path
from uuid import uuid4

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.api.routes_agent import _apply_query_plan, _normalize_query_plan, _query_mods_with_plan
from app.models.mod import Mod
from app.models.summary import ModSummary


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


def _agent_mod(
    external_id: str,
    title: str,
    *,
    game: str = "Stellar Blade",
    source: str = "nexusmods",
    author: str = "Author",
    adult_content: bool = False,
    updated_at_remote: str = "2026-05-20T00:00:00",
    first_seen_at: str = "2026-05-20T00:00:00",
) -> Mod:
    return Mod(
        id=abs(hash(external_id)) % 100000,
        source=source,
        external_id=external_id,
        game=game,
        title=title,
        author=author,
        url=f"https://example.com/{external_id}",
        adult_content=adult_content,
        updated_at_remote=updated_at_remote,
        first_seen_at=first_seen_at,
        last_seen_at=first_seen_at,
    )


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


def test_apply_query_plan_fallback_filters_by_score_and_explicit_adult_constraint():
    clean = _agent_mod("clean", "XXTB Prototype Suit", adult_content=False)
    adult = _agent_mod("adult", "XXTB Adult Suit", adult_content=True)
    unrelated = _agent_mod("other", "Kawaii War Dress", adult_content=False)

    results = _apply_query_plan([clean, adult, unrelated], "XXTB 非成人 mod", None)

    assert [mod.external_id for _, mod in results] == ["clean"]


def test_apply_query_plan_recent_sorts_by_remote_update_then_first_seen():
    older = _agent_mod(
        "older",
        "Stellar Armor",
        updated_at_remote="2026-05-20T00:00:00",
        first_seen_at="2026-05-21T00:00:00",
    )
    newest_seen_later = _agent_mod(
        "newer-b",
        "Stellar Armor B",
        updated_at_remote="2026-05-22T00:00:00",
        first_seen_at="2026-05-22T02:00:00",
    )
    newest_seen_earlier = _agent_mod(
        "newer-a",
        "Stellar Armor A",
        updated_at_remote="2026-05-22T00:00:00",
        first_seen_at="2026-05-22T01:00:00",
    )

    results = _apply_query_plan(
        [older, newest_seen_earlier, newest_seen_later],
        "最近有什么 mod 更新",
        {"intent": "recent", "limit": 8},
    )

    assert [mod.external_id for _, mod in results] == ["newer-b", "newer-a", "older"]


def test_apply_query_plan_explicit_constraints_return_empty_without_match():
    unrelated = _agent_mod("skyrim", "Skyrim Armor", game="Skyrim Special Edition")

    results = _apply_query_plan(
        [unrelated],
        "Stellar Blade armor",
        {"intent": "search", "game": "Stellar Blade", "keywords": ["armor"], "limit": 8},
    )

    assert results == []


def test_apply_query_plan_keywords_match_extra_text_and_increase_score():
    plain = _agent_mod("plain", "Generic Outfit")
    translated = _agent_mod("translated", "Generic Dress")

    results = _apply_query_plan(
        [plain, translated],
        "玻尿酸",
        {"intent": "search", "keywords": ["玻尿酸"], "limit": 8},
        extra_text_by_mod={translated.id or 0: "玻尿酸化面部网格"},
    )

    assert [mod.external_id for _, mod in results] == ["translated"]


def test_agent_scope_constraints_override_source_game_domain_and_sort():
    slot_options = {
        "games": ["Skyrim Special Edition"],
        "game_domains": ["skyrimspecialedition"],
        "categories": [],
        "sources": ["nexusmods", "loverslab"],
    }

    plan = _normalize_query_plan(
        {"intent": "recent", "keywords": ["armor"]},
        "最近更新的护甲 Mod\n\n[scope]\nsource=nexusmods\ngame=skyrimspecialedition\nsort_field=downloads",
        slot_options,
    )

    assert plan["sources"] == ["nexusmods"]
    assert plan["game_domains"] == ["skyrimspecialedition"]
    assert plan["sort_field"] == "downloads"


def test_agent_ignores_llm_adult_guess_without_explicit_user_marker():
    slot_options = {
        "games": ["Stellar Blade"],
        "game_domains": [],
        "categories": [],
        "sources": ["nexusmods"],
    }

    plan = _normalize_query_plan(
        {"intent": "search", "keywords": ["XXTB"], "adult_content": True},
        "XXTB的mod\n\n[scope]\nsource=nexusmods\ngame=Stellar Blade",
        slot_options,
    )

    assert plan["adult_content"] is None


def test_agent_keeps_explicit_adult_marker():
    slot_options = {
        "games": ["Stellar Blade"],
        "game_domains": [],
        "categories": [],
        "sources": ["nexusmods"],
    }

    plan = _normalize_query_plan(
        {"intent": "search", "keywords": ["XXTB"], "adult_content": None},
        "XXTB的成人mod\n\n[scope]\nsource=nexusmods\ngame=Stellar Blade",
        slot_options,
    )

    assert plan["adult_content"] is True


def test_chinese_semantic_query_infers_existing_categories_and_keywords():
    slot_options = {
        "games": ["Skyrim Special Edition"],
        "game_domains": ["skyrimspecialedition"],
        "categories": ["Outfits", "Clothing and Accessories", "Body, Face, and Hair", "Gameplay", "Visuals and Graphics"],
        "sources": ["nexusmods", "loverslab"],
    }

    plan = _normalize_query_plan(
        {"intent": "search", "keywords": []},
        "只看女性服装",
        slot_options,
    )

    assert plan["categories"] == ["Outfits", "Clothing and Accessories"]
    assert plan["category_match_mode"] == "db_fuzzy"
    assert "female" in plan["keywords"]
    assert "outfit" in plan["keywords"]


def test_semantic_query_filters_unrelated_llm_categories_against_db_values():
    slot_options = {
        "games": ["Skyrim Special Edition"],
        "game_domains": ["skyrimspecialedition"],
        "categories": ["Outfits", "Clothing and Accessories", "Skills and Leveling"],
        "sources": ["nexusmods", "loverslab"],
    }

    plan = _normalize_query_plan(
        {"intent": "search", "keywords": [], "categories": ["Outfits", "Skills and Leveling"]},
        "只看女性服装",
        slot_options,
    )

    assert plan["categories"] == ["Outfits", "Clothing and Accessories"]


def test_specific_keyword_query_drops_broad_llm_category_guess():
    slot_options = {
        "games": ["Skyrim Special Edition"],
        "game_domains": ["skyrimspecialedition"],
        "categories": ["Body, Face, and Hair", "NPC"],
        "sources": ["nexusmods", "loverslab"],
    }

    plan = _normalize_query_plan(
        {"intent": "search", "keywords": [], "categories": ["Body, Face, and Hair"]},
        "有什么和玻尿酸相关的mod",
        slot_options,
    )

    assert plan["categories"] == []
    assert "玻尿酸" in plan["keywords"]
    assert "botox" in plan["keywords"]


def test_db_fuzzy_category_query_returns_category_match_without_keyword_hit():
    engine = _make_engine()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        session.add_all(
            [
                Mod(
                    source="nexusmods",
                    external_id="outfit-1",
                    game="Stellar Blade",
                    category="Outfits",
                    title="Ocean String",
                    url="https://example.com/outfit",
                    updated_at_remote="2026-05-20T00:00:00",
                    first_seen_at="2026-05-20T00:00:00",
                    last_seen_at="2026-05-20T00:00:00",
                ),
                Mod(
                    source="nexusmods",
                    external_id="patch-1",
                    game="Stellar Blade",
                    category="Patches",
                    title="Patch Collection",
                    url="https://example.com/patch",
                    updated_at_remote="2026-05-20T00:00:00",
                    first_seen_at="2026-05-20T00:00:00",
                    last_seen_at="2026-05-20T00:00:00",
                ),
            ]
        )
        session.commit()
        slot_options = {
            "games": ["Stellar Blade"],
            "game_domains": [],
            "categories": ["Outfits", "Patches"],
            "sources": ["nexusmods"],
        }

        plan = _normalize_query_plan(
            {"intent": "search", "keywords": [], "sources": ["nexusmods"]},
            "只看女性服装",
            slot_options,
        )
        results = _query_mods_with_plan(session, "只看女性服装", plan)

    assert [mod.external_id for _, mod in results] == ["outfit-1"]


def test_agent_query_matches_translated_summary_text():
    engine = _make_engine()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        mod = Mod(
            source="loverslab",
            external_id="botox-1",
            game="skyrimspecialedition",
            title="Paradise Halls Enhanced - Botoxed",
            url="https://example.com/botoxed",
            original_summary="Botoxed face meshes and textures.",
            adult_content=True,
            updated_at_remote="2026-05-22T00:00:00",
            first_seen_at="2026-05-22T00:00:00",
            last_seen_at="2026-05-22T00:00:00",
        )
        other = Mod(
            source="nexusmods",
            external_id="face-1",
            game="Skyrim Special Edition",
            category="Body, Face, and Hair",
            title="Generic Face Preset",
            url="https://example.com/face",
            updated_at_remote="2026-05-22T00:00:00",
            first_seen_at="2026-05-22T00:00:00",
            last_seen_at="2026-05-22T00:00:00",
        )
        session.add_all([mod, other])
        session.commit()
        session.refresh(mod)
        session.add(
            ModSummary(
                mod_id=mod.id or 0,
                language="zh-CN",
                summary_type="brief",
                content="天堂大厅增强版-玻尿酸化，包含面部网格和纹理。",
                generated_at="2026-05-22T00:00:00",
            )
        )
        session.commit()
        slot_options = {
            "games": ["Skyrim Special Edition", "skyrimspecialedition"],
            "game_domains": [],
            "categories": ["Body, Face, and Hair"],
            "sources": ["nexusmods", "loverslab"],
        }

        plan = _normalize_query_plan(
            {"intent": "search", "keywords": []},
            "有什么和玻尿酸相关的mod",
            slot_options,
        )
        results = _query_mods_with_plan(session, "有什么和玻尿酸相关的mod", plan)

    assert [mod.external_id for _, mod in results] == ["botox-1"]


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
