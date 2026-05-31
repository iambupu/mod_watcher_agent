"""Tests for mods API routes."""

import asyncio

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.db import get_session
from app.main import app as fastapi_app
from app.models.favorite import Favorite
from app.models.mod import Mod
from app.models.settings import Setting
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

    def test_search_filter_matches_category_and_summary(self, client, session):
        outfit = Mod(
            source="nexusmods",
            external_id="1",
            game="Stellar Blade",
            category="Outfits",
            title="Ocean String",
            url="https://a.com",
            first_seen_at="2025-01-01T00:00:00",
            last_seen_at="2025-01-01T00:00:00",
        )
        patch = Mod(
            source="nexusmods",
            external_id="2",
            game="Stellar Blade",
            category="Patches",
            title="Patch Collection",
            url="https://b.com",
            first_seen_at="2025-01-02T00:00:00",
            last_seen_at="2025-01-02T00:00:00",
        )
        session.add_all([outfit, patch])
        session.commit()
        session.refresh(patch)
        session.add(
            ModSummary(
                mod_id=patch.id,
                language="zh-CN",
                summary_type="brief",
                content="修复摄像机控制问题。",
                model="test",
                generated_at="2025-01-02T00:00:00",
            )
        )
        session.commit()

        category_response = client.get("/api/mods?search=女性服装")
        summary_response = client.get("/api/mods?search=摄像机")

        assert category_response.json()["items"][0]["category"] == "Outfits"
        assert summary_response.json()["items"][0]["title"] == "Patch Collection"

    def test_search_filter_matches_visible_fields_without_summaries(self, client, session):
        mod = Mod(
            source="loverslab",
            external_id="48837",
            game="X-Change Life",
            game_domain="x-change-life",
            category=None,
            title="Valentina playable character",
            url="https://www.loverslab.com/files/file/48837-valentina-playable-character/",
            tags_json='["playable", "character"]',
            original_summary=None,
            first_seen_at="2025-01-01T00:00:00",
            last_seen_at="2025-01-01T00:00:00",
        )
        session.add(mod)
        session.commit()

        id_response = client.get("/api/mods?search=48837")
        url_response = client.get("/api/mods?search=valentina-playable")
        tag_response = client.get("/api/mods?search=playable")

        assert id_response.json()["items"][0]["title"] == "Valentina playable character"
        assert url_response.json()["items"][0]["title"] == "Valentina playable character"
        assert tag_response.json()["items"][0]["title"] == "Valentina playable character"

    def test_search_filter_matches_translated_summary_when_original_summary_missing(self, client, session):
        mod = Mod(
            source="nexusmods",
            external_id="camera",
            game="Stellar Blade",
            title="Improved Camera Control",
            url="https://example.com/camera",
            original_summary=None,
            first_seen_at="2025-01-01T00:00:00",
            last_seen_at="2025-01-01T00:00:00",
        )
        session.add(mod)
        session.commit()
        session.refresh(mod)
        session.add(
            ModSummary(
                mod_id=mod.id,
                language="zh-CN",
                summary_type="brief",
                content="改进摄像机控制和锁定目标。",
                model="test",
                generated_at="2025-01-01T00:00:00",
            )
        )
        session.commit()

        response = client.get("/api/mods?search=摄像机控制")

        assert response.json()["items"][0]["title"] == "Improved Camera Control"

    def test_search_fallback_matches_translated_title(self, client, session, monkeypatch):
        monkeypatch.setattr(
            "app.services.mod_service.ModService._ensure_sqlite_fts_ready",
            lambda self: False,
        )
        mod = Mod(
            source="nexusmods",
            external_id="translated-title",
            game="Stellar Blade",
            title="Ocean String",
            translated_title_zh="海洋弦",
            url="https://example.com/ocean-string",
            first_seen_at="2025-01-01T00:00:00",
            last_seen_at="2025-01-01T00:00:00",
        )
        session.add(mod)
        session.commit()

        response = client.get("/api/mods?search=海洋弦")

        assert response.status_code == 200
        assert response.json()["items"][0]["title"] == "Ocean String"

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
            Mod(source="loverslab", external_id="4", game="X-Change Life",
                game_domain=None, title="LL Mod1",
                url="https://d.com", first_seen_at="2025-01-01T00:00:00", last_seen_at="2025-01-01T00:00:00"),
            Mod(source="loverslab", external_id="5", game="X-Change Life",
                game_domain="loverslab", title="LL Mod2",
                url="https://e.com", first_seen_at="2025-01-01T00:00:00", last_seen_at="2025-01-01T00:00:00"),
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
            {"value": "X-Change Life", "label": "X-Change Life", "count": 2},
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

    def test_regenerate_summary_keeps_existing_target_language_summary_until_job_succeeds(self, client, session):
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
        assert isinstance(response.json()["job_id"], int)

        response = client.get("/api/mods")
        assert response.status_code == 200
        assert response.json()["items"][0]["translated_summary"] == "旧摘要"

    def test_regenerate_summary_enqueues_locked_single_summary_handler(self, client, session, monkeypatch):
        captured: dict[str, object] = {}

        def fake_enqueue_job_run(job_run_id, handler):
            captured["job_run_id"] = job_run_id
            captured["handler"] = handler

        async def fake_generate_single_summary_payload_locked(job_session, *, mod_id, language, summary_type):  # noqa: ARG001
            captured["payload"] = {
                "mod_id": mod_id,
                "language": language,
                "summary_type": summary_type,
            }
            return {"items_scanned": 1, "items_matched": 1}

        monkeypatch.setattr("app.api.routes_mods.enqueue_job_run", fake_enqueue_job_run)
        monkeypatch.setattr(
            "app.api.routes_mods.generate_single_summary_payload_locked",
            fake_generate_single_summary_payload_locked,
        )
        mod = Mod(source="nexusmods", external_id="locked-route", game="Skyrim Special Edition",
                  game_domain="skyrimspecialedition", title="Locked Route",
                  original_summary="Original summary",
                  url="https://a.com", first_seen_at="2025-01-01T00:00:00", last_seen_at="2025-01-01T00:00:00")
        session.add(mod)
        session.commit()
        session.refresh(mod)

        response = client.post(f"/api/mods/{mod.id}/summary/regenerate")

        assert response.status_code == 200
        assert response.json()["job_id"] == captured["job_run_id"]
        assert callable(captured["handler"])

        result = asyncio.run(captured["handler"]())

        assert result == {"items_scanned": 1, "items_matched": 1}
        assert captured["payload"] == {
            "mod_id": mod.id,
            "language": "zh-CN",
            "summary_type": "brief",
        }

    def test_list_queues_missing_summaries_when_provider_chain_enabled(self, client, session, monkeypatch):
        queued: list[tuple[list[int], str]] = []

        async def fake_run_missing_summaries_job(mod_ids, language):
            queued.append((mod_ids, language))

        monkeypatch.setattr("app.api.routes_mods.run_missing_summaries_job", fake_run_missing_summaries_job)
        mod = make_mod(
            external_id="provider-chain",
            title="Provider Chain Mod",
            original_summary="Summary to translate",
        )
        session.add(mod)
        session.add(Setting(
            key="llm_providers_json",
            value='[{"provider":"deepseek","enabled":true,"priority":1,"model":"deepseek-v4-flash","api_key":"valid-key","base_url":"https://api.deepseek.com/v1"}]',
            updated_at="2025-01-01T00:00:00",
        ))
        session.add(Setting(
            key="summary_language",
            value="zh-CN",
            updated_at="2025-01-01T00:00:00",
        ))
        session.commit()
        session.refresh(mod)

        response = client.get("/api/mods")

        assert response.status_code == 200
        assert queued == [([mod.id], "zh-CN")]

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

    def test_list_mods_rejects_non_positive_limit(self, client):
        response = client.get("/api/mods?limit=0")

        assert response.status_code == 422

    def test_list_ignored_mods_rejects_non_positive_limit(self, client):
        response = client.get("/api/mods/ignored?limit=0")

        assert response.status_code == 422

    def test_ignored_list_and_unignore_restore_mod(self, client, session):
        visible = make_mod(external_id="visible", title="Visible Mod")
        ignored = make_mod(external_id="ignored", title="Hidden Mod", ignored=True)
        session.add_all([visible, ignored])
        session.commit()
        session.refresh(ignored)

        visible_response = client.get("/api/mods")
        assert visible_response.status_code == 200
        assert [item["title"] for item in visible_response.json()["items"]] == ["Visible Mod"]

        ignored_response = client.get("/api/mods/ignored")
        assert ignored_response.status_code == 200
        assert ignored_response.json()["total"] == 1
        assert ignored_response.json()["items"][0]["title"] == "Hidden Mod"

        restore_response = client.post(f"/api/mods/{ignored.id}/unignore")
        assert restore_response.status_code == 200
        assert restore_response.json() == {"ignored": False}

        restored_response = client.get("/api/mods")
        assert restored_response.status_code == 200
        assert restored_response.json()["total"] == 2

    def test_recommendations_use_favorite_preference_profile(self, client, session):
        favorite_mod = make_mod(
            external_id="fav",
            game="Stellar Blade",
            category="Outfits",
            title="Favorited Outfit",
            downloads=10,
        )
        profile_match = make_mod(
            external_id="match",
            game="Stellar Blade",
            category="Outfits",
            title="Profile Matched Outfit",
            downloads=50,
        )
        popular_unrelated = make_mod(
            external_id="popular",
            game="Fallout 4",
            category="Weapons",
            title="Popular Unrelated Weapon",
            downloads=999999,
        )
        session.add_all([favorite_mod, profile_match, popular_unrelated])
        session.commit()
        session.refresh(favorite_mod)
        session.add(Favorite(
            mod_id=favorite_mod.id,
            created_at="2025-01-01T00:00:00",
            updated_at="2025-01-01T00:00:00",
        ))
        session.add(Setting(
            key="agent_preferences_dirty",
            value="true",
            updated_at="2025-01-01T00:00:00",
        ))
        session.commit()

        response = client.get("/api/mods/recommendations?limit=1")

        assert response.status_code == 200
        items = response.json()["items"]
        assert [item["title"] for item in items] == ["Profile Matched Outfit"]

    def test_recommendations_fall_back_to_downloads_without_profile(self, client, session):
        low = make_mod(external_id="low", title="Low Downloads", downloads=10)
        high = make_mod(external_id="high", title="High Downloads", downloads=1000)
        session.add_all([low, high])
        session.commit()

        response = client.get("/api/mods/recommendations?limit=1")

        assert response.status_code == 200
        assert response.json()["items"][0]["title"] == "High Downloads"


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
