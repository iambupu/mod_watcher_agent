from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import main as main_module
from app import security
from app.api import routes_loverslab_browser
from app.jobs import scheduler as scheduler_module
from app.services.browser import page_fetcher


class _SchedulerSpy:
    def __init__(
        self,
        events: list[str],
        *,
        shutdown_error: Exception | None = None,
    ) -> None:
        self.events = events
        self.running = False
        self.shutdown_error = shutdown_error

    def shutdown(self, *, wait: bool) -> None:
        self.events.append(f"scheduler.shutdown:{wait}")
        self.running = False
        if self.shutdown_error is not None:
            raise self.shutdown_error


class _FetcherSpy:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    async def close_login(self) -> None:
        self.events.append("browser.close")


def _install_lifespan_fakes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    session_exit_error: Exception | None = None,
    scheduler_shutdown_error: Exception | None = None,
) -> tuple[list[str], _SchedulerSpy]:
    events: list[str] = []
    fake_session = object()
    fake_scheduler = _SchedulerSpy(
        events,
        shutdown_error=scheduler_shutdown_error,
    )

    class FakeSessionContext:
        def __init__(self, _engine: object) -> None:
            pass

        def __enter__(self) -> object:
            events.append("session.enter")
            return fake_session

        def __exit__(self, _exc_type, _exc, _traceback) -> None:
            events.append("session.exit")
            if session_exit_error is not None:
                raise session_exit_error

    class FakeSettingsService:
        def __init__(self, session: object) -> None:
            assert session is fake_session

        def init_defaults(self) -> None:
            events.append("settings.init")

    class PolicySpy:
        def evaluate(self, request) -> security.AccessDecision:
            events.append(f"policy.evaluate:{request.url.path}")
            return security.AccessDecision(allow=True)

    async def setup_scheduler(_session: object) -> None:
        assert _session is fake_session
        events.append("scheduler.start")
        fake_scheduler.running = True

    async def deferred_maintenance() -> None:
        return None

    frontend_dir = tmp_path / "frontend-dist"
    frontend_dir.mkdir()
    frontend_dir.joinpath("index.html").write_text("test frontend", encoding="utf-8")

    monkeypatch.setattr(main_module, "require_safe_bind_host", lambda: events.append("bind.check"))
    monkeypatch.setattr(main_module, "setup_logging", lambda: events.append("logging.setup"))
    monkeypatch.setattr(main_module, "init_db", lambda: events.append("database.init"))
    monkeypatch.setattr(main_module, "Session", FakeSessionContext)
    monkeypatch.setattr(main_module, "SettingsService", FakeSettingsService)
    monkeypatch.setattr(main_module, "mark_interrupted_jobs_failed", lambda _session: 0)
    monkeypatch.setattr(main_module, "setup_scheduler", setup_scheduler)
    monkeypatch.setattr(main_module, "_run_deferred_startup_maintenance", deferred_maintenance)
    monkeypatch.setattr(main_module, "AccessPolicy", PolicySpy)
    monkeypatch.setattr(main_module, "FRONTEND_DIST_DIR", frontend_dir)
    monkeypatch.setattr(main_module, "is_frozen", lambda: True)
    monkeypatch.setattr(scheduler_module, "scheduler", fake_scheduler)
    monkeypatch.setattr(routes_loverslab_browser, "fetcher", _FetcherSpy(events))
    monkeypatch.setattr(main_module.app.state, "database_ready", False, raising=False)
    return events, fake_scheduler


def test_health_reports_live_desktop_runtime_and_runs_cleanup(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("MW_DESKTOP_MODE", "true")
    events, fake_scheduler = _install_lifespan_fakes(monkeypatch, tmp_path)

    with TestClient(main_module.app) as client:
        assert main_module.app.state.database_ready is True
        response = client.get("/api/health")

        assert response.status_code == 200
        assert response.json() == {
            "status": "ok",
            "version": main_module.app.version,
            "database": "ready",
            "scheduler": "running",
            "frontend": "ready",
            "desktop": True,
            "packaged": True,
        }
        assert fake_scheduler.running is True
        assert "scheduler.shutdown:False" not in events
        assert "browser.close" not in events

    assert events.count("policy.evaluate:/api/health") == 1
    assert events.index("scheduler.shutdown:False") < events.index("browser.close")
    assert main_module.app.state.database_ready is False


def test_lifespan_cleans_started_resources_when_startup_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    events, _fake_scheduler = _install_lifespan_fakes(
        monkeypatch,
        tmp_path,
        session_exit_error=RuntimeError("session teardown failed"),
    )

    with (
        pytest.raises(RuntimeError, match="session teardown failed"),
        TestClient(main_module.app),
    ):
        pass

    assert events.index("scheduler.shutdown:False") < events.index("browser.close")
    assert main_module.app.state.database_ready is False


def test_lifespan_continues_cleanup_when_scheduler_shutdown_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    events, _fake_scheduler = _install_lifespan_fakes(
        monkeypatch,
        tmp_path,
        scheduler_shutdown_error=RuntimeError("scheduler shutdown failed"),
    )

    with (
        caplog.at_level("ERROR", logger="app.main"),
        TestClient(main_module.app),
    ):
        pass

    assert events.index("scheduler.shutdown:False") < events.index("browser.close")
    assert "Failed to stop the scheduler" in caplog.text
    assert main_module.app.state.database_ready is False


def test_browser_paths_delegate_to_runtime_paths_after_import(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("MW_USER_DATA_DIR", "portable-runtime")
    monkeypatch.setenv("MW_BROWSER_PROFILE_ROOT", str(tmp_path / "legacy-profiles"))
    monkeypatch.setenv("MW_SNAPSHOT_ROOT", str(tmp_path / "legacy-snapshots"))

    assert page_fetcher.browser_profile_root() == Path("portable-runtime/data/browser_profiles")
    assert routes_loverslab_browser.snapshot_root() == Path("portable-runtime/data/snapshots")
