"""Tests for /api/jobs/stats week-boundary behavior."""

from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.db import get_session
from app.main import app as fastapi_app
from app.models.favorite import Favorite
from app.models.mod import Mod
from app.models.update_event import ModUpdateEvent
from app.models.watch_rule import WatchRule


def _make_engine():
    return create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


def _make_mod(**kwargs) -> Mod:
    defaults = {
        "source": "loverslab",
        "external_id": "1001",
        "game": "skyrimspecialedition",
        "title": "Test Mod",
        "url": "https://example.com/mod/1001",
        "first_seen_at": "2026-05-18T00:00:00+00:00",
        "last_seen_at": "2026-05-18T00:00:00+00:00",
    }
    defaults.update(kwargs)
    return Mod(**defaults)


def test_stats_counts_new_mods_by_week_start(monkeypatch):
    engine = _make_engine()
    SQLModel.metadata.create_all(engine)

    def override_get_session():
        with Session(engine) as session:
            yield session

    fastapi_app.dependency_overrides[get_session] = override_get_session
    client = TestClient(fastapi_app)

    try:
        with Session(engine) as session:
            # One mod before week boundary, two mods inside this week.
            mod_old = _make_mod(
                external_id="old",
                title="Old Mod",
                first_seen_at="2026-05-11T15:59:59+00:00",
                last_seen_at="2026-05-11T15:59:59+00:00",
            )
            mod_new_a = _make_mod(
                external_id="new-a",
                title="New Mod A",
                first_seen_at="2026-05-11T16:00:00+00:00",
                last_seen_at="2026-05-11T16:00:00+00:00",
            )
            mod_new_b = _make_mod(
                external_id="new-b",
                title="New Mod B",
                first_seen_at="2026-05-12T00:00:00+00:00",
                last_seen_at="2026-05-12T00:00:00+00:00",
            )
            session.add_all([mod_old, mod_new_a, mod_new_b])
            session.commit()
            session.refresh(mod_new_a)

            session.add(
                Favorite(
                    mod_id=mod_new_a.id,
                    tracking_enabled=True,
                    notify_on_update=True,
                    created_at="2026-05-18T00:00:00+00:00",
                    updated_at="2026-05-18T00:00:00+00:00",
                )
            )
            session.add(
                WatchRule(
                    name="rule-1",
                    enabled=True,
                    source="loverslab",
                    source_config_json="{}",
                    filters_json="{}",
                    notification_json='{"enabled":false,"mode":"daily_digest","channels":[]}',
                    created_at="2026-05-18T00:00:00+00:00",
                    updated_at="2026-05-18T00:00:00+00:00",
                )
            )
            session.add(
                ModUpdateEvent(
                    mod_id=mod_new_a.id,
                    detected_at="2026-05-18T00:00:00+00:00",
                    seen=False,
                )
            )
            session.commit()

        # Monday 00:00 in UTC+8 equals Sunday 16:00 UTC.
        monkeypatch.setattr(
            "app.api.routes_jobs._current_week_start_utc_iso",
            lambda: "2026-05-11T16:00:00+00:00",
        )

        response = client.get("/api/jobs/stats")
        assert response.status_code == 200
        data = response.json()
        assert data["total_mods"] == 3
        assert data["new_mods_this_week"] == 2
        assert data["total_favorites"] == 1
        assert data["total_rules"] == 1
        assert data["unseen_updates"] == 1
    finally:
        fastapi_app.dependency_overrides.clear()
