from sqlalchemy import text
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app import db as app_db
from app.models.favorite import Favorite
from app.models.mod import Mod
from app.models.summary import ModSummary
from app.models.update_event import ModUpdateEvent


def _make_engine():
    return create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


def test_normalize_mod_identity_merges_duplicates_and_relinks_foreign_keys(monkeypatch) -> None:
    engine = _make_engine()
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        legacy = Mod(
            source="nexusmods",
            external_id="1001",
            game="Skyrim Special Edition",
            game_domain="skyrimspecialedition",
            title="Legacy Skyrim Row",
            url="https://www.nexusmods.com/skyrimspecialedition/mods/1001",
            first_seen_at="2026-01-01T00:00:00+00:00",
            last_seen_at="2026-01-01T00:00:00+00:00",
        )
        canonical = Mod(
            source="nexusmods",
            external_id="skyrimspecialedition:1001",
            game="Skyrim Special Edition",
            game_domain="skyrimspecialedition",
            title="Canonical Skyrim Row",
            url="https://www.nexusmods.com/skyrimspecialedition/mods/1001",
            first_seen_at="2026-01-02T00:00:00+00:00",
            last_seen_at="2026-01-02T00:00:00+00:00",
        )
        numeric_other_game = Mod(
            source="nexusmods",
            external_id="2002",
            game="Stellar Blade",
            game_domain="stellarblade",
            title="Stellar Legacy Row",
            url="https://www.nexusmods.com/stellarblade/mods/2002",
            first_seen_at="2026-01-03T00:00:00+00:00",
            last_seen_at="2026-01-03T00:00:00+00:00",
        )
        session.add_all([legacy, canonical, numeric_other_game])
        session.commit()
        session.refresh(legacy)
        session.refresh(canonical)

        legacy_favorite = Favorite(
            mod_id=legacy.id,
            tracking_enabled=False,
            notify_on_update=True,
            user_note="legacy note",
            user_tags_json='["legacy"]',
            last_known_version="1.0",
            last_known_updated_at="2026-01-03T00:00:00+00:00",
            last_checked_at="2026-01-03T00:00:00+00:00",
            created_at="2026-01-03T00:00:00+00:00",
            updated_at="2026-01-03T00:00:00+00:00",
        )
        canonical_favorite = Favorite(
            mod_id=canonical.id,
            tracking_enabled=True,
            notify_on_update=False,
            user_note="",
            user_tags_json='["canonical"]',
            last_known_version=None,
            last_known_updated_at="2026-01-02T00:00:00+00:00",
            last_checked_at="2026-01-02T00:00:00+00:00",
            created_at="2026-01-02T00:00:00+00:00",
            updated_at="2026-01-02T00:00:00+00:00",
        )
        session.add_all([legacy_favorite, canonical_favorite])
        session.commit()
        session.refresh(legacy_favorite)
        session.refresh(canonical_favorite)

        session.add(
            ModSummary(
                mod_id=legacy.id,
                language="zh-CN",
                summary_type="manual",
                content="legacy summary",
                model="test",
                generated_at="2026-01-04T00:00:00+00:00",
            )
        )
        session.add(
            ModUpdateEvent(
                mod_id=legacy.id,
                favorite_id=legacy_favorite.id,
                old_version="0.9",
                new_version="1.0",
                old_updated_at="2026-01-01T00:00:00+00:00",
                new_updated_at="2026-01-03T00:00:00+00:00",
                raw_changelog="x",
                change_summary="y",
                detected_at="2026-01-04T00:00:00+00:00",
                seen=False,
            )
        )
        session.commit()

    monkeypatch.setattr(app_db, "engine", engine)
    app_db._normalize_mod_identity_data()

    with Session(engine) as session:
        skyrim_rows = session.exec(
            select(Mod).where(
                Mod.source == "nexusmods",
                Mod.external_id == "skyrimspecialedition:1001",
            )
        ).all()
        assert len(skyrim_rows) == 1
        assert session.exec(
            select(Mod).where(Mod.source == "nexusmods", Mod.external_id == "1001")
        ).first() is None

        stellar_row = session.exec(
            select(Mod).where(
                Mod.source == "nexusmods",
                Mod.title == "Stellar Legacy Row",
            )
        ).first()
        assert stellar_row is not None
        assert stellar_row.external_id == "stellarblade:2002"

        merged_favorites = session.exec(
            select(Favorite).where(Favorite.mod_id == skyrim_rows[0].id)
        ).all()
        assert len(merged_favorites) == 1
        favorite = merged_favorites[0]
        assert favorite.tracking_enabled is True
        assert favorite.notify_on_update is True
        assert favorite.user_note == "legacy note"
        assert favorite.user_tags_json == '["canonical", "legacy"]'
        assert favorite.last_known_version == "1.0"

        summaries = session.exec(select(ModSummary)).all()
        assert len(summaries) == 1
        assert summaries[0].mod_id == skyrim_rows[0].id

        events = session.exec(select(ModUpdateEvent)).all()
        assert len(events) == 1
        assert events[0].mod_id == skyrim_rows[0].id
        assert events[0].favorite_id == favorite.id


def test_normalize_mod_identity_scopes_loverslab_ids_by_game_and_merges_duplicates(monkeypatch) -> None:
    engine = _make_engine()
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        legacy = Mod(
            source="loverslab",
            external_id="48837",
            game="X-Change Life",
            title="Legacy LoversLab Row",
            url="https://www.loverslab.com/files/file/48837-old-title/",
            first_seen_at="2026-01-01T00:00:00+00:00",
            last_seen_at="2026-01-01T00:00:00+00:00",
        )
        canonical = Mod(
            source="loverslab",
            external_id="x-change-life:48837",
            game="X-Change Life",
            title="Canonical LoversLab Row",
            url="https://www.loverslab.com/files/file/48837-new-title/",
            first_seen_at="2026-01-02T00:00:00+00:00",
            last_seen_at="2026-01-02T00:00:00+00:00",
        )
        other_game = Mod(
            source="loverslab",
            external_id="48838",
            game="Stellar Blade",
            title="Stellar LoversLab Row",
            url="https://www.loverslab.com/files/file/48838-stellar/",
            first_seen_at="2026-01-03T00:00:00+00:00",
            last_seen_at="2026-01-03T00:00:00+00:00",
        )
        generic = Mod(
            source="loverslab",
            external_id="99999",
            game="LoversLab",
            title="Generic LoversLab Row",
            url="https://www.loverslab.com/files/file/99999-generic/",
            first_seen_at="2026-01-04T00:00:00+00:00",
            last_seen_at="2026-01-04T00:00:00+00:00",
        )
        session.add_all([legacy, canonical, other_game, generic])
        session.commit()
        session.refresh(legacy)
        session.refresh(canonical)

        session.add(
            Favorite(
                mod_id=legacy.id,
                tracking_enabled=True,
                notify_on_update=True,
                user_note="legacy favorite",
                user_tags_json='["legacy"]',
                created_at="2026-01-05T00:00:00+00:00",
                updated_at="2026-01-05T00:00:00+00:00",
            )
        )
        session.add(
            ModSummary(
                mod_id=legacy.id,
                language="zh-CN",
                summary_type="manual",
                content="legacy loverslab summary",
                model="test",
                generated_at="2026-01-05T00:00:00+00:00",
            )
        )
        session.commit()

    monkeypatch.setattr(app_db, "engine", engine)
    app_db._normalize_mod_identity_data()

    with Session(engine) as session:
        rows = session.exec(select(Mod).where(Mod.source == "loverslab")).all()
        by_title = {row.title: row for row in rows}

        assert "Legacy LoversLab Row" not in by_title
        assert by_title["Canonical LoversLab Row"].external_id == "x-change-life:48837"
        assert by_title["Stellar LoversLab Row"].external_id == "stellar-blade:48838"
        assert by_title["Generic LoversLab Row"].external_id == "99999"

        favorite = session.exec(select(Favorite)).one()
        assert favorite.mod_id == by_title["Canonical LoversLab Row"].id
        assert favorite.user_note == "legacy favorite"

        summary = session.exec(select(ModSummary)).one()
        assert summary.mod_id == by_title["Canonical LoversLab Row"].id


def test_normalize_mod_identity_is_safe_for_legacy_minimal_mod_table(monkeypatch) -> None:
    engine = _make_engine()
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE mods (id INTEGER PRIMARY KEY, source TEXT NOT NULL, external_id TEXT NOT NULL)"))

    monkeypatch.setattr(app_db, "engine", engine)
    app_db._normalize_mod_identity_data()

    with engine.begin() as conn:
        count = conn.execute(text("SELECT COUNT(*) FROM mods")).scalar_one()
    assert count == 0
