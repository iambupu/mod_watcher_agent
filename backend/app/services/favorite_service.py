from datetime import UTC, datetime

from sqlmodel import Session, select

from app.adapters.nexusmods import NexusModsAdapter
from app.models.favorite import Favorite
from app.models.mod import Mod
from app.models.update_event import ModUpdateEvent
from app.services.settings_service import SettingsService


class FavoriteService:
    _adapter_class = NexusModsAdapter

    def __init__(self, session: Session):
        self.session = session

    async def add_favorite(self, mod_id: int, user_note: str | None = None) -> Favorite:
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
        fav = self.session.get(Favorite, favorite_id)
        if fav is None:
            raise ValueError(f"Favorite id={favorite_id} not found")
        self.session.delete(fav)
        self.session.commit()

    async def update_favorite(self, favorite_id: int, **fields) -> Favorite:
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
        fav = self.session.get(Favorite, favorite_id)
        if fav is None:
            raise ValueError(f"Favorite id={favorite_id} not found")
        mod = self.session.get(Mod, fav.mod_id)
        if mod is None:
            return None
        # Read API key from DB settings (supports settings-page configured key)
        settings_svc = SettingsService(self.session)
        nexus_api_key = settings_svc.get("nexus_api_key") or ""
        adapter = self._adapter_class(api_key=nexus_api_key)
        latest = await adapter.fetch_mod_detail(str(mod.external_id), mod.game_domain)
        if latest is None:
            return None
        old_version = fav.last_known_version
        new_version = latest.get("version")
        old_updated = fav.last_known_updated_at
        new_updated = latest.get("updated_at_remote")
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
