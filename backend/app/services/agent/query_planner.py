import re
from dataclasses import dataclass, field
from typing import Any

from sqlmodel import Session, select

from app.models.mod import Mod
from app.services.agent.identity_inference import infer_identity_constraints, source_from_url
from app.services.agent.list_utils import merge_unique_text as _merge_unique
from app.services.agent.planning.executor_query_plan import build_executor_query_plan
from app.services.agent.planning.keyword_cleanup import (
    drop_absolute_date_keywords as _drop_absolute_date_keywords,
)
from app.services.agent.planning.keyword_cleanup import (
    drop_adult_keywords as _drop_adult_keywords,
)
from app.services.agent.planning.keyword_cleanup import (
    drop_author_keywords as _drop_author_keywords,
)
from app.services.agent.planning.keyword_cleanup import (
    drop_compatibility_keywords as _drop_compatibility_keywords,
)
from app.services.agent.planning.keyword_cleanup import (
    drop_excluded_categories as _drop_excluded_categories,
)
from app.services.agent.planning.keyword_cleanup import (
    drop_excluded_keywords as _drop_excluded_keywords,
)
from app.services.agent.planning.keyword_cleanup import (
    drop_identity_keywords as _drop_identity_keywords,
)
from app.services.agent.planning.keyword_cleanup import (
    drop_metric_keywords as _drop_metric_keywords,
)
from app.services.agent.planning.keyword_cleanup import (
    drop_requirement_keywords as _drop_requirement_keywords,
)
from app.services.agent.planning.keyword_cleanup import (
    drop_sort_keywords as _drop_sort_keywords,
)
from app.services.agent.planning.keyword_cleanup import (
    drop_source_keywords as _drop_source_keywords,
)
from app.services.agent.planning.keyword_cleanup import (
    drop_summary_language_keywords as _drop_summary_language_keywords,
)
from app.services.agent.planning.keyword_cleanup import (
    drop_tag_keywords as _drop_tag_keywords,
)
from app.services.agent.planning.keyword_cleanup import (
    drop_time_window_keywords as _drop_time_window_keywords,
)
from app.services.agent.planning.keyword_cleanup import (
    drop_version_keywords as _drop_version_keywords,
)
from app.services.agent.planning.keyword_cleanup import (
    query_without_excluded_terms as _query_without_excluded_terms,
)
from app.services.agent.planning.query_intent import (
    _is_gameplay_support_search,
    detect_adult_constraint,
    detect_query_intent,
    infer_sort_preference,
    infer_source_constraints,
    is_open_discovery_query,
    is_recent_query,
)
from app.services.agent.planning.query_plan_contract import DATE_RANGE_FIELDS, METRIC_FIELDS
from app.services.agent.planning.query_plan_hygiene import (
    sanitize_category_slot_options,
    sanitize_query_plan_fields,
)
from app.services.agent.planning.slot_normalization import (
    normalize_absolute_date as _normalize_absolute_date,
)
from app.services.agent.planning.slot_normalization import (
    normalize_allowed_list as _normalize_allowed_list,
)
from app.services.agent.planning.slot_normalization import (
    normalize_exclude_titles as _normalize_exclude_titles,
)
from app.services.agent.planning.slot_normalization import (
    normalize_external_id as _normalize_external_id,
)
from app.services.agent.planning.slot_normalization import (
    normalize_limit,
)
from app.services.agent.planning.slot_normalization import (
    normalize_min_metric as _normalize_min_metric,
)
from app.services.agent.planning.slot_normalization import (
    normalize_optional_bool as _normalize_optional_bool,
)
from app.services.agent.planning.slot_normalization import (
    normalize_time_window as _normalize_time_window,
)
from app.services.agent.planning.slot_value_normalization import (
    drop_excluded_summary_languages as _drop_excluded_summary_languages,
)
from app.services.agent.planning.slot_value_normalization import (
    drop_gameplay_support_compatibility_terms as _drop_gameplay_support_compatibility_terms,
)
from app.services.agent.planning.slot_value_normalization import (
    has_explicit_tag_constraint as _has_explicit_tag_constraint,
)
from app.services.agent.planning.slot_value_normalization import (
    normalize_author as _normalize_author,
)
from app.services.agent.planning.slot_value_normalization import (
    normalize_compatibility_terms as _normalize_compatibility_terms,
)
from app.services.agent.planning.slot_value_normalization import (
    normalize_exact_title as _normalize_exact_title,
)
from app.services.agent.planning.slot_value_normalization import (
    normalize_excluded_keywords as _normalize_excluded_keywords,
)
from app.services.agent.planning.slot_value_normalization import (
    normalize_requirement_terms as _normalize_requirement_terms,
)
from app.services.agent.planning.slot_value_normalization import (
    normalize_source_url as _normalize_source_url,
)
from app.services.agent.planning.slot_value_normalization import (
    normalize_summary_languages as _normalize_summary_languages,
)
from app.services.agent.planning.slot_value_normalization import (
    normalize_tags as _normalize_tags,
)
from app.services.agent.planning.slot_value_normalization import (
    normalize_version as _normalize_version,
)
from app.services.agent.semantic_search import (
    category_match_score,
    infer_categories,
    semantic_query,
)
from app.services.agent.slot_attribute_inference import (
    infer_summary_language_constraints,
    infer_tag_constraints,
    infer_thumbnail_constraint,
)
from app.services.agent.slot_constraint_inference import (
    infer_absolute_date_constraints,
    infer_numeric_constraints,
    infer_time_window,
)
from app.services.agent.slot_text_inference import (
    infer_compatibility_terms,
    infer_excluded_keywords,
    infer_requirement_terms,
    infer_title_constraint,
    infer_version_constraint,
)
from app.services.game_alias_service import (
    add_game_alias_mappings,
    alias_key,
    build_resolved_aliases,
)
from app.services.source_identity import canonical_external_id

SLOT_OPTION_LIMIT = 200
DEFAULT_AGENT_LIMIT = 8
MAX_AGENT_LIMIT = 20
RELEVANCE_PREFETCH_LIMIT = 50

__all__ = [
    "DEFAULT_AGENT_LIMIT",
    "MAX_AGENT_LIMIT",
    "RELEVANCE_PREFETCH_LIMIT",
    "SORT_COLUMNS",
    "build_executor_query_plan",
    "detect_adult_constraint",
    "detect_query_intent",
    "infer_sort_preference",
    "infer_source_constraints",
    "is_open_discovery_query",
    "is_recent_query",
    "load_slot_options",
    "normalize_query_plan",
]

SORT_COLUMNS = {
    "updated_at_remote": Mod.updated_at_remote,
    "first_seen_at": Mod.first_seen_at,
    "created_at_remote": Mod.created_at_remote,
    "published_at_remote": Mod.published_at_remote,
    "downloads": Mod.downloads,
    "unique_downloads": Mod.unique_downloads,
    "endorsements": Mod.endorsements,
    "views": Mod.views,
    "likes": Mod.likes,
}

def _distinct_non_empty_values(session: Session, column: Any, limit: int = SLOT_OPTION_LIMIT) -> list[str]:
    """从数据库列读取非空去重槽位，作为查询计划的允许值集合。"""
    rows = session.exec(
        select(column)
        .where(column.is_not(None), column != "")
        .distinct()
        .order_by(column)
        .limit(limit)
    ).all()
    return [str(value).strip() for value in rows if str(value or "").strip()]


def load_slot_options(session: Session) -> dict[str, list[str]]:
    """加载当前库内可用的游戏、分类和来源，约束 LLM 计划不要生成离散值。"""
    return {
        "games": _distinct_non_empty_values(session, Mod.game),
        "game_domains": _distinct_non_empty_values(session, Mod.game_domain),
        "categories": _distinct_non_empty_values(session, Mod.category),
        "sources": _merge_unique(_distinct_non_empty_values(session, Mod.source), ["nexusmods", "loverslab"]),
    }


def _infer_allowed_values_from_text(text: str, aliases: dict[str, list[str]]) -> list[str]:
    """用规范化别名 key 从用户文本里推断已知槽位值。"""
    key = alias_key(text)
    if not key:
        return []
    inferred: list[str] = []
    for alias_key_value, values in aliases.items():
        if alias_key_value and alias_key_value in key:
            inferred = _merge_unique(inferred, values)
    return inferred


def _normalize_sort_field(raw: Any, intent: str) -> str:
    """把用户或 LLM 给出的排序别名收敛到数据库字段或相关性排序。"""
    value = str(raw or "").strip().lower()
    aliases = {
        "updated": "updated_at_remote",
        "latest": "updated_at_remote",
        "recent": "updated_at_remote",
        "new": "first_seen_at",
        "first_seen": "first_seen_at",
        "created": "created_at_remote",
        "published": "published_at_remote",
        "download": "downloads",
        "downloads": "downloads",
        "unique_download": "unique_downloads",
        "endorsement": "endorsements",
        "endorsements": "endorsements",
        "like": "likes",
        "likes": "likes",
        "view": "views",
        "views": "views",
        "relevance": "relevance",
    }
    mapped = aliases.get(value, value)
    if mapped in SORT_COLUMNS or mapped == "relevance":
        return mapped
    return "updated_at_remote" if intent == "recent" else "relevance"


def _extract_scope_constraints(query: str) -> dict[str, str]:
    """从查询末尾的 [scope] 块读取前端强制约束。"""

    marker = "[scope]"
    if marker not in query:
        return {}
    _, scope_text = query.split(marker, 1)
    constraints: dict[str, str] = {}
    for line in scope_text.splitlines():
        key, sep, value = line.partition("=")
        if sep != "=":
            continue
        key = key.strip().lower()
        value = value.strip()
        if key in {"source", "game", "sort_field"} and value:
            constraints[key] = value
    return constraints


def _apply_scope_overrides(
    raw: dict[str, Any],
    query: str,
    slot_options: dict[str, list[str]],
) -> dict[str, Any]:
    """让显式 scope 约束覆盖 LLM 计划，保证页面来源和游戏过滤不漂移。"""

    scope = _extract_scope_constraints(query)
    if not scope:
        return raw
    scoped = dict(raw)
    if scope.get("source"):
        scoped["sources"] = [scope["source"]]
    if scope.get("sort_field"):
        scoped["sort_field"] = scope["sort_field"]
    scoped_game = scope.get("game")
    if scoped_game:
        domain_keys = {alias_key(value): value for value in slot_options["game_domains"]}
        game_key = alias_key(scoped_game)
        if game_key in domain_keys:
            scoped["game_domains"] = [domain_keys[game_key]]
        else:
            scoped["games"] = [scoped_game]
    return scoped


def _normalize_intent(raw: dict[str, Any], query: str = "") -> str:
    """把未知 intent 收敛为 search，避免下游分支处理未定义值。"""

    intent = str(raw.get("intent") or "search").strip().lower()
    if intent not in {
        "recent",
        "search",
        "author",
        "game",
        "comparison",
        "alternative",
        "install_risk",
        "preference_summary",
        "unknown",
    }:
        return "search"
    if intent == "install_risk" and _is_gameplay_support_search(query):
        return "search"
    return intent


def _normalize_keywords_and_games(
    raw: dict[str, Any],
    query: str,
    slot_options: dict[str, list[str]],
) -> tuple[list[str], list[str]]:
    """解析游戏别名，并从关键词中移除已经被识别为游戏的词。"""

    game_aliases_raw = raw.get("game_aliases")
    if game_aliases_raw:
        add_game_alias_mappings(game_aliases_raw, slot_options["games"])
    # 游戏名既可能来自用户原文，也可能来自 LLM 的 keyword 列表；先统一成 alias key
    # 再回写到 games，避免把 "Skyrim SE" 同时当成游戏和普通关键词。
    game_aliases = {alias_key(game): [game] for game in slot_options["games"] if alias_key(game)}
    game_aliases.update(_builtin_game_aliases(slot_options["games"]))
    game_aliases.update(build_resolved_aliases(slot_options["games"]))
    keywords = [str(item).strip().lower() for item in raw.get("keywords") or [] if str(item).strip()]
    inferred_games = _infer_allowed_values_from_text(query, game_aliases)
    for keyword in keywords:
        inferred_games = _merge_unique(inferred_games, _infer_allowed_values_from_text(keyword, game_aliases))
    inferred_games = _drop_broader_game_matches(inferred_games)
    if inferred_games:
        alias_keys = set(game_aliases)
        keywords = [
            keyword
            for keyword in keywords
            if not _keyword_matches_game_alias(keyword, alias_keys)
        ]
    games = _normalize_allowed_list(raw.get("games") or raw.get("game"), slot_options["games"], game_aliases)
    return keywords, _drop_broader_game_matches(_merge_unique(games, inferred_games))


def _builtin_game_aliases(allowed_games: list[str]) -> dict[str, list[str]]:
    """补齐数据库里常见英文缩写和正式游戏名之间的映射。"""
    allowed_by_key = {alias_key(game): game for game in allowed_games}
    aliases: dict[str, list[str]] = {}

    def add(alias: str, *target_keys: str) -> None:
        targets = [allowed_by_key[key] for key in target_keys if key in allowed_by_key]
        if targets:
            aliases[alias_key(alias)] = targets

    add("sse", "skyrimspecialedition")
    add("skyrim se", "skyrimspecialedition")
    add("skyrimse", "skyrimspecialedition")
    add("skyrim special edition", "skyrimspecialedition")
    add("skyrim vr", "skyrimvr")
    add("skyrimvr", "skyrimvr")
    add("skyrim le", "skyrimlegendaryedition", "skyrim")
    add("skyrimle", "skyrimlegendaryedition", "skyrim")
    add("oldrim", "skyrimlegendaryedition", "skyrim")
    add("skyrim legendary edition", "skyrimlegendaryedition", "skyrim")
    return aliases


def _drop_broader_game_matches(games: list[str]) -> list[str]:
    """同一句命中 Skyrim 与 Skyrim Special Edition 时，只保留更具体的游戏。"""
    keys = {game: alias_key(game) for game in games}
    return [
        game
        for game in games
        if not any(
            other != game and key and len(key) < len(other_key) and key in other_key
            for other, other_key in keys.items()
            for key in [keys[game]]
        )
    ]


def _keyword_matches_game_alias(keyword: str, game_alias_keys: set[str]) -> bool:
    """判断关键词是否已经被游戏槽位吸收，避免后续 FTS 再用它硬匹配。"""
    keyword_key = alias_key(keyword)
    if not keyword_key:
        return False
    return any(key in keyword_key or keyword_key in key for key in game_alias_keys)


def _normalize_adult_content(query: str) -> bool | None:
    """只信任用户原文中的成人内容标记，忽略 LLM 对 adult_content 的猜测。"""

    return detect_adult_constraint(query)


def _normalize_limit(raw: dict[str, Any]) -> int:
    """把 limit 限制在 Agent 查询允许的范围内。"""

    return normalize_limit(raw, default=DEFAULT_AGENT_LIMIT, maximum=MAX_AGENT_LIMIT)


def _normalize_categories(
    raw: dict[str, Any],
    query: str,
    slot_options: dict[str, list[str]],
) -> tuple[list[str], list[str], str, list[str]]:
    """合并上游分类和语义分类；未明确要求分类时只产生软提示。"""

    available_categories = sanitize_category_slot_options(slot_options["categories"])
    explicit_categories = _normalize_allowed_list(
        raw.get("categories") or raw.get("category"),
        available_categories,
    )
    if explicit_categories and is_open_discovery_query(query) and not _query_mentions_category_scope(query):
        explicit_categories = []
    explicit_semantic = semantic_query(query)
    if explicit_categories and explicit_semantic.all_terms and not explicit_semantic.category_aliases:
        explicit_categories = []
    if explicit_categories and explicit_semantic.category_aliases:
        semantic_matched_categories = [
            category
            for category in explicit_categories
            if category_match_score(category, explicit_semantic) > 0
        ]
        if semantic_matched_categories:
            explicit_categories = semantic_matched_categories
    inferred_categories = infer_categories(query, available_categories, [], semantic=explicit_semantic)
    hard_category_query = _query_mentions_category_scope(query)
    if explicit_categories or hard_category_query:
        categories = _merge_unique(explicit_categories, inferred_categories)
        category_hints: list[str] = []
    else:
        categories = []
        category_hints = inferred_categories
    category_match_mode = "exact" if explicit_categories else "db_fuzzy"
    semantic = semantic_query(query)
    return categories, category_hints, category_match_mode, semantic.expanded_terms


@dataclass
class _QueryPlanNormalization:
    raw: dict[str, Any]
    query: str
    slot_options: dict[str, list[str]]
    intent: str
    keywords: list[str]
    games: list[str]
    categories: list[str]
    category_hints: list[str]
    category_match_mode: str
    excluded_keywords: list[str]
    sources: list[str] = field(default_factory=list)
    excluded_sources: list[str] = field(default_factory=list)
    author: str | None = None
    metrics: dict[str, int | None] = field(default_factory=dict)
    updated_since_days: int | None = None
    date_ranges: dict[str, str | None] = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)
    has_thumbnail: bool | None = None
    summary_languages: list[str] = field(default_factory=list)
    excluded_summary_languages: list[str] = field(default_factory=list)
    requirement_terms: list[str] = field(default_factory=list)
    compatibility_terms: list[str] = field(default_factory=list)
    exact_title: str | None = None
    version: str | None = None
    game_domains: list[str] = field(default_factory=list)
    source_url: str | None = None
    external_id: str | None = None
    adult_content: bool | None = None
    sort_field: str = "relevance"
    open_discovery: bool = False
    retrieval_mode: str = "filtered"


def normalize_query_plan(
    plan: dict | None,
    query: str,
    slot_options: dict[str, list[str]],
) -> dict[str, Any]:
    """将 executor 兼容查询计划规范化为数据库查询可消费的结构。"""

    state = _start_query_plan_normalization(plan, query, slot_options)
    _normalize_source_constraints(state)
    _normalize_metric_and_date_constraints(state)
    _normalize_content_constraints(state)
    _normalize_identity_and_sort_constraints(state)
    normalized = _build_normalized_query_plan(state)
    return sanitize_query_plan_fields(normalized, query=query)


def _start_query_plan_normalization(
    plan: dict | None,
    query: str,
    slot_options: dict[str, list[str]],
) -> _QueryPlanNormalization:
    raw = plan if isinstance(plan, dict) else {}
    raw = _apply_scope_overrides(raw, query, slot_options)
    if not raw.get("excluded_keywords") and not raw.get("exclude_keywords"):
        inferred_exclusions = infer_excluded_keywords(query)
        if inferred_exclusions:
            raw = {**raw, **inferred_exclusions}
    excluded_keywords = _normalize_excluded_keywords(
        raw.get("excluded_keywords") or raw.get("exclude_keywords")
    )
    keywords, games = _normalize_keywords_and_games(raw, query, slot_options)
    categories, category_hints, category_match_mode, semantic_keywords = _normalize_categories(
        raw,
        _query_without_excluded_terms(query, excluded_keywords),
        slot_options,
    )
    return _QueryPlanNormalization(
        raw=raw,
        query=query,
        slot_options=slot_options,
        intent=_normalize_intent(raw, query),
        keywords=_drop_excluded_keywords(
            _merge_unique(keywords, semantic_keywords), excluded_keywords
        ),
        games=games,
        categories=_drop_excluded_categories(categories, excluded_keywords),
        category_hints=_drop_excluded_categories(category_hints, excluded_keywords),
        category_match_mode=category_match_mode,
        excluded_keywords=excluded_keywords,
    )


def _normalize_source_constraints(state: _QueryPlanNormalization) -> None:
    raw = state.raw
    allowed_sources = state.slot_options["sources"]
    state.excluded_sources = _normalize_allowed_list(
        raw.get("excluded_sources") or raw.get("excluded_source"), allowed_sources
    )
    state.sources = _normalize_allowed_list(
        raw.get("sources") or raw.get("source"), allowed_sources
    )
    if state.excluded_sources and not state.sources:
        excluded = set(state.excluded_sources)
        state.sources = [source for source in allowed_sources if source not in excluded]
    if state.sources or state.excluded_sources:
        state.keywords = _drop_source_keywords(state.keywords)
    state.author = _normalize_author(
        raw.get("author") or raw.get("authors") or raw.get("creator") or raw.get("modder")
    )
    if state.author:
        state.keywords = _drop_author_keywords(state.keywords, state.author)


def _normalize_metric_and_date_constraints(state: _QueryPlanNormalization) -> None:
    raw = state.raw
    state.metrics = {field: _normalize_min_metric(raw.get(field)) for field in METRIC_FIELDS}
    if not any(value is not None for value in state.metrics.values()):
        inferred_metrics = infer_numeric_constraints(state.query)
        state.metrics = {field: inferred_metrics.get(field) for field in METRIC_FIELDS}
    state.keywords = _drop_metric_keywords(state.keywords, state.metrics)
    state.updated_since_days = _normalize_time_window(
        raw.get("updated_since_days") or raw.get("updated_within_days")
    )
    if state.updated_since_days is None:
        state.updated_since_days = infer_time_window(state.query).get("updated_since_days")
    state.keywords = _drop_time_window_keywords(state.keywords, state.updated_since_days)
    inferred_dates = infer_absolute_date_constraints(state.query)
    state.date_ranges = {
        field: _normalize_absolute_date(raw.get(field) or inferred_dates.get(field))
        for field in DATE_RANGE_FIELDS
    }
    state.keywords = _drop_absolute_date_keywords(state.keywords, state.date_ranges)


def _normalize_content_constraints(state: _QueryPlanNormalization) -> None:
    raw = state.raw
    raw_tags = _normalize_tags(raw.get("tags") or raw.get("tag"))
    inferred_tags = _normalize_tags(infer_tag_constraints(state.query).get("tags"))
    state.tags = raw_tags or inferred_tags if _has_explicit_tag_constraint(state.query) else []
    if state.tags:
        state.keywords = _drop_tag_keywords(state.keywords, state.tags)
    elif raw_tags:
        state.keywords = _merge_unique(state.keywords, raw_tags)
    state.has_thumbnail = _normalize_optional_bool(raw.get("has_thumbnail"))
    if state.has_thumbnail is None:
        state.has_thumbnail = infer_thumbnail_constraint(state.query).get("has_thumbnail")
    _normalize_language_constraints(state)
    _normalize_dependency_constraints(state)
    state.exact_title = _normalize_exact_title(raw.get("exact_title") or raw.get("title"))
    if state.exact_title is None:
        state.exact_title = infer_title_constraint(state.query).get("exact_title")
    state.version = _normalize_version(raw.get("version") or raw.get("mod_version"))
    if state.version is None:
        state.version = infer_version_constraint(state.query).get("version")
    state.keywords = _drop_version_keywords(state.keywords, state.version)


def _normalize_language_constraints(state: _QueryPlanNormalization) -> None:
    raw = state.raw
    inferred = infer_summary_language_constraints(state.query)
    state.summary_languages = _normalize_summary_languages(
        raw.get("summary_languages") or raw.get("summary_language")
    ) or _normalize_summary_languages(inferred.get("summary_languages"))
    state.excluded_summary_languages = _normalize_summary_languages(
        raw.get("excluded_summary_languages") or raw.get("excluded_summary_language")
    ) or _normalize_summary_languages(inferred.get("excluded_summary_languages"))
    state.summary_languages = _drop_excluded_summary_languages(
        state.summary_languages, state.excluded_summary_languages
    )
    state.keywords = _drop_summary_language_keywords(
        state.keywords,
        _merge_unique(state.summary_languages, state.excluded_summary_languages),
    )


def _normalize_dependency_constraints(state: _QueryPlanNormalization) -> None:
    raw = state.raw
    state.requirement_terms = _normalize_requirement_terms(
        raw.get("requirement_terms") or raw.get("requirements") or raw.get("dependencies")
    ) or _normalize_requirement_terms(infer_requirement_terms(state.query).get("requirement_terms"))
    state.keywords = _drop_requirement_keywords(state.keywords, state.requirement_terms)
    state.compatibility_terms = _normalize_compatibility_terms(
        raw.get("compatibility_terms") or raw.get("compatible_with") or raw.get("compatibility")
    ) or _normalize_compatibility_terms(
        infer_compatibility_terms(state.query).get("compatibility_terms")
    )
    state.compatibility_terms = _drop_gameplay_support_compatibility_terms(
        state.query, state.compatibility_terms
    )
    state.keywords = _drop_compatibility_keywords(state.keywords, state.compatibility_terms)


def _normalize_identity_and_sort_constraints(state: _QueryPlanNormalization) -> None:
    raw = state.raw
    game_domains = state.slot_options["game_domains"]
    state.game_domains = _merge_unique(
        _normalize_allowed_list(raw.get("game_domains") or raw.get("game_domain"), game_domains),
        _game_domains_from_games(state.games, game_domains),
    )
    identity = infer_identity_constraints(state.query)
    state.source_url = _normalize_source_url(
        raw.get("source_url") or raw.get("url") or identity.get("source_url")
    )
    state.external_id = _normalize_external_id(
        raw.get("external_id") or raw.get("source_id") or identity.get("external_id")
    )
    _apply_identity_source_constraints(state, identity)
    state.external_id = _canonicalize_nexus_external_id(
        state.external_id,
        state.sources,
        state.games,
        state.game_domains,
        state.slot_options,
    )
    state.keywords = _drop_identity_keywords(
        state.keywords, state.external_id, state.source_url
    )
    state.adult_content = _normalize_adult_content(state.query)
    state.keywords = _drop_adult_keywords(state.keywords, state.adult_content)
    state.sort_field = _normalize_sort_field(
        raw.get("sort_field") or raw.get("sort"), state.intent
    )
    state.keywords = _drop_sort_keywords(state.keywords, state.sort_field)
    state.open_discovery = bool(_normalize_optional_bool(raw.get("open_discovery"))) or is_open_discovery_query(
        state.query
    )
    state.retrieval_mode = "fuzzy" if state.open_discovery else "filtered"


def _apply_identity_source_constraints(
    state: _QueryPlanNormalization,
    identity: dict[str, Any],
) -> None:
    if state.source_url:
        inferred_source = source_from_url(state.source_url)
        if inferred_source and not state.sources:
            state.sources = [inferred_source]
        if inferred_source and not state.external_id:
            state.external_id = canonical_external_id(inferred_source, "", state.source_url)
    if identity.get("sources") and not state.sources:
        state.sources = _normalize_allowed_list(
            identity.get("sources"), state.slot_options["sources"]
        )


def _build_normalized_query_plan(state: _QueryPlanNormalization) -> dict[str, Any]:
    raw = state.raw
    normalized: dict[str, Any] = {
        "intent": state.intent,
        "open_discovery": state.open_discovery,
        "retrieval_mode": state.retrieval_mode,
        "keywords": state.keywords[:10],
        "games": state.games,
        "game_domains": state.game_domains,
        "categories": state.categories,
        "category_hints": state.category_hints,
        "category_match_mode": state.category_match_mode,
        "sources": state.sources,
        "adult_content": state.adult_content,
        "sort_field": state.sort_field,
        "sort_order": "asc" if str(raw.get("sort_order") or "").strip().lower() == "asc" else "desc",
        "limit": _normalize_limit(raw),
    }
    _add_present_values(normalized, state.metrics, none_only=True)
    _add_present_values(normalized, state.date_ranges)
    optional_values = {
        "tags": state.tags,
        "summary_languages": state.summary_languages,
        "excluded_summary_languages": state.excluded_summary_languages,
        "requirement_terms": state.requirement_terms,
        "compatibility_terms": state.compatibility_terms,
        "exact_title": state.exact_title,
        "version": state.version,
        "external_id": state.external_id,
        "source_url": state.source_url,
        "author": state.author,
        "excluded_sources": state.excluded_sources,
        "exclude_titles": _normalize_exclude_titles(raw.get("exclude_titles")),
        "excluded_keywords": state.excluded_keywords,
    }
    _add_present_values(normalized, optional_values)
    if state.updated_since_days is not None:
        normalized["updated_since_days"] = state.updated_since_days
    if state.has_thumbnail is not None:
        normalized["has_thumbnail"] = state.has_thumbnail
    evidence_id = str(raw.get("evidence_id") or "").strip()
    if evidence_id:
        normalized["evidence_id"] = evidence_id
    if str(raw.get("keyword_match_mode") or "").strip().lower() == "all":
        normalized["keyword_match_mode"] = "all"
    return normalized


def _add_present_values(
    target: dict[str, Any],
    values: dict[str, Any],
    *,
    none_only: bool = False,
) -> None:
    for key, value in values.items():
        if value is not None if none_only else bool(value):
            target[key] = value


def _query_mentions_category_scope(query: str) -> bool:
    """判断用户是否真的在问分类/类型，避免开放发现被误收窄到错误分类。"""
    text = str(query or "").lower()
    markers = [
        "服装",
        "衣服",
        "身体",
        "体型",
        "预设",
        "任务",
        "对话",
        "生存",
        "战斗",
        "武器",
        "护甲",
        "盔甲",
        "outfit",
        "clothing",
        "body",
        "preset",
        "quest",
        "dialogue",
        "survival",
        "combat",
        "weapon",
        "armor",
        "armour",
    ]
    return any(marker in text for marker in markers)


def _game_domains_from_games(games: list[str], allowed_domains: list[str]) -> list[str]:
    """根据游戏名推回 Nexus game_domain，供在线检索使用。"""
    domains: list[str] = []
    for game in games:
        game_key = alias_key(game)
        for domain in allowed_domains:
            domain_key = alias_key(domain)
            if domain_key and (domain_key == game_key or domain_key in game_key or game_key in domain_key):
                domains = _merge_unique(domains, [domain])
    return domains


def _canonicalize_nexus_external_id(
    external_id: str | None,
    sources: list[str],
    games: list[str],
    game_domains: list[str],
    slot_options: dict[str, list[str]],
) -> str | None:
    """Nexus 纯数字 ID 需要带 game_domain，避免不同游戏的 mod id 冲突。"""
    if not external_id or not re.fullmatch(r"\d{2,12}", external_id):
        return external_id
    if "nexusmods" not in {source.strip().lower() for source in sources}:
        return external_id
    domain = _identity_game_domain(games, game_domains, slot_options)
    return f"{domain}:{external_id}" if domain else external_id


def _identity_game_domain(
    games: list[str],
    game_domains: list[str],
    slot_options: dict[str, list[str]],
) -> str | None:
    """从显式 domain 或游戏名中推断 Nexus 身份命名空间。"""
    if game_domains:
        return game_domains[0]
    for game in games:
        game_key = alias_key(game)
        for domain in slot_options["game_domains"]:
            domain_key = alias_key(domain)
            if game_key and domain_key and (game_key == domain_key or game_key in domain_key or domain_key in game_key):
                return domain
    return None
