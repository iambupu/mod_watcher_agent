"""Tests for /api/jobs/stats week-boundary behavior."""

from apscheduler.schedulers.base import STATE_PAUSED, STATE_RUNNING
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.api import routes_jobs
from app.db import get_session
from app.main import app as fastapi_app
from app.models.favorite import Favorite
from app.models.job_run import JobRun
from app.models.mod import Mod
from app.models.update_event import ModUpdateEvent
from app.models.watch_rule import WatchRule
from app.services import job_queue_service


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


def test_scheduler_status_reports_paused_state(monkeypatch):
    class FakeScheduler:
        state = STATE_PAUSED

        def get_jobs(self):
            return []

    monkeypatch.setattr(routes_jobs, "scheduler", FakeScheduler())
    client = TestClient(fastapi_app)

    response = client.get("/api/jobs/status")

    assert response.status_code == 200
    data = response.json()
    assert data["running"] is False
    assert data["state"] == STATE_PAUSED


def test_recent_job_runs_rejects_unbounded_limit():
    client = TestClient(fastapi_app)

    response = client.get("/api/jobs/runs/recent?limit=1000")

    assert response.status_code == 422


def test_recent_job_runs_accepts_max_dashboard_limit(monkeypatch):
    engine = _make_engine()
    SQLModel.metadata.create_all(engine)

    def override_get_session():
        with Session(engine) as session:
            yield session

    fastapi_app.dependency_overrides[get_session] = override_get_session
    client = TestClient(fastapi_app)

    try:
        with Session(engine) as session:
            session.add(JobRun(job_name="job", status="succeeded", started_at="2026-05-18T00:00:00+00:00"))
            session.commit()

        response = client.get("/api/jobs/runs/recent?limit=200")

        assert response.status_code == 200
        assert response.json()["items"][0]["job_name"] == "job"
    finally:
        fastapi_app.dependency_overrides.clear()


def test_scheduler_pause_and_resume_return_actual_state(monkeypatch):
    class FakeScheduler:
        state = STATE_RUNNING

        def pause(self):
            self.state = STATE_PAUSED

        def resume(self):
            self.state = STATE_RUNNING

    fake_scheduler = FakeScheduler()
    monkeypatch.setattr(routes_jobs, "scheduler", fake_scheduler)
    client = TestClient(fastapi_app)

    pause_response = client.post("/api/jobs/pause")
    resume_response = client.post("/api/jobs/resume")

    assert pause_response.status_code == 200
    assert pause_response.json()["running"] is False
    assert pause_response.json()["state"] == STATE_PAUSED
    assert resume_response.status_code == 200
    assert resume_response.json()["running"] is True
    assert resume_response.json()["state"] == STATE_RUNNING


def test_discovery_result_counter_ignores_bool_and_normalizes_dirty_counts():
    scanned, matched = job_queue_service._count_numeric_values({
        "rule-a": "3",
        "rule-b": True,
        "rule-c": -1,
        "rule-d": "bad",
    })

    assert scanned == 4
    assert matched == 3


def test_favorite_check_result_counter_parses_dirty_boolean_flags():
    scanned, matched = job_queue_service._count_favorite_check_result({
        "fav-a": {"update_detected": "true"},
        "fav-b": {"update_detected": "false"},
        "fav-c": {"update_detected": 1},
        "fav-d": {"update_detected": "bad"},
    })

    assert scanned == 4
    assert matched == 2
