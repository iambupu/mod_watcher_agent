import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

import httpx
from selectolax.parser import HTMLParser
from sqlmodel import Session

from app.models.mod import Mod
from app.services.agent.search_types import SearchResult
from app.services.agent.semantic_search import semantic_query
from app.services.agent.tools.loverslab_google_search_tool import (
    loverslab_google_input_from_plan,
)
from app.services.agent.tools.loverslab_search_common import (
    LOVERSLAB_HOSTS,
    REQUEST_TIMEOUT,
    LoversLabSearchRecord,
    clean_loverslab_query,
    is_loverslab_url,
    loverslab_search_results,
    upsert_loverslab_search_records,
)
from app.services.settings_service import SettingsService

MAX_SCRAPE_RESULTS = 10
SEARCH_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
)


@dataclass
class LoversLabSearchScrapeInput:
    query: str = ""
    game: str | None = None
    adult_content: bool | None = None
    updated_since_days: int | None = None
    sort_field: str = "relevance"
    limit: int = 8


@dataclass
class SearchScrapeResult:
    title: str
    url: str
    snippet: str | None = None


class LoversLabSearchScrapeTool:
    """抓取公开搜索结果页中的 LoversLab 链接。"""

    name = "loverslab_scrape_search"

    def __init__(self, session: Session):
        """保存数据库会话和设置项，便于按配置启停公开搜索页抓取。"""
        self.session = session
        self.settings = SettingsService(session)
        self.last_status = "not_started"
        self.last_reason: str | None = None

    async def run(self, tool_input: LoversLabSearchScrapeInput) -> list[SearchResult]:
        """抓取公开搜索页里的 LoversLab 链接，物化后按相关性排序。"""
        self.last_status = "succeeded"
        self.last_reason = None
        enabled = (self.settings.get("loverslab_search_scrape_enabled") or "true").strip().lower()
        if enabled not in {"1", "true", "yes", "on"}:
            self.last_status = "skipped"
            self.last_reason = "disabled"
            return []

        engine = (self.settings.get("loverslab_search_scrape_engine") or "duckduckgo").strip().lower()
        query = self._build_query(tool_input)
        try:
            html = await self._fetch_search_page(query=query, engine=engine, limit=tool_input.limit)
        except httpx.HTTPError:
            self.last_status = "degraded"
            self.last_reason = "http_error"
            return []

        results = self._parse_results(html, engine)
        mods = self._upsert(results, tool_input, engine)
        return loverslab_search_results(
            mods,
            query=tool_input.query,
            limit=tool_input.limit,
            tool_name=self.name,
        )

    def _build_query(self, tool_input: LoversLabSearchScrapeInput) -> str:
        """构造带 site:loverslab.com 的公开搜索查询。"""
        parts = ["site:loverslab.com", semantic_query(clean_loverslab_query(tool_input.query)).search_text()]
        if tool_input.game:
            parts.append(tool_input.game)
        if tool_input.updated_since_days:
            parts.append("mod")
        return " ".join(part for part in parts if part).strip()

    async def _fetch_search_page(self, *, query: str, engine: str, limit: int) -> str:
        """请求 Google 或 DuckDuckGo 的 HTML 搜索页。"""
        headers = {
            "User-Agent": SEARCH_USER_AGENT,
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }
        params: dict[str, str | int]
        url: str
        if engine == "google":
            url = "https://www.google.com/search"
            params = {"q": query, "num": max(1, min(MAX_SCRAPE_RESULTS, limit)), "hl": "zh-CN", "safe": "off"}
        else:
            url = "https://html.duckduckgo.com/html/"
            params = {"q": query}
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT, follow_redirects=True, headers=headers) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            return response.text

    def _parse_results(self, html: str, engine: str) -> list[SearchScrapeResult]:
        """按搜索引擎类型解析 HTML 结果列表。"""
        tree = HTMLParser(html)
        return _parse_google_results(tree) if engine == "google" else _parse_duckduckgo_results(tree)

    def _upsert(
        self,
        results: list[SearchScrapeResult],
        tool_input: LoversLabSearchScrapeInput,
        engine: str,
    ) -> list[Mod]:
        """规范化搜索结果 URL，写入 LoversLab 本地缓存。"""
        records: list[LoversLabSearchRecord] = []
        for result in results:
            url = _normalize_loverslab_url(result.url)
            if not url:
                continue
            raw = {"title": result.title, "url": result.url, "snippet": result.snippet, "engine": engine}
            records.append(
                LoversLabSearchRecord(
                    title=result.title,
                    url=url,
                    summary=result.snippet,
                    category=f"Search Scrape ({engine})",
                    thumbnail_url=None,
                    raw=raw,
                )
            )
        return upsert_loverslab_search_records(
            self.session,
            records,
            game=tool_input.game,
            adult_content=tool_input.adult_content,
        )

def loverslab_scrape_input_from_plan(query: str, plan: dict[str, Any]) -> LoversLabSearchScrapeInput | None:
    """复用 Google 工具的 plan 转换逻辑，保证两个 LoversLab 在线入口约束一致。"""
    google_input = loverslab_google_input_from_plan(query, plan)
    if google_input is None:
        return None
    return LoversLabSearchScrapeInput(**google_input.__dict__)


def _parse_duckduckgo_results(tree: HTMLParser) -> list[SearchScrapeResult]:
    """解析 DuckDuckGo HTML 结果，提取标题、最终 URL 和摘要。"""
    results: list[SearchScrapeResult] = []
    for node in tree.css(".result"):
        link = node.css_first("a.result__a")
        if link is None:
            continue
        url = _normalize_loverslab_url(link.attributes.get("href") or "")
        if not url:
            continue
        snippet_node = node.css_first(".result__snippet")
        results.append(
            SearchScrapeResult(
                title=_text(link),
                url=url,
                snippet=_text(snippet_node) if snippet_node is not None else None,
            )
        )
    return results


def _parse_google_results(tree: HTMLParser) -> list[SearchScrapeResult]:
    """解析 Google HTML 结果；只保留能还原到 LoversLab 的链接。"""
    results: list[SearchScrapeResult] = []
    for link in tree.css("a[href]"):
        url = _normalize_loverslab_url(link.attributes.get("href") or "")
        if not url:
            continue
        title_node = link.css_first("h3")
        title = _text(title_node) if title_node is not None else _text(link)
        if not title or title.lower() in LOVERSLAB_HOSTS:
            continue
        results.append(SearchScrapeResult(title=title, url=url, snippet=None))
    return results


def _normalize_loverslab_url(value: str) -> str | None:
    """还原搜索引擎跳转 URL，移除 UTM 参数，并校验 LoversLab 域名。"""
    value = value.strip()
    if not value:
        return None
    parsed = urlparse(value)
    if parsed.path == "/url":
        qs = parse_qs(parsed.query)
        value = str(qs.get("q", [""])[0])
    if (not parsed.netloc or parsed.netloc.endswith("duckduckgo.com")) and parsed.path.startswith("/l/"):
        qs = parse_qs(parsed.query)
        value = str(qs.get("uddg", [""])[0])
    value = unquote(value).strip()
    value = re.sub(r"([?&])utm_[^&]+", "", value)
    value = value.rstrip("&?")
    return value if is_loverslab_url(value) else None


def _text(node: Any) -> str:
    """压缩 DOM 节点文本中的多余空白。"""
    return re.sub(r"\s+", " ", node.text(separator=" ", strip=True)).strip()
