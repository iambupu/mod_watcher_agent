import json
import logging
from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.adapters.base import BaseAdapter
from app.models.mod import Mod
from app.models.mod_item import ModItem
from app.models.watch_rule import WatchRule
from app.services.filter_service import FilterService
from app.services.settings_service import SettingsService

logger = logging.getLogger(__name__)


class DiscoveryService:
    """Service for discovering new mods from configured sources."""

    def __init__(self, session: Session):
        self.session = session

    async def discover_from_rule(self, rule_id: int) -> list[dict]:
        try:
            rule = self.session.get(WatchRule, rule_id)
            if rule is None:
                raise ValueError(f"WatchRule id={rule_id} not found")
            if not rule.enabled:
                raise ValueError(f"WatchRule id={rule_id} is disabled")

            AdapterClass = BaseAdapter.adapters.get(rule.source)
            if AdapterClass is None:
                raise ValueError(
                    f"Unknown source '{rule.source}' for rule id={rule_id}"
                )

            # Read API key from DB settings for NexusMods (supports settings-page configured key)
            nexus_api_key = rule.source == "nexusmods" and SettingsService(self.session).get("nexus_api_key") or ""
            adapter = AdapterClass(api_key=nexus_api_key) if rule.source == "nexusmods" else AdapterClass()
            raw_items: list[ModItem] = await adapter.fetch(rule.source_config_json)

            all_mods: list[dict] = [_mod_item_to_dict(item) for item in raw_items]

            filter_service = FilterService()
            filtered = filter_service.apply_filters(rule, all_mods, self.session)

            now = datetime.now(timezone.utc).isoformat()
            results: list[dict] = []

            for mod_dict in filtered:
                existing = self.session.exec(
                    select(Mod).where(
                        Mod.source == mod_dict["source"],
                        Mod.external_id == mod_dict["external_id"],
                    )
                ).first()

                if existing:
                    existing.last_seen_at = now
                    existing.title = mod_dict.get("title", existing.title)
                    existing.author = mod_dict.get("author", existing.author)
                    existing.category = mod_dict.get("category", existing.category)
                    existing.version = mod_dict.get("version", existing.version)
                    existing.downloads = mod_dict.get("downloads", existing.downloads)
                    existing.unique_downloads = mod_dict.get("unique_downloads", existing.unique_downloads)
                    existing.endorsements = mod_dict.get("endorsements", existing.endorsements)
                    existing.views = mod_dict.get("views", existing.views)
                    existing.adult_content = mod_dict.get("adult_content", existing.adult_content)
                    existing.thumbnail_url = mod_dict.get("thumbnail_url", existing.thumbnail_url)
                    existing.updated_at_remote = mod_dict.get("updated_at_remote", existing.updated_at_remote)
                    self.session.add(existing)
                    results.append(_mod_to_dict(existing))
                else:
                    new_mod = Mod(
                        source=mod_dict["source"],
                        external_id=mod_dict["external_id"],
                        game=mod_dict.get("game", ""),
                        game_domain=mod_dict.get("game_domain"),
                        title=mod_dict["title"],
                        url=mod_dict.get("url", ""),
                        author=mod_dict.get("author"),
                        category=mod_dict.get("category"),
                        version=mod_dict.get("version"),
                        created_at_remote=mod_dict.get("created_at_remote"),
                        updated_at_remote=mod_dict.get("updated_at_remote"),
                        published_at_remote=mod_dict.get("published_at_remote"),
                        downloads=mod_dict.get("downloads"),
                        unique_downloads=mod_dict.get("unique_downloads"),
                        endorsements=mod_dict.get("endorsements"),
                        views=mod_dict.get("views"),
                        likes=mod_dict.get("likes"),
                        adult_content=mod_dict.get("adult_content"),
                        thumbnail_url=mod_dict.get("thumbnail_url"),
                        original_summary=mod_dict.get("original_summary"),
                        first_seen_at=now,
                        last_seen_at=now,
                    )
                    try:
                        with self.session.begin_nested():
                            self.session.add(new_mod)
                            self.session.flush()
                        results.append(_mod_to_dict(new_mod))
                    except IntegrityError:
                        # Another concurrent run inserted the same source/external_id.
                        existing = self.session.exec(
                            select(Mod).where(
                                Mod.source == mod_dict["source"],
                                Mod.external_id == mod_dict["external_id"],
                            )
                        ).first()
                        if existing:
                            existing.last_seen_at = now
                            self.session.add(existing)
                            results.append(_mod_to_dict(existing))

            self.session.commit()
            return results

        except Exception:
            logger.exception("discover_from_rule failed for rule_id=%s", rule_id)
            self.session.rollback()
            raise


def _mod_item_to_dict(item: ModItem) -> dict:
    raw = item.raw or {}
    game = raw.get("game") or {}
    return {
        "source": item.source,
        "external_id": item.source_id,
        "title": item.name,
        "game": item.game,
        "game_domain": game.get("domainName"),
        "url": item.url,
        "author": item.author,
        "category": item.categories[0] if item.categories else None,
        "version": (item.raw or {}).get("version"),
        "created_at_remote": raw.get("createdAt"),
        "updated_at_remote": item.updated_at.isoformat() if item.updated_at else None,
        "published_at_remote": raw.get("publishedAt"),
        "downloads": item.downloads,
        "unique_downloads": raw.get("uniqueDownloads"),
        "endorsements": item.endorsements,
        "views": raw.get("views"),
        "likes": item.likes,
        "adult_content": item.is_adult,
        "thumbnail_url": item.thumbnail_url,
        "original_summary": item.summary,
    }


def _mod_to_dict(mod: Mod) -> dict:
    return {
        "id": mod.id,
        "source": mod.source,
        "external_id": mod.external_id,
        "game": mod.game,
        "game_domain": mod.game_domain,
        "title": mod.title,
        "url": mod.url,
        "author": mod.author,
        "category": mod.category,
        "tags_json": mod.tags_json,
        "original_summary": mod.original_summary,
        "version": mod.version,
        "created_at_remote": mod.created_at_remote,
        "updated_at_remote": mod.updated_at_remote,
        "published_at_remote": mod.published_at_remote,
        "downloads": mod.downloads,
        "unique_downloads": mod.unique_downloads,
        "endorsements": mod.endorsements,
        "views": mod.views,
        "likes": mod.likes,
        "adult_content": mod.adult_content,
        "thumbnail_url": mod.thumbnail_url,
        "first_seen_at": mod.first_seen_at,
        "last_seen_at": mod.last_seen_at,
    }
