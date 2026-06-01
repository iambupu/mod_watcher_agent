"""Job: Check all favorited mods for updates.

Triggers: Every 12 hours (configurable via FAVORITE_CHECK_HOURS env).
"""

from sqlmodel import Session, select

from app.db import engine
from app.models.favorite import Favorite
from app.models.mod import Mod
from app.services.favorite_service import FavoriteService
from app.services.system_notification_service import SystemNotificationService


async def check_favorite_updates() -> dict:
    """Iterate all favorites with tracking enabled and check each for updates.

    Returns:
        Structured summary plus per-favorite status entries for job metadata.
    """
    results: dict[str, dict] = {}
    with Session(engine) as session:
        favorites = session.exec(
            select(Favorite).where(Favorite.tracking_enabled.is_(True))
        ).all()

        if not favorites:
            return {
                "summary": {
                    "scanned": 0,
                    "updated": 0,
                    "failed": 0,
                    "message": "No favorites with tracking enabled",
                },
                "favorites": [],
            }

        service = FavoriteService(session)
        for fav in favorites:
            mod = session.get(Mod, fav.mod_id)
            entry = {
                "favorite_id": fav.id,
                "mod_id": fav.mod_id,
                "title": mod.title if mod else f"Mod #{fav.mod_id}",
                "source": mod.source if mod else None,
                "url": mod.url if mod else None,
                "update_detected": False,
                "update_event_id": None,
                "old_version": fav.last_known_version,
                "new_version": None,
                "old_updated_at": fav.last_known_updated_at,
                "new_updated_at": None,
                "last_checked_at": None,
                "notification_sent": False,
                "error": None,
            }
            try:
                detail = await service.check_update(fav.id)
                session.refresh(fav)
                entry["last_checked_at"] = fav.last_checked_at
                entry["update_detected"] = detail is not None
                if detail is not None:
                    entry.update({
                        "update_event_id": detail.id,
                        "old_version": detail.old_version,
                        "new_version": detail.new_version,
                        "old_updated_at": detail.old_updated_at,
                        "new_updated_at": detail.new_updated_at,
                        "notification_sent": bool(getattr(detail, "notification_sent", False)),
                    })
                session.commit()
                if detail is not None and fav.notify_on_update:
                    mod = session.get(Mod, detail.mod_id)
                    if mod:
                        SystemNotificationService(session).create_event(
                            event_type="favorite_updated",
                            title=f"收藏更新 - {mod.title}",
                            message=f"{mod.title} 从 {detail.old_version or '未知'} 更新到 {detail.new_version or '未知'}",
                            mod_id=mod.id,
                            related_url=mod.url,
                        )
            except Exception as e:
                session.rollback()
                entry["error"] = str(e)
            results[str(fav.id)] = entry

    entries = list(results.values())
    return {
        "summary": {
            "scanned": len(entries),
            "updated": sum(1 for entry in entries if entry.get("update_detected")),
            "failed": sum(1 for entry in entries if entry.get("error")),
        },
        "favorites": entries,
    }
