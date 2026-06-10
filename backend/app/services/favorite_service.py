import logging
from datetime import UTC, datetime
from html import unescape

from sqlmodel import Session, select

from app.adapters.base import BaseAdapter
from app.adapters.loverslab import LoversLabAdapter  # noqa: F401 - registers adapter
from app.adapters.nexusmods import NexusModsAdapter
from app.models.favorite import Favorite
from app.models.mod import Mod
from app.models.mod_item import ModItem
from app.models.summary import ModSummary
from app.models.update_event import ModUpdateEvent
from app.schemas.favorite import FavoriteImportCreate
from app.services.adapter_utils import call_with_adapter
from app.services.agent.memory.preference_service import AgentPreferenceService
from app.services.settings_service import SettingsService
from app.services.source_identity import canonical_external_id, find_existing_mod_by_identity
from app.services.summary_service import SummaryService
from app.services.update_tracking_service import record_favorite_metadata_update
from app.utils.numeric import safe_nonnegative_int

SUPPORTED_IMPORT_SOURCES = {"nexusmods", "loverslab"}
GENERIC_GAME_LABELS = {"", "loverslab", "nexusmods", "nexus mods"}
logger = logging.getLogger(__name__)


class FavoriteService:
    _adapter_class = NexusModsAdapter

    def __init__(self, session: Session):
        """初始化实例并保存运行所需的依赖。"""
        self.session = session

    async def add_favorite(self, mod_id: int, user_note: str | None = None, *, commit: bool = True) -> Favorite:
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
        if commit:
            self.session.commit()
            self.session.refresh(fav)
            AgentPreferenceService(self.session).mark_dirty()
        else:
            self.session.flush()
            AgentPreferenceService(self.session).mark_dirty(commit=False)
        return fav

    async def import_and_favorite(self, data: FavoriteImportCreate) -> Favorite:
        """Upsert a mod captured from a browser page and mark it as favorite."""
        now = datetime.now(UTC).isoformat()
        source = data.source.strip().lower()
        if source not in SUPPORTED_IMPORT_SOURCES:
            raise ValueError("Only Nexus Mods and LoversLab pages can be imported")
        external_id = canonical_external_id(
            source,
            data.external_id,
            data.url,
            game=data.game,
            game_domain=data.game_domain,
        )
        if not source or not external_id:
            raise ValueError("source and external_id are required")
        title = _clean_import_text(data.title)
        if not title:
            raise ValueError("title is required")

        mod = self._find_imported_mod(
            source,
            external_id,
            data.url,
            game=data.game,
            game_domain=data.game_domain,
        )
        imported_game = _clean_import_game(data.game, existing=mod)
        external_id = canonical_external_id(
            source,
            data.external_id,
            data.url,
            game=imported_game or data.game,
            game_domain=data.game_domain,
        )
        if mod is None:
            mod = self._find_imported_mod(
                source,
                external_id,
                data.url,
                game=imported_game or data.game,
                game_domain=data.game_domain,
            )
        mod_fields = {
            "source": source,
            "external_id": external_id,
            "game": imported_game or (source if mod is None else None),
            "game_domain": data.game_domain.strip() if data.game_domain else None,
            "title": title,
            "translated_title_zh": _clean_import_text(data.translated_title_zh) if data.translated_title_zh else None,
            "url": data.url.strip(),
            "author": _clean_import_text(data.author) if data.author else None,
            "category": _clean_import_text(data.category) if data.category else None,
            "tags_json": data.tags_json or "[]",
            "original_summary": _clean_import_text(data.original_summary) if data.original_summary else None,
            "version": data.version,
            "created_at_remote": data.created_at_remote,
            "updated_at_remote": data.updated_at_remote,
            "published_at_remote": data.published_at_remote,
            "downloads": data.downloads,
            "unique_downloads": data.unique_downloads,
            "endorsements": data.endorsements,
            "views": data.views,
            "likes": data.likes,
            "adult_content": data.adult_content,
            "thumbnail_url": data.thumbnail_url,
            "raw_json": data.raw_json,
            "ignored": False,
            "last_seen_at": now,
        }
        if mod is None:
            mod = Mod(first_seen_at=now, **mod_fields)
        else:
            record_favorite_metadata_update(
                self.session,
                mod,
                new_version=data.version or mod.version,
                new_updated_at=data.updated_at_remote or mod.updated_at_remote,
                detected_at=now,
            )
            for key, value in mod_fields.items():
                if value is not None:
                    setattr(mod, key, value)
        try:
            self.session.add(mod)
            self.session.flush()

            fav = await self.add_favorite(mod.id, data.user_note, commit=False)
            update_fields = {}
            if data.tracking_enabled is not None:
                update_fields["tracking_enabled"] = data.tracking_enabled
            if data.notify_on_update is not None:
                update_fields["notify_on_update"] = data.notify_on_update
            if data.user_tags_json is not None:
                update_fields["user_tags_json"] = data.user_tags_json
            if data.user_note is not None:
                update_fields["user_note"] = data.user_note
            if update_fields:
                fav = await self.update_favorite(fav.id, commit=False, **update_fields)
            self.session.commit()
            self.session.refresh(fav)
            return fav
        except Exception:
            self.session.rollback()
            raise

    def _find_imported_mod(
        self,
        source: str,
        external_id: str,
        url: str,
        *,
        game: str | None = None,
        game_domain: str | None = None,
    ) -> Mod | None:
        """Find existing records created by discovery, search, or prior imports."""
        return find_existing_mod_by_identity(
            self.session,
            source,
            external_id,
            url,
            game=game,
            game_domain=game_domain,
        )

    async def remove_favorite(self, favorite_id: int) -> None:
        """处理当前模块的业务逻辑并返回结果。"""
        fav = self.session.get(Favorite, favorite_id)
        if fav is None:
            raise ValueError(f"Favorite id={favorite_id} not found")
        self.session.delete(fav)
        self.session.commit()
        AgentPreferenceService(self.session).mark_dirty()

    async def update_favorite(self, favorite_id: int, *, commit: bool = True, **fields) -> Favorite:
        """更新已有数据并返回结果。"""
        fav = self.session.get(Favorite, favorite_id)
        if fav is None:
            raise ValueError(f"Favorite id={favorite_id} not found")
        for key, value in fields.items():
            if hasattr(fav, key):
                setattr(fav, key, value)
        fav.updated_at = datetime.now(UTC).isoformat()
        self.session.add(fav)
        if commit:
            self.session.commit()
            self.session.refresh(fav)
        else:
            self.session.flush()
        return fav

    def reconcile_local_metadata_updates(self) -> int:
        """Backfill update events when local mod metadata advanced outside the tracker."""
        now = datetime.now(UTC).isoformat()
        rows = self.session.exec(
            select(Favorite, Mod).join(Mod, Favorite.mod_id == Mod.id)
        ).all()
        created = 0
        for favorite, mod in rows:
            event = record_favorite_metadata_update(
                self.session,
                mod,
                new_version=mod.version,
                new_updated_at=mod.updated_at_remote,
                detected_at=now,
                favorite=favorite,
            )
            if event is not None:
                created += 1
        if created:
            self.session.commit()
        return created

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
        latest: ModItem | dict | None = None
        adapter = adapter_class(api_key=nexus_api_key)

        async def _run(a: BaseAdapter) -> ModItem | dict | None:
            return await a.fetch_mod_detail(str(mod.external_id), mod.game_domain)

        latest = await call_with_adapter(
            adapter=adapter,
            callback=_run,
            logger=logger,
            context=f"favorite.update_check favorite_id={favorite_id} source={mod.source}",
        )
        if latest is None:
            fav.last_checked_at = datetime.now(UTC).isoformat()
            self.session.add(fav)
            self.session.commit()
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
        summary_changed = self._sync_mod_update_metadata(mod, latest, new_version, new_updated)
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
        if summary_changed:
            self._delete_brief_summaries(mod.id)
        self.session.add(fav)
        self.session.add(mod)
        self.session.commit()
        self.session.refresh(event)

        if summary_changed:
            language = settings_svc.get("summary_language") or "zh-CN"
            await SummaryService(self.session).generate_summary(
                mod.id,
                language=language,
                summary_type="brief",
            )

        notification_sent = False
        if fav.notify_on_update:
            from app.services.notification_service import NotificationService
            notifier = NotificationService(self.session)
            notification_result = await notifier.notify_updates([event])
            if isinstance(notification_result, dict):
                notification_sent = safe_nonnegative_int(notification_result.get("notified_count")) > 0
        object.__setattr__(event, "notification_sent", notification_sent)

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
                self.session.rollback()
                logger.exception("Failed to check favorite update for favorite_id=%s", fav.id)
                continue
        return events

    def _sync_mod_update_metadata(
        self,
        mod: Mod,
        detail: ModItem | dict,
        version: str | None,
        updated_at_remote: str | None,
    ) -> bool:
        """Sync local mod metadata from an update detail response."""
        now = datetime.now(UTC).isoformat()
        if version:
            mod.version = version
        if updated_at_remote:
            mod.updated_at_remote = updated_at_remote
        mod.last_seen_at = now

        original_summary = _extract_original_summary(detail)
        if original_summary is None:
            return False
        original_summary = _clean_import_text(original_summary)
        if not original_summary or original_summary == (mod.original_summary or ""):
            return False
        mod.original_summary = original_summary
        return True

    def _delete_brief_summaries(self, mod_id: int | None) -> None:
        if mod_id is None:
            return
        rows = self.session.exec(
            select(ModSummary).where(
                ModSummary.mod_id == mod_id,
                ModSummary.summary_type == "brief",
            )
        ).all()
        for row in rows:
            self.session.delete(row)


def _extract_version_and_updated_at(detail: ModItem | dict) -> tuple[str | None, str | None]:
    """从原始内容中提取目标字段。"""
    if isinstance(detail, ModItem):
        raw = detail.raw if isinstance(detail.raw, dict) else {}
        updated_at = detail.updated_at.isoformat() if detail.updated_at is not None else None
        return raw.get("version"), updated_at or raw.get("updated_at_remote") or raw.get("updatedAt")
    return detail.get("version"), detail.get("updated_at_remote") or detail.get("updatedAt")


def _extract_original_summary(detail: ModItem | dict) -> str | None:
    if isinstance(detail, ModItem):
        return detail.summary or (detail.raw or {}).get("original_summary") or (detail.raw or {}).get("summary")
    return detail.get("original_summary") or detail.get("summary") or detail.get("description")


def _clean_import_text(value: str) -> str:
    return unescape(value).strip()


def _clean_import_game(value: str, existing: Mod | None = None) -> str:
    game = _clean_import_text(value) if value else ""
    if game.lower() in GENERIC_GAME_LABELS:
        return "" if existing is not None else game
    return game
