from dataclasses import dataclass
from typing import Any

import httpx
from sqlmodel import Session

from app.models.mod import Mod
from app.services.agent.filter_value_utils import optional_time_window
from app.services.agent.planning.query_intent import detect_adult_constraint
from app.services.agent.planning.slot_normalization import normalize_limit
from app.services.agent.search_types import SearchResult
from app.services.agent.semantic_search import semantic_query, strip_scope
from app.services.agent.tools.loverslab_search_common import (
    REQUEST_TIMEOUT,
    LoversLabSearchRecord,
    clean_loverslab_query,
    is_loverslab_url,
    score_and_sort_loverslab_mods,
    upsert_loverslab_search_records,
)
from app.services.settings_service import SettingsService

GOOGLE_CUSTOM_SEARCH_ENDPOINT = "https://customsearch.googleapis.com/customsearch/v1"
MAX_GOOGLE_RESULTS = 10


@dataclass
class LoversLabGoogleSearchInput:
    query: str = ""
    game: str | None = None
    adult_content: bool | None = None
    updated_since_days: int | None = None
    sort_field: str = "relevance"
    limit: int = 8


class LoversLabGoogleSearchTool:
    """通过 Google Custom Search 查找已索引的 LoversLab 页面。"""

    name = "loverslab_google_search"

    def __init__(self, session: Session):
        """保存数据库会话和搜索配置，状态字段用于 evidence 说明跳过/降级原因。"""
        self.session = session
        self.settings = SettingsService(session)
        self.last_status = "not_started"
        self.last_reason: str | None = None

    async def run(self, tool_input: LoversLabGoogleSearchInput) -> list[SearchResult]:
        """调用 Google Custom Search，物化 LoversLab 链接后按本轮查询排序。"""
        self.last_status = "succeeded"
        self.last_reason = None
        api_key = (self.settings.get("google_search_api_key") or "").strip()
        engine_id = (self.settings.get("google_search_engine_id") or "").strip()
        if not api_key or not engine_id:
            self.last_status = "skipped"
            self.last_reason = "missing_credentials"
            return []

        params = self._build_params(tool_input, api_key, engine_id)
        try:
            data = await self._fetch(params)
        except httpx.HTTPError:
            self.last_status = "degraded"
            self.last_reason = "http_error"
            return []
        except ValueError:
            self.last_status = "degraded"
            self.last_reason = "invalid_response"
            return []

        mods = self._upsert(data.get("items") or [], tool_input)
        return self._score_and_sort(mods, tool_input)

    def _build_params(
        self,
        tool_input: LoversLabGoogleSearchInput,
        api_key: str,
        engine_id: str,
    ) -> dict[str, str | int]:
        """构建 Google Custom Search 参数，并把查询限制到 loverslab.com。"""
        query = semantic_query(clean_loverslab_query(tool_input.query)).search_text()
        if tool_input.game:
            query = f"{query} {tool_input.game}".strip()
        params: dict[str, str | int] = {
            "key": api_key,
            "cx": engine_id,
            "q": query or "mod",
            "siteSearch": "loverslab.com",
            "siteSearchFilter": "i",
            "num": max(1, min(MAX_GOOGLE_RESULTS, tool_input.limit)),
            "safe": "off",
            "filter": "1",
        }
        days = optional_time_window(tool_input.updated_since_days)
        if days is not None:
            params["dateRestrict"] = f"d{days}"
        return params

    async def _fetch(self, params: dict[str, str | int]) -> dict[str, Any]:
        """请求 Google Custom Search API 并校验响应是对象。"""
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            response = await client.get(GOOGLE_CUSTOM_SEARCH_ENDPOINT, params=params)
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict):
                raise ValueError("Google Custom Search response is not an object")
            return data

    def _upsert(self, items: list[dict[str, Any]], tool_input: LoversLabGoogleSearchInput) -> list[Mod]:
        """把 Google 搜索条目转换成 LoversLab 搜索记录并写回本地缓存。"""
        records: list[LoversLabSearchRecord] = []
        for item in items:
            url = str(item.get("link") or "").strip()
            if not is_loverslab_url(url):
                continue
            records.append(
                LoversLabSearchRecord(
                    title=str(item.get("title") or "").strip(),
                    url=url,
                    summary=str(item.get("snippet") or "").strip() or None,
                    category="Google Search",
                    thumbnail_url=_thumbnail_url(item),
                    raw=item,
                )
            )
        return upsert_loverslab_search_records(
            self.session,
            records,
            game=tool_input.game,
            adult_content=tool_input.adult_content,
        )

    def _score_and_sort(self, mods: list[Mod], tool_input: LoversLabGoogleSearchInput) -> list[SearchResult]:
        """复用 LoversLab 公共排序，返回统一 SearchResult。"""
        scored = score_and_sort_loverslab_mods(mods, query=tool_input.query, limit=tool_input.limit)
        return [SearchResult(score=score, mod=mod, tool_name=self.name) for score, mod in scored]


def loverslab_google_input_from_plan(query: str, plan: dict[str, Any]) -> LoversLabGoogleSearchInput | None:
    """从通用 query_plan 构造 Google LoversLab 搜索输入；非 LoversLab 来源直接跳过。"""
    sources = [str(value).strip().lower() for value in (plan.get("sources") or []) if str(value).strip()]
    if sources and "loverslab" not in sources:
        return None
    games = [str(value).strip() for value in (plan.get("games") or []) if str(value).strip()]
    game_domains = [str(value).strip() for value in (plan.get("game_domains") or []) if str(value).strip()]
    days = optional_time_window(plan.get("updated_since_days"))
    if days is None and str(plan.get("sort_field") or "") in {"updated_at_remote", "first_seen_at"}:
        days = 30
    return LoversLabGoogleSearchInput(
        query=strip_scope(query),
        game=games[0] if games else game_domains[0] if game_domains else None,
        adult_content=plan.get("adult_content") if isinstance(plan.get("adult_content"), bool) else detect_adult_constraint(query),
        updated_since_days=days,
        sort_field=str(plan.get("sort_field") or "relevance"),
        limit=normalize_limit(plan, default=8, maximum=20),
    )


def _thumbnail_url(item: dict[str, Any]) -> str | None:
    """从 Google pagemap 中提取可展示缩略图。"""
    pagemap = item.get("pagemap")
    if not isinstance(pagemap, dict):
        return None
    for key in ("cse_thumbnail", "cse_image"):
        values = pagemap.get(key)
        if isinstance(values, list) and values and isinstance(values[0], dict):
            src = str(values[0].get("src") or "").strip()
            if src:
                return src
    return None
