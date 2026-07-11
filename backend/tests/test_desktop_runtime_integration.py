from __future__ import annotations

from fastapi.testclient import TestClient

from app import security
from app.api import routes_loverslab_browser
from app.main import app as fastapi_app
from app.services.browser import page_fetcher


def test_health_reports_desktop_runtime(monkeypatch) -> None:
    monkeypatch.setenv("MW_DESKTOP_MODE", "true")
    monkeypatch.setattr(
        security,
        "_load_runtime_policy",
        lambda force_refresh=False: security.RuntimePolicy(
            profile="local_relaxed",
            allow_lan=False,
            admin_token="",
        ),
    )

    client = TestClient(fastapi_app)
    try:
        response = client.get("/api/health")
    finally:
        client.close()

    assert response.status_code == 200
    payload = response.json()
    assert payload["desktop"] is True
    assert {
        "status",
        "version",
        "database",
        "scheduler",
        "frontend",
        "desktop",
        "packaged",
    } <= payload.keys()


def test_browser_paths_follow_runtime_environment(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("MW_BROWSER_PROFILE_ROOT", str(tmp_path / "profiles"))
    monkeypatch.setenv("MW_SNAPSHOT_ROOT", str(tmp_path / "snapshots"))

    assert page_fetcher.browser_profile_root() == tmp_path / "profiles"
    assert routes_loverslab_browser.snapshot_root() == tmp_path / "snapshots"
