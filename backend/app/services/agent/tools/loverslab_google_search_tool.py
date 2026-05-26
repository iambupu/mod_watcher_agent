from dataclasses import dataclass
from typing import Any

import httpx
from sqlmodel import Session

from app.models.mod import Mod
from app.services.agent.planning.query_intent import detect_adult_constraint
from app.services.agent.search_types import SearchResult
from app.services.agent.semantic_search import semantic_query
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
    """Agent tool that searches Google for indexed LoversLab pages."""

    name = "loverslab_google_search"

    def __init__(self, session: Session):
        """初始化实例并保存运行所需的依赖。"""
        self.session = session
        self.settings = SettingsService(session)
        self.last_status = "not_started"
        self.last_reason: str | None = None

    async def run(self, tool_input: LoversLabGoogleSearchInput) -> list[SearchResult]:
        """执行任务流程并返回结果。"""
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
        """构建内部流程需要的数据结构。"""
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
        if tool_input.updated_since_days:
            days = max(1, min(365, int(tool_input.updated_since_days)))
            params["dateRestrict"] = f"d{days}"
        return params

    async def _fetch(self, params: dict[str, str | int]) -> dict[str, Any]:
        """请求外部数据并返回标准化结果。"""
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            response = await client.get(GOOGLE_CUSTOM_SEARCH_ENDPOINT, params=params)
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict):
                raise ValueError("Google Custom Search response is not an object")
            return data

    def _upsert(self, items: list[dict[str, Any]], tool_input: LoversLabGoogleSearchInput) -> list[Mod]:
        """内部辅助函数，用于拆分上层流程中的局部规则。"""
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
        """内部辅助函数，用于拆分上层流程中的局部规则。"""
        scored = score_and_sort_loverslab_mods(mods, query=tool_input.query, limit=tool_input.limit)
        return [SearchResult(score=score, mod=mod, tool_name=self.name) for score, mod in scored]


def loverslab_google_input_from_plan(query: str, plan: dict[str, Any]) -> LoversLabGoogleSearchInput | None:
    """处理当前模块的业务逻辑并返回结果。"""
    sources = [str(value).strip().lower() for value in (plan.get("sources") or []) if str(value).strip()]
    if sources and "loverslab" not in sources:
        return None
    games = [str(value).strip() for value in (plan.get("games") or []) if str(value).strip()]
    game_domains = [str(value).strip() for value in (plan.get("game_domains") or []) if str(value).strip()]
    days = _optional_time_window(plan.get("updated_since_days"))
    if days is None and str(plan.get("sort_field") or "") in {"updated_at_remote", "first_seen_at"}:
        days = 30
    return LoversLabGoogleSearchInput(
        query=query.split("[scope]", 1)[0].strip(),
        game=games[0] if games else game_domains[0] if game_domains else None,
        adult_content=plan.get("adult_content") if isinstance(plan.get("adult_content"), bool) else detect_adult_constraint(query),
        updated_since_days=days,
        sort_field=str(plan.get("sort_field") or "relevance"),
        limit=int(plan.get("limit") or 8),
    )


def _optional_time_window(value: Any) -> int | None:
    try:
        parsed = int(str(value or "").replace(",", "").strip())
    except (TypeError, ValueError):
        return None
    return max(1, min(365, parsed))


def _thumbnail_url(item: dict[str, Any]) -> str | None:
    """内部辅助函数，用于拆分上层流程中的局部规则。"""
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
