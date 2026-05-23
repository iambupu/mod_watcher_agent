"""TDD tests for translated_summary support in /api/favorites and /api/updates.

These tests verify that:
1. zh-CN summary available → translated_summary returns zh-CN content
2. Only en summary available → translated_summary falls back to en (TDD: fails until implemented)
3. No summary → translated_summary is None
4. Only ja-JP summary → translated_summary is None (no zh-CN, no en fallback)

These tests are in RED phase — FavoriteRead and UpdateEventRead schemas
do not yet have a translated_summary field. They will fail with KeyError
until Task 10 adds the field to the schemas and routes.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.db import get_session
from app.main import app as fastapi_app
from app.models.favorite import Favorite
from app.models.mod import Mod
from app.models.summary import ModSummary
from app.models.update_event import ModUpdateEvent
from app.services.favorite_service import FavoriteService


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


class TestFavoriteTranslatedSummary:
    """Tests for translated_summary in GET /api/favorites."""

    def test_favorite_with_zh_cn_summary(self, client, session):
        """zh-CN summary available → translated_summary returns zh-CN content."""
        mod = make_mod(external_id="fav-zhcn-1")
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
        session.add(Favorite(
            mod_id=mod.id,
            created_at="2025-01-01T00:00:00",
            updated_at="2025-01-01T00:00:00",
        ))
        session.commit()

        response = client.get("/api/favorites")
        assert response.status_code == 200
        items = response.json()
        assert len(items) == 1
        assert items[0]["translated_summary"] == "中文内容"

    def test_favorite_fallback_to_en(self, client, session):
        """Only en summary → translated_summary falls back to en content. (TDD: RED)"""
        mod = make_mod(external_id="fav-en-1")
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
        session.add(Favorite(
            mod_id=mod.id,
            created_at="2025-01-01T00:00:00",
            updated_at="2025-01-01T00:00:00",
        ))
        session.commit()

        response = client.get("/api/favorites")
        assert response.status_code == 200
        items = response.json()
        assert len(items) == 1
        assert items[0]["translated_summary"] == "English fallback content"

    def test_favorite_no_summary(self, client, session):
        """No summary at all → translated_summary is None. (TDD: RED)"""
        mod = make_mod(external_id="fav-none-1")
        session.add(mod)
        session.commit()
        session.refresh(mod)
        session.add(Favorite(
            mod_id=mod.id,
            created_at="2025-01-01T00:00:00",
            updated_at="2025-01-01T00:00:00",
        ))
        session.commit()

        response = client.get("/api/favorites")
        assert response.status_code == 200
        items = response.json()
        assert len(items) == 1
        assert items[0]["translated_summary"] is None

    def test_check_update_route_detects_update(self, client, session, monkeypatch):
        class FakeAdapter:
            def __init__(self, *args, **kwargs):
                pass

            async def fetch_mod_detail(self, external_id, game_domain):
                return {
                    "version": "2.0.0",
                    "updated_at_remote": "2025-02-01T00:00:00Z",
                }

        monkeypatch.setattr(FavoriteService, "_adapter_class", FakeAdapter)
        mod = make_mod(
            external_id="fav-check-update",
            version="1.0.0",
            updated_at_remote="2025-01-01T00:00:00Z",
        )
        session.add(mod)
        session.commit()
        session.refresh(mod)
        fav = Favorite(
            mod_id=mod.id,
            last_known_version="1.0.0",
            last_known_updated_at="2025-01-01T00:00:00Z",
            created_at="2025-01-01T00:00:00",
            updated_at="2025-01-01T00:00:00",
        )
        session.add(fav)
        session.commit()
        session.refresh(fav)

        response = client.post(f"/api/favorites/{fav.id}/check-update")
        assert response.status_code == 200
        data = response.json()
        assert data["favorite_id"] == fav.id
        assert data["update_detected"] is True
        assert data["update_event"]["new_version"] == "2.0.0"

    def test_favorite_ja_jp_only_returns_none(self, client, session):
        """Only ja-JP summary → translated_summary is None (no zh-CN or en). (TDD: RED)"""
        mod = make_mod(external_id="fav-ja-1")
        session.add(mod)
        session.commit()
        session.refresh(mod)
        session.add(ModSummary(
            mod_id=mod.id,
            language="ja-JP",
            summary_type="brief",
            content="日本語の内容",
            model="test",
            generated_at="2025-01-01T00:00:00",
        ))
        session.commit()
        session.add(Favorite(
            mod_id=mod.id,
            created_at="2025-01-01T00:00:00",
            updated_at="2025-01-01T00:00:00",
        ))
        session.commit()

        response = client.get("/api/favorites")
        assert response.status_code == 200
        items = response.json()
        assert len(items) == 1
        assert items[0]["translated_summary"] is None


class TestUpdateTranslatedSummary:
    """Tests for translated_summary in GET /api/updates."""

    def test_update_with_zh_cn_summary(self, client, session):
        """zh-CN summary available → translated_summary returns zh-CN content."""
        mod = make_mod(external_id="upd-zhcn-1")
        session.add(mod)
        session.commit()
        session.refresh(mod)
        session.add(ModSummary(
            mod_id=mod.id,
            language="zh-CN",
            summary_type="brief",
            content="中文更新摘要",
            model="test",
            generated_at="2025-01-01T00:00:00",
        ))
        session.commit()
        fav = Favorite(
            mod_id=mod.id,
            created_at="2025-01-01T00:00:00",
            updated_at="2025-01-01T00:00:00",
        )
        session.add(fav)
        session.commit()
        session.refresh(fav)
        session.add(ModUpdateEvent(
            mod_id=mod.id,
            favorite_id=fav.id,
            detected_at="2025-01-02T00:00:00",
        ))
        session.commit()

        response = client.get("/api/updates", params={"favorite_id": fav.id})
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["items"][0]["translated_summary"] == "中文更新摘要"
        assert data["items"][0]["mod"]["id"] == mod.id
        assert data["items"][0]["mod"]["translated_summary"] == "中文更新摘要"

    def test_update_fallback_to_en(self, client, session):
        """Only en summary → translated_summary falls back to en content. (TDD: RED)"""
        mod = make_mod(external_id="upd-en-1")
        session.add(mod)
        session.commit()
        session.refresh(mod)
        session.add(ModSummary(
            mod_id=mod.id,
            language="en",
            summary_type="brief",
            content="English update summary",
            model="test",
            generated_at="2025-01-01T00:00:00",
        ))
        session.commit()
        fav = Favorite(
            mod_id=mod.id,
            created_at="2025-01-01T00:00:00",
            updated_at="2025-01-01T00:00:00",
        )
        session.add(fav)
        session.commit()
        session.refresh(fav)
        session.add(ModUpdateEvent(
            mod_id=mod.id,
            favorite_id=fav.id,
            detected_at="2025-01-02T00:00:00",
        ))
        session.commit()

        response = client.get("/api/updates", params={"favorite_id": fav.id})
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["items"][0]["translated_summary"] == "English update summary"
        assert data["items"][0]["mod"]["translated_summary"] == "English update summary"

    def test_update_no_summary(self, client, session):
        """No summary at all → translated_summary is None. (TDD: RED)"""
        mod = make_mod(external_id="upd-none-1")
        session.add(mod)
        session.commit()
        session.refresh(mod)
        fav = Favorite(
            mod_id=mod.id,
            created_at="2025-01-01T00:00:00",
            updated_at="2025-01-01T00:00:00",
        )
        session.add(fav)
        session.commit()
        session.refresh(fav)
        session.add(ModUpdateEvent(
            mod_id=mod.id,
            favorite_id=fav.id,
            detected_at="2025-01-02T00:00:00",
        ))
        session.commit()

        response = client.get("/api/updates", params={"favorite_id": fav.id})
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["items"][0]["translated_summary"] is None
        assert data["items"][0]["mod"]["id"] == mod.id

    def test_update_ja_jp_only_returns_none(self, client, session):
        """Only ja-JP summary → translated_summary is None (no zh-CN or en). (TDD: RED)"""
        mod = make_mod(external_id="upd-ja-1")
        session.add(mod)
        session.commit()
        session.refresh(mod)
        session.add(ModSummary(
            mod_id=mod.id,
            language="ja-JP",
            summary_type="brief",
            content="日本語の更新内容",
            model="test",
            generated_at="2025-01-01T00:00:00",
        ))
        session.commit()
        fav = Favorite(
            mod_id=mod.id,
            created_at="2025-01-01T00:00:00",
            updated_at="2025-01-01T00:00:00",
        )
        session.add(fav)
        session.commit()
        session.refresh(fav)
        session.add(ModUpdateEvent(
            mod_id=mod.id,
            favorite_id=fav.id,
            detected_at="2025-01-02T00:00:00",
        ))
        session.commit()

        response = client.get("/api/updates", params={"favorite_id": fav.id})
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["items"][0]["translated_summary"] is None
        assert data["items"][0]["mod"]["id"] == mod.id

    def test_mark_all_updates_seen_endpoint(self, client, session):
        mod = make_mod(external_id="upd-mark-all")
        session.add(mod)
        session.commit()
        session.refresh(mod)
        session.add(ModUpdateEvent(
            mod_id=mod.id,
            detected_at="2025-01-02T00:00:00",
            seen=False,
        ))
        session.add(ModUpdateEvent(
            mod_id=mod.id,
            detected_at="2025-01-03T00:00:00",
            seen=False,
        ))
        session.commit()

        response = client.patch("/api/updates/seen")
        assert response.status_code == 200
        assert response.json() == {"updated": 2}
        data = client.get("/api/updates").json()
        assert all(item["seen"] for item in data["items"])
