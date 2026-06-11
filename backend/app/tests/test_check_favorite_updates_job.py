# 中文注释：说明 backend/app/tests/test_check_favorite_updates_job.py 的模块职责，便于后续维护定位。

from unittest.mock import AsyncMock

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.jobs.check_favorite_updates import check_favorite_updates
from app.models.favorite import Favorite
from app.models.mod import Mod
from app.services.favorite_service import FavoriteService


@pytest.fixture(name="engine")
def fixture_engine():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    return engine


@pytest.mark.asyncio
async def test_check_favorite_updates_metadata_uses_actual_notification_result(engine, monkeypatch):
    class FakeAdapter:
        def __init__(self, *args, **kwargs):
            pass

        async def fetch_mod_detail(self, external_id, game_domain):
            return {
                "version": "2.0.0",
                "updated_at_remote": "2025-02-01T00:00:00Z",
            }

    monkeypatch.setattr("app.jobs.check_favorite_updates.engine", engine)
    monkeypatch.setattr(FavoriteService, "_adapter_class", FakeAdapter)
    monkeypatch.setattr(
        "app.services.notification_service.NotificationService.notify_updates",
        AsyncMock(return_value={"telegram_ok": False, "discord_ok": False, "notified_count": 0}),
    )
    with Session(engine) as session:
        mod = Mod(
            source="nexusmods",
            external_id="1001",
            game="skyrim",
            title="Tracked Mod",
            url="https://example.com/mod",
            version="1.0.0",
            updated_at_remote="2025-01-01T00:00:00Z",
            first_seen_at="2025-01-01T00:00:00+00:00",
            last_seen_at="2025-01-01T00:00:00+00:00",
        )
        session.add(mod)
        session.commit()
        session.refresh(mod)
        session.add(
            Favorite(
                mod_id=mod.id,
                tracking_enabled=True,
                notify_on_update=True,
                last_known_version="1.0.0",
                last_known_updated_at="2025-01-01T00:00:00Z",
                created_at="2025-01-01T00:00:00+00:00",
                updated_at="2025-01-01T00:00:00+00:00",
            )
        )
        session.commit()

    result = await check_favorite_updates()

    assert result["summary"]["updated"] == 1
    assert result["favorites"][0]["update_detected"] is True
    assert result["favorites"][0]["notification_sent"] is False
