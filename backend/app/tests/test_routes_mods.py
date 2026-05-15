"""Tests for mods API routes."""

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


class TestListMods:
    def test_empty_db_returns_empty_list(self, client, session):
        response = client.get("/api/mods")
        assert response.status_code == 200
        data = response.json()
        assert data == {"items": [], "total": 0}

    def test_with_seed_data_default_sort_desc(self, client, session):
        mods = [
            Mod(source="nexusmods", external_id="1", game="skyrim", title="B Mod",
                url="https://a.com", first_seen_at="2025-01-01T00:00:00", last_seen_at="2025-01-01T00:00:00"),
            Mod(source="nexusmods", external_id="2", game="skyrim", title="A Mod",
                url="https://b.com", first_seen_at="2025-01-02T00:00:00", last_seen_at="2025-01-02T00:00:00"),
        ]
        session.add_all(mods)
        session.commit()

        response = client.get("/api/mods")
        items = response.json()["items"]
        assert items[0]["first_seen_at"] >= items[1]["first_seen_at"]

    def test_search_filter(self, client, session):
        mods = [
            Mod(source="nexusmods", external_id="1", game="skyrim", title="Awesome Sword",
                url="https://a.com", first_seen_at="2025-01-01T00:00:00", last_seen_at="2025-01-01T00:00:00"),
            Mod(source="nexusmods", external_id="2", game="skyrim", title="Cool Armor",
                url="https://b.com", first_seen_at="2025-01-02T00:00:00", last_seen_at="2025-01-02T00:00:00"),
        ]
        session.add_all(mods)
        session.commit()

        response = client.get("/api/mods?search=sword")
        data = response.json()
        assert data["total"] == 1
        assert data["items"][0]["title"] == "Awesome Sword"

    def test_game_filter(self, client, session):
        mods = [
            Mod(source="nexusmods", external_id="1", game="Skyrim Special Edition",
                game_domain="skyrimspecialedition", title="Mod1",
                url="https://a.com", first_seen_at="2025-01-01T00:00:00", last_seen_at="2025-01-01T00:00:00"),
            Mod(source="nexusmods", external_id="2", game="Fallout 4",
                game_domain="fallout4", title="Mod2",
                url="https://b.com", first_seen_at="2025-01-01T00:00:00", last_seen_at="2025-01-01T00:00:00"),
        ]
        session.add_all(mods)
        session.commit()

        response = client.get("/api/mods?game=skyrimspecialedition")
        data = response.json()
        assert data["total"] == 1
        assert data["items"][0]["game"] == "Skyrim Special Edition"

    def test_source_filter(self, client, session):
        mods = [
            Mod(source="nexusmods", external_id="1", game="skyrim", title="Mod1",
                url="https://a.com", first_seen_at="2025-01-01T00:00:00", last_seen_at="2025-01-01T00:00:00"),
            Mod(source="loverslab", external_id="2", game="skyrim", title="Mod2",
                url="https://b.com", first_seen_at="2025-01-01T00:00:00", last_seen_at="2025-01-01T00:00:00"),
        ]
        session.add_all(mods)
        session.commit()

        response = client.get("/api/mods?source=loverslab")
        data = response.json()
        assert data["total"] == 1
        assert data["items"][0]["source"] == "loverslab"

    def test_adult_content_filter(self, client, session):
        mods = [
            Mod(source="nexusmods", external_id="1", game="skyrim", title="Mod1",
                url="https://a.com", first_seen_at="2025-01-01T00:00:00", last_seen_at="2025-01-01T00:00:00",
                adult_content=True),
            Mod(source="nexusmods", external_id="2", game="skyrim", title="Mod2",
                url="https://b.com", first_seen_at="2025-01-01T00:00:00", last_seen_at="2025-01-01T00:00:00",
                adult_content=False),
        ]
        session.add_all(mods)
        session.commit()

        response = client.get("/api/mods?adult_content=only")
        data = response.json()
        assert data["total"] == 1
        assert data["items"][0]["adult_content"] is True

    def test_pagination_offset_limit(self, client, session):
        mods = [Mod(source="nexusmods", external_id=str(i), game="skyrim", title=f"Mod{i}",
                     url="https://a.com", first_seen_at=f"2025-01-0{i}T00:00:00",
                     last_seen_at=f"2025-01-0{i}T00:00:00")
                for i in range(1, 6)]
        session.add_all(mods)
        session.commit()

        response = client.get("/api/mods?offset=1&limit=2")
        data = response.json()
        assert data["total"] == 5
        assert len(data["items"]) == 2

    def test_sort_by_downloads_asc(self, client, session):
        mods = [
            Mod(source="nexusmods", external_id="1", game="skyrim", title="Mod1",
                url="https://a.com", first_seen_at="2025-01-01T00:00:00", last_seen_at="2025-01-01T00:00:00",
                downloads=100),
            Mod(source="nexusmods", external_id="2", game="skyrim", title="Mod2",
                url="https://b.com", first_seen_at="2025-01-02T00:00:00", last_seen_at="2025-01-02T00:00:00",
                downloads=50),
        ]
        session.add_all(mods)
        session.commit()

        response = client.get("/api/mods?sort_by=downloads&sort_order=asc")
        items = response.json()["items"]
        assert items[0]["downloads"] <= items[1]["downloads"]

    def test_sort_by_downloads_desc(self, client, session):
        mods = [
            Mod(source="nexusmods", external_id="1", game="skyrim", title="Low",
                url="https://a.com", first_seen_at="2025-01-01T00:00:00", last_seen_at="2025-01-01T00:00:00",
                downloads=50),
            Mod(source="nexusmods", external_id="2", game="skyrim", title="High",
                url="https://b.com", first_seen_at="2025-01-02T00:00:00", last_seen_at="2025-01-02T00:00:00",
                downloads=100),
        ]
        session.add_all(mods)
        session.commit()

        response = client.get("/api/mods?sort_by=downloads&sort_order=desc")
        items = response.json()["items"]
        assert [item["title"] for item in items] == ["High", "Low"]

    def test_game_options_are_aggregated_from_mod_list(self, client, session):
        mods = [
            Mod(source="nexusmods", external_id="1", game="Skyrim Special Edition",
                game_domain="skyrimspecialedition", title="Mod1",
                url="https://a.com", first_seen_at="2025-01-01T00:00:00", last_seen_at="2025-01-01T00:00:00"),
            Mod(source="nexusmods", external_id="2", game="Skyrim Special Edition",
                game_domain="skyrimspecialedition", title="Mod2",
                url="https://b.com", first_seen_at="2025-01-01T00:00:00", last_seen_at="2025-01-01T00:00:00"),
            Mod(source="nexusmods", external_id="3", game="Fallout 4",
                game_domain="fallout4", title="Mod3",
                url="https://c.com", first_seen_at="2025-01-01T00:00:00", last_seen_at="2025-01-01T00:00:00"),
        ]
        session.add_all(mods)
        session.commit()

        response = client.get("/api/mods/games")
        assert response.status_code == 200
        data = response.json()
        assert data == [
            {
                "value": "skyrimspecialedition",
                "label": "Skyrim Special Edition",
                "count": 2,
            },
            {"value": "fallout4", "label": "Fallout 4", "count": 1},
        ]

    def test_list_includes_translated_summary_for_setting_language(self, client, session):
        mod = Mod(source="nexusmods", external_id="1", game="Skyrim Special Edition",
                  game_domain="skyrimspecialedition", title="Mod1",
                  original_summary="Original summary",
                  url="https://a.com", first_seen_at="2025-01-01T00:00:00", last_seen_at="2025-01-01T00:00:00")
        session.add(mod)
        session.commit()
        session.refresh(mod)
        session.add(ModSummary(
            mod_id=mod.id,
            language="zh-CN",
            summary_type="brief",
            content="中文摘要",
            model="test",
            generated_at="2025-01-01T00:00:00",
        ))
        session.commit()

        response = client.get("/api/mods")
        assert response.status_code == 200
        item = response.json()["items"][0]
        assert item["original_summary"] == "Original summary"
        assert item["translated_summary"] == "中文摘要"

    def test_regenerate_summary_deletes_existing_target_language_summary(self, client, session):
        mod = Mod(source="nexusmods", external_id="1", game="Skyrim Special Edition",
                  game_domain="skyrimspecialedition", title="Mod1",
                  original_summary="Original summary",
                  url="https://a.com", first_seen_at="2025-01-01T00:00:00", last_seen_at="2025-01-01T00:00:00")
        session.add(mod)
        session.commit()
        session.refresh(mod)
        session.add(ModSummary(
            mod_id=mod.id,
            language="zh-CN",
            summary_type="brief",
            content="旧摘要",
            model="test",
            generated_at="2025-01-01T00:00:00",
        ))
        session.commit()

        response = client.post(f"/api/mods/{mod.id}/summary/regenerate")
        assert response.status_code == 200
        assert response.json()["status"] == "queued"

        response = client.get("/api/mods")
        assert response.status_code == 200
        assert response.json()["items"][0]["translated_summary"] is None

    def test_combined_filters(self, client, session):
        mods = [
            Mod(source="nexusmods", external_id="1", game="skyrim", title="Cool Sword",
                url="https://a.com", first_seen_at="2025-01-01T00:00:00", last_seen_at="2025-01-01T00:00:00",
                adult_content=False),
            Mod(source="nexusmods", external_id="2", game="fallout4", title="Cool Sword",
                url="https://b.com", first_seen_at="2025-01-01T00:00:00", last_seen_at="2025-01-01T00:00:00",
                adult_content=False),
            Mod(source="nexusmods", external_id="3", game="skyrim", title="Hot Armor",
                url="https://c.com", first_seen_at="2025-01-01T00:00:00", last_seen_at="2025-01-01T00:00:00",
                adult_content=False),
        ]
        session.add_all(mods)
        session.commit()

        response = client.get("/api/mods?game=skyrim&search=cool")
        data = response.json()
        assert data["total"] == 1
        assert data["items"][0]["title"] == "Cool Sword"


class TestGetMod:
    def test_get_single_mod(self, client, session):
        mod = Mod(source="nexusmods", external_id="1", game="skyrim", title="Single Mod",
                   url="https://a.com", first_seen_at="2025-01-01T00:00:00", last_seen_at="2025-01-01T00:00:00")
        session.add(mod)
        session.commit()
        session.refresh(mod)

        response = client.get(f"/api/mods/{mod.id}")
        assert response.status_code == 200
        assert response.json()["title"] == "Single Mod"
        assert response.json()["source"] == "nexusmods"

    def test_get_nonexistent_returns_404(self, client, session):
        response = client.get("/api/mods/99999")
        assert response.status_code == 404
        assert response.json()["detail"] == "Mod not found"
