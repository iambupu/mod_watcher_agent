"""Tests for FavoriteService."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

from app.adapters.base import BaseAdapter
from app.models.favorite import Favorite
from app.models.mod import Mod
from app.models.mod_item import ModItem
from app.models.summary import ModSummary
from app.models.update_event import ModUpdateEvent
from app.schemas.favorite import FavoriteImportCreate
from app.services.favorite_service import FavoriteService


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


@pytest.fixture
def mod(session):
    m = Mod(
        source="nexusmods",
        external_id="1001",
        game="Skyrim Special Edition",
        game_domain="skyrimspecialedition",
        title="Test Mod",
        url="https://www.nexusmods.com/skyrimspecialedition/mods/1001",
        version="1.0.0",
        updated_at_remote="2025-01-01T00:00:00Z",
        first_seen_at="2025-01-01T00:00:00Z",
        last_seen_at="2025-01-01T00:00:00Z",
    )
    session.add(m)
    session.commit()
    session.refresh(m)
    return m


@pytest.fixture
def service(session):
    return FavoriteService(session=session)


class TestAddFavorite:
    @pytest.mark.asyncio
    async def test_add_creates_favorite_with_baseline(self, service, mod, session):
        fav = await service.add_favorite(mod.id)
        assert fav is not None
        assert fav.mod_id == mod.id
        assert fav.last_known_version == "1.0.0"
        assert fav.last_known_updated_at == "2025-01-01T00:00:00Z"
        assert fav.tracking_enabled is True
        assert fav.created_at is not None
        assert fav.updated_at is not None

    @pytest.mark.asyncio
    async def test_add_duplicate_returns_existing(self, service, mod, session):
        first = await service.add_favorite(mod.id)
        second = await service.add_favorite(mod.id)
        assert first.id == second.id
        count = len(session.exec(select(Favorite)).all())
        assert count == 1

    @pytest.mark.asyncio
    async def test_add_on_nonexistent_mod_raises_valueerror(self, service):
        with pytest.raises(ValueError, match="not found"):
            await service.add_favorite(9999)


class TestRemoveFavorite:
    @pytest.mark.asyncio
    async def test_removes_existing_favorite(self, service, mod, session):
        fav = await service.add_favorite(mod.id)
        fid = fav.id
        await service.remove_favorite(fid)
        assert session.get(Favorite, fid) is None

    @pytest.mark.asyncio
    async def test_remove_nonexistent_raises_valueerror(self, service):
        with pytest.raises(ValueError, match="not found"):
            await service.remove_favorite(9999)


class TestUpdateFavorite:
    @pytest.mark.asyncio
    async def test_update_changes_tracking_enabled(self, service, mod, session):
        fav = await service.add_favorite(mod.id)
        assert fav.tracking_enabled is True
        updated = await service.update_favorite(fav.id, tracking_enabled=False)
        assert updated.tracking_enabled is False
        reloaded = session.get(Favorite, fav.id)
        assert reloaded.tracking_enabled is False

    @pytest.mark.asyncio
    async def test_update_nonexistent_raises_valueerror(self, service):
        with pytest.raises(ValueError, match="not found"):
            await service.update_favorite(9999, tracking_enabled=False)

    @pytest.mark.asyncio
    async def test_update_clears_nullable_values(self, service, mod, session):
        fav = await service.add_favorite(mod.id, user_note="original")
        updated = await service.update_favorite(fav.id, user_note=None)
        assert updated.user_note is None

    @pytest.mark.asyncio
    async def test_update_clears_user_tags(self, service, mod, session):
        fav = await service.add_favorite(mod.id)
        updated = await service.update_favorite(fav.id, user_tags_json='["tag"]')
        assert updated.user_tags_json == '["tag"]'

        updated = await service.update_favorite(fav.id, user_tags_json="[]")

        assert updated.user_tags_json == "[]"


class TestCheckUpdate:
    @pytest.mark.asyncio
    async def test_no_change_returns_none_and_updates_checked_at(self, service, mod, session):
        fav = await service.add_favorite(mod.id)
        mock_detail = {
            "version": "1.0.0",
            "updated_at_remote": "2025-01-01T00:00:00Z",
        }
        adapter = service._adapter_class()
        with patch.object(adapter, "fetch_mod_detail", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = mock_detail
            with patch.object(service, "_adapter_class", return_value=adapter):
                result = await service.check_update(fav.id)
        assert result is None
        reloaded = session.get(Favorite, fav.id)
        assert reloaded.last_checked_at is not None

    @pytest.mark.asyncio
    async def test_detects_version_change_and_creates_event(self, service, mod, session):
        fav = await service.add_favorite(mod.id)
        mock_detail = {
            "version": "2.0.0",
            "updated_at_remote": "2025-06-01T12:00:00Z",
        }
        adapter = service._adapter_class()
        with patch.object(
            adapter, "fetch_mod_detail",
            new_callable=AsyncMock,
            return_value=mock_detail,
        ), patch.object(service, "_adapter_class", return_value=adapter):
            result = await service.check_update(fav.id)

        assert result is not None
        assert isinstance(result, ModUpdateEvent)
        assert result.old_version == "1.0.0"
        assert result.new_version == "2.0.0"
        assert result.mod_id == mod.id
        assert result.favorite_id == fav.id
        reloaded = session.get(Favorite, fav.id)
        assert reloaded.last_known_version == "2.0.0"
        assert reloaded.last_checked_at is not None

    @pytest.mark.asyncio
    async def test_update_changed_summary_invalidates_and_regenerates_translation(self, service, mod, session):
        mod.original_summary = "Old remote summary"
        session.add(mod)
        session.add(
            ModSummary(
                mod_id=mod.id,
                language="zh-CN",
                summary_type="brief",
                content="旧译文",
                model="test",
                generated_at="2025-01-01T00:00:00Z",
            )
        )
        session.commit()
        fav = await service.add_favorite(mod.id)
        mock_detail = {
            "version": "2.0.0",
            "updated_at_remote": "2025-06-01T12:00:00Z",
            "original_summary": "New remote summary",
        }
        adapter = service._adapter_class()
        with patch.object(
            adapter,
            "fetch_mod_detail",
            new_callable=AsyncMock,
            return_value=mock_detail,
        ), patch.object(service, "_adapter_class", return_value=adapter), patch(
            "app.services.favorite_service.SummaryService.generate_summary",
            new_callable=AsyncMock,
            return_value={"content": "新译文", "model": "test"},
        ) as mock_generate:
            result = await service.check_update(fav.id)

        assert result is not None
        reloaded_mod = session.get(Mod, mod.id)
        assert reloaded_mod.original_summary == "New remote summary"
        assert reloaded_mod.version == "2.0.0"
        assert reloaded_mod.updated_at_remote == "2025-06-01T12:00:00Z"
        assert session.exec(select(ModSummary).where(ModSummary.mod_id == mod.id)).all() == []
        mock_generate.assert_awaited_once_with(mod.id, language="zh-CN", summary_type="brief")

    @pytest.mark.asyncio
    async def test_update_notification_respects_favorite_toggle(self, service, mod, session):
        fav = await service.add_favorite(mod.id)
        await service.update_favorite(fav.id, notify_on_update=False)
        mock_detail = {
            "version": "2.0.0",
            "updated_at_remote": "2025-06-01T12:00:00Z",
        }
        adapter = service._adapter_class()
        with patch.object(
            adapter,
            "fetch_mod_detail",
            new_callable=AsyncMock,
            return_value=mock_detail,
        ), patch.object(service, "_adapter_class", return_value=adapter), patch(
            "app.services.notification_service.NotificationService.notify_updates",
            new_callable=AsyncMock,
        ) as mock_notify:
            result = await service.check_update(fav.id)

        assert result is not None
        mock_notify.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_update_notification_tolerates_invalid_notified_count(self, service, mod, session):
        fav = await service.add_favorite(mod.id)
        await service.update_favorite(fav.id, notify_on_update=True)
        mock_detail = {
            "version": "2.0.0",
            "updated_at_remote": "2025-06-01T12:00:00Z",
        }
        adapter = service._adapter_class()
        with patch.object(
            adapter,
            "fetch_mod_detail",
            new_callable=AsyncMock,
            return_value=mock_detail,
        ), patch.object(service, "_adapter_class", return_value=adapter), patch(
            "app.services.notification_service.NotificationService.notify_updates",
            new_callable=AsyncMock,
            return_value={"notified_count": "unknown"},
        ):
            result = await service.check_update(fav.id)

        assert result is not None
        assert result.notification_sent is False

    @pytest.mark.asyncio
    async def test_detects_update_from_mod_item_detail(self, service, mod, session):
        fav = await service.add_favorite(mod.id)
        mock_detail = ModItem(
            source_id="1001",
            source="nexusmods",
            name="Test Mod",
            game="Skyrim Special Edition",
            url="https://www.nexusmods.com/skyrimspecialedition/mods/1001",
            updated_at=datetime(2025, 6, 1, 12, 0, tzinfo=UTC),
            raw={"version": "2.0.0"},
        )
        adapter = service._adapter_class()
        with patch.object(
            adapter,
            "fetch_mod_detail",
            new_callable=AsyncMock,
            return_value=mock_detail,
        ), patch.object(service, "_adapter_class", return_value=adapter):
            result = await service.check_update(fav.id)

        assert result is not None
        assert result.new_version == "2.0.0"
        assert result.new_updated_at == "2025-06-01T12:00:00+00:00"

    @pytest.mark.asyncio
    async def test_loverslab_favorite_uses_source_adapter(self, service, session, monkeypatch):
        class FakeLoversLabAdapter:
            def __init__(self, *args, **kwargs):
                pass

            async def fetch_mod_detail(self, external_id, game_domain):
                assert external_id == "ll-file-1001"
                return ModItem(
                    source_id=external_id,
                    source="loverslab",
                    name="LL Mod",
                    game="LoversLab",
                    url="https://www.loverslab.com/files/file/1001-ll-mod/",
                    updated_at=datetime(2025, 6, 1, 12, 0, tzinfo=UTC),
                    raw={"version": "2.0.0"},
                )

        monkeypatch.setitem(BaseAdapter.adapters, "loverslab", FakeLoversLabAdapter)
        ll_mod = Mod(
            source="loverslab",
            external_id="ll-file-1001",
            game="LoversLab",
            title="LL Mod",
            url="https://www.loverslab.com/files/file/1001-ll-mod/",
            version="1.0.0",
            updated_at_remote="2025-01-01T00:00:00Z",
            first_seen_at="2025-01-01T00:00:00Z",
            last_seen_at="2025-01-01T00:00:00Z",
        )
        session.add(ll_mod)
        session.commit()
        session.refresh(ll_mod)
        fav = await service.add_favorite(ll_mod.id)

        result = await service.check_update(fav.id)

        assert result is not None
        assert result.new_version == "2.0.0"

    @pytest.mark.asyncio
    async def test_nonexistent_favorite_raises_valueerror(self, service):
        with pytest.raises(ValueError, match="not found"):
            await service.check_update(9999)

    @pytest.mark.asyncio
    async def test_nonexistent_mod_returns_none(self, service, mod, session):
        fav = await service.add_favorite(mod.id)
        session.delete(mod)
        session.commit()
        result = await service.check_update(fav.id)
        assert result is None

    @pytest.mark.asyncio
    async def test_adapter_returns_none_returns_none(self, service, mod, session):
        fav = await service.add_favorite(mod.id)
        adapter = service._adapter_class()
        with patch.object(
            adapter, "fetch_mod_detail",
            new_callable=AsyncMock,
            return_value=None,
        ), patch.object(service, "_adapter_class", return_value=adapter):
            result = await service.check_update(fav.id)
        assert result is None


class TestImportFavorite:
    @pytest.mark.asyncio
    async def test_import_existing_favorite_records_local_metadata_update(self, service, mod, session):
        fav = await service.add_favorite(mod.id)

        result = await service.import_and_favorite(
            FavoriteImportCreate(
                source="nexusmods",
                external_id="1001",
                game="Skyrim Special Edition",
                game_domain="skyrimspecialedition",
                title="Test Mod",
                url="https://www.nexusmods.com/skyrimspecialedition/mods/1001",
                version="1.0.0",
                updated_at_remote="2025-06-01T12:00:00Z",
            )
        )

        event = session.exec(select(ModUpdateEvent).where(ModUpdateEvent.favorite_id == fav.id)).one()
        assert result.id == fav.id
        assert event.old_version == "1.0.0"
        assert event.new_version == "1.0.0"
        assert event.old_updated_at == "2025-01-01T00:00:00Z"
        assert event.new_updated_at == "2025-06-01T12:00:00Z"
        reloaded = session.get(Favorite, fav.id)
        assert reloaded.last_known_updated_at == "2025-06-01T12:00:00Z"
        assert reloaded.last_checked_at is not None


class TestReconcileLocalMetadataUpdates:
    def test_reconcile_creates_event_for_stale_favorite_baseline(self, service, mod, session):
        favorite = Favorite(
            mod_id=mod.id,
            tracking_enabled=True,
            notify_on_update=True,
            last_known_version="1.0.0",
            last_known_updated_at="2025-01-01T00:00:00Z",
            created_at="2025-01-01T00:00:00Z",
            updated_at="2025-01-01T00:00:00Z",
        )
        session.add(favorite)
        session.commit()
        session.refresh(favorite)
        mod.version = "1.0.0"
        mod.updated_at_remote = "2025-06-01T12:00:00Z"
        session.add(mod)
        session.commit()

        created = service.reconcile_local_metadata_updates()

        event = session.exec(select(ModUpdateEvent).where(ModUpdateEvent.favorite_id == favorite.id)).one()
        reloaded = session.get(Favorite, favorite.id)
        assert created == 1
        assert event.old_updated_at == "2025-01-01T00:00:00Z"
        assert event.new_updated_at == "2025-06-01T12:00:00Z"
        assert reloaded.last_known_updated_at == "2025-06-01T12:00:00Z"

    def test_reconcile_is_idempotent_after_baseline_updated(self, service, mod, session):
        favorite = Favorite(
            mod_id=mod.id,
            tracking_enabled=True,
            notify_on_update=True,
            last_known_version=mod.version,
            last_known_updated_at=mod.updated_at_remote,
            created_at="2025-01-01T00:00:00Z",
            updated_at="2025-01-01T00:00:00Z",
        )
        session.add(favorite)
        session.commit()

        assert service.reconcile_local_metadata_updates() == 0
        assert session.exec(select(ModUpdateEvent)).all() == []


class TestCheckAllFavorites:
    @pytest.mark.asyncio
    async def test_checks_all_enabled_favorites(self, service, mod, session):
        await service.add_favorite(mod.id)
        mock_detail = {
            "version": "2.0.0",
            "updated_at_remote": "2025-06-01T12:00:00Z",
        }
        adapter = service._adapter_class()
        with patch.object(
            adapter, "fetch_mod_detail",
            new_callable=AsyncMock,
            return_value=mock_detail,
        ), patch.object(service, "_adapter_class", return_value=adapter):
            events = await service.check_all_favorites()
        assert len(events) == 1
        assert events[0].new_version == "2.0.0"

    @pytest.mark.asyncio
    async def test_skips_disabled_favorites(self, service, mod, session):
        fav = await service.add_favorite(mod.id)
        await service.update_favorite(fav.id, tracking_enabled=False)
        mock_detail = {
            "version": "2.0.0",
            "updated_at_remote": "2025-06-01T12:00:00Z",
        }
        adapter = service._adapter_class()
        with patch.object(
            adapter, "fetch_mod_detail",
            new_callable=AsyncMock,
            return_value=mock_detail,
        ), patch.object(service, "_adapter_class", return_value=adapter):
            events = await service.check_all_favorites()
        assert len(events) == 0

    @pytest.mark.asyncio
    async def test_check_all_favorites_rolls_back_and_logs_failed_favorite(self, service, mod, session, caplog):
        fav = await service.add_favorite(mod.id)

        async def failing_check_update(favorite_id):
            assert favorite_id == fav.id
            raise RuntimeError("adapter failed")

        service.check_update = failing_check_update

        events = await service.check_all_favorites()

        assert events == []
        assert "Failed to check favorite update" in caplog.text
