# 中文注释：说明 backend/app/tests/test_routes_rules.py 的模块职责，便于后续维护定位。

"""Tests for rules API routes."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.adapters.base import BaseAdapter
from app.api import routes_rules
from app.db import get_session
from app.main import app as fastapi_app
from app.models.mod import Mod
from app.models.mod_item import ModItem
from app.models.watch_rule import WatchRule
from app.services.rule_import_service import RuleImportError, require_public_host


@pytest.fixture(name="engine")
def engine_fixture():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    yield engine


@pytest.fixture(name="session")
def session_fixture(engine):
    with Session(engine) as session:
        yield session


@pytest.fixture(name="client")
def client_fixture(engine):
    def override_get_session():
        with Session(engine) as session:
            yield session

    fastapi_app.dependency_overrides[get_session] = override_get_session
    client = TestClient(fastapi_app)
    yield client
    fastapi_app.dependency_overrides.clear()


def make_nexusmods_payload(**overrides):
    """Build a valid NexusMods rule creation payload."""
    payload = {
        "name": "Skyrim SE Watcher",
        "enabled": True,
        "source": "nexusmods",
        "sourceConfig": {
            "gameDomainName": "skyrimspecialedition",
            "updatedSinceDays": 7,
            "queryMode": "updated",
            "categoryNames": [],
            "tags": [],
            "sortBy": "updatedAt_desc",
        },
        "filters": {
            "includeKeywords": [],
            "excludeKeywords": [],
            "adultPolicy": "include",
            "missingMetricsPolicy": "pass",
        },
        "notification": {
            "enabled": False,
            "mode": "daily_digest",
            "channels": [],
        },
    }
    payload.update(overrides)
    return payload


def make_loverslab_payload(**overrides):
    """Build a valid LoversLab rule creation payload."""
    payload = {
        "name": "LL Skyrim Watcher",
        "enabled": True,
        "source": "loverslab",
        "sourceConfig": {
            "gameLabel": "Skyrim SE",
            "feedUrls": ["https://www.loverslab.com/files/rss/"],
            "maxItemsPerRun": 50,
            "updateDetection": "published_time",
        },
        "filters": {
            "includeKeywords": [],
            "excludeKeywords": [],
            "adultPolicy": "include",
            "missingMetricsPolicy": "pass",
        },
        "notification": {
            "enabled": False,
            "mode": "daily_digest",
            "channels": [],
        },
    }
    payload.update(overrides)
    return payload


class _RouteMockNexusAdapter(BaseAdapter):
    source = "route_mock_nexus"

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key

    async def fetch(self, source_config_json: str) -> list[ModItem]:
        return [
            ModItem(
                source_id="1001",
                source="nexusmods",
                name="Sword Mod",
                game="Skyrim Special Edition",
                url="https://www.nexusmods.com/skyrimspecialedition/mods/1001",
                summary="A test sword mod.",
                author="TestAuthor",
                downloads=100,
                endorsements=10,
                raw={
                    "version": "1.0",
                    "game": {"domainName": "skyrimspecialedition"},
                    "updatedAt": "2026-05-01T00:00:00Z",
                },
            )
        ]

    async def fetch_mod_detail(self, external_id: str, game_domain=None):
        return None

    def normalize(self, raw_item: dict) -> ModItem:
        return ModItem(source_id="", source="", name="", game="", url="")


class _RouteMockLoversLabTimeoutAdapter(BaseAdapter):
    source = "route_mock_loverslab_timeout"

    async def fetch(self, source_config_json: str) -> list[ModItem]:
        raise TimeoutError("RSS request timeout")

    async def fetch_mod_detail(self, external_id: str, game_domain=None):
        return None

    def normalize(self, raw_item: dict) -> ModItem:
        return ModItem(source_id="", source="", name="", game="", url="")


class _RouteMockLoversLabTooLargeAdapter(BaseAdapter):
    source = "route_mock_loverslab_too_large"

    async def fetch(self, source_config_json: str) -> list[ModItem]:
        raise ValueError("RSS payload too large")

    async def fetch_mod_detail(self, external_id: str, game_domain=None):
        return None

    def normalize(self, raw_item: dict) -> ModItem:
        return ModItem(source_id="", source="", name="", game="", url="")


class _RouteMockLoversLabInvalidFeedAdapter(BaseAdapter):
    source = "route_mock_loverslab_invalid_feed"

    async def fetch(self, source_config_json: str) -> list[ModItem]:
        raise ValueError("Invalid RSS/Atom feed: malformed XML")

    async def fetch_mod_detail(self, external_id: str, game_domain=None):
        return None

    def normalize(self, raw_item: dict) -> ModItem:
        return ModItem(source_id="", source="", name="", game="", url="")


@pytest.fixture
def mock_nexus_adapter():
    saved = BaseAdapter.adapters.get("nexusmods")
    BaseAdapter.adapters["nexusmods"] = _RouteMockNexusAdapter
    yield
    if saved is None:
        BaseAdapter.adapters.pop("nexusmods", None)
    else:
        BaseAdapter.adapters["nexusmods"] = saved


class TestCreateRule:
    def test_create_rule_nexusmods(self, client):
        payload = make_nexusmods_payload()
        response = client.post("/api/rules", json=payload)
        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "Skyrim SE Watcher"
        assert data["source"] == "nexusmods"
        assert data["sourceConfig"]["gameDomainName"] == "skyrimspecialedition"
        assert data["filters"]["adultPolicy"] == "include"
        assert "id" in data
        assert "created_at" in data
        assert "updated_at" in data

    def test_create_rule_loverslab(self, client):
        payload = make_loverslab_payload()
        response = client.post("/api/rules", json=payload)
        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "LL Skyrim Watcher"
        assert data["source"] == "loverslab"
        assert data["sourceConfig"]["gameLabel"] == "Skyrim SE"
        assert data["sourceConfig"]["feedUrls"] == ["https://www.loverslab.com/files/rss/"]

    def test_create_rule_validation_error(self, client):
        payload = make_nexusmods_payload()
        del payload["name"]
        response = client.post("/api/rules", json=payload)
        assert response.status_code == 422

    def test_create_rule_invalid_source_config(self, client):
        payload = make_nexusmods_payload()
        del payload["sourceConfig"]["gameDomainName"]
        response = client.post("/api/rules", json=payload)
        assert response.status_code == 422

    def test_create_rule_rolls_back_when_scheduler_registration_fails(self, engine, monkeypatch):
        def override_get_session():
            with Session(engine) as session:
                yield session

        def fail_register_jobs(_session: Session) -> None:
            raise RuntimeError("scheduler unavailable")

        fastapi_app.dependency_overrides[get_session] = override_get_session
        monkeypatch.setattr(routes_rules, "register_jobs", fail_register_jobs)
        client = TestClient(fastapi_app, raise_server_exceptions=False)
        try:
            response = client.post("/api/rules", json=make_nexusmods_payload())
        finally:
            fastapi_app.dependency_overrides.clear()

        assert response.status_code == 500
        with Session(engine) as session:
            rules = session.exec(select(WatchRule)).all()
        assert rules == []

    def test_create_loverslab_rss_requires_feed_urls(self, client):
        payload = make_loverslab_payload()
        payload["sourceConfig"]["feedUrls"] = []
        response = client.post("/api/rules", json=payload)
        assert response.status_code == 422


class TestPatchRule:
    def test_patch_rule_update_fields(self, client):
        create_resp = client.post("/api/rules", json=make_nexusmods_payload())
        rule_id = create_resp.json()["id"]

        patch_payload = {
            "name": "Updated Watcher",
            "enabled": False,
            "filters": {
                "includeKeywords": ["armor"],
                "excludeKeywords": [],
                "adultPolicy": "exclude",
                "missingMetricsPolicy": "reject",
            },
        }
        response = client.patch(f"/api/rules/{rule_id}", json=patch_payload)
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Updated Watcher"
        assert data["enabled"] is False
        assert data["filters"]["includeKeywords"] == ["armor"]
        assert data["filters"]["adultPolicy"] == "exclude"
        assert data["filters"]["missingMetricsPolicy"] == "reject"
        assert data["source"] == "nexusmods"

    def test_patch_rule_cannot_change_source(self, client):
        create_resp = client.post("/api/rules", json=make_nexusmods_payload())
        rule_id = create_resp.json()["id"]

        patch_payload = {"source": "loverslab"}
        response = client.patch(f"/api/rules/{rule_id}", json=patch_payload)
        assert response.status_code == 422

    def test_patch_rule_rejects_mismatched_source_config(self, client):
        create_resp = client.post("/api/rules", json=make_nexusmods_payload())
        rule_id = create_resp.json()["id"]

        patch_payload = {
            "sourceConfig": {
                "gameLabel": "Skyrim SE",
                "feedUrls": ["https://www.loverslab.com/files/rss/"],
            }
        }
        response = client.patch(f"/api/rules/{rule_id}", json=patch_payload)
        assert response.status_code == 422


class TestGetRules:
    def test_get_rules_normalizes_invalid_stored_interval(self, client, session):
        for name, interval_minutes in [("Too low interval", -5), ("Too high interval", 2000)]:
            session.add(
                WatchRule(
                    name=name,
                    enabled=True,
                    source="nexusmods",
                    interval_minutes=interval_minutes,
                    source_config_json='{"gameDomainName":"skyrimspecialedition","updatedSinceDays":7}',
                    filters_json="{}",
                    notification_json="{}",
                    created_at="2026-05-01T00:00:00+00:00",
                    updated_at="2026-05-01T00:00:00+00:00",
                )
            )
        session.commit()

        response = client.get("/api/rules")

        assert response.status_code == 200
        intervals_by_name = {item["name"]: item["intervalMinutes"] for item in response.json()}
        assert intervals_by_name["Too low interval"] == 360
        assert intervals_by_name["Too high interval"] == 1440

    def test_get_rules_recovers_from_invalid_stored_json_payloads(self, client, session):
        session.add(
            WatchRule(
                name="Corrupt json",
                enabled=True,
                source="nexusmods",
                interval_minutes=30,
                source_config_json="{bad json",
                filters_json="[not-object]",
                notification_json="null",
                created_at="2026-05-01T00:00:00+00:00",
                updated_at="2026-05-01T00:00:00+00:00",
            )
        )
        session.commit()

        response = client.get("/api/rules")

        assert response.status_code == 200
        data = response.json()
        assert data[0]["name"] == "Corrupt json"
        assert data[0]["sourceConfig"]["gameDomainName"] == "skyrimspecialedition"
        assert data[0]["filters"]["includeKeywords"] == []
        assert data[0]["notification"]["mode"] == "daily_digest"

    def test_get_rules_with_source_filter(self, client):
        client.post("/api/rules", json=make_nexusmods_payload(name="NM Rule"))
        client.post("/api/rules", json=make_loverslab_payload(name="LL Rule"))

        response = client.get("/api/rules?source=nexusmods")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["name"] == "NM Rule"
        assert data[0]["source"] == "nexusmods"

    def test_get_rules_with_enabled_filter(self, client):
        client.post("/api/rules", json=make_nexusmods_payload(name="Enabled", enabled=True))
        client.post("/api/rules", json=make_nexusmods_payload(name="Disabled", enabled=False))

        response = client.get("/api/rules?enabled=true")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["name"] == "Enabled"

    def test_get_rules_with_q_search(self, client):
        client.post("/api/rules", json=make_nexusmods_payload(name="Skyrim Mods"))
        client.post("/api/rules", json=make_nexusmods_payload(name="Fallout Mods"))

        response = client.get("/api/rules?q=skyrim")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["name"] == "Skyrim Mods"


class TestImportExportRules:
    def test_export_rules_uses_static_route(self, client):
        client.post("/api/rules", json=make_nexusmods_payload(name="Exported Rule"))

        response = client.get("/api/rules/export")

        assert response.status_code == 200
        data = response.json()
        assert data["version"] == 1
        assert data["rules"][0]["name"] == "Exported Rule"
        assert data["rules"][0]["intervalMinutes"] == 360

    def test_import_url_blocks_private_redirect_before_following(self, client, monkeypatch):
        requested_urls: list[str] = []

        class FakeResponse:
            status_code = 302
            headers = {"Location": "http://127.0.0.1/rules.json"}

            def raise_for_status(self):
                raise AssertionError("redirect response should not be treated as final")

        class FakeClient:
            def __init__(self, *args, **kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return None

            def get(self, url):
                requested_urls.append(url)
                return FakeResponse()

        def fake_require_public_host(hostname):
            if hostname == "127.0.0.1":
                raise routes_rules.HTTPException(status_code=422, detail="Private or loopback hosts are not allowed")
            return {"203.0.113.10"}

        monkeypatch.setattr(routes_rules.httpx, "Client", FakeClient)
        monkeypatch.setattr(routes_rules, "_require_public_host", fake_require_public_host)

        response = client.post("/api/rules/import", json={"url": "https://example.com/rules.json"})

        assert response.status_code == 422
        assert requested_urls == ["https://example.com/rules.json"]

    @pytest.mark.parametrize("ip", ["127.0.0.1", "10.0.0.1", "169.254.1.1", "224.0.0.1", "0.0.0.0"])
    def test_require_public_host_rejects_non_public_addresses(self, monkeypatch, ip):
        monkeypatch.setattr(
            "app.services.rule_import_service.socket.getaddrinfo",
            lambda *_args, **_kwargs: [(None, None, None, None, (ip, 0))],
        )

        with pytest.raises(RuleImportError, match="Only public hosts are allowed"):
            require_public_host("example.com")


class TestDryRun:
    def test_test_rule_nexusmods_dry_run(self, client, mock_nexus_adapter):
        payload = make_nexusmods_payload(name="DryRun Test")
        request_body = {"rule": payload, "dryRun": True}

        response = client.post("/api/rules/test", json=request_body)
        assert response.status_code == 200
        data = response.json()
        assert "scanned" in data
        assert "normalized" in data
        assert "passedDeterministicFilters" in data
        assert "items" in data
        assert isinstance(data["items"], list)
        assert data["scanned"] == 1
        assert data["items"][0]["external_id"] == "1001"

    def test_test_rule_preview_keeps_existing_matches_with_rejection_reason(self, client, session, mock_nexus_adapter):
        session.add(
            Mod(
                source="nexusmods",
                external_id="1001",
                game="Skyrim Special Edition",
                title="Existing Mod",
                url="https://example.com/mod/1001",
                first_seen_at="2025-01-01T00:00:00+00:00",
                last_seen_at="2025-01-01T00:00:00+00:00",
            )
        )
        session.commit()

        payload = make_nexusmods_payload(name="DryRun Existing Preview")
        request_body = {"rule": payload, "dryRun": True}

        response = client.post("/api/rules/test", json=request_body)

        assert response.status_code == 200
        data = response.json()
        assert data["passedLlmFilters"] == 1
        assert data["rejectedReasons"] == {"already_exists_or_ignored": 1}
        assert data["rejectedItems"][0]["reason"] == "already_exists_or_ignored"
        assert data["items"][0]["external_id"] == "1001"

    @pytest.mark.parametrize(
        ("adapter_cls", "expected_detail"),
        [
            (_RouteMockLoversLabTimeoutAdapter, "RSS request timeout"),
            (_RouteMockLoversLabTooLargeAdapter, "RSS payload too large"),
            (_RouteMockLoversLabInvalidFeedAdapter, "Invalid RSS/Atom feed"),
        ],
    )
    def test_test_rule_loverslab_dry_run_failure_paths(self, client, adapter_cls, expected_detail):
        saved = BaseAdapter.adapters.get("loverslab")
        BaseAdapter.adapters["loverslab"] = adapter_cls
        try:
            payload = make_loverslab_payload(name="LoversLab DryRun Error")
            request_body = {"rule": payload, "dryRun": True}
            response = client.post("/api/rules/test", json=request_body)
        finally:
            if saved is None:
                BaseAdapter.adapters.pop("loverslab", None)
            else:
                BaseAdapter.adapters["loverslab"] = saved

        assert response.status_code == 502
        assert expected_detail in response.json()["detail"]

class TestRunRule:
    def test_run_rule_discovery(self, client, mock_nexus_adapter):
        create_resp = client.post("/api/rules", json=make_nexusmods_payload(
            name="run-test",
        ))
        assert create_resp.status_code == 201
        rule_id = create_resp.json()["id"]

        run_resp = client.post(f"/api/rules/{rule_id}/run")
        assert run_resp.status_code == 202
        data = run_resp.json()
        assert data["status"] == "queued"
        assert isinstance(data["job_id"], int)

        job_resp = client.get(f"/api/jobs/{data['job_id']}")
        assert job_resp.status_code == 200
        job = job_resp.json()
        assert job["job_name"] == "run_rule_discovery"
        assert job["status"] == "queued"
        assert f'"rule_id": {rule_id}' in job["metadata_json"]

    def test_run_rule_not_found(self, client):
        run_resp = client.post("/api/rules/99999/run")
        assert run_resp.status_code == 404

    def test_run_rule_disabled(self, client):
        create_resp = client.post("/api/rules", json=make_nexusmods_payload(
            name="disabled-test",
            enabled=False,
        ))
        assert create_resp.status_code == 201
        rule_id = create_resp.json()["id"]

        run_resp = client.post(f"/api/rules/{rule_id}/run")
        assert run_resp.status_code == 400
        assert "disabled" in run_resp.json()["detail"].lower()
