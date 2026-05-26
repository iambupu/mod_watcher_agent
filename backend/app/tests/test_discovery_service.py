"""Tests for DiscoveryService single-source dispatch."""

import hashlib
import json
from unittest.mock import patch

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

from app.adapters.base import BaseAdapter
from app.models.mod import Mod
from app.models.mod_item import ModItem
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
