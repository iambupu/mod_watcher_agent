import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlmodel import Session, select

from app.adapters.nexusmods import MOD_FIELDS, NexusModsAdapter, RateLimitError
from app.models.mod import Mod
from app.models.mod_item import ModItem
from app.services.agent.search_types import SearchResult
from app.services.agent.semantic_search import (
    base_keywords,
    semantic_query,
    text_score,
    unique_terms,
)
from app.services.settings_service import SettingsService
from app.services.source_identity import canonical_external_id, find_existing_mod_by_identity

MAX_AGENT_NEXUS_RESULTS = 100
DEFAULT_UPDATED_WINDOW_DAYS = 30
DEFAULT_SEARCH_WINDOW_DAYS = 365


@dataclass
class NexusModsSearchInput:
    query: str = ""
    game_domain: str | None = None
    game_name: str | None = None
    game_id: str | None = None
    categories: list[str] | None = None
    tags: list[str] | None = None
    adult_content: bool | None = None
    author: str | None = None
    min_downloads: int | None = None
    min_endorsements: int | None = None
    min_views: int | None = None
    min_likes: int | None = None
    updated_since_days: int | None = None
    sort_field: str = "updated_at_remote"
    sort_order: str = "desc"
    limit: int = 8


class NexusModsSearchTool:
    """Flexible Agent tool for Nexus Mods GraphQL mod search."""

    name = "nexusmods_search"

    def __init__(self, session: Session):
        """初始化实例并保存运行所需的依赖。"""
        self.session = session
        self.settings = SettingsService(session)
        self.last_status = "not_started"
        self.last_reason: str | None = None

    async def run(self, tool_input: NexusModsSearchInput) -> list[SearchResult]:
        """执行任务流程并返回结果。"""
        self.last_status = "succeeded"
        self.last_reason = None
        api_key = (self.settings.get("nexus_api_key") or "").strip()
        if not api_key:
            self.last_status = "skipped"
            self.last_reason = "missing_credentials"
            return []

        search_input = self._with_default_game(tool_input)
        graphql_filter = self._build_filter(search_input)
        if not graphql_filter:
            self.last_status = "skipped"
            self.last_reason = "empty_filter"
            return []

        adapter = NexusModsAdapter(api_key=api_key)
        try:
            items = await self._fetch(adapter, search_input, graphql_filter)
        except RateLimitError:
            self.last_status = "degraded"
            self.last_reason = "rate_limited"
            return []
        except ValueError:
            self.last_status = "degraded"
            self.last_reason = "invalid_response"
            return []

        mods = self._upsert(items[:MAX_AGENT_NEXUS_RESULTS])
        return self._score_and_sort(mods, search_input)

    def _with_default_game(self, tool_input: NexusModsSearchInput) -> NexusModsSearchInput:
        """内部辅助函数，用于拆分上层流程中的局部规则。"""
        if tool_input.game_domain or tool_input.game_name or tool_input.game_id:
            return tool_input
        return NexusModsSearchInput(
            **{
                **tool_input.__dict__,
                "game_domain": self.settings.get("game_domain") or None,
            }
        )

    def _build_filter(self, tool_input: NexusModsSearchInput) -> dict[str, Any] | None:
        """构建内部流程需要的数据结构。"""
        clauses: list[dict[str, Any]] = []
        if tool_input.game_domain:
            clauses.append(_clause("gameDomainName", "EQUALS", tool_input.game_domain))
        if tool_input.game_name:
            clauses.append(_clause("gameName", "EQUALS", tool_input.game_name))
        if tool_input.game_id:
            clauses.append(_clause("gameId", "EQUALS", tool_input.game_id))

        categories = _category_hints(tool_input.query, tool_input.categories or [])
        clauses.extend(_keyword_filter_clauses(tool_input.query, categories))

        for category in categories:
            if category:
                clauses.append(_clause("categoryName", "EQUALS", category))
        for tag in tool_input.tags or []:
            if tag:
                clauses.append(_clause("tag", "EQUALS", tag))
        if isinstance(tool_input.adult_content, bool):
            clauses.append({"adultContent": [{"op": "EQUALS", "value": tool_input.adult_content}]})
        if tool_input.author:
            clauses.append(_clause("author", "MATCHES", tool_input.author))
        if tool_input.min_downloads is not None:
            clauses.append({"downloads": [{"op": "GTE", "value": int(tool_input.min_downloads)}]})
        if tool_input.min_endorsements is not None:
            clauses.append({"endorsements": [{"op": "GTE", "value": int(tool_input.min_endorsements)}]})
        if tool_input.min_views is not None:
            clauses.append({"views": [{"op": "GTE", "value": int(tool_input.min_views)}]})
        if tool_input.min_likes is not None:
            clauses.append({"likes": [{"op": "GTE", "value": int(tool_input.min_likes)}]})

        window_days = tool_input.updated_since_days
        if window_days is None:
            window_days = DEFAULT_UPDATED_WINDOW_DAYS if _is_recent(tool_input) else DEFAULT_SEARCH_WINDOW_DAYS
        if window_days > 0:
            field = "createdAt" if tool_input.sort_field == "created_at_remote" else "updatedAt"
            cutoff = datetime.now(UTC) - timedelta(days=min(window_days, 365))
            clauses.append({field: [{"op": "GTE", "value": str(int(cutoff.timestamp()))}]})

        if not clauses:
            return None
        if len(clauses) == 1:
            return {"op": "AND", **clauses[0]}
        return {"op": "AND", "filter": clauses}

    async def _fetch(
        self,
        adapter: NexusModsAdapter,
        tool_input: NexusModsSearchInput,
        graphql_filter: dict[str, Any],
    ) -> list[ModItem]:
        """请求外部数据并返回标准化结果。"""
        query = f"""
        query($filter: ModsFilter, $sort: [ModsSort!], $offset: Int, $count: Int) {{
            mods(filter: $filter, sort: $sort, offset: $offset, count: $count) {{
                nodes {{
                    {MOD_FIELDS}
                }}
                nodesCount
                totalCount
            }}
        }}
        """
        count = max(1, min(MAX_AGENT_NEXUS_RESULTS, max(tool_input.limit * 4, tool_input.limit)))
        variables = {
            "filter": graphql_filter,
            "sort": [_sort_value(tool_input.sort_field, tool_input.sort_order)],
            "offset": 0,
            "count": count,
        }
        data = await adapter._graphql_query(query, variables)
        nodes = data.get("data", {}).get("mods", {}).get("nodes") or []
        return [adapter.normalize(node) for node in nodes]

    def _upsert(self, items: list[ModItem]) -> list[Mod]:
        """内部辅助函数，用于拆分上层流程中的局部规则。"""
        now = datetime.now(UTC).isoformat()
        mods: list[Mod] = []
        for item in items:
            fields = _mod_item_fields(item)
            if not fields["source"] or not fields["external_id"] or not fields["title"]:
                continue
            fields["external_id"] = canonical_external_id(
                fields["source"],
                fields["external_id"],
                fields.get("url") or "",
            )
            existing = find_existing_mod_by_identity(
                self.session,
                fields["source"],
                fields["external_id"],
                fields.get("url") or "",
            )
            if existing:
                for key, value in fields.items():
                    if key not in {"source", "external_id"}:
                        setattr(existing, key, value)
                existing.last_seen_at = now
                self.session.add(existing)
                mods.append(existing)
                continue

            mod = Mod(**fields, first_seen_at=now, last_seen_at=now)
            self.session.add(mod)
            self.session.flush()
            mods.append(mod)

        self.session.commit()
        for mod in mods:
            self.session.refresh(mod)
        return mods

    def _score_and_sort(self, mods: list[Mod], tool_input: NexusModsSearchInput) -> list[SearchResult]:
        """内部辅助函数，用于拆分上层流程中的局部规则。"""
        scored: list[tuple[int, Mod]] = []
        has_keywords = bool(_keywords(tool_input.query))
        for mod in mods:
            if mod.id is None or mod.ignored:
                continue
            if isinstance(tool_input.adult_content, bool) and bool(mod.adult_content) != tool_input.adult_content:
                continue
            score = _score(tool_input.query, mod)
            if has_keywords and score <= 0:
                continue
            scored.append((max(score, 1), mod))

        if tool_input.sort_field == "downloads":
            scored.sort(key=lambda item: (item[1].downloads or 0, item[0]), reverse=tool_input.sort_order != "asc")
        elif tool_input.sort_field == "endorsements":
            scored.sort(key=lambda item: (item[1].endorsements or 0, item[0]), reverse=tool_input.sort_order != "asc")
        elif tool_input.sort_field == "relevance":
            scored.sort(key=lambda item: (item[0], item[1].first_seen_at), reverse=True)
        else:
            scored.sort(
                key=lambda item: ((item[1].updated_at_remote or ""), item[0]),
                reverse=tool_input.sort_order != "asc",
            )
        return [
            SearchResult(score=score, mod=mod, tool_name=self.name)
            for score, mod in scored[: max(1, min(20, tool_input.limit))]
        ]


def nexus_tool_input_from_plan(session: Session, query: str, plan: dict[str, Any]) -> NexusModsSearchInput | None:
    """处理当前模块的业务逻辑并返回结果。"""
    sources = [str(value).strip().lower() for value in (plan.get("sources") or []) if str(value).strip()]
    if sources and "nexusmods" not in sources:
        return None

    game_domains = [str(value).strip() for value in (plan.get("game_domains") or []) if str(value).strip()]
    games = [str(value).strip() for value in (plan.get("games") or []) if str(value).strip()]
    game_domain = game_domains[0] if game_domains else _domain_for_game(session, games[0]) if games else None
    return NexusModsSearchInput(
        query=query.split("[scope]", 1)[0].strip(),
        game_domain=game_domain,
        game_name=None if game_domain else games[0] if games else None,
        categories=_category_hints(query, [str(value) for value in (plan.get("categories") or [])]),
        tags=[str(value).strip() for value in (plan.get("tags") or []) if str(value).strip()] or None,
        adult_content=plan.get("adult_content") if isinstance(plan.get("adult_content"), bool) else None,
        author=str(plan.get("author") or "").strip() or None,
        min_downloads=_optional_min_metric(plan.get("min_downloads")),
        min_endorsements=_optional_min_metric(plan.get("min_endorsements")),
        min_views=_optional_min_metric(plan.get("min_views")),
        min_likes=_optional_min_metric(plan.get("min_likes")),
        updated_since_days=_optional_time_window(plan.get("updated_since_days")),
        sort_field=str(plan.get("sort_field") or "updated_at_remote"),
        sort_order="asc" if str(plan.get("sort_order") or "").lower() == "asc" else "desc",
        limit=int(plan.get("limit") or 8),
    )


def _domain_for_game(session: Session, game: str) -> str | None:
    """内部辅助函数，用于拆分上层流程中的局部规则。"""
    return session.exec(
        select(Mod.game_domain)
        .where(Mod.source == "nexusmods", Mod.game == game, Mod.game_domain.is_not(None), Mod.game_domain != "")
        .limit(1)
    ).first()


def _optional_min_metric(value: Any) -> int | None:
    try:
        parsed = int(str(value or "").replace(",", "").strip())
    except (TypeError, ValueError):
        return None
    return max(0, parsed)


def _optional_time_window(value: Any) -> int | None:
    try:
        parsed = int(str(value or "").replace(",", "").strip())
    except (TypeError, ValueError):
        return None
    return max(1, min(365, parsed))


def _clause(field: str, op: str, value: str) -> dict[str, Any]:
    """内部辅助函数，用于拆分上层流程中的局部规则。"""
    return {field: [{"op": op, "value": value}]}


def _keywords(query: str) -> list[str]:
    """内部辅助函数，用于拆分上层流程中的局部规则。"""
    return base_keywords(query)


def _search_keywords(query: str, categories: list[str] | None) -> list[str]:
    """内部辅助函数，用于拆分上层流程中的局部规则。"""
    return semantic_query(query, categories).all_terms


def _semantic_terms(query: str, categories: list[str] | None) -> list[str]:
    """内部辅助函数，用于拆分上层流程中的局部规则。"""
    return semantic_query(query, categories).expanded_terms


def _keyword_filter_clauses(query: str, categories: list[str] | None) -> list[dict[str, Any]]:
    """内部辅助函数，用于拆分上层流程中的局部规则。"""
    semantic_terms = _semantic_terms(query, categories)
    if semantic_terms:
        return [
            {
                "op": "OR",
                "filter": [
                    clause
                    for keyword in semantic_terms[:8]
                    for clause in (
                        _clause("nameStemmed", "MATCHES", keyword),
                        _clause("description", "MATCHES", keyword),
                    )
                ],
            }
        ]

    clauses: list[dict[str, Any]] = []
    for keyword in _keywords(query)[:4]:
        if re.search(r"[\u4e00-\u9fff]", keyword):
            continue
        clauses.append(
            {
                "op": "OR",
                "filter": [
                    _clause("nameStemmed", "MATCHES", keyword),
                    _clause("description", "MATCHES", keyword),
                ],
            }
        )
    return clauses


def _category_hints(query: str, categories: list[str]) -> list[str]:
    """内部辅助函数，用于拆分上层流程中的局部规则。"""
    if categories:
        return categories
    semantic = semantic_query(query)
    hints: list[str] = []
    nexus_categories = ["Clothing and Accessories", "Armour", "Outfits", "Gameplay", "Visuals and Graphics"]
    for category in nexus_categories:
        key = category.lower()
        if any(alias in key for alias in semantic.category_aliases):
            hints.append(category)
    return hints


def _merge_unique_tokens(values: list[str]) -> list[str]:
    """合并多个来源的数据并保持稳定顺序。"""
    return unique_terms(values)


def _is_recent(tool_input: NexusModsSearchInput) -> bool:
    """判断内部条件是否成立。"""
    return tool_input.sort_field in {"updated_at_remote", "created_at_remote"} or any(
        marker in tool_input.query.lower() for marker in ["最近", "最新", "更新", "recent", "latest", "new"]
    )


def _sort_value(sort_field: str, sort_order: str) -> dict[str, Any]:
    """内部辅助函数，用于拆分上层流程中的局部规则。"""
    field_map = {
        "updated_at_remote": "updatedAt",
        "created_at_remote": "createdAt",
        "published_at_remote": "updatedAt",
        "downloads": "downloads",
        "endorsements": "endorsements",
        "relevance": "updatedAt",
    }
    field = field_map.get(sort_field, "updatedAt")
    return {field: {"direction": "ASC" if sort_order == "asc" else "DESC"}}


def _mod_item_fields(item: ModItem) -> dict[str, Any]:
    """内部辅助函数，用于拆分上层流程中的局部规则。"""
    raw = item.raw or {}
    game = raw.get("game") if isinstance(raw.get("game"), dict) else {}
    category = item.categories[0] if item.categories else None
    return {
        "source": item.source,
        "external_id": item.source_id,
        "game": item.game,
        "game_domain": game.get("domainName"),
        "title": item.name,
        "url": item.url or "",
        "author": item.author,
        "category": category,
        "tags_json": json.dumps(item.tags or [], ensure_ascii=False),
        "original_summary": item.summary,
        "version": raw.get("version"),
        "created_at_remote": raw.get("createdAt"),
        "updated_at_remote": item.updated_at.isoformat() if item.updated_at is not None else None,
        "published_at_remote": raw.get("publishedAt"),
        "downloads": item.downloads,
        "unique_downloads": raw.get("uniqueDownloads"),
        "endorsements": item.endorsements,
        "views": raw.get("views"),
        "likes": item.likes,
        "adult_content": item.is_adult,
        "thumbnail_url": item.thumbnail_url,
        "raw_json": json.dumps(raw, ensure_ascii=False) if raw else None,
    }


def _score(query: str, mod: Mod) -> int:
    """内部辅助函数，用于拆分上层流程中的局部规则。"""
    return text_score(
        query,
        [mod.title, mod.game, mod.author, mod.category, mod.original_summary],
        [mod.category] if mod.category else None,
    )
