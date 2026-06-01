import pytest
from sqlalchemy import text
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.models.mod import Mod
from app.models.summary import ModSummary
from app.services.agent.retrievers.sqlite_fts_retriever import (
    ensure_mods_fts,
    mods_fts_needs_rebuild,
    query_mods_fts,
    rebuild_mods_fts,
)


@pytest.fixture(name="session")
def session_fixture():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _mod(**kwargs) -> Mod:
    defaults = {
        "source": "nexusmods",
        "external_id": "1",
        "game": "Stellar Blade",
        "title": "Ocean String",
        "url": "https://example.com",
        "first_seen_at": "2025-01-01T00:00:00",
        "last_seen_at": "2025-01-01T00:00:00",
        "adult_content": True,
    }
    defaults.update(kwargs)
    return Mod(**defaults)


def test_fts_retriever_matches_translated_summary_and_preserves_filters(session):
    target = _mod(external_id="1", title="Ocean String", category="Outfits")
    ignored = _mod(external_id="2", title="Ignored Outfit", ignored=True)
    sfw = _mod(external_id="3", title="Safe Outfit", adult_content=False)
    other_game = _mod(external_id="4", game="Skyrim", title="Skyrim Outfit")
    session.add_all([target, ignored, sfw, other_game])
    session.commit()
    session.refresh(target)
    session.add(
        ModSummary(
            mod_id=target.id,
            content="中文摘要：适合剑星的成人服装。",
            language="zh-CN",
            summary_type="brief",
            model="test",
            generated_at="2025-01-01T00:00:00",
        )
    )
    session.commit()

    ensure_mods_fts(session)
    rebuild_mods_fts(session)

    results = query_mods_fts(
        session,
        keywords=["成人服装"],
        filters={"games": ["Stellar Blade"], "adult_content": True},
        limit=5,
    )

    assert [item.mod.id for item in results] == [target.id]
    assert results[0].score > 0
    assert results[0].stage == "sqlite_fts"


def test_fts_retriever_returns_empty_for_missing_keywords(session):
    session.add(_mod(title="Ocean String"))
    session.commit()
    ensure_mods_fts(session)
    rebuild_mods_fts(session)

    assert query_mods_fts(session, keywords=[], filters={}, limit=5) == []


def test_fts_retriever_tolerates_invalid_limit(session):
    mod = _mod(title="Existing Local Mod")
    session.add(mod)
    session.commit()
    ensure_mods_fts(session)
    rebuild_mods_fts(session)

    results = query_mods_fts(session, keywords=["Existing Local"], filters={}, limit="many")  # type: ignore[arg-type]

    assert [item.mod.id for item in results] == [mod.id]


def test_fts_triggers_index_new_mods_and_summary_updates(session):
    assert ensure_mods_fts(session) is True
    mod = _mod(title="Late Imported Outfit", original_summary="initial")
    session.add(mod)
    session.commit()
    session.refresh(mod)

    title_results = query_mods_fts(session, keywords=["Late Imported"], filters={}, limit=5)
    assert [item.mod.id for item in title_results] == [mod.id]

    session.add(
        ModSummary(
            mod_id=mod.id,
            content="新增中文摘要：星刃晚礼服。",
            language="zh-CN",
            summary_type="brief",
            model="test",
            generated_at="2025-01-01T00:00:00",
        )
    )
    session.commit()

    summary_results = query_mods_fts(session, keywords=["晚礼服"], filters={}, limit=5)
    assert [item.mod.id for item in summary_results] == [mod.id]


def test_fts_needs_rebuild_when_schema_exists_but_index_is_empty(session):
    mod = _mod(title="Existing Local Mod")
    session.add(mod)
    session.commit()

    assert ensure_mods_fts(session) is True
    session.execute(text("DELETE FROM mods_fts"))
    session.commit()

    assert mods_fts_needs_rebuild(session) is True
    assert rebuild_mods_fts(session) is True
    assert mods_fts_needs_rebuild(session) is False
    results = query_mods_fts(session, keywords=["Existing Local"], filters={}, limit=5)
    assert [item.mod.id for item in results] == [mod.id]


def test_fts_needs_rebuild_when_summary_content_is_missing_from_existing_index(session):
    mod = _mod(title="Existing Local Mod")
    session.add(mod)
    session.commit()
    session.refresh(mod)
    session.add(
        ModSummary(
            mod_id=mod.id,
            content="中文摘要：包含重建检测关键字。",
            language="zh-CN",
            summary_type="brief",
            model="test",
            generated_at="2025-01-01T00:00:00",
        )
    )
    session.commit()

    assert ensure_mods_fts(session) is True
    assert rebuild_mods_fts(session) is True
    assert mods_fts_needs_rebuild(session) is False

    session.execute(text("UPDATE mods_fts SET translated_summary = '' WHERE mod_id = :mod_id"), {"mod_id": mod.id})
    session.commit()

    assert mods_fts_needs_rebuild(session) is True
    assert rebuild_mods_fts(session) is True
    assert mods_fts_needs_rebuild(session) is False


def test_fts_applies_negative_filters_and_all_keyword_mode(session):
    target = _mod(external_id="1", source="nexusmods", title="Bimbo Preset")
    blocked_source = _mod(external_id="2", source="loverslab", title="LoversLab Bimbo Preset")
    blocked_title = _mod(external_id="3", source="nexusmods", title="Blocked Bimbo Preset")
    partial = _mod(external_id="4", source="nexusmods", title="Bimbo Outfit")
    session.add_all([target, blocked_source, blocked_title, partial])
    session.commit()

    ensure_mods_fts(session)
    rebuild_mods_fts(session)

    results = query_mods_fts(
        session,
        keywords=["Bimbo", "Preset"],
        filters={
            "excluded_sources": ["loverslab"],
            "exclude_titles": ["Blocked Bimbo Preset"],
            "keyword_match_mode": "all",
        },
        limit=10,
    )

    assert [item.mod.title for item in results] == ["Bimbo Preset"]
