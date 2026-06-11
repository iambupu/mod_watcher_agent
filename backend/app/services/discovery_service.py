import json
import logging
from datetime import UTC, datetime

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session

from app.adapters.base import BaseAdapter
from app.models.mod import Mod
from app.models.mod_item import ModItem
from app.models.watch_rule import WatchRule
from app.services.adapter_utils import call_with_adapter
from app.services.filter_service import FilterService
from app.services.llm_client import create_llm_filter_client
from app.services.settings_service import SettingsService
from app.services.source_identity import (
    canonical_external_id,
    find_existing_mod_by_identity,
)
from app.services.update_tracking_service import record_favorite_metadata_update
from app.utils.boolean import parse_optional_bool
from app.utils.numeric import optional_nonnegative_int

logger = logging.getLogger(__name__)


class DiscoveryService:
    """Service for discovering new mods from configured sources."""

    def __init__(self, session: Session):
        """保存数据库会话，用于读取规则、过滤结果和持久化 Mod。"""
        self.session = session

    async def discover_from_rule(self, rule_id: int) -> list[dict]:
        """执行单条监控规则的抓取、过滤和入库流程。"""
        adapter = None
        try:
            rule = self.session.get(WatchRule, rule_id)
            if rule is None:
                raise ValueError(f"WatchRule id={rule_id} not found")
            if not rule.enabled:
                raise ValueError(f"WatchRule id={rule_id} is disabled")

            adapter_class = BaseAdapter.adapters.get(rule.source)
            if adapter_class is None:
                raise ValueError(
                    f"Unknown source '{rule.source}' for rule id={rule_id}"
                )

            # Read API key from DB settings for NexusMods (supports settings-page configured key)
            nexus_api_key = ""
            if rule.source == "nexusmods":
                nexus_api_key = SettingsService(self.session).get("nexus_api_key") or ""
            adapter = adapter_class(api_key=nexus_api_key) if rule.source == "nexusmods" else adapter_class()

            async def _run(a: BaseAdapter) -> list[dict]:
                raw_items: list[ModItem] = await a.fetch(rule.source_config_json)
                all_mods: list[dict] = [_mod_item_to_dict(item) for item in raw_items]
                filter_service = FilterService(llm_client=create_llm_filter_client(self.session))
                filtered = filter_service.apply_filters(rule, all_mods, self.session)
                results = self.upsert_mod_dicts(filtered)
                return list(results["created_items"])

            return await call_with_adapter(
                adapter=adapter,
                callback=_run,
                logger=logger,
                context=f"discover_from_rule rule_id={rule_id}",
            )

        except Exception:
            logger.exception("discover_from_rule failed for rule_id=%s", rule_id)
            self.session.rollback()
            raise
    def upsert_mod_items(self, items: list[ModItem]) -> dict:
        """Persist normalized mod items and return created/updated counts."""
        return self.upsert_mod_dicts([_mod_item_to_dict(item) for item in items])

    def upsert_mod_dicts(self, mod_dicts: list[dict]) -> dict:
        """Persist normalized mod dictionaries with source/external-id de-duplication."""
        now = datetime.now(UTC).isoformat()
        created_items: list[dict] = []
        updated = 0

        for mod_dict in mod_dicts:
            source = str(mod_dict["source"]).strip().lower()
            external_id = canonical_external_id(
                source,
                str(mod_dict["external_id"]),
                str(mod_dict.get("url") or ""),
                game=str(mod_dict.get("game") or ""),
                game_domain=mod_dict.get("game_domain"),
            )
            mod_dict["source"] = source
            mod_dict["external_id"] = external_id
            url = str(mod_dict.get("url") or "").strip()
            existing = find_existing_mod_by_identity(
                self.session,
                source,
                external_id,
                url,
                game=str(mod_dict.get("game") or ""),
                game_domain=mod_dict.get("game_domain"),
            )

            if existing:
                record_favorite_metadata_update(
                    self.session,
                    existing,
                    new_version=_nonblank_or_existing(mod_dict.get("version"), existing.version),
                    new_updated_at=_nonblank_or_existing(mod_dict.get("updated_at_remote"), existing.updated_at_remote),
                    detected_at=now,
                )
                _update_existing_mod(existing, mod_dict, now)
                self.session.add(existing)
                updated += 1
                continue

            new_mod = _new_mod_from_dict(mod_dict, now)
            try:
                with self.session.begin_nested():
                    self.session.add(new_mod)
                    self.session.flush()
                created_items.append(_mod_to_dict(new_mod))
            except IntegrityError:
                existing = find_existing_mod_by_identity(
                    self.session,
                    source,
                    external_id,
                    url,
                    game=str(mod_dict.get("game") or ""),
                    game_domain=mod_dict.get("game_domain"),
                )
                if existing:
                    record_favorite_metadata_update(
                        self.session,
                        existing,
                        new_version=_nonblank_or_existing(mod_dict.get("version"), existing.version),
                        new_updated_at=_nonblank_or_existing(mod_dict.get("updated_at_remote"), existing.updated_at_remote),
                        detected_at=now,
                    )
                    _update_existing_mod(existing, mod_dict, now)
                    self.session.add(existing)
                    updated += 1

        self.session.commit()
        return {
            "created": len(created_items),
            "updated": updated,
            "created_items": created_items,
        }


def _mod_item_to_dict(item: ModItem) -> dict:
    """把适配器 ModItem 统一转换为入库前的字段字典。"""
    raw = item.raw or {}
    game = raw.get("game") if isinstance(raw.get("game"), dict) else {}
    category = item.categories[0] if item.categories and len(item.categories) > 0 else None
    updated_at_str = item.updated_at.isoformat() if item.updated_at is not None else None
    return {
        "source": item.source,
        "external_id": item.source_id,
        "title": item.name,
        "game": item.game,
        "game_domain": game.get("domainName"),
        "url": item.url or "",
        "author": item.author,
        "category": category,
        "tags_json": json.dumps(item.tags, ensure_ascii=False),
        "version": raw.get("version"),
        "created_at_remote": raw.get("createdAt"),
        "updated_at_remote": updated_at_str,
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


def _update_existing_mod(mod: Mod, mod_dict: dict, now: str) -> None:
    """Update an existing mod with fresh remote metadata."""
    mod.external_id = mod_dict["external_id"]
    mod.last_seen_at = now
    mod.game = _nonblank_or_existing(mod_dict.get("game"), mod.game)
    mod.game_domain = _nonblank_or_existing(mod_dict.get("game_domain"), mod.game_domain)
    mod.title = _nonblank_or_existing(mod_dict.get("title"), mod.title)
    mod.url = _nonblank_or_existing(mod_dict.get("url"), mod.url)
    mod.author = _nonblank_or_existing(mod_dict.get("author"), mod.author)
    mod.category = _nonblank_or_existing(mod_dict.get("category"), mod.category)
    mod.tags_json = _nonblank_or_existing(_tags_json_value(mod_dict.get("tags_json")), mod.tags_json)
    mod.original_summary = _nonblank_or_existing(mod_dict.get("original_summary"), mod.original_summary)
    mod.version = _nonblank_or_existing(mod_dict.get("version"), mod.version)
    mod.created_at_remote = _nonblank_or_existing(mod_dict.get("created_at_remote"), mod.created_at_remote)
    mod.updated_at_remote = _nonblank_or_existing(mod_dict.get("updated_at_remote"), mod.updated_at_remote)
    mod.published_at_remote = _nonblank_or_existing(mod_dict.get("published_at_remote"), mod.published_at_remote)
    mod.downloads = _value_or_existing(optional_nonnegative_int(mod_dict.get("downloads")), mod.downloads)
    mod.unique_downloads = _value_or_existing(optional_nonnegative_int(mod_dict.get("unique_downloads")), mod.unique_downloads)
    mod.endorsements = _value_or_existing(optional_nonnegative_int(mod_dict.get("endorsements")), mod.endorsements)
    mod.views = _value_or_existing(optional_nonnegative_int(mod_dict.get("views")), mod.views)
    mod.likes = _value_or_existing(optional_nonnegative_int(mod_dict.get("likes")), mod.likes)
    mod.adult_content = _value_or_existing(parse_optional_bool(mod_dict.get("adult_content")), mod.adult_content)
    mod.thumbnail_url = _nonblank_or_existing(mod_dict.get("thumbnail_url"), mod.thumbnail_url)


def _value_or_existing(value, existing):
    return existing if value is None else value


def _nonblank_or_existing(value, existing):
    if value is None:
        return existing
    if isinstance(value, str) and not value.strip():
        return existing
    return value


def _new_mod_from_dict(mod_dict: dict, now: str) -> Mod:
    """Build a persistent Mod row from normalized metadata."""
    return Mod(
        source=mod_dict["source"],
        external_id=mod_dict["external_id"],
        game=mod_dict.get("game", ""),
        game_domain=mod_dict.get("game_domain"),
        title=mod_dict["title"],
        url=mod_dict.get("url", ""),
        author=mod_dict.get("author"),
        category=mod_dict.get("category"),
        tags_json=_tags_json_value(mod_dict.get("tags_json")) or "[]",
        version=mod_dict.get("version"),
        created_at_remote=mod_dict.get("created_at_remote"),
        updated_at_remote=mod_dict.get("updated_at_remote"),
        published_at_remote=mod_dict.get("published_at_remote"),
        downloads=optional_nonnegative_int(mod_dict.get("downloads")),
        unique_downloads=optional_nonnegative_int(mod_dict.get("unique_downloads")),
        endorsements=optional_nonnegative_int(mod_dict.get("endorsements")),
        views=optional_nonnegative_int(mod_dict.get("views")),
        likes=optional_nonnegative_int(mod_dict.get("likes")),
        adult_content=parse_optional_bool(mod_dict.get("adult_content")),
        thumbnail_url=mod_dict.get("thumbnail_url"),
        original_summary=mod_dict.get("original_summary"),
        first_seen_at=now,
        last_seen_at=now,
    )


def _tags_json_value(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value if value.strip() else None
    if isinstance(value, list):
        return json.dumps(value, ensure_ascii=False)
    return None


def _mod_to_dict(mod: Mod) -> dict:
    """把已持久化的 Mod 行转换为发现结果字典。"""
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
