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
        dict mapping favorite_id -> update_detected boolean or error string.
    """
    results: dict[int, dict] = {}
    with Session(engine) as session:
        favorites = session.exec(
            select(Favorite).where(Favorite.tracking_enabled == True)
        ).all()

        if not favorites:
            return {"message": "No favorites with tracking enabled"}

        service = FavoriteService(session)
        for fav in favorites:
            try:
                detail = await service.check_update(fav.id)
                results[fav.id] = {
                    "update_detected": detail is not None,
                    "detail": detail,
                }
                session.commit()
                if detail is not None:
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
                results[fav.id] = {"error": str(e)}

    return results
