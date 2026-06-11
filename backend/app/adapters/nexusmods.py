import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import httpx

from app.adapters.base import BaseAdapter
from app.config import settings
from app.models.mod_item import ModItem
from app.schemas.watch_rule import NexusModsRuleConfig
from app.utils.boolean import parse_bool
from app.utils.numeric import safe_nonnegative_int
from app.utils.time import parse_utc_datetime

logger = logging.getLogger(__name__)


class RateLimitError(Exception):
    pass


@dataclass(frozen=True)
class NexusModsBatch:
    items: list[ModItem]
    total_count: int
    offset: int


GRAPHQL_ENDPOINT = "https://api.nexusmods.com/v2/graphql"
REST_MOD_DETAIL_ENDPOINT = "https://api.nexusmods.com/v1/games/{game_domain}/mods/{mod_id}.json"
MAX_PAGES = 5
PAGE_SIZE = 100
REQUEST_TIMEOUT = 30.0

MOD_FIELDS = """
    uid
    modId
    name
    summary
    author
    category
    game {
        domainName
        name
    }
    gameId
    version
    createdAt
    updatedAt
    downloads
    endorsements
    adultContent
    thumbnailUrl
    tags {
        name
    }
"""


def _parse_unix_timestamp(value: int | float | str | None) -> datetime | None:
    """解析 Unix 时间戳并返回 UTC 时间。"""
    if value is None:
        return None
    try:
        return datetime.fromtimestamp(int(str(value)), tz=UTC)
    except (TypeError, ValueError, OSError):
        return None


def _unix_timestamp_days_ago(days: int) -> str:
    """生成 Nexus GraphQL 时间过滤需要的 Unix 秒级时间戳。"""
    cutoff = datetime.now(UTC) - timedelta(days=days)
    return str(int(cutoff.timestamp()))


class NexusModsAdapter(BaseAdapter):
    """Adapter for the NexusMods GraphQL v2 API."""

    source = "nexusmods"

    def __init__(self, api_key: str | None = None):
        """保存 Nexus API key；调用方可显式覆盖全局配置。"""
        self.api_key = api_key or settings.NEXUS_API_KEY

    async def _graphql_query(
        self, query: str, variables: dict | None = None
    ) -> dict:
        """执行 Nexus GraphQL 请求，并把 429 转为可识别的限流异常。"""
        headers = {
            "Content-Type": "application/json",
            "Application-Name": "ModWatcherAgent",
            "Application-Version": "0.2.1",
        }
        if self.api_key:
            headers["apikey"] = self.api_key
        payload = {"query": query}
        if variables:
            payload["variables"] = variables

        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            response = await client.post(
                GRAPHQL_ENDPOINT, json=payload, headers=headers
            )
            if response.status_code == 429:
                logger.warning("NexusMods API returned 429 rate limit")
                raise RateLimitError("NexusMods API rate limit exceeded")
            response.raise_for_status()
            data = response.json()
            if data.get("errors"):
                logger.error("NexusMods GraphQL errors: %s", data["errors"])
                raise ValueError(f"NexusMods GraphQL error: {data['errors']}")
            return data

    def _build_filter(self, config: NexusModsRuleConfig) -> dict:
        """根据监控规则构造 Nexus GraphQL 过滤条件。"""
        clauses: list[dict] = [
            {
                "gameDomainName": [
                    {"op": "EQUALS", "value": config.gameDomainName}
                ]
            }
        ]
        if config.queryMode is not None:
            date_field = "updatedAt" if config.queryMode == "updated" else "createdAt"
            clauses.append(
                {
                    date_field: [
                        {
                            "op": "GTE",
                            "value": _unix_timestamp_days_ago(config.updatedSinceDays),
                        }
                    ]
                }
            )
        for category_name in config.categoryNames:
            if category_name:
                clauses.append(
                    {"categoryName": [{"op": "EQUALS", "value": category_name}]}
                )
        for tag in config.tags:
            if tag:
                clauses.append({"tag": [{"op": "EQUALS", "value": tag}]})
        if len(clauses) == 1:
            return {"op": "AND", **clauses[0]}
        return {"op": "AND", "filter": clauses}

    def _build_sort(self, sort_by: str) -> list[dict]:
        """把规则排序枚举映射为 Nexus GraphQL sort 参数。"""
        field_map = {
            "updatedAt_desc": "updatedAt",
            "createdAt_desc": "createdAt",
            "downloads_desc": "downloads",
            "endorsements_desc": "endorsements",
        }
        field = field_map.get(sort_by, "updatedAt")
        return [{field: {"direction": "DESC"}}]

    async def fetch(self, source_config_json: str) -> list[ModItem]:
        """分页读取 Nexus 规则结果；限流时返回已抓到的部分结果。"""
        try:
            config = NexusModsRuleConfig.model_validate_json(source_config_json)
        except Exception:
            logger.exception("Invalid NexusMods source config")
            return []

        query = f"""
        query($filter: ModsFilter, $sort: [ModsSort!], $offset: Int, $count: Int) {{
            mods(
                filter: $filter
                sort: $sort
                offset: $offset
                count: $count
            ) {{
                nodes {{
                    {MOD_FIELDS}
                }}
                nodesCount
                totalCount
            }}
        }}
        """

        results: list[ModItem] = []
        page_count = 0

        while page_count < MAX_PAGES:
            variables = {
                "filter": self._build_filter(config),
                "sort": self._build_sort(config.sortBy),
                "offset": page_count * PAGE_SIZE,
                "count": PAGE_SIZE,
            }
            try:
                data = await self._graphql_query(query, variables)
            except RateLimitError:
                return results

            if not data:
                break

            connection = data.get("data", {}).get("mods") or {}
            nodes = connection.get("nodes") or []

            for node in nodes:
                results.append(self.normalize(node))

            page_count += 1
            if len(nodes) < PAGE_SIZE:
                break

        return results

    async def iter_game_mod_batches(
        self,
        game_domain_name: str,
        *,
        batch_size: int = PAGE_SIZE,
        max_batches: int | None = None,
    ) -> AsyncIterator[NexusModsBatch]:
        """Yield NexusMods game mods in API-sized batches."""
        query = f"""
        query($filter: ModsFilter, $sort: [ModsSort!], $offset: Int, $count: Int) {{
            mods(
                filter: $filter
                sort: $sort
                offset: $offset
                count: $count
            ) {{
                nodes {{
                    {MOD_FIELDS}
                }}
                totalCount
            }}
        }}
        """
        filter_value = {
            "op": "AND",
            "gameDomainName": [{"op": "EQUALS", "value": game_domain_name}],
        }
        sort_value = self._build_sort("updatedAt_desc")
        page_count = 0
        offset = 0
        while max_batches is None or page_count < max_batches:
            variables = {
                "filter": filter_value,
                "sort": sort_value,
                "offset": offset,
                "count": batch_size,
            }
            data = await self._graphql_query(query, variables)
            connection = data.get("data", {}).get("mods") or {}
            nodes = connection.get("nodes") or []
            total_count = connection.get("totalCount")
            if total_count is None:
                raise ValueError("NexusMods response missing totalCount")
            if not nodes:
                return
            batch_offset = offset
            offset += len(nodes)
            yield NexusModsBatch(
                items=[self.normalize(node) for node in nodes],
                total_count=int(total_count),
                offset=batch_offset,
            )
            page_count += 1
            if offset >= int(total_count):
                return

    async def fetch_mod_detail(
        self, external_id: str, game_domain: str | None = None
    ) -> ModItem | None:
        """优先用带 game_domain 的 REST 详情，必要时回退 GraphQL 查单个 modId。"""
        embedded_game_domain, mod_id = _parse_external_id(external_id)
        if mod_id is None:
            return None
        resolved_game_domain = (game_domain or embedded_game_domain or "").strip().lower() or None

        if resolved_game_domain:
            try:
                rest_detail = await self._fetch_mod_detail_rest(resolved_game_domain, mod_id)
            except RateLimitError:
                return None
            except Exception as exc:
                logger.warning(
                    "NexusMods REST detail failed for %s:%s; fallback to GraphQL. error=%s",
                    resolved_game_domain,
                    mod_id,
                    exc,
                )
            else:
                if rest_detail is not None:
                    return rest_detail

        query = f"""
        query($filter: ModsFilter, $offset: Int, $count: Int) {{
            mods(filter: $filter, offset: $offset, count: $count) {{
                nodes {{
                    {MOD_FIELDS}
                }}
            }}
        }}
        """

        filter_clauses: list[dict] = [
            {"modId": [{"op": "EQUALS", "value": str(mod_id)}]}
        ]
        if resolved_game_domain:
            filter_clauses.append(
                {"gameDomainName": [{"op": "EQUALS", "value": resolved_game_domain}]}
            )
        variables = {
            "filter": {"op": "AND", "filter": filter_clauses},
            "offset": 0,
            "count": 1,
        }
        try:
            data = await self._graphql_query(query, variables)
        except RateLimitError:
            return None
        except ValueError as exc:
            if not resolved_game_domain:
                logger.warning("NexusMods detail lookup failed for modId=%s: %s", mod_id, exc)
                return None
            logger.warning(
                "NexusMods detail GraphQL failed for %s:%s; fallback to REST detail endpoint. error=%s",
                resolved_game_domain,
                mod_id,
                exc,
            )
            return await self._fetch_mod_detail_rest(resolved_game_domain, mod_id)
        if not data:
            if not resolved_game_domain:
                return None
            return await self._fetch_mod_detail_rest(resolved_game_domain, mod_id)

        nodes = data.get("data", {}).get("mods", {}).get("nodes") or []
        mod_node = nodes[0] if nodes else None
        if mod_node is None:
            if not resolved_game_domain:
                return None
            return await self._fetch_mod_detail_rest(resolved_game_domain, mod_id)

        return self.normalize(mod_node)

    async def _fetch_mod_detail_rest(self, game_domain: str, mod_id: int) -> ModItem | None:
        """Fallback REST detail fetch for APIs that require gameId in GraphQL filters."""
        headers = {
            "Application-Name": "ModWatcherAgent",
            "Application-Version": "0.2.1",
        }
        if self.api_key:
            headers["apikey"] = self.api_key
        url = REST_MOD_DETAIL_ENDPOINT.format(game_domain=game_domain, mod_id=mod_id)

        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            response = await client.get(url, headers=headers)
        if response.status_code == 404:
            return None
        if response.status_code == 429:
            raise RateLimitError("NexusMods API rate limit exceeded")
        response.raise_for_status()
        payload = response.json() or {}
        return self._normalize_rest_detail(payload, game_domain=game_domain, mod_id=mod_id)

    def _normalize_rest_detail(self, payload: dict, *, game_domain: str, mod_id: int) -> ModItem:
        """Normalize Nexus v1 REST mod detail shape into ModItem."""
        rest_mod_id = payload.get("mod_id") or payload.get("modId") or mod_id
        game_name = (
            payload.get("game_name")
            or (payload.get("game") or {}).get("name")
            or game_domain
        )
        category_name = (
            payload.get("category_name")
            or payload.get("category")
            or ""
        )
        updated_at = parse_utc_datetime(payload.get("updatedAt")) or parse_utc_datetime(payload.get("updated_time"))
        if updated_at is None:
            updated_at = _parse_unix_timestamp(payload.get("updated_timestamp") or payload.get("updated_time"))
        summary = (payload.get("summary") or payload.get("description") or "").strip()
        author = payload.get("author") or payload.get("uploaded_by") or ""
        thumbnail_url = payload.get("picture_url") or payload.get("thumbnail_url") or ""
        downloads = payload.get("mod_downloads") or payload.get("downloads") or 0
        endorsements = payload.get("endorsement_count") or payload.get("endorsements") or 0

        raw_payload = {
            "uid": payload.get("uid"),
            "modId": rest_mod_id,
            "name": payload.get("name", ""),
            "summary": summary,
            "author": author,
            "category": category_name,
            "game": {"domainName": game_domain, "name": game_name},
            "gameId": payload.get("game_id") or payload.get("gameId"),
            "version": payload.get("version"),
            "createdAt": payload.get("createdAt"),
            "updatedAt": payload.get("updatedAt"),
            "downloads": downloads,
            "endorsements": endorsements,
            "adultContent": payload.get("contains_adult_content")
            if payload.get("contains_adult_content") is not None
            else payload.get("adultContent"),
            "thumbnailUrl": thumbnail_url,
            "tags": payload.get("tags") if isinstance(payload.get("tags"), list) else [],
            "raw_detail_payload": payload,
        }

        adult_content = payload.get("contains_adult_content")
        if adult_content is None:
            adult_content = payload.get("adultContent")

        return ModItem(
            source_id=f"{game_domain}:{rest_mod_id}",
            source="nexusmods",
            name=payload.get("name", ""),
            game=game_name,
            url=f"https://www.nexusmods.com/{game_domain}/mods/{rest_mod_id}",
            summary=summary,
            author=author,
            downloads=safe_nonnegative_int(downloads),
            endorsements=safe_nonnegative_int(endorsements),
            likes=safe_nonnegative_int(payload.get("likes")),
            categories=[category_name] if category_name else [],
            tags=[],
            thumbnail_url=thumbnail_url,
            updated_at=updated_at,
            is_adult=parse_bool(adult_content),
            raw=raw_payload,
        )

    def normalize(self, raw_item: dict) -> ModItem:
        """把 Nexus GraphQL 节点转换为统一 ModItem，并把 source_id 命名空间化。"""
        game = raw_item.get("game") or {}
        game_domain = game.get("domainName", "")
        category = raw_item.get("category")
        tags = [
            tag.get("name")
            for tag in raw_item.get("tags") or []
            if isinstance(tag, dict) and tag.get("name")
        ]

        return ModItem(
            source_id=f"{game_domain}:{raw_item.get('modId')}" if game_domain else str(raw_item.get("modId", "")),
            source="nexusmods",
            name=raw_item.get("name", ""),
            game=game.get("name", ""),
            url=f"https://www.nexusmods.com/{game_domain}/mods/{raw_item.get('modId')}",
            summary=raw_item.get("summary", ""),
            author=raw_item.get("author") or "",
            downloads=safe_nonnegative_int(raw_item.get("downloads")),
            endorsements=safe_nonnegative_int(raw_item.get("endorsements")),
            likes=0,
            categories=[category] if category else [],
            tags=tags,
            thumbnail_url=raw_item.get("thumbnailUrl", ""),
            updated_at=parse_utc_datetime(raw_item.get("updatedAt")),
            is_adult=parse_bool(raw_item.get("adultContent")),
            raw=raw_item,
        )


def _parse_external_id(external_id: str) -> tuple[str | None, int | None]:
    value = str(external_id or "").strip()
    if ":" in value:
        game_domain, mod_id = value.split(":", 1)
        try:
            parsed_mod_id = int(mod_id)
        except ValueError:
            return game_domain.strip().lower() or None, None
        return game_domain.strip().lower() or None, parsed_mod_id if parsed_mod_id > 0 else None
    try:
        parsed_mod_id = int(value)
    except ValueError:
        return None, None
    return None, parsed_mod_id if parsed_mod_id > 0 else None
