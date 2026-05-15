"""Tests for target-language translation selection in list_mods.

These tests cover the expected behavior:
1. zh-CN summary available → returns zh-CN content
2. Only en summary available → does not masquerade as zh-CN content
3. No summary at all → translated_summary is null
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.db import get_session
from app.main import app as fastapi_app
from app.models.mod import Mod
from app.models.summary import ModSummary


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


def make_mod(**kwargs):
    defaults = {
        "source": "nexusmods",
        "external_id": "12345",
        "game": "skyrim",
        "title": "Test Mod",
        "url": "https://example.com",
        "first_seen_at": "2025-01-01T00:00:00",
        "last_seen_at": "2025-01-02T00:00:00",
    }
    defaults.update(kwargs)
    return Mod(**defaults)


class TestTranslationFallback:
    def test_zh_cn_summary_returns_zh_cn_content(self, client, session):
        mod = make_mod(external_id="1")
        session.add(mod)
        session.commit()
        session.refresh(mod)
        session.add(ModSummary(
            mod_id=mod.id,
            language="zh-CN",
            summary_type="brief",
            content="中文内容",
            model="test",
            generated_at="2025-01-01T00:00:00",
        ))
        session.commit()

        response = client.get("/api/mods")
        assert response.status_code == 200
        item = response.json()["items"][0]
        assert item["translated_summary"] == "中文内容"

    def test_does_not_fall_back_to_en_when_zh_cn_missing(self, client, session):
        mod = make_mod(external_id="2")
        session.add(mod)
        session.commit()
        session.refresh(mod)
        session.add(ModSummary(
            mod_id=mod.id,
            language="en",
            summary_type="brief",
            content="English fallback content",
            model="test",
            generated_at="2025-01-01T00:00:00",
        ))
        session.commit()

        response = client.get("/api/mods")
        assert response.status_code == 200
        item = response.json()["items"][0]
        assert item["translated_summary"] is None

    def test_translated_summary_null_when_no_summaries(self, client, session):
        mod = make_mod(external_id="3")
        session.add(mod)
        session.commit()

        response = client.get("/api/mods")
        assert response.status_code == 200
        item = response.json()["items"][0]
        assert item["translated_summary"] is None
