import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlmodel import Session, select

from app.adapters.nexusmods import MOD_FIELDS, NexusModsAdapter, RateLimitError
from app.models.mod import Mod
from app.models.mod_item import ModItem
from app.services.agent.filter_value_utils import optional_min_metric, optional_time_window
from app.services.agent.planning.slot_normalization import normalize_limit
from app.services.agent.search_types import SearchResult
from app.services.agent.semantic_search import (
    base_keywords,
    semantic_query,
    strip_scope,
    text_score,
)
from app.services.settings_service import SettingsService
from app.services.source_identity import canonical_external_id, find_existing_mod_by_identity
from app.services.update_tracking_service import record_favorite_metadata_update
from app.utils.boolean import parse_bool
from app.utils.numeric import safe_nonnegative_int

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
    """面向 Nexus Mods GraphQL 的受控 MOD 搜索工具。"""

    name = "nexusmods_search"

    def __init__(self, session: Session):
        """保存数据库会话和设置服务，运行状态用于上层 evidence 记录降级原因。"""
        self.session = session
        self.settings = SettingsService(session)
        self.last_status = "not_started"
        self.last_reason: str | None = None

    async def run(self, tool_input: NexusModsSearchInput) -> list[SearchResult]:
        """调用 Nexus GraphQL，持久化新鲜结果，再按本轮查询重新打分排序。"""
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
        """没有显式游戏时使用全局默认 game_domain，避免向 Nexus 发过宽查询。"""
        if tool_input.game_domain or tool_input.game_name or tool_input.game_id:
            return tool_input
        return NexusModsSearchInput(
            **{
                **tool_input.__dict__,
                "game_domain": self.settings.get("game_domain") or None,
            }
        )

    def _build_filter(self, tool_input: NexusModsSearchInput) -> dict[str, Any] | None:
        """把规范化查询计划翻译成 Nexus GraphQL filter。"""
        clauses: list[dict[str, Any]] = []
        if tool_input.game_domain:
            clauses.append(_clause("gameDomainName", "EQUALS", tool_input.game_domain))
        if tool_input.game_name:
            clauses.append(_clause("gameName", "EQUALS", tool_input.game_name))
        if tool_input.game_id:
            clauses.append(_clause("gameId", "EQUALS", tool_input.game_id))

        # Nexus 的分类字段较硬，先从语义查询中提取少量分类提示，再补关键词模糊匹配。
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
            clauses.append({"downloads": [{"op": "GTE", "value": safe_nonnegative_int(tool_input.min_downloads)}]})
        if tool_input.min_endorsements is not None:
            clauses.append({"endorsements": [{"op": "GTE", "value": safe_nonnegative_int(tool_input.min_endorsements)}]})
        if tool_input.min_views is not None:
            clauses.append({"views": [{"op": "GTE", "value": safe_nonnegative_int(tool_input.min_views)}]})
        if tool_input.min_likes is not None:
            clauses.append({"likes": [{"op": "GTE", "value": safe_nonnegative_int(tool_input.min_likes)}]})

        window_days = tool_input.updated_since_days
        if window_days is None:
            # 普通搜索限定一年窗口，近期意图默认 30 天，避免在线召回过旧结果。
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
        """执行 GraphQL 查询，并复用 Nexus 适配器把节点规范化成 ModItem。"""
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
        """将在线结果写回本地缓存，保证后续排序和详情页使用统一 Mod 模型。"""
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
                # 已收藏的 Mod 更新版本/更新时间时，要同步记录通知所需的元数据差异。
                record_favorite_metadata_update(
                    self.session,
                    existing,
                    new_version=str(fields.get("version") or existing.version) if fields.get("version") else existing.version,
                    new_updated_at=str(fields.get("updated_at_remote") or existing.updated_at_remote)
                    if fields.get("updated_at_remote")
                    else existing.updated_at_remote,
                    detected_at=now,
                )
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
        """过滤忽略项和成人内容约束，再按用户要求的排序方式返回候选。"""
        scored: list[tuple[int, Mod]] = []
        has_keywords = bool(_keywords(tool_input.query))
        for mod in mods:
            if mod.id is None or mod.ignored:
                continue
            if isinstance(tool_input.adult_content, bool) and parse_bool(mod.adult_content) != tool_input.adult_content:
                continue
            score = _score(tool_input.query, mod)
            if has_keywords and score <= 0:
                continue
            scored.append((max(score, 1), mod))

        if tool_input.sort_field == "downloads":
            scored.sort(key=lambda item: (safe_nonnegative_int(item[1].downloads), item[0]), reverse=tool_input.sort_order != "asc")
        elif tool_input.sort_field == "endorsements":
            scored.sort(key=lambda item: (safe_nonnegative_int(item[1].endorsements), item[0]), reverse=tool_input.sort_order != "asc")
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
    """从通用 query_plan 构造 Nexus 工具输入；来源不包含 Nexus 时直接跳过。"""
    sources = [str(value).strip().lower() for value in (plan.get("sources") or []) if str(value).strip()]
    if sources and "nexusmods" not in sources:
        return None

    game_domains = [str(value).strip() for value in (plan.get("game_domains") or []) if str(value).strip()]
    games = [str(value).strip() for value in (plan.get("games") or []) if str(value).strip()]
    game_domain = game_domains[0] if game_domains else _domain_for_game(session, games[0]) if games else None
    return NexusModsSearchInput(
        query=strip_scope(query),
        game_domain=game_domain,
        game_name=None if game_domain else games[0] if games else None,
        categories=_category_hints(query, [str(value) for value in (plan.get("categories") or [])]),
        tags=[str(value).strip() for value in (plan.get("tags") or []) if str(value).strip()] or None,
        adult_content=plan.get("adult_content") if isinstance(plan.get("adult_content"), bool) else None,
        author=str(plan.get("author") or "").strip() or None,
        min_downloads=optional_min_metric(plan.get("min_downloads")),
        min_endorsements=optional_min_metric(plan.get("min_endorsements")),
        min_views=optional_min_metric(plan.get("min_views")),
        min_likes=optional_min_metric(plan.get("min_likes")),
        updated_since_days=optional_time_window(plan.get("updated_since_days")),
        sort_field=str(plan.get("sort_field") or "updated_at_remote"),
        sort_order="asc" if str(plan.get("sort_order") or "").lower() == "asc" else "desc",
        limit=normalize_limit(plan, default=8, maximum=20),
    )


def _domain_for_game(session: Session, game: str) -> str | None:
    """用本地历史记录把游戏名映射回 Nexus game_domain。"""
    return session.exec(
        select(Mod.game_domain)
        .where(Mod.source == "nexusmods", Mod.game == game, Mod.game_domain.is_not(None), Mod.game_domain != "")
        .limit(1)
    ).first()


def _clause(field: str, op: str, value: str) -> dict[str, Any]:
    """生成 Nexus GraphQL 单字段过滤子句。"""
    return {field: [{"op": op, "value": value}]}


def _keywords(query: str) -> list[str]:
    """复用语义层的基础关键词提取，保持本地和在线搜索一致。"""
    return base_keywords(query)


def _semantic_terms(query: str, categories: list[str] | None) -> list[str]:
    """返回适合 Nexus name/description MATCHES 的语义扩展词。"""
    return semantic_query(query, categories).expanded_terms


def _keyword_filter_clauses(query: str, categories: list[str] | None) -> list[dict[str, Any]]:
    """为关键词构造 OR 匹配；纯中文词跳过 Nexus 文本查询以减少噪声。"""
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
    """把内部语义分类收敛到 Nexus 常见分类名。"""
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


def _is_recent(tool_input: NexusModsSearchInput) -> bool:
    """判断本轮查询是否属于近期/更新优先意图。"""
    return tool_input.sort_field in {"updated_at_remote", "created_at_remote"} or any(
        marker in tool_input.query.lower() for marker in ["最近", "最新", "更新", "recent", "latest", "new"]
    )


def _sort_value(sort_field: str, sort_order: str) -> dict[str, Any]:
    """把内部排序字段映射到 Nexus GraphQL sort 字段。"""
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
    """把适配器产物转换为本地 Mod 入库字段。"""
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
    """用标题、游戏、作者、分类和摘要计算本轮查询相关性。"""
    return text_score(
        query,
        [mod.title, mod.game, mod.author, mod.category, mod.original_summary],
        [mod.category] if mod.category else None,
    )
