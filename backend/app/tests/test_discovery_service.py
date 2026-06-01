"""Tests for DiscoveryService single-source dispatch."""

import hashlib
import json
from unittest.mock import patch

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

from app.adapters.base import BaseAdapter
from app.models.favorite import Favorite
from app.models.mod import Mod
from app.models.mod_item import ModItem
from app.models.update_event import ModUpdateEvent
from app.models.watch_rule import WatchRule
from app.services.discovery_service import DiscoveryService


class _MockFetchAdapter(BaseAdapter):
    source = "mock_test"
    fetch_items: list[ModItem] = []

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key

    async def fetch(self, source_config_json: str) -> list[ModItem]:
        return self.__class__.fetch_items

    def normalize(self, raw_item: dict) -> ModItem:
        return ModItem(source_id="", source="", name="", game="", url="")

    async def fetch_mod_detail(self, external_id: str, game_domain=None):
        return None


def _make_mock_adapter(source_name: str, items: list[ModItem]) -> type:
    cls = type(
        f"MockAdapter_{source_name}",
        (_MockFetchAdapter,),
        {"source": source_name},
    )
    cls.fetch_items = items
    return cls


def _make_mod_item(source_id="1001", source="nexusmods", name="Test Mod",
                   game="Skyrim Special Edition", url="https://example.com/mods/1001",
                   **kwargs):
    return ModItem(
        source_id=source_id,
        source=source,
        name=name,
        game=game,
        url=url,
        summary=kwargs.get("summary", "A test mod."),
        author=kwargs.get("author", "TestAuthor"),
        downloads=kwargs.get("downloads", 0),
        endorsements=kwargs.get("endorsements", 0),
        likes=kwargs.get("likes", 0),
        categories=kwargs.get("categories", []),
        tags=kwargs.get("tags", []),
        thumbnail_url=kwargs.get("thumbnail_url", ""),
        updated_at=kwargs.get("updated_at"),
        is_adult=kwargs.get("is_adult", False),
        raw=kwargs.get("raw"),
    )


@pytest.fixture(name="engine")
def engine_fixture():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
    )
    SQLModel.metadata.create_all(engine)
    yield engine


@pytest.fixture(name="session")
def session_fixture(engine):
    with Session(engine) as session:
        yield session


@pytest.fixture(autouse=True)
def restore_adapters():
    saved = dict(BaseAdapter.adapters)
    yield
    BaseAdapter.adapters.clear()
    BaseAdapter.adapters.update(saved)


def _create_rule(session, name, enabled=True, source="mocknexus",
                 source_config=None):
    if source_config is None:
        source_config = {}
    r = WatchRule(
        name=name,
        enabled=enabled,
        source=source,
        source_config_json=json.dumps(source_config),
        filters_json="{}",
        notification_json="{}",
        created_at="2025-01-01T00:00:00",
        updated_at="2025-01-01T00:00:00",
    )
    session.add(r)
    session.commit()
    session.refresh(r)
    return r


class TestDiscoverNexusmodsRule:
    @pytest.mark.asyncio
    async def test_discover_nexusmods_rule(self, session):
        """Single-source dispatch for nexusmods adapter produces results."""
        BaseAdapter.adapters["nexusmods"] = _make_mock_adapter(
            "nexusmods",
            [_make_mod_item(source_id="2001", source="nexusmods", name="Sword Mod")],
        )

        rule = _create_rule(session, "nexus-rule", source="nexusmods")

        with patch(
            "app.services.discovery_service.FilterService.apply_filters",
            return_value=[
                {
                    "source": "nexusmods",
                    "external_id": "2001",
                    "title": "Sword Mod",
                    "game": "Skyrim Special Edition",
                    "game_domain": None,
                    "url": "https://example.com/mods/1001",
                    "author": "TestAuthor",
                    "category": None,
                    "version": None,
                    "created_at_remote": None,
                    "updated_at_remote": None,
                    "published_at_remote": None,
                    "downloads": 0,
                    "unique_downloads": None,
                    "endorsements": 0,
                    "views": None,
                    "likes": 0,
                    "adult_content": False,
                    "thumbnail_url": "",
                    "original_summary": "A test mod.",
                }
            ],
        ):
            service = DiscoveryService(session)
            results = await service.discover_from_rule(rule.id)

        assert len(results) == 1
        assert results[0]["external_id"] == "2001"
        assert results[0]["title"] == "Sword Mod"

    @pytest.mark.asyncio
    async def test_discover_loverslab_rule(self, session):
        """Single-source dispatch for loverslab adapter produces results."""
        BaseAdapter.adapters["loverslab"] = _make_mock_adapter(
            "loverslab",
            [_make_mod_item(source_id="3001", source="loverslab", name="LL Mod")],
        )

        rule = _create_rule(session, "ll-rule", source="loverslab")

        with patch(
            "app.services.discovery_service.FilterService.apply_filters",
            return_value=[
                {
                    "source": "loverslab",
                    "external_id": "3001",
                    "title": "LL Mod",
                    "game": "Skyrim Special Edition",
                    "game_domain": None,
                    "url": "https://example.com/mods/1001",
                    "author": "TestAuthor",
                    "category": None,
                    "version": None,
                    "created_at_remote": None,
                    "updated_at_remote": None,
                    "published_at_remote": None,
                    "downloads": 0,
                    "unique_downloads": None,
                    "endorsements": 0,
                    "views": None,
                    "likes": 0,
                    "adult_content": False,
                    "thumbnail_url": "",
                    "original_summary": "A test mod.",
                }
            ],
        ):
            service = DiscoveryService(session)
            results = await service.discover_from_rule(rule.id)

        assert len(results) == 1
        assert results[0]["external_id"] == "skyrim-special-edition:3001"
        assert results[0]["source"] == "loverslab"

    @pytest.mark.asyncio
    async def test_discover_disabled_rule_skipped(self, session):
        """Disabled rule raises ValueError."""
        rule = _create_rule(session, "disabled-rule", enabled=False)

        service = DiscoveryService(session)
        with pytest.raises(ValueError, match="disabled"):
            await service.discover_from_rule(rule.id)

    @pytest.mark.asyncio
    async def test_discover_unknown_source_error(self, session):
        """Rule with unknown source raises ValueError."""
        rule = _create_rule(session, "unknown-rule", source="unknown_source")

        service = DiscoveryService(session)
        with pytest.raises(ValueError, match="Unknown source"):
            await service.discover_from_rule(rule.id)

    @pytest.mark.asyncio
    async def test_discover_empty_adapter_result(self, session):
        """Empty adapter fetch returns empty results."""
        BaseAdapter.adapters["nexusmods"] = _make_mock_adapter(
            "nexusmods", []
        )

        rule = _create_rule(session, "empty-rule", source="nexusmods")

        service = DiscoveryService(session)
        results = await service.discover_from_rule(rule.id)

        assert results == []

    @pytest.mark.asyncio
    async def test_discover_existing_mod_updates_seen_but_does_not_return_new_mod(self, session):
        """Existing matches should not be reported as newly discovered."""
        BaseAdapter.adapters["nexusmods"] = _make_mock_adapter(
            "nexusmods",
            [_make_mod_item(source_id="2001", source="nexusmods", name="Sword Mod")],
        )
        session.add(
            Mod(
                source="nexusmods",
                external_id="2001",
                game="Skyrim Special Edition",
                title="Old Sword Mod",
                url="https://example.com/mods/1001",
                first_seen_at="2025-01-01T00:00:00+00:00",
                last_seen_at="2025-01-01T00:00:00+00:00",
            )
        )
        session.commit()
        rule = _create_rule(session, "nexus-rule", source="nexusmods")

        with patch(
            "app.services.discovery_service.FilterService.apply_filters",
            return_value=[
                {
                    "source": "nexusmods",
                    "external_id": "2001",
                    "title": "Sword Mod",
                    "game": "Skyrim Special Edition",
                    "game_domain": None,
                    "url": "https://example.com/mods/1001",
                    "author": "TestAuthor",
                    "category": None,
                    "version": None,
                    "created_at_remote": None,
                    "updated_at_remote": None,
                    "published_at_remote": None,
                    "downloads": 0,
                    "unique_downloads": None,
                    "endorsements": 0,
                    "views": None,
                    "likes": 0,
                    "adult_content": False,
                    "thumbnail_url": "",
                    "original_summary": "A test mod.",
                }
            ],
        ):
            service = DiscoveryService(session)
            results = await service.discover_from_rule(rule.id)

        assert results == []
        existing = session.exec(
            select(Mod).where(Mod.source == "nexusmods", Mod.external_id == "2001")
        ).one()
        assert existing is not None
        assert existing.title == "Sword Mod"
        assert existing.last_seen_at != "2025-01-01T00:00:00+00:00"

    def test_upsert_existing_mod_does_not_erase_metadata_when_discovery_value_missing(self, session):
        existing = Mod(
            source="nexusmods",
            external_id="skyrimspecialedition:2001",
            game="Skyrim Special Edition",
            game_domain="skyrimspecialedition",
            title="Old Sword Mod",
            url="https://www.nexusmods.com/skyrimspecialedition/mods/2001",
            category="Armor",
            original_summary="Existing summary",
            version="1.0.0",
            downloads=12,
            adult_content=False,
            first_seen_at="2025-01-01T00:00:00+00:00",
            last_seen_at="2025-01-01T00:00:00+00:00",
        )
        session.add(existing)
        session.commit()
        session.refresh(existing)

        result = DiscoveryService(session).upsert_mod_dicts([
            {
                "source": "nexusmods",
                "external_id": "2001",
                "title": "Updated Sword Mod",
                "game": "Skyrim Special Edition",
                "game_domain": None,
                "url": "https://www.nexusmods.com/skyrimspecialedition/mods/2001",
                "author": None,
                "category": None,
                "version": None,
                "created_at_remote": None,
                "updated_at_remote": None,
                "published_at_remote": None,
                "downloads": None,
                "unique_downloads": None,
                "endorsements": None,
                "views": None,
                "likes": None,
                "adult_content": None,
                "thumbnail_url": "",
                "original_summary": None,
            }
        ])

        refreshed = session.get(Mod, existing.id)

        assert result["created"] == 0
        assert result["updated"] == 1
        assert refreshed.title == "Updated Sword Mod"
        assert refreshed.game_domain == "skyrimspecialedition"
        assert refreshed.category == "Armor"
        assert refreshed.original_summary == "Existing summary"
        assert refreshed.version == "1.0.0"
        assert refreshed.downloads == 12
        assert refreshed.adult_content is False

    def test_upsert_existing_favorite_records_metadata_update_event(self, session):
        existing = Mod(
            source="nexusmods",
            external_id="skyrimspecialedition:2005",
            game="Skyrim Special Edition",
            game_domain="skyrimspecialedition",
            title="Tracked Mod",
            url="https://www.nexusmods.com/skyrimspecialedition/mods/2005",
            version="1.0.0",
            updated_at_remote="2025-01-01T00:00:00Z",
            first_seen_at="2025-01-01T00:00:00+00:00",
            last_seen_at="2025-01-01T00:00:00+00:00",
        )
        session.add(existing)
        session.commit()
        session.refresh(existing)
        favorite = Favorite(
            mod_id=existing.id,
            tracking_enabled=True,
            notify_on_update=True,
            last_known_version="1.0.0",
            last_known_updated_at="2025-01-01T00:00:00Z",
            created_at="2025-01-01T00:00:00+00:00",
            updated_at="2025-01-01T00:00:00+00:00",
        )
        session.add(favorite)
        session.commit()
        session.refresh(favorite)

        result = DiscoveryService(session).upsert_mod_dicts([
            {
                "source": "nexusmods",
                "external_id": "2005",
                "title": "Tracked Mod",
                "game": "Skyrim Special Edition",
                "game_domain": "skyrimspecialedition",
                "url": "https://www.nexusmods.com/skyrimspecialedition/mods/2005",
                "author": None,
                "category": None,
                "tags_json": [],
                "version": "1.1.0",
                "created_at_remote": None,
                "updated_at_remote": "2025-02-01T00:00:00Z",
                "published_at_remote": None,
                "downloads": None,
                "unique_downloads": None,
                "endorsements": None,
                "views": None,
                "likes": None,
                "adult_content": None,
                "thumbnail_url": "",
                "original_summary": None,
            }
        ])

        event = session.exec(select(ModUpdateEvent).where(ModUpdateEvent.favorite_id == favorite.id)).one()
        refreshed_favorite = session.get(Favorite, favorite.id)
        assert result["updated"] == 1
        assert event.old_version == "1.0.0"
        assert event.new_version == "1.1.0"
        assert event.old_updated_at == "2025-01-01T00:00:00Z"
        assert event.new_updated_at == "2025-02-01T00:00:00Z"
        assert refreshed_favorite.last_known_version == "1.1.0"
        assert refreshed_favorite.last_known_updated_at == "2025-02-01T00:00:00Z"

    def test_upsert_mod_dicts_normalizes_string_metrics_booleans_and_tags(self, session):
        result = DiscoveryService(session).upsert_mod_dicts([
            {
                "source": "nexusmods",
                "external_id": "2002",
                "title": "String Metrics Mod",
                "game": "Skyrim Special Edition",
                "game_domain": "skyrimspecialedition",
                "url": "https://www.nexusmods.com/skyrimspecialedition/mods/2002",
                "author": "Author",
                "category": None,
                "tags_json": ["armor", "cbbe"],
                "version": None,
                "created_at_remote": None,
                "updated_at_remote": None,
                "published_at_remote": None,
                "downloads": "1,200",
                "unique_downloads": "800",
                "endorsements": "-5",
                "views": "many",
                "likes": "12",
                "adult_content": "false",
                "thumbnail_url": "",
                "original_summary": "Summary",
            }
        ])

        mod = session.exec(select(Mod).where(Mod.source == "nexusmods")).one()

        assert result["created"] == 1
        assert mod.downloads == 1200
        assert mod.unique_downloads == 800
        assert mod.endorsements == 0
        assert mod.views is None
        assert mod.likes == 12
        assert mod.adult_content is False
        assert mod.tags_json == '["armor", "cbbe"]'

    def test_upsert_mod_dicts_rejects_boolean_metric_values(self, session):
        result = DiscoveryService(session).upsert_mod_dicts([
            {
                "source": "nexusmods",
                "external_id": "2004",
                "title": "Boolean Metrics Mod",
                "game": "Skyrim Special Edition",
                "game_domain": "skyrimspecialedition",
                "url": "https://www.nexusmods.com/skyrimspecialedition/mods/2004",
                "author": "Author",
                "category": None,
                "tags_json": [],
                "version": None,
                "created_at_remote": None,
                "updated_at_remote": None,
                "published_at_remote": None,
                "downloads": True,
                "unique_downloads": False,
                "endorsements": True,
                "views": False,
                "likes": True,
                "adult_content": "false",
                "thumbnail_url": "",
                "original_summary": "Summary",
            }
        ])

        mod = session.exec(select(Mod).where(Mod.source == "nexusmods")).one()

        assert result["created"] == 1
        assert mod.downloads is None
        assert mod.unique_downloads is None
        assert mod.endorsements is None
        assert mod.views is None
        assert mod.likes is None

    def test_upsert_existing_mod_preserves_values_when_incoming_strings_are_invalid(self, session):
        existing = Mod(
            source="nexusmods",
            external_id="skyrimspecialedition:2003",
            game="Skyrim Special Edition",
            game_domain="skyrimspecialedition",
            title="Existing",
            url="https://www.nexusmods.com/skyrimspecialedition/mods/2003",
            downloads=99,
            adult_content=True,
            tags_json='["old"]',
            first_seen_at="2025-01-01T00:00:00+00:00",
            last_seen_at="2025-01-01T00:00:00+00:00",
        )
        session.add(existing)
        session.commit()

        result = DiscoveryService(session).upsert_mod_dicts([
            {
                "source": "nexusmods",
                "external_id": "2003",
                "title": "Existing Updated",
                "game": "Skyrim Special Edition",
                "game_domain": "skyrimspecialedition",
                "url": "https://www.nexusmods.com/skyrimspecialedition/mods/2003",
                "author": None,
                "category": None,
                "tags_json": [],
                "version": None,
                "created_at_remote": None,
                "updated_at_remote": None,
                "published_at_remote": None,
                "downloads": "unknown",
                "unique_downloads": None,
                "endorsements": None,
                "views": None,
                "likes": None,
                "adult_content": "maybe",
                "thumbnail_url": "",
                "original_summary": None,
            }
        ])
        refreshed = session.get(Mod, existing.id)

        assert result["updated"] == 1
        assert refreshed.title == "Existing Updated"
        assert refreshed.downloads == 99
        assert refreshed.adult_content is True
        assert refreshed.tags_json == "[]"

    def test_nexusmods_same_numeric_id_different_games_create_separate_rows(self, session):
        service = DiscoveryService(session)

        result = service.upsert_mod_dicts([
            {
                "source": "nexusmods",
                "external_id": "1001",
                "title": "Skyrim Mod",
                "game": "Skyrim Special Edition",
                "game_domain": "skyrimspecialedition",
                "url": "https://www.nexusmods.com/skyrimspecialedition/mods/1001",
                "author": "Author",
                "category": None,
                "version": None,
                "created_at_remote": None,
                "updated_at_remote": None,
                "published_at_remote": None,
                "downloads": 0,
                "unique_downloads": None,
                "endorsements": 0,
                "views": None,
                "likes": 0,
                "adult_content": False,
                "thumbnail_url": "",
                "original_summary": "Skyrim summary",
            },
            {
                "source": "nexusmods",
                "external_id": "1001",
                "title": "Stellar Blade Mod",
                "game": "Stellar Blade",
                "game_domain": "stellarblade",
                "url": "https://www.nexusmods.com/stellarblade/mods/1001",
                "author": "Author",
                "category": None,
                "version": None,
                "created_at_remote": None,
                "updated_at_remote": None,
                "published_at_remote": None,
                "downloads": 0,
                "unique_downloads": None,
                "endorsements": 0,
                "views": None,
                "likes": 0,
                "adult_content": False,
                "thumbnail_url": "",
                "original_summary": "Stellar summary",
            },
        ])

        mods = session.exec(select(Mod).where(Mod.source == "nexusmods")).all()

        assert result["created"] == 2
        assert {mod.external_id for mod in mods} == {"skyrimspecialedition:1001", "stellarblade:1001"}
        assert {mod.title for mod in mods} == {"Skyrim Mod", "Stellar Blade Mod"}

    def test_loverslab_same_file_id_different_games_create_separate_rows(self, session):
        service = DiscoveryService(session)

        result = service.upsert_mod_dicts([
            {
                "source": "loverslab",
                "external_id": "48837",
                "title": "Skyrim LL Mod",
                "game": "Skyrim Special Edition",
                "game_domain": None,
                "url": "https://www.loverslab.com/files/file/48837-skyrim/",
                "author": "Author",
                "category": None,
                "version": None,
                "created_at_remote": None,
                "updated_at_remote": None,
                "published_at_remote": None,
                "downloads": 0,
                "unique_downloads": None,
                "endorsements": 0,
                "views": None,
                "likes": 0,
                "adult_content": True,
                "thumbnail_url": "",
                "original_summary": "Skyrim summary",
            },
            {
                "source": "loverslab",
                "external_id": "48837",
                "title": "Stellar LL Mod",
                "game": "Stellar Blade",
                "game_domain": None,
                "url": "https://www.loverslab.com/files/file/48837-stellar/",
                "author": "Author",
                "category": None,
                "version": None,
                "created_at_remote": None,
                "updated_at_remote": None,
                "published_at_remote": None,
                "downloads": 0,
                "unique_downloads": None,
                "endorsements": 0,
                "views": None,
                "likes": 0,
                "adult_content": True,
                "thumbnail_url": "",
                "original_summary": "Stellar summary",
            },
        ])

        mods = session.exec(select(Mod).where(Mod.source == "loverslab")).all()

        assert result["created"] == 2
        assert {mod.external_id for mod in mods} == {
            "skyrim-special-edition:48837",
            "stellar-blade:48837",
        }
        assert {mod.title for mod in mods} == {"Skyrim LL Mod", "Stellar LL Mod"}

    @pytest.mark.asyncio
    async def test_discover_loverslab_reuses_legacy_search_hash_record(self, session):
        """LoversLab discovery should dedupe records previously saved by search."""
        url = "https://www.loverslab.com/files/file/48837-valentina-playable-character/"
        legacy_external_id = hashlib.sha256(url.encode("utf-8")).hexdigest()[:32]
        BaseAdapter.adapters["loverslab"] = _make_mock_adapter(
            "loverslab",
            [_make_mod_item(source_id="48837", source="loverslab", name="Valentina", url=url)],
        )
        session.add(
            Mod(
                source="loverslab",
                external_id=legacy_external_id,
                game="LoversLab",
                game_domain="loverslab",
                title="Search Result Title",
                url=url,
                first_seen_at="2026-01-01T00:00:00+00:00",
                last_seen_at="2026-01-01T00:00:00+00:00",
            )
        )
        session.commit()
        rule = _create_rule(session, "ll-rule", source="loverslab")

        with patch(
            "app.services.discovery_service.FilterService.apply_filters",
            return_value=[
                {
                    "source": "loverslab",
                    "external_id": "48837",
                    "title": "Valentina playable character",
                    "game": "LoversLab",
                    "game_domain": None,
                    "url": url,
                    "author": "TestAuthor",
                    "category": None,
                    "version": None,
                    "created_at_remote": None,
                    "updated_at_remote": None,
                    "published_at_remote": None,
                    "downloads": 0,
                    "unique_downloads": None,
                    "endorsements": 0,
                    "views": None,
                    "likes": 0,
                    "adult_content": True,
                    "thumbnail_url": "",
                    "original_summary": "A test mod.",
                }
            ],
        ):
            results = await DiscoveryService(session).discover_from_rule(rule.id)

        assert results == []
        mods = session.exec(select(Mod).where(Mod.source == "loverslab")).all()
        assert len(mods) == 1
        assert mods[0].external_id == "48837"
        assert mods[0].title == "Valentina playable character"

    @pytest.mark.asyncio
    async def test_discover_loverslab_prefers_existing_canonical_row_when_legacy_duplicate_exists(self, session):
        url = "https://www.loverslab.com/files/file/48837-valentina-playable-character/"
        legacy_external_id = hashlib.sha256(url.encode("utf-8")).hexdigest()[:32]
        BaseAdapter.adapters["loverslab"] = _make_mock_adapter(
            "loverslab",
            [_make_mod_item(source_id="48837", source="loverslab", name="Valentina", url=url)],
        )
        session.add_all([
            Mod(
                source="loverslab",
                external_id=legacy_external_id,
                game="LoversLab",
                game_domain="loverslab",
                title="Legacy Search Result",
                url=url,
                first_seen_at="2026-01-01T00:00:00+00:00",
                last_seen_at="2026-01-01T00:00:00+00:00",
            ),
            Mod(
                source="loverslab",
                external_id="48837",
                game="LoversLab",
                game_domain=None,
                title="Canonical Result",
                url=url,
                first_seen_at="2026-01-02T00:00:00+00:00",
                last_seen_at="2026-01-02T00:00:00+00:00",
            ),
        ])
        session.commit()
        rule = _create_rule(session, "ll-rule", source="loverslab")

        with patch(
            "app.services.discovery_service.FilterService.apply_filters",
            return_value=[
                {
                    "source": "loverslab",
                    "external_id": "48837",
                    "title": "Valentina playable character",
                    "game": "LoversLab",
                    "game_domain": None,
                    "url": url,
                    "author": "TestAuthor",
                    "category": None,
                    "version": None,
                    "created_at_remote": None,
                    "updated_at_remote": None,
                    "published_at_remote": None,
                    "downloads": 0,
                    "unique_downloads": None,
                    "endorsements": 0,
                    "views": None,
                    "likes": 0,
                    "adult_content": True,
                    "thumbnail_url": "",
                    "original_summary": "A test mod.",
                }
            ],
        ):
            results = await DiscoveryService(session).discover_from_rule(rule.id)

        assert results == []
        mods = session.exec(select(Mod).where(Mod.source == "loverslab")).all()
        assert len(mods) == 2
        canonical = next(mod for mod in mods if mod.external_id == "48837")
        assert canonical.title == "Valentina playable character"
