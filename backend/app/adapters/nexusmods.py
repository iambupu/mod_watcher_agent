import logging
from datetime import datetime, timedelta, timezone

import httpx

from app.adapters.base import BaseAdapter
from app.config import settings
from app.models.mod_item import ModItem
from app.schemas.watch_rule import NexusModsRuleConfig

logger = logging.getLogger(__name__)


class RateLimitError(Exception):
    pass

GRAPHQL_ENDPOINT = "https://api.nexusmods.com/v2/graphql"
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


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    value = value.replace("Z", "+00:00")
    return datetime.fromisoformat(value)


def _unix_timestamp_days_ago(days: int) -> str:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    return str(int(cutoff.timestamp()))


class NexusModsAdapter(BaseAdapter):
    """Adapter for the NexusMods GraphQL v2 API."""

    source = "nexusmods"

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or settings.NEXUS_API_KEY

    async def _graphql_query(
        self, query: str, variables: dict | None = None
    ) -> dict:
        headers = {
            "Content-Type": "application/json",
            "Application-Name": "ModWatcherAgent",
            "Application-Version": "0.1.0",
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
        clauses: list[dict] = [
            {
                "gameDomainName": [
                    {"op": "EQUALS", "value": config.gameDomainName}
                ]
            }
        ]
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
        field_map = {
            "updatedAt_desc": "updatedAt",
            "createdAt_desc": "createdAt",
            "downloads_desc": "downloads",
            "endorsements_desc": "endorsements",
        }
        field = field_map.get(sort_by, "updatedAt")
        return [{field: {"direction": "DESC"}}]

    async def fetch(self, source_config_json: str) -> list[ModItem]:
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

    async def fetch_mod_detail(
        self, external_id: str, game_domain: str | None = None
    ) -> ModItem | None:
        mod_id = int(external_id)

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
        if game_domain:
            filter_clauses.append(
                {"gameDomainName": [{"op": "EQUALS", "value": game_domain}]}
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
        if not data:
            return None

        nodes = data.get("data", {}).get("mods", {}).get("nodes") or []
        mod_node = nodes[0] if nodes else None
        if mod_node is None:
            return None

        return self.normalize(mod_node)

    def normalize(self, raw_item: dict) -> ModItem:
        game = raw_item.get("game") or {}
        game_domain = game.get("domainName", "")
        category = raw_item.get("category")
        tags = [
            tag.get("name")
            for tag in raw_item.get("tags") or []
            if isinstance(tag, dict) and tag.get("name")
        ]

        return ModItem(
            source_id=str(raw_item.get("modId", "")),
            source="nexusmods",
            name=raw_item.get("name", ""),
            game=game.get("name", ""),
            url=f"https://www.nexusmods.com/{game_domain}/mods/{raw_item.get('modId')}",
            summary=raw_item.get("summary", ""),
            author=raw_item.get("author") or "",
            downloads=raw_item.get("downloads") or 0,
            endorsements=raw_item.get("endorsements") or 0,
            likes=0,
            categories=[category] if category else [],
            tags=tags,
            thumbnail_url=raw_item.get("thumbnailUrl", ""),
            updated_at=_parse_datetime(raw_item.get("updatedAt")),
            is_adult=raw_item.get("adultContent", False),
            raw=raw_item,
        )
