import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.models.mod import Mod
from app.services.agent import mod_search_service
from app.services.agent.retrievers.sqlite_fts_retriever import SqliteFtsResult
from app.services.agent.search_types import SearchPlan
from app.services.agent.tools.local_db_search_tool import LocalDbSearchInput, LocalDbSearchTool


def _engine():
    return create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)


@pytest.mark.asyncio
async def test_local_db_tool_returns_search_results():
    engine = _engine()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(
            Mod(
                source="nexusmods",
                external_id="1",
                game="Stellar Blade",
                title="XXTB Suit",
                url="https://example.com/1",
                first_seen_at="2026-05-20T00:00:00+00:00",
                last_seen_at="2026-05-20T00:00:00+00:00",
            )
        )
        session.commit()

        plan = SearchPlan.from_query_plan({"keywords": ["XXTB"], "limit": 8})
        results = await LocalDbSearchTool(session).run(LocalDbSearchInput(query="XXTB的mod", plan=plan))

    assert results
    assert results[0].tool_name == "local_db_search"
    assert results[0].mod.title == "XXTB Suit"
    assert results[0].score >= 1


@pytest.mark.asyncio
async def test_local_db_tool_uses_sqlite_fts_for_relevance_keywords(monkeypatch):
    engine = _engine()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        mod = Mod(
            source="nexusmods",
            external_id="1",
            game="Stellar Blade",
            title="Ocean String",
            url="https://example.com/1",
            first_seen_at="2026-05-20T00:00:00+00:00",
            last_seen_at="2026-05-20T00:00:00+00:00",
        )
        session.add(mod)
        session.commit()
        session.refresh(mod)
        seen = {}

        def fake_query_mods_fts(session_arg, *, keywords, filters, limit):
            seen["keywords"] = keywords
            seen["filters"] = filters
            seen["limit"] = limit
            return [SqliteFtsResult(mod=mod, score=77)]

        monkeypatch.setattr(mod_search_service, "query_mods_fts", fake_query_mods_fts)

        plan = SearchPlan.from_query_plan({"keywords": ["成人服装"], "sort_field": "relevance", "limit": 8})
        results = await LocalDbSearchTool(session).run(LocalDbSearchInput(query="成人服装", plan=plan))

    assert seen["keywords"] == ["成人服装"]
    assert seen["filters"]["sort_field"] == "relevance"
    assert seen["limit"] == 8
    assert results[0].score == 77
    assert results[0].mod.title == "Ocean String"


@pytest.mark.asyncio
async def test_local_db_tool_treats_game_domain_as_legacy_game_alias_for_fts():
    engine = _engine()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        vanilla = Mod(
            source="loverslab",
            external_id="489",
            game="skyrimspecialedition",
            game_domain=None,
            title="Vanilla Sexism 2",
            translated_title_zh="纯 vanilla 性别歧视 2",
            url="https://example.com/sexism-2",
            first_seen_at="2026-05-22T00:00:00+00:00",
            last_seen_at="2026-05-22T00:00:00+00:00",
        )
        guard_replacer = Mod(
            source="nexusmods",
            external_id="2",
            game="Skyrim Special Edition",
            game_domain="skyrimspecialedition",
            title="Katsune Sexist Guards Player Audio Replacer",
            translated_title_zh="Katsune 性别歧视守卫玩家音频替换器",
            url="https://example.com/guards",
            first_seen_at="2026-05-20T00:00:00+00:00",
            last_seen_at="2026-05-20T00:00:00+00:00",
        )
        session.add_all([vanilla, guard_replacer])
        session.commit()

        plan = SearchPlan.from_query_plan(
            {
                "keywords": ["性别歧视"],
                "games": ["skyrimspecialedition"],
                "game_domains": ["skyrimspecialedition"],
                "sort_field": "relevance",
                "sort_order": "desc",
                "limit": 8,
            }
        )
        results = await LocalDbSearchTool(session).run(
            LocalDbSearchInput(query="性别歧视主题的 mod", plan=plan)
        )

    assert [result.mod.title for result in results[:2]] == [
        "Vanilla Sexism 2",
        "Katsune Sexist Guards Player Audio Replacer",
    ]
    assert results[0].score >= 90


@pytest.mark.asyncio
async def test_local_db_tool_preserves_negative_filter_fields_for_fts(monkeypatch):
    engine = _engine()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        mod = Mod(
            source="nexusmods",
            external_id="1",
            game="Skyrim Special Edition",
            title="Bimbo Preset",
            url="https://example.com/1",
            first_seen_at="2026-05-20T00:00:00+00:00",
            last_seen_at="2026-05-20T00:00:00+00:00",
        )
        session.add(mod)
        session.commit()
        session.refresh(mod)
        seen = {}

        def fake_query_mods_fts(session_arg, *, keywords, filters, limit):
            seen["filters"] = filters
            return [SqliteFtsResult(mod=mod, score=77)]

        monkeypatch.setattr(mod_search_service, "query_mods_fts", fake_query_mods_fts)

        plan = SearchPlan.from_query_plan(
            {
                "keywords": ["bimbo", "preset"],
                "excluded_sources": ["loverslab"],
                "exclude_titles": ["Blocked Bimbo"],
                "keyword_match_mode": "all",
                "sort_field": "relevance",
                "limit": 8,
            }
        )
        await LocalDbSearchTool(session).run(LocalDbSearchInput(query="bimbo preset", plan=plan))

    assert seen["filters"]["excluded_sources"] == ["loverslab"]
    assert seen["filters"]["exclude_titles"] == ["Blocked Bimbo"]
    assert seen["filters"]["keyword_match_mode"] == "all"


@pytest.mark.asyncio
async def test_local_db_tool_applies_negative_filter_fields_in_sql_path():
    engine = _engine()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        target = Mod(
            source="nexusmods",
            external_id="1",
            game="Skyrim Special Edition",
            title="Bimbo Preset",
            updated_at_remote="2026-05-20T00:00:00+00:00",
            url="https://example.com/1",
            first_seen_at="2026-05-20T00:00:00+00:00",
            last_seen_at="2026-05-20T00:00:00+00:00",
        )
        blocked_source = Mod(
            source="loverslab",
            external_id="2",
            game="Skyrim Special Edition",
            title="LoversLab Bimbo Preset",
            updated_at_remote="2026-05-21T00:00:00+00:00",
            url="https://example.com/2",
            first_seen_at="2026-05-21T00:00:00+00:00",
            last_seen_at="2026-05-21T00:00:00+00:00",
        )
        blocked_title = Mod(
            source="nexusmods",
            external_id="3",
            game="Skyrim Special Edition",
            title="Blocked Bimbo Preset",
            updated_at_remote="2026-05-22T00:00:00+00:00",
            url="https://example.com/3",
            first_seen_at="2026-05-22T00:00:00+00:00",
            last_seen_at="2026-05-22T00:00:00+00:00",
        )
        partial = Mod(
            source="nexusmods",
            external_id="4",
            game="Skyrim Special Edition",
            title="Bimbo Outfit",
            updated_at_remote="2026-05-23T00:00:00+00:00",
            url="https://example.com/4",
            first_seen_at="2026-05-23T00:00:00+00:00",
            last_seen_at="2026-05-23T00:00:00+00:00",
        )
        session.add_all([target, blocked_source, blocked_title, partial])
        session.commit()

        plan = SearchPlan.from_query_plan(
            {
                "keywords": ["bimbo", "preset"],
                "excluded_sources": ["loverslab"],
                "exclude_titles": ["Blocked Bimbo Preset"],
                "keyword_match_mode": "all",
                "sort_field": "updated_at_remote",
                "limit": 8,
            }
        )
        results = await LocalDbSearchTool(session).run(LocalDbSearchInput(query="bimbo preset", plan=plan))

    assert [result.mod.title for result in results] == ["Bimbo Preset"]


@pytest.mark.asyncio
async def test_local_db_tool_relaxes_strong_filters_for_open_discovery(monkeypatch):
    engine = _engine()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        mod = Mod(
            source="nexusmods",
            external_id="1",
            game="Skyrim Special Edition",
            title="Bimbo Roleplay Framework",
            category="Gameplay",
            url="https://example.com/1",
            first_seen_at="2026-05-20T00:00:00+00:00",
            last_seen_at="2026-05-20T00:00:00+00:00",
        )
        session.add(mod)
        session.commit()
        session.refresh(mod)
        seen = {}

        def fake_query_mods_fts(session_arg, *, keywords, filters, limit):
            seen["keywords"] = keywords
            seen["filters"] = filters
            seen["limit"] = limit
            return [SqliteFtsResult(mod=mod, score=80)]

        monkeypatch.setattr(mod_search_service, "query_mods_fts", fake_query_mods_fts)

        plan = SearchPlan.from_query_plan(
            {
                "keywords": ["bimbo"],
                "open_discovery": True,
                "retrieval_mode": "fuzzy",
                "sources": ["loverslab"],
                "categories": ["Gameplay"],
                "requirement_terms": ["framework"],
                "compatibility_terms": ["quest"],
                "sort_field": "relevance",
                "limit": 8,
            }
        )
        results = await LocalDbSearchTool(session).run(LocalDbSearchInput(query="有什么bimbo路线mod", plan=plan))

    assert seen["filters"]["retrieval_mode"] == "fuzzy"
    assert seen["filters"]["sources"] == []
    assert seen["filters"]["categories"] == []
    assert seen["filters"]["requirement_terms"] == []
    assert "bimbo" in seen["keywords"]
    assert "bimbos" in seen["keywords"]
    assert "bimbofication" in seen["keywords"]
    assert "gameplay" in seen["keywords"]
    assert "framework" in seen["keywords"]
    assert "quest" in seen["keywords"]
    assert results[0].mod.title == "Bimbo Roleplay Framework"


@pytest.mark.asyncio
async def test_local_db_tool_drops_broad_semantic_expansions_for_open_discovery(monkeypatch):
    engine = _engine()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        mod = Mod(
            source="loverslab",
            external_id="1",
            game="skyrimspecialedition",
            title="Bimbos Of Skyrim LE SE",
            url="https://example.com/1",
            first_seen_at="2026-05-20T00:00:00+00:00",
            last_seen_at="2026-05-20T00:00:00+00:00",
        )
        session.add(mod)
        session.commit()
        session.refresh(mod)
        seen = {}

        def fake_query_mods_fts(session_arg, *, keywords, filters, limit):
            seen["keywords"] = keywords
            seen["filters"] = filters
            return [SqliteFtsResult(mod=mod, score=80)]

        monkeypatch.setattr(mod_search_service, "query_mods_fts", fake_query_mods_fts)

        plan = SearchPlan.from_query_plan(
            {
                "keywords": ["bimbo", "roleplay", "character progression", "scenario", "quest"],
                "category_hints": ["Bimbos Of Skyrim", "identity_style"],
                "open_discovery": True,
                "retrieval_mode": "fuzzy",
                "sort_field": "relevance",
                "limit": 8,
            }
        )
        await LocalDbSearchTool(session).run(LocalDbSearchInput(query="天际有什么扮演bimbo的MOD", plan=plan))

    assert seen["keywords"] == ["bimbo", "bimbos", "bimbofication", "bimbofied"]
    assert "Bimbos Of Skyrim" not in seen["keywords"]
    assert "identity_style" not in seen["keywords"]


@pytest.mark.asyncio
async def test_local_db_tool_preserves_explicit_source_for_open_discovery(monkeypatch):
    engine = _engine()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        mod = Mod(
            source="loverslab",
            external_id="1",
            game="skyrimspecialedition",
            title="LoversLab Bimbo Roleplay",
            url="https://example.com/1",
            first_seen_at="2026-05-20T00:00:00+00:00",
            last_seen_at="2026-05-20T00:00:00+00:00",
        )
        session.add(mod)
        session.commit()
        session.refresh(mod)
        seen = {}

        def fake_query_mods_fts(session_arg, *, keywords, filters, limit):
            seen["filters"] = filters
            seen["limit"] = limit
            return [SqliteFtsResult(mod=mod, score=80)]

        monkeypatch.setattr(mod_search_service, "query_mods_fts", fake_query_mods_fts)

        plan = SearchPlan.from_query_plan(
            {
                "keywords": ["bimbo"],
                "open_discovery": True,
                "retrieval_mode": "fuzzy",
                "sources": ["loverslab"],
                "sort_field": "relevance",
                "limit": 8,
                "candidate_pool_limit": 40,
            }
        )
        await LocalDbSearchTool(session).run(LocalDbSearchInput(query="LoversLab 有什么 bimbo MOD", plan=plan))

    assert seen["filters"]["sources"] == ["loverslab"]
    assert seen["limit"] == 40
