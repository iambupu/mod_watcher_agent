import json
import re
from typing import Any

from sqlalchemy import inspect as sqlalchemy_inspect
from sqlmodel import Session, select

from app.models.mod import Mod
from app.services.agent.history import compress_history
from app.services.agent.identity_inference import infer_identity_constraints, source_from_url
from app.services.agent.planning.fallback_query_plan import build_fallback_query_plan
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
    is_recent_query,
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
from app.services.agent.schemas import AgentHistoryItem
from app.services.agent.semantic_search import (
    SemanticQuery,
    category_match_score,
    infer_categories,
    semantic_query_from_anchors,
    semantic_query,
    strip_scope,
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
from app.services.llm_client import create_llm_client
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
    "build_database_schema_text",
    "build_fallback_query_plan",
    "detect_adult_constraint",
    "detect_query_intent",
    "infer_sort_preference",
    "infer_source_constraints",
    "is_recent_query",
    "load_slot_options",
    "normalize_query_plan",
    "plan_query_with_llm",
    "safe_json_loads",
]

FIELD_DESCRIPTIONS: dict[str, dict[str, str]] = {
    "mods": {
        "id": "本地 Mod 主键",
        "source": "来源平台，例如 nexusmods 或 loverslab",
        "external_id": "源站资源 ID",
        "game": "游戏展示名称",
        "game_domain": "游戏标准域名或来源侧标识",
        "title": "Mod 标题",
        "url": "源站详情页 URL",
        "author": "作者名称",
        "category": "来源侧分类",
        "tags_json": "标签 JSON 数组字符串",
        "original_summary": "源站原文摘要",
        "version": "版本号",
        "created_at_remote": "源站创建时间",
        "updated_at_remote": "源站更新时间",
        "published_at_remote": "源站发布时间",
        "downloads": "下载量",
        "unique_downloads": "唯一下载量",
        "endorsements": "Nexus 背书/点赞数",
        "views": "浏览量",
        "likes": "喜欢数",
        "adult_content": "是否成人内容",
        "thumbnail_url": "缩略图 URL",
        "raw_json": "源站原始数据 JSON",
        "ignored": "用户是否忽略该 Mod",
        "first_seen_at": "首次被本系统发现时间",
        "last_seen_at": "最近一次被本系统看到时间",
    },
    "mod_summaries": {
        "mod_id": "关联 mods.id",
        "language": "摘要语言",
        "summary_type": "摘要类型，例如 brief 或 introduction",
        "content": "摘要正文",
        "model": "生成摘要使用的模型",
        "generated_at": "摘要生成时间",
    },
}

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

def safe_json_loads(text: str) -> dict | None:
    """处理当前模块的业务逻辑并返回结果。"""
    raw = (text or "").strip()
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(raw[start : end + 1])
        except json.JSONDecodeError:
            return None
    return None

def _field_description(table: str, column: str) -> str:
    """内部辅助函数，用于拆分上层流程中的局部规则。"""
    return FIELD_DESCRIPTIONS.get(table, {}).get(column, "当前仅作为数据库字段参与查询/展示")


def build_database_schema_text(session: Session) -> str:
    """构建后续流程需要的数据结构。"""
    inspector = sqlalchemy_inspect(session.get_bind())
    lines = []
    for table_name in sorted(inspector.get_table_names()):
        lines.append(f"表 {table_name}:")
        for column in inspector.get_columns(table_name):
            name = str(column["name"])
            col_type = str(column["type"])
            lines.append(f"- {name} ({col_type}): {_field_description(table_name, name)}")
    return "\n".join(lines)


def _distinct_non_empty_values(session: Session, column: Any, limit: int = SLOT_OPTION_LIMIT) -> list[str]:
    """内部辅助函数，用于拆分上层流程中的局部规则。"""
    rows = session.exec(
        select(column)
        .where(column.is_not(None), column != "")
        .distinct()
        .order_by(column)
        .limit(limit)
    ).all()
    return [str(value).strip() for value in rows if str(value or "").strip()]


def load_slot_options(session: Session) -> dict[str, list[str]]:
    """加载配置或持久化数据。"""
    return {
        "games": _distinct_non_empty_values(session, Mod.game),
        "game_domains": _distinct_non_empty_values(session, Mod.game_domain),
        "categories": _distinct_non_empty_values(session, Mod.category),
        "sources": _merge_unique(_distinct_non_empty_values(session, Mod.source), ["nexusmods", "loverslab"]),
    }


def _format_slot_options(options: dict[str, list[str]]) -> str:
    """格式化内部展示或通知文本。"""
    lines = []
    for key in ["games", "game_domains", "categories", "sources"]:
        values = options.get(key, [])
        lines.append(f"{key}: {json.dumps(values, ensure_ascii=False)}")
    return "\n".join(lines)


def _merge_unique(values: list[str], additions: list[str]) -> list[str]:
    """合并多个来源的数据并保持稳定顺序。"""
    merged = list(values)
    seen = set(values)
    for item in additions:
        if item not in seen:
            merged.append(item)
            seen.add(item)
    return merged


def _infer_allowed_values_from_text(text: str, aliases: dict[str, list[str]]) -> list[str]:
    """内部辅助函数，用于拆分上层流程中的局部规则。"""
    key = alias_key(text)
    if not key:
        return []
    inferred: list[str] = []
    for alias_key_value, values in aliases.items():
        if alias_key_value and alias_key_value in key:
            inferred = _merge_unique(inferred, values)
    return inferred


def _normalize_sort_field(raw: Any, intent: str) -> str:
    """规范化内部数据，供后续流程使用。"""
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
    planning_source: str = "",
) -> tuple[list[str], str, list[str]]:
    """合并上游分类和语义分类；LLM 来源只使用 LLM anchors，不再重跑词面语义规则。"""

    explicit_categories = _normalize_allowed_list(
        raw.get("categories") or raw.get("category"),
        slot_options["categories"],
    )
    explicit_semantic = _semantic_query_for_normalization(raw, query, planning_source=planning_source)
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
    categories = list(explicit_categories)
    categories = infer_categories(query, slot_options["categories"], categories, semantic=explicit_semantic)
    category_match_mode = "exact" if explicit_categories else "db_fuzzy"
    semantic = _semantic_query_for_normalization(raw, query, planning_source=planning_source)
    return categories, category_match_mode, semantic.expanded_terms


def _semantic_query_for_normalization(raw: dict[str, Any], query: str, *, planning_source: str) -> SemanticQuery:
    if planning_source == "llm":
        anchors = _string_list(raw.get("semantic_anchors"))
        if anchors:
            return semantic_query_from_anchors(query, anchors)
        return SemanticQuery(raw_query=query, clean_query=strip_scope(query))
    return semantic_query(query)


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()][:12]


def normalize_query_plan(
    plan: dict | None,
    query: str,
    slot_options: dict[str, list[str]],
    *,
    planning_source: str = "",
) -> dict[str, Any]:
    """将 LLM 或兜底生成的查询计划规范化为数据库查询可消费的结构。"""

    raw = plan if isinstance(plan, dict) else {}
    raw = _apply_scope_overrides(raw, query, slot_options)
    if not raw.get("excluded_keywords") and not raw.get("exclude_keywords"):
        inferred_exclusions = infer_excluded_keywords(query)
        if inferred_exclusions:
            raw = {**raw, **inferred_exclusions}
    excluded_keywords = _normalize_excluded_keywords(raw.get("excluded_keywords") or raw.get("exclude_keywords"))
    semantic_query_text = _query_without_excluded_terms(query, excluded_keywords)
    intent = _normalize_intent(raw, query)
    keywords, games = _normalize_keywords_and_games(raw, query, slot_options)
    categories, category_match_mode, semantic_keywords = _normalize_categories(
        raw,
        semantic_query_text,
        slot_options,
        planning_source=planning_source,
    )
    keywords = _merge_unique(keywords, semantic_keywords)
    keywords = _drop_excluded_keywords(keywords, excluded_keywords)
    categories = _drop_excluded_categories(categories, excluded_keywords)

    excluded_sources = _normalize_allowed_list(
        raw.get("excluded_sources") or raw.get("excluded_source"),
        slot_options["sources"],
    )
    sources = _normalize_allowed_list(raw.get("sources") or raw.get("source"), slot_options["sources"])
    if excluded_sources and not sources:
        excluded = set(excluded_sources)
        sources = [source for source in slot_options["sources"] if source not in excluded]
    if sources or excluded_sources:
        keywords = _drop_source_keywords(keywords)
    author = _normalize_author(raw.get("author") or raw.get("authors") or raw.get("creator") or raw.get("modder"))
    if author:
        keywords = _drop_author_keywords(keywords, author)
    metrics = {
        "min_downloads": _normalize_min_metric(raw.get("min_downloads")),
        "min_endorsements": _normalize_min_metric(raw.get("min_endorsements")),
        "min_views": _normalize_min_metric(raw.get("min_views")),
        "min_likes": _normalize_min_metric(raw.get("min_likes")),
    }
    if not any(value is not None for value in metrics.values()):
        inferred_metrics = infer_numeric_constraints(query)
        metrics = {
            "min_downloads": inferred_metrics.get("min_downloads"),
            "min_endorsements": inferred_metrics.get("min_endorsements"),
            "min_views": inferred_metrics.get("min_views"),
            "min_likes": inferred_metrics.get("min_likes"),
        }
    keywords = _drop_metric_keywords(keywords, metrics)
    updated_since_days = _normalize_time_window(raw.get("updated_since_days") or raw.get("updated_within_days"))
    if updated_since_days is None:
        updated_since_days = infer_time_window(query).get("updated_since_days")
    keywords = _drop_time_window_keywords(keywords, updated_since_days)
    inferred_dates = infer_absolute_date_constraints(query)
    date_ranges = {
        "updated_after": _normalize_absolute_date(raw.get("updated_after") or inferred_dates.get("updated_after")),
        "updated_before": _normalize_absolute_date(raw.get("updated_before") or inferred_dates.get("updated_before")),
        "published_after": _normalize_absolute_date(raw.get("published_after") or inferred_dates.get("published_after")),
        "published_before": _normalize_absolute_date(raw.get("published_before") or inferred_dates.get("published_before")),
        "created_after": _normalize_absolute_date(raw.get("created_after") or inferred_dates.get("created_after")),
        "created_before": _normalize_absolute_date(raw.get("created_before") or inferred_dates.get("created_before")),
    }
    keywords = _drop_absolute_date_keywords(keywords, date_ranges)
    explicit_tag_constraint = _has_explicit_tag_constraint(query)
    raw_tags = _normalize_tags(raw.get("tags") or raw.get("tag"))
    inferred_tags = _normalize_tags(infer_tag_constraints(query).get("tags"))
    tags = raw_tags or inferred_tags if explicit_tag_constraint else []
    if tags:
        keywords = _drop_tag_keywords(keywords, tags)
    elif raw_tags:
        keywords = _merge_unique(keywords, raw_tags)
    inferred_thumbnail = infer_thumbnail_constraint(query)
    has_thumbnail = _normalize_optional_bool(raw.get("has_thumbnail"))
    if has_thumbnail is None:
        has_thumbnail = inferred_thumbnail.get("has_thumbnail")
    inferred_summary_languages = infer_summary_language_constraints(query)
    summary_languages = _normalize_summary_languages(raw.get("summary_languages") or raw.get("summary_language"))
    if not summary_languages:
        summary_languages = _normalize_summary_languages(inferred_summary_languages.get("summary_languages"))
    excluded_summary_languages = _normalize_summary_languages(
        raw.get("excluded_summary_languages") or raw.get("excluded_summary_language")
    )
    if not excluded_summary_languages:
        excluded_summary_languages = _normalize_summary_languages(
            inferred_summary_languages.get("excluded_summary_languages")
        )
    summary_languages = _drop_excluded_summary_languages(summary_languages, excluded_summary_languages)
    keywords = _drop_summary_language_keywords(
        keywords,
        _merge_unique(summary_languages, excluded_summary_languages),
    )
    requirement_terms = _normalize_requirement_terms(
        raw.get("requirement_terms") or raw.get("requirements") or raw.get("dependencies")
    )
    if not requirement_terms:
        requirement_terms = _normalize_requirement_terms(infer_requirement_terms(query).get("requirement_terms"))
    keywords = _drop_requirement_keywords(keywords, requirement_terms)
    compatibility_terms = _normalize_compatibility_terms(
        raw.get("compatibility_terms") or raw.get("compatible_with") or raw.get("compatibility")
    )
    if not compatibility_terms:
        compatibility_terms = _normalize_compatibility_terms(
            infer_compatibility_terms(query).get("compatibility_terms")
        )
    compatibility_terms = _drop_gameplay_support_compatibility_terms(query, compatibility_terms)
    keywords = _drop_compatibility_keywords(keywords, compatibility_terms)
    exact_title = _normalize_exact_title(raw.get("exact_title") or raw.get("title"))
    if exact_title is None:
        exact_title = infer_title_constraint(query).get("exact_title")
    version = _normalize_version(raw.get("version") or raw.get("mod_version"))
    if version is None:
        version = infer_version_constraint(query).get("version")
    keywords = _drop_version_keywords(keywords, version)
    game_domains = _normalize_allowed_list(
        raw.get("game_domains") or raw.get("game_domain"),
        slot_options["game_domains"],
    )
    identity = infer_identity_constraints(query)
    source_url = _normalize_source_url(raw.get("source_url") or raw.get("url") or identity.get("source_url"))
    external_id = _normalize_external_id(raw.get("external_id") or raw.get("source_id") or identity.get("external_id"))
    if source_url:
        inferred_source = source_from_url(source_url)
        if inferred_source and not sources:
            sources = [inferred_source]
        if inferred_source and not external_id:
            external_id = canonical_external_id(inferred_source, "", source_url)
    if identity.get("sources") and not sources:
        sources = _normalize_allowed_list(identity.get("sources"), slot_options["sources"])
    external_id = _canonicalize_nexus_external_id(external_id, sources, games, game_domains, slot_options)
    keywords = _drop_identity_keywords(keywords, external_id, source_url)

    adult_content = _normalize_adult_content(query)
    keywords = _drop_adult_keywords(keywords, adult_content)
    sort_field = _normalize_sort_field(raw.get("sort_field") or raw.get("sort"), intent)
    keywords = _drop_sort_keywords(keywords, sort_field)

    normalized = {
        "intent": intent,
        "keywords": keywords[:10],
        "games": games,
        "game_domains": game_domains,
        "categories": categories,
        "category_match_mode": category_match_mode,
        "sources": sources,
        "adult_content": adult_content,
        "sort_field": sort_field,
        "sort_order": "asc" if str(raw.get("sort_order") or "").strip().lower() == "asc" else "desc",
        "limit": _normalize_limit(raw),
    }
    evidence_id = str(raw.get("evidence_id") or "").strip()
    if evidence_id:
        normalized["evidence_id"] = evidence_id
    for key, value in metrics.items():
        if value is not None:
            normalized[key] = value
    if updated_since_days is not None:
        normalized["updated_since_days"] = updated_since_days
    for key, value in date_ranges.items():
        if value:
            normalized[key] = value
    if tags:
        normalized["tags"] = tags
    if has_thumbnail is not None:
        normalized["has_thumbnail"] = has_thumbnail
    if summary_languages:
        normalized["summary_languages"] = summary_languages
    if excluded_summary_languages:
        normalized["excluded_summary_languages"] = excluded_summary_languages
    if requirement_terms:
        normalized["requirement_terms"] = requirement_terms
    if compatibility_terms:
        normalized["compatibility_terms"] = compatibility_terms
    if exact_title:
        normalized["exact_title"] = exact_title
    if version:
        normalized["version"] = version
    if external_id:
        normalized["external_id"] = external_id
    if source_url:
        normalized["source_url"] = source_url
    if author:
        normalized["author"] = author
    if excluded_sources:
        normalized["excluded_sources"] = excluded_sources
    exclude_titles = _normalize_exclude_titles(raw.get("exclude_titles"))
    if exclude_titles:
        normalized["exclude_titles"] = exclude_titles
    if str(raw.get("keyword_match_mode") or "").strip().lower() == "all":
        normalized["keyword_match_mode"] = "all"
    if excluded_keywords:
        normalized["excluded_keywords"] = excluded_keywords
    return normalized


def _canonicalize_nexus_external_id(
    external_id: str | None,
    sources: list[str],
    games: list[str],
    game_domains: list[str],
    slot_options: dict[str, list[str]],
) -> str | None:
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
    if game_domains:
        return game_domains[0]
    for game in games:
        game_key = alias_key(game)
        for domain in slot_options["game_domains"]:
            domain_key = alias_key(domain)
            if game_key and domain_key and (game_key == domain_key or game_key in domain_key or domain_key in game_key):
                return domain
    return None


async def plan_query_with_llm(
    *,
    query: str,
    provider: str,
    api_key: str,
    base_url: str,
    model: str,
    history: list[AgentHistoryItem],
    database_schema: str,
    slot_options: dict[str, list[str]],
) -> dict | None:
    """处理当前模块的业务逻辑并返回结果。"""
    client = create_llm_client(provider=provider, api_key=api_key, base_url=base_url)
    history_summary, recent_history = compress_history(history, max_items=8, max_chars=1200)
    prompt_lines = [
        "你是 Mod 数据库查询意图识别器。请根据用户问题输出结构化查询词槽 JSON。",
        "数据库表结构与字段含义：",
        database_schema,
        "",
        "数据库中可匹配的枚举值如下。game、game_domain、category、source 必须只从这些枚举值中选择；可以选择多个。",
        _format_slot_options(slot_options),
        "输出规则：",
        "1) 只输出一个 JSON 对象，不要额外解释",
        "2) JSON 结构:",
        '{ "intent":"recent|search|author|game|comparison|alternative|install_risk|preference_summary|unknown", "keywords":[string], "excluded_keywords":[string], "exact_title":string|null, "version":string|null, "external_id":string|null, "source_url":string|null, "games":[string], "game_domains":[string], "categories":[string], "tags":[string], "summary_languages":[string], "excluded_summary_languages":[string], "requirement_terms":[string], "compatibility_terms":[string], "semantic_anchors":[string], "semantic_domains":[string], "has_thumbnail":true|false|null, "adult_content":true|false|null, "sources":[string], "excluded_sources":[string], "author":string|null, "min_downloads":number|null, "min_endorsements":number|null, "min_views":number|null, "min_likes":number|null, "updated_since_days":number|null, "updated_after":string|null, "updated_before":string|null, "published_after":string|null, "published_before":string|null, "created_after":string|null, "created_before":string|null, "sort_field":"updated_at_remote|first_seen_at|created_at_remote|published_at_remote|downloads|unique_downloads|endorsements|views|likes|relevance", "sort_order":"asc|desc", "limit":8, "game_aliases":[{"alias":string,"game":string}] }',
        "3) 用户说成人/R18/NSFW 时 adult_content=true；非成人/SFW/排除成人时 adult_content=false；未提及时为 null",
        "4) 下载量最高用 downloads desc；点赞/背书最高用 endorsements desc 或 likes desc；最近/最新/更新用 updated_at_remote desc",
        "5) 下载至少/超过 N 用 min_downloads=N；背书/点赞至少/超过 N 用 min_endorsements=N；浏览量至少/超过 N 用 min_views=N；喜欢数至少/超过 N 用 min_likes=N；不要把 N 或指标阈值词放入 keywords",
        "6) 最近/过去/last/past/within 明确 N 天/周/月时输出 updated_since_days，按天数换算并限制 1~365；不要把时间数字或时间单位放入 keywords",
        "7) 用户说 2024 年以后更新/after 2024-01-01 published/before 2023 created 等绝对日期范围时，输出对应 updated_after/updated_before/published_after/published_before/created_after/created_before，格式为 ISO 字符串；不要把日期或 after/before/更新/发布/创建放入 keywords",
        "8) 用户明确说 标签/tag/tagged/带某标签 时，把标签值放入 tags；不要把 tag/标签或标签值重复放入 keywords",
        "9) 用户用引号、named/called/titled/title、叫/名叫/标题/名字明确指名某个 Mod 标题时，把完整标题放入 exact_title",
        "10) 用户明确写 version/v/版本 + 数字版本号时，把版本号放入 version；不要把 version/v/版本或版本号重复放入 keywords",
        "11) 用户贴 NexusMods/LoversLab URL 或明确说 Nexus mod id / LoversLab file id 时，输出 source_url/external_id 和对应 sources；不要把 URL、id 或来源名重复放入 keywords",
        "12) 用户问前置/依赖/requirements/dependencies 且明确给出 SKSE/CBBE/Bodyslide 等依赖名时，把依赖名放入 requirement_terms；不要把依赖名或前置/依赖词重复放入 keywords",
        "13) 用户问支持/兼容/适配/compatible with/for 且明确给出 AE/VR/1.6.640 等兼容目标时，把目标放入 compatibility_terms；不要把兼容目标或支持/兼容词重复放入 keywords",
        "14) 用户明确要求有图/预览图/截图/thumbnail/preview 时 has_thumbnail=true；要求无图/不要图片/no image 时 has_thumbnail=false；不要把图片/预览/截图词放入 keywords",
        "15) 用户明确要求有中文/英文/日文摘要、介绍或说明时，把语言放入 summary_languages（中文=zh-CN，英文=en，日文=ja-JP）；明确要求无/不要/without/no 某语言摘要时，把语言放入 excluded_summary_languages，不要同时放入 summary_languages；不要把语言名或摘要/介绍/summary 放入 keywords",
        "16) limit 范围 1~20，默认 8",
        "17) keywords 只放无法映射到上述词槽的自由文本关键词",
        "18) semantic_anchors/semantic_domains 用来表达整体语义，不要只复述关键词；每个 anchor 必须能由用户原文、同义表达或明确上下文支持",
        "19) 玩法/机制类表达输出 mechanics 域，例如 扮演/角色扮演/身份路线/职业路线/bimbo 养成 输出 roleplay + mechanics；怀孕/妊娠/生育/受孕/繁殖玩法 输出 pregnancy + mechanics",
        "20) 风格/外观类表达输出 identity_style 或 content_type 域，例如 妓女/娼妓/风尘/夜店/escort 风格服装 输出 sexworker_style + content_type；不要因为出现“风格”就输出 roleplay/mechanics",
        "21) 体系/framework/source 类表达要拆开：体系/框架/核心系统 输出 framework；LoversLab/爱的实验室/LL/llab 输出 loverslab + source_scope，并在 sources 中选择 loverslab",
        "22) query rewrite 时保留用户真正的自由检索词；不要把 source、game、date、tag、requirement、compatibility、semantic anchor 解释词重复塞进 keywords",
        "23) 如果用户使用了翻译名/俗称/缩写，并且你能确定它对应某个 games 枚举值，请在 game_aliases 中输出映射，例如 {\"alias\":\"剑星\",\"game\":\"Stellar Blade\"}",
    ]
    if history_summary:
        prompt_lines.extend(["", history_summary])
    if recent_history:
        prompt_lines.append("最近对话：")
        for item in recent_history:
            prefix = "用户" if item.role == "user" else "助手"
            prompt_lines.append(f"{prefix}: {item.text[:180]}")
    prompt_lines.extend(["", f"用户问题：{query}"])
    plan_text = await client.chat("\n".join(prompt_lines), model=model, max_tokens=240)
    plan = safe_json_loads(plan_text)
    if not isinstance(plan, dict):
        return None
    return plan
