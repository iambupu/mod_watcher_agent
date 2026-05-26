import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.models.mod import Mod
from app.models.summary import ModSummary
from app.services.agent.retrievers.sqlite_fts_retriever import (
    ensure_mods_fts,
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
