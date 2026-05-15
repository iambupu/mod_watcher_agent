"""Job: Discover new mods from all enabled watch rules."""

import logging

from sqlmodel import Session, select

from app.db import engine
from app.models.watch_rule import WatchRule
from app.services.discovery_service import DiscoveryService
from app.services.notification_service import NotificationService
from app.services.system_notification_service import SystemNotificationService

logger = logging.getLogger(__name__)


async def discover_new_mods() -> dict:
    with Session(engine) as session:
        rules = session.exec(select(WatchRule).where(WatchRule.enabled == True)).all()
        notification_service = NotificationService(session)
        results = {}
        for rule in rules:
            discovery = DiscoveryService(session)
            try:
                new_mods = await discovery.discover_from_rule(rule.id)
                results[rule.name] = len(new_mods)
                session.commit()
                if new_mods:
                    SystemNotificationService(session).create_event(
                        event_type="new_mod_discovered",
                        title=f"新 Mod 发现 - {rule.name}",
                        message=f"{len(new_mods)} 个新 Mod 命中规则「{rule.name}」",
                    )
                    nc = notification_service.parse_notification_config(rule)
                    if nc.enabled and nc.mode == "instant":
                        await notification_service.notify_new_mods(new_mods, rule.name, notification_config=nc)
            except ValueError as e:
                logger.warning("Rule '%s': %s", rule.name, e)
                continue
            except Exception as e:
                session.rollback()
                logger.error("Rule '%s': %s", rule.name, e)
                results[rule.name] = f"error: {e}"
                SystemNotificationService(session).create_event(
                    event_type="scrape_error",
                    title=f"抓取失败 - {rule.name}",
                    message=str(e),
                )
        return results
