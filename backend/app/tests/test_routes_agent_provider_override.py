import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.db import get_session
from app.main import app as fastapi_app
from app.models.mod import Mod


@pytest.fixture(name="engine")
def engine_fixture():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    yield engine


@pytest.fixture(name="client")
def client_fixture(engine):
    def override_get_session():
        with Session(engine) as session:
            yield session

    fastapi_app.dependency_overrides[get_session] = override_get_session
    yield TestClient(fastapi_app, raise_server_exceptions=False)
    fastapi_app.dependency_overrides.clear()


def test_chat_rejects_unknown_provider_override_with_422(client):
    response = client.post(
        "/api/agent/chat",
        json={"message": "最近有什么新 Mod", "provider_override": "missing"},
    )

    assert response.status_code == 422
    assert response.json() == {
        "detail": "Unknown or disabled LLM provider override: missing"
    }


def test_mod_detail_rejects_unknown_provider_override_with_422(client, engine):
    with Session(engine) as session:
        mod = Mod(
            source="nexusmods",
            external_id="provider-override-test",
            game="Skyrim Special Edition",
            title="Provider Override Test",
            url="https://example.com/provider-override-test",
            first_seen_at="2026-07-13T00:00:00+00:00",
            last_seen_at="2026-07-13T00:00:00+00:00",
        )
        session.add(mod)
        session.commit()
        session.refresh(mod)
        mod_id = mod.id

    response = client.post(
        "/api/agent/mod-detail",
        json={
            "mod_id": mod_id,
            "question": "详细介绍",
            "provider_override": "missing",
        },
    )

    assert response.status_code == 422
    assert response.json() == {
        "detail": "Unknown or disabled LLM provider override: missing"
    }
