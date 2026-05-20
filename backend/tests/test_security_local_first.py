from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi import Request
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app import security
from app.config import settings
from app.models.settings import Setting
from app.security import AccessPolicy, require_safe_bind_host, validate_outbound_url


@pytest.fixture(autouse=True)
def isolated_policy_engine(monkeypatch: pytest.MonkeyPatch):
    test_engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(test_engine)
    monkeypatch.setattr(security, "engine", test_engine)
    security._policy_cache["value"] = None
    security._policy_cache["expires_at"] = 0.0
    yield
    security._policy_cache["value"] = None
    security._policy_cache["expires_at"] = 0.0


def _make_request(host: str, path: str, token: str = "") -> Request:
    headers = []
    if token:
        headers.append((b"x-mod-watcher-token", token.encode("utf-8")))
    scope = {
        "type": "http",
        "method": "GET",
        "path": path,
        "raw_path": path.encode("utf-8"),
        "query_string": b"",
        "headers": headers,
        "client": (host, 50000),
        "server": ("testserver", 80),
        "scheme": "http",
        "http_version": "1.1",
        "root_path": "",
    }
    return Request(scope)


def test_access_policy_local_relaxed_blocks_remote(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "MW_ACCESS_PROFILE", "local_relaxed")
    monkeypatch.setattr(settings, "MW_ALLOW_LAN", False)
    monkeypatch.setattr(settings, "MW_ADMIN_TOKEN", "")

    decision = AccessPolicy().evaluate(_make_request("192.168.1.5", "/api/settings"))

    assert decision.allow is False
    assert decision.status_code == 403


def test_access_policy_local_strict_requires_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "MW_ACCESS_PROFILE", "local_strict")
    monkeypatch.setattr(settings, "MW_ALLOW_LAN", False)
    monkeypatch.setattr(settings, "MW_ADMIN_TOKEN", "secret-token")

    no_token = AccessPolicy().evaluate(_make_request("127.0.0.1", "/api/settings"))
    ok_token = AccessPolicy().evaluate(_make_request("127.0.0.1", "/api/settings", token="secret-token"))

    assert no_token.allow is False
    assert no_token.status_code == 401
    assert ok_token.allow is True


def test_access_policy_shared_lan_restricts_control_endpoints(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "MW_ACCESS_PROFILE", "shared_lan")
    monkeypatch.setattr(settings, "MW_ALLOW_LAN", True)
    monkeypatch.setattr(settings, "MW_ADMIN_TOKEN", "secret-token")

    decision = AccessPolicy().evaluate(
        _make_request("192.168.1.9", "/api/logs/open-dir", token="secret-token")
    )

    assert decision.allow is False
    assert decision.status_code == 403


def test_validate_outbound_url_security_rules(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "MW_ALLOW_LOCAL_LLM", True)

    assert validate_outbound_url("ollama", "http://localhost:11434/v1") == "http://localhost:11434/v1"
    assert validate_outbound_url("siliconflow", "") == "https://api.siliconflow.cn/v1"
    assert validate_outbound_url("xai", "") == "https://api.x.ai/v1"
    assert validate_outbound_url("kimi", "") == "https://api.moonshot.cn/v1"
    assert validate_outbound_url("qwen", "") == "https://dashscope.aliyuncs.com/compatible-mode/v1"
    assert validate_outbound_url("minimax", "") == "https://api.minimax.io/v1"

    with pytest.raises(Exception) as private_err:
        validate_outbound_url("openai", "https://169.254.169.254/latest")
    assert getattr(private_err.value, "status_code", None) == 422

    with pytest.raises(Exception) as scheme_err:
        validate_outbound_url("openai", "http://api.openai.com/v1")
    assert getattr(scheme_err.value, "status_code", None) == 422


def test_shared_lan_allows_domain_gateway_but_blocks_private_ip(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "MW_ALLOW_LOCAL_LLM", True)
    monkeypatch.setattr(
        security,
        "_load_runtime_policy",
        lambda force_refresh=False: security.RuntimePolicy(  # noqa: ARG005
            profile="shared_lan",
            allow_lan=True,
            admin_token="",
        ),
    )

    assert validate_outbound_url("openai", "http://my-gateway.lan/v1") == "http://my-gateway.lan/v1"

    with pytest.raises(Exception) as private_err:
        validate_outbound_url("openai", "https://192.168.1.10/v1")
    assert getattr(private_err.value, "status_code", None) == 422


def test_runtime_policy_reads_db_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    db_engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(db_engine)
    now = datetime.now(UTC).isoformat()
    with Session(db_engine) as session:
        session.add(Setting(key="access_profile", value="shared_lan", updated_at=now))
        session.add(Setting(key="allow_lan", value="true", updated_at=now))
        session.commit()

    monkeypatch.setattr(security, "engine", db_engine)
    security._policy_cache["value"] = None
    security._policy_cache["expires_at"] = 0.0
    policy = security._load_runtime_policy(force_refresh=True)

    assert policy.profile == "shared_lan"
    assert policy.allow_lan is True


def test_require_safe_bind_host(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "MW_ACCESS_PROFILE", "local_relaxed")
    monkeypatch.setattr(settings, "MW_BIND_HOST", "0.0.0.0")

    with pytest.raises(RuntimeError):
        require_safe_bind_host()
