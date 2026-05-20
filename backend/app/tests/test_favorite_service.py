"""Tests for FavoriteService."""

from unittest.mock import AsyncMock, patch

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

from app.models.favorite import Favorite
from app.models.mod import Mod
from app.models.update_event import ModUpdateEvent
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
    async def test_update_ignores_none_values(self, service, mod, session):
        fav = await service.add_favorite(mod.id, user_note="original")
        updated = await service.update_favorite(fav.id, user_note=None)
        assert updated.user_note == "original"


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
