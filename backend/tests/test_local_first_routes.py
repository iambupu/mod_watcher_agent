from __future__ import annotations

import sys
import time
import types
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app import security
from app.db import get_session
from app.main import app as fastapi_app
from app.models.agent_message import AgentMessage
from app.models.settings import Setting
from app.services.settings_update_service import apply_settings_update


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

    security._policy_cache["value"] = None
    security._policy_cache["expires_at"] = 0.0
    security.engine = engine
    fastapi_app.dependency_overrides[get_session] = override_get_session
    client = TestClient(fastapi_app)
    yield client
    fastapi_app.dependency_overrides.clear()
    security._policy_cache["value"] = None
    security._policy_cache["expires_at"] = 0.0


def test_settings_put_invalid_numeric_returns_422(client: TestClient) -> None:
    resp = client.put("/api/settings", json={"settings": {"watchdog_check_interval_minutes": "abc"}})
    assert resp.status_code == 422
    assert "watchdog_check_interval_minutes" in resp.json()["detail"]


def test_settings_put_discord_webhook_requires_https(client: TestClient) -> None:
    resp = client.put("/api/settings", json={"settings": {"discord_webhook_url": "http://discord.com/api/webhooks/1/2"}})
    assert resp.status_code == 422
    assert "https://" in resp.json()["detail"]


def test_settings_import_reuses_settings_validation(client: TestClient) -> None:
    resp = client.post("/api/settings/import", json={"watchdog_check_interval_minutes": "abc"})

    assert resp.status_code == 422
    assert "watchdog_check_interval_minutes" in resp.json()["detail"]


def test_google_search_engine_id_is_visible_and_exported(
    client: TestClient,
    session: Session,
) -> None:
    session.add(Setting(
        key="google_search_api_key",
        value="google-secret-key",
        updated_at="2026-01-01T00:00:00+00:00",
    ))
    session.add(Setting(
        key="google_search_engine_id",
        value="public-cx-id",
        updated_at="2026-01-01T00:00:00+00:00",
    ))
    session.commit()

    get_resp = client.get("/api/settings")
    export_resp = client.post("/api/settings/export")

    assert get_resp.status_code == 200
    settings_payload = get_resp.json()["settings"]
    assert settings_payload["google_search_api_key"] == "********"
    assert settings_payload["google_search_engine_id"] == "public-cx-id"
    assert export_resp.status_code == 200
    exported = export_resp.json()
    assert "google_search_api_key" not in exported
    assert exported["google_search_engine_id"] == "public-cx-id"


def test_settings_rejects_token_profile_without_admin_token(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.services.settings_payload_service.settings.MW_ADMIN_TOKEN", "")

    resp = client.put("/api/settings", json={"settings": {"access_profile": "local_strict"}})

    assert resp.status_code == 422
    assert "MW_ADMIN_TOKEN" in resp.json()["detail"]


def test_settings_update_invalidates_runtime_policy_cache(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.services.settings_payload_service.settings.MW_ADMIN_TOKEN", "secret-token")
    monkeypatch.setattr(security.settings, "MW_ADMIN_TOKEN", "secret-token")
    security._policy_cache["value"] = security.RuntimePolicy(
        profile="local_relaxed",
        allow_lan=False,
        admin_token="secret-token",
    )
    security._policy_cache["expires_at"] = time.monotonic() + 60

    resp = client.put("/api/settings", json={"settings": {"access_profile": "local_strict"}})

    assert resp.status_code == 200
    policy = security._load_runtime_policy()
    assert policy.profile == "local_strict"


def test_settings_update_rolls_back_when_scheduler_registration_fails(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_register_jobs(_session: Session) -> None:
        raise RuntimeError("scheduler unavailable")

    monkeypatch.setattr("app.services.settings_update_service.register_jobs", fail_register_jobs)

    with pytest.raises(RuntimeError, match="scheduler unavailable"):
        apply_settings_update(session, {"watchdog_check_interval_minutes": "9"})

    row = session.exec(
        select(Setting).where(Setting.key == "watchdog_check_interval_minutes")
    ).first()
    assert row is None


def test_auto_start_updates_windows_registry_and_setting(
    client: TestClient,
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str]] = []
    fake_winreg = types.SimpleNamespace(
        HKEY_CURRENT_USER=object(),
        KEY_SET_VALUE=1,
        REG_SZ=1,
        OpenKey=lambda *args: "registry-key",
        SetValueEx=lambda key, name, reserved, reg_type, value: calls.append((name, value)),
        CloseKey=lambda key: None,
        DeleteValue=lambda key, name: None,
    )
    monkeypatch.setattr("app.api.routes_settings.platform.system", lambda: "Windows")
    monkeypatch.setitem(sys.modules, "winreg", fake_winreg)

    resp = client.post("/api/settings/auto-start", json={"enabled": True})

    assert resp.status_code == 200
    assert resp.json() == {"success": True, "enabled": True}
    assert calls
    assert calls[0][0] == "ModWatcherAgent"
    row = session.exec(select(Setting).where(Setting.key == "auto_start")).first()
    assert row is not None
    assert row.value == "true"


def test_llm_test_blocks_private_targets(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    class _FakeClient:
        async def chat(self, prompt: str, model: str, max_tokens: int = 64) -> str:  # noqa: ARG002
            return "ok"

    monkeypatch.setattr("app.api.routes_settings.create_llm_client", lambda provider, api_key, base_url: _FakeClient())

    blocked = client.post(
        "/api/settings/llm/test",
        json={
            "providers": [
                {
                    "provider": "openai",
                    "enabled": True,
                    "priority": 1,
                    "model": "gpt-4o-mini",
                    "api_key": "sk-real-key-123",
                    "base_url": "https://169.254.169.254/v1",
                }
            ]
        },
    )
    assert blocked.status_code == 422

    allowed = client.post(
        "/api/settings/llm/test",
        json={
            "providers": [
                {
                    "provider": "ollama",
                    "enabled": True,
                    "priority": 1,
                    "model": "qwen3:8b",
                    "api_key": "",
                    "base_url": "http://localhost:11434/v1",
                }
            ]
        },
    )
    assert allowed.status_code == 200
    assert allowed.json()["results"][0]["success"] is True


def test_conversation_state_isolation_and_stale_gate(client: TestClient, session: Session) -> None:
    session.add(
        AgentMessage(
            message_id="s2-msg",
            role="assistant",
            text="session2",
            session_id="s2",
            created_at="2026-01-01T00:00:00+00:00",
            sort_index=0,
        )
    )
    session.add(
        AgentMessage(
            message_id="old-s1-msg",
            role="assistant",
            text="old session1",
            session_id="s1",
            created_at="2026-01-01T00:00:00+00:00",
            sort_index=0,
        )
    )
    session.commit()

    now = datetime.now(UTC)
    fresh = now.isoformat()
    stale = (now - timedelta(minutes=5)).isoformat()

    payload = {
        "messages": [
            {
                "id": "new-s1-msg",
                "role": "user",
                "text": "hello",
                "session_id": "s1",
                "created_at": fresh,
            }
        ],
        "active_session_id": "s1",
        "client_updated_at": fresh,
    }
    ok_resp = client.post("/api/agent/conversation-state", json=payload)
    assert ok_resp.status_code == 200

    all_rows = session.exec(select(AgentMessage)).all()
    ids = {row.message_id for row in all_rows}
    assert "s2-msg" in ids
    assert "new-s1-msg" in ids
    assert "old-s1-msg" not in ids

    stale_payload = dict(payload)
    stale_payload["client_updated_at"] = stale
    conflict = client.post("/api/agent/conversation-state", json=stale_payload)
    assert conflict.status_code == 409


def test_conversation_state_orders_messages_by_session_then_message_order(
    client: TestClient,
    session: Session,
) -> None:
    session.add(
        AgentMessage(
            message_id="s1-a",
            role="user",
            text="s1 first",
            session_id="s1",
            created_at="2026-01-01T00:00:00+00:00",
            sort_index=0,
        )
    )
    session.add(
        AgentMessage(
            message_id="s1-b",
            role="assistant",
            text="s1 second",
            session_id="s1",
            created_at="2026-01-01T00:00:01+00:00",
            sort_index=1,
        )
    )
    session.commit()
    session.add(
        AgentMessage(
            message_id="s2-a",
            role="assistant",
            text="s2 first",
            session_id="s2",
            created_at="2026-01-01T00:00:02+00:00",
            sort_index=0,
        )
    )
    session.commit()

    response = client.get("/api/agent/conversation-state")

    assert response.status_code == 200
    assert [item["id"] for item in response.json()["messages"]] == ["s1-a", "s1-b", "s2-a"]
