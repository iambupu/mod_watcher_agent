from datetime import UTC, datetime

from sqlmodel import Session, select

from app.adapters.base import BaseAdapter
from app.adapters.loverslab import LoversLabAdapter  # noqa: F401 - registers adapter
from app.adapters.nexusmods import NexusModsAdapter
from app.models.favorite import Favorite
from app.models.mod import Mod
from app.models.mod_item import ModItem
from app.models.update_event import ModUpdateEvent
from app.services.settings_service import SettingsService


class FavoriteService:
    _adapter_class = NexusModsAdapter

    def __init__(self, session: Session):
        """初始化实例并保存运行所需的依赖。"""
        self.session = session

    async def add_favorite(self, mod_id: int, user_note: str | None = None) -> Favorite:
        """处理当前模块的业务逻辑并返回结果。"""
        mod = self.session.get(Mod, mod_id)
        if mod is None:
            raise ValueError(f"Mod id={mod_id} not found")
        existing = self.session.exec(
            select(Favorite).where(Favorite.mod_id == mod_id)
        ).first()
        if existing:
            return existing
        now = datetime.now(UTC).isoformat()
        fav = Favorite(
            mod_id=mod_id,
            user_note=user_note,
            last_known_version=mod.version,
            last_known_updated_at=mod.updated_at_remote,
            created_at=now,
            updated_at=now,
        )
        self.session.add(fav)
        self.session.commit()
        self.session.refresh(fav)
        return fav

    async def remove_favorite(self, favorite_id: int) -> None:
        """处理当前模块的业务逻辑并返回结果。"""
        fav = self.session.get(Favorite, favorite_id)
        if fav is None:
            raise ValueError(f"Favorite id={favorite_id} not found")
        self.session.delete(fav)
        self.session.commit()

    async def update_favorite(self, favorite_id: int, **fields) -> Favorite:
        """更新已有数据并返回结果。"""
        fav = self.session.get(Favorite, favorite_id)
        if fav is None:
            raise ValueError(f"Favorite id={favorite_id} not found")
        for key, value in fields.items():
            if hasattr(fav, key) and value is not None:
                setattr(fav, key, value)
        fav.updated_at = datetime.now(UTC).isoformat()
        self.session.add(fav)
        self.session.commit()
        self.session.refresh(fav)
        return fav

    async def check_update(self, favorite_id: int) -> ModUpdateEvent | None:
        """处理当前模块的业务逻辑并返回结果。"""
        fav = self.session.get(Favorite, favorite_id)
        if fav is None:
            raise ValueError(f"Favorite id={favorite_id} not found")
        mod = self.session.get(Mod, fav.mod_id)
        if mod is None:
            return None
        # Read API key from DB settings (supports settings-page configured key)
        settings_svc = SettingsService(self.session)
        nexus_api_key = settings_svc.get("nexus_api_key") or ""
        adapter_class = self._adapter_class if mod.source == "nexusmods" else BaseAdapter.adapters.get(mod.source)
        if adapter_class is None:
            raise ValueError(f"Unknown source '{mod.source}' for favorite id={favorite_id}")
        adapter = adapter_class(api_key=nexus_api_key)
        latest = await adapter.fetch_mod_detail(str(mod.external_id), mod.game_domain)
        if latest is None:
            return None
        old_version = fav.last_known_version
        old_updated = fav.last_known_updated_at
        new_version, new_updated = _extract_version_and_updated_at(latest)
        changed = False
        if new_version and new_version != old_version:
            changed = True
        if new_updated and new_updated != old_updated:
            changed = True
        if not changed:
            fav.last_checked_at = datetime.now(UTC).isoformat()
            self.session.add(fav)
            self.session.commit()
            return None
        event = ModUpdateEvent(
            mod_id=mod.id,
            favorite_id=fav.id,
            old_version=old_version,
            new_version=new_version,
            old_updated_at=old_updated,
            new_updated_at=new_updated,
            detected_at=datetime.now(UTC).isoformat(),
            seen=False,
        )
        self.session.add(event)
        fav.last_known_version = new_version
        fav.last_known_updated_at = new_updated
        fav.last_checked_at = datetime.now(UTC).isoformat()
        self.session.add(fav)
        self.session.commit()
        self.session.refresh(event)

        # Send notification for the update
        from app.services.notification_service import NotificationService
        notifier = NotificationService(self.session)
        await notifier.notify_updates([event])

        return event

    async def check_all_favorites(self) -> list[ModUpdateEvent]:
        """处理当前模块的业务逻辑并返回结果。"""
        favs = self.session.exec(
            select(Favorite).where(Favorite.tracking_enabled.is_(True))
        ).all()
        events: list[ModUpdateEvent] = []
        for fav in favs:
            try:
                event = await self.check_update(fav.id)
                if event is not None:
                    events.append(event)
            except Exception:
                continue
        return events


def _extract_version_and_updated_at(detail: ModItem | dict) -> tuple[str | None, str | None]:
    """从原始内容中提取目标字段。"""
    if isinstance(detail, ModItem):
        raw = detail.raw if isinstance(detail.raw, dict) else {}
        updated_at = detail.updated_at.isoformat() if detail.updated_at is not None else None
        return raw.get("version"), updated_at or raw.get("updated_at_remote") or raw.get("updatedAt")
    return detail.get("version"), detail.get("updated_at_remote") or detail.get("updatedAt")
