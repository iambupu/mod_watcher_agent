import logging
import re
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func, not_, or_
from sqlmodel import Session, select

from app.models.mod import Mod
from app.models.summary import ModSummary
from app.services.agent.filter_value_utils import (
    optional_min_metric,
    optional_time_window,
    url_without_query,
)
from app.services.agent.list_utils import string_list as _string_list
from app.services.agent.planning.open_discovery_policy import (
    build_open_discovery_retrieval_plan,
    open_discovery_result_limit,
)
from app.services.agent.query_planner import (
    DEFAULT_AGENT_LIMIT,
    RELEVANCE_PREFETCH_LIMIT,
    SORT_COLUMNS,
)
from app.services.agent.retrievers.sqlite_fts_retriever import query_mods_fts
from app.services.agent.semantic_search import semantic_query, text_score, unique_terms
from app.services.source_identity import external_id_aliases
from app.services.summary_service import load_preferred_brief_summary_map

logger = logging.getLogger(__name__)


def score_mod(query: str, mod: Mod, extra_text: str = "") -> int:
    """用标题、翻译标题、分类、摘要和补充摘要文本计算候选相关性。"""
    return text_score(
        query,
        [mod.title, mod.translated_title_zh, mod.game, mod.author, mod.category, mod.original_summary, extra_text],
        [mod.category] if mod.category else None,
    )


def _content_visibility_conditions(plan: dict[str, Any]) -> list[Any]:
    conditions: list[Any] = []
    adult_content = plan.get("adult_content")
    if isinstance(adult_content, bool):
        conditions.append(Mod.adult_content == adult_content)

    has_thumbnail = plan.get("has_thumbnail")
    if not isinstance(has_thumbnail, bool):
        return conditions
    thumbnail_condition = Mod.thumbnail_url.is_not(None) if has_thumbnail else Mod.thumbnail_url.is_(None)
    if has_thumbnail:
        conditions.extend((thumbnail_condition, Mod.thumbnail_url != ""))
    else:
        conditions.append(or_(thumbnail_condition, Mod.thumbnail_url == ""))
    return conditions


def _source_identity_filter_conditions(plan: dict[str, Any]) -> list[Any]:
    conditions: list[Any] = []
    sources = plan.get("sources") or []
    if sources:
        conditions.append(Mod.source.in_(sources))
    excluded_sources = _string_list(plan.get("excluded_sources"))
    if excluded_sources:
        conditions.append(not_(Mod.source.in_(excluded_sources)))
    identity_conditions = _identity_conditions(plan, sources)
    if identity_conditions:
        conditions.append(or_(*identity_conditions))
    author = str(plan.get("author") or "").strip()
    if author:
        conditions.append(Mod.author.ilike(f"%{author}%"))
    return conditions


def _metric_and_time_filter_conditions(plan: dict[str, Any]) -> list[Any]:
    conditions: list[Any] = []
    for key, column in {
        "min_downloads": Mod.downloads,
        "min_endorsements": Mod.endorsements,
        "min_views": Mod.views,
        "min_likes": Mod.likes,
    }.items():
        minimum = optional_min_metric(plan.get(key))
        if minimum is not None:
            conditions.append(column >= minimum)

    updated_since_days = optional_time_window(plan.get("updated_since_days"))
    if updated_since_days is not None:
        cutoff = (datetime.now(UTC) - timedelta(days=updated_since_days)).isoformat()
        conditions.append(or_(Mod.updated_at_remote >= cutoff, Mod.published_at_remote >= cutoff))

    for key, column in {
        "updated_after": Mod.updated_at_remote,
        "updated_before": Mod.updated_at_remote,
        "published_after": Mod.published_at_remote,
        "published_before": Mod.published_at_remote,
        "created_after": Mod.created_at_remote,
        "created_before": Mod.created_at_remote,
    }.items():
        value = str(plan.get(key) or "").strip()
        if value:
            conditions.append(column >= value if key.endswith("_after") else column <= value)
    return conditions


def _text_and_summary_filter_conditions(plan: dict[str, Any]) -> list[Any]:
    conditions: list[Any] = []
    for tag in _string_list(plan.get("tags")):
        conditions.append(Mod.tags_json.ilike(f"%{tag}%"))

    summary_languages = _string_list(plan.get("summary_languages"))
    if summary_languages:
        # 指定摘要语言时必须 join ModSummary，且只看用户可读的 brief/introduction。
        conditions.extend(
            (
                ModSummary.language.in_(summary_languages),
                ModSummary.summary_type.in_(["brief", "introduction"]),
            )
        )
    excluded_summary_languages = _string_list(plan.get("excluded_summary_languages"))
    if excluded_summary_languages:
        excluded_summary_ids = (
            select(ModSummary.mod_id)
            .where(
                ModSummary.language.in_(excluded_summary_languages),
                ModSummary.summary_type.in_(["brief", "introduction"]),
            )
            .distinct()
        )
        conditions.append(not_(Mod.id.in_(excluded_summary_ids)))

    for term in _string_list(plan.get("requirement_terms")):
        conditions.append(_requirement_condition(term))
    for term in _string_list(plan.get("compatibility_terms")):
        conditions.append(_compatibility_condition(term))

    exact_title = str(plan.get("exact_title") or "").strip()
    if exact_title:
        # 精确标题同时匹配原文和中文标题，避免翻译标题查询漏召回。
        exact_key = _title_key(exact_title)
        conditions.append(
            or_(
                func.lower(func.trim(func.coalesce(Mod.title, ""))) == exact_key,
                func.lower(func.trim(func.coalesce(Mod.translated_title_zh, ""))) == exact_key,
            )
        )
    version = str(plan.get("version") or "").strip()
    if version:
        conditions.append(Mod.version.ilike(f"%{version}%"))
    return conditions


def _keyword_and_category_filter_conditions(plan: dict[str, Any], categories: list[str]) -> list[Any]:
    conditions: list[Any] = []
    keywords = _db_fuzzy_keywords(plan, categories)
    keyword_conditions = [_keyword_condition(keyword) for keyword in keywords]
    excluded_keyword_conditions = [
        _keyword_condition(keyword)
        for keyword in (plan.get("excluded_keywords") or [])
        if str(keyword).strip()
    ]
    if excluded_keyword_conditions:
        conditions.append(not_(or_(*excluded_keyword_conditions)))

    exclude_titles = [_title_key(value) for value in _string_list(plan.get("exclude_titles"))]
    if exclude_titles:
        conditions.append(
            not_(
                or_(
                    func.lower(func.trim(func.coalesce(Mod.title, ""))).in_(exclude_titles),
                    func.lower(func.trim(func.coalesce(Mod.translated_title_zh, ""))).in_(exclude_titles),
                )
            )
        )

    category_conditions = [Mod.category.in_(categories)] if categories else []
    if not category_conditions and not keyword_conditions:
        return conditions
    if plan.get("category_match_mode") == "db_fuzzy" and category_conditions and keyword_conditions:
        # 语义推断出的分类是软提示，和关键词 OR 起来提升召回，不能变成硬过滤。
        conditions.append(or_(*(category_conditions + keyword_conditions)))
        return conditions
    conditions.extend(category_conditions)
    if str(plan.get("keyword_match_mode") or "").strip().lower() == "all":
        conditions.extend(keyword_conditions)
    elif keyword_conditions:
        conditions.append(or_(*keyword_conditions))
    return conditions


def _build_mod_query_from_plan(plan: dict[str, Any]):
    """把规范化 query_plan 翻译成只读 SQLModel 查询。"""
    conditions = [Mod.ignored == False]  # noqa: E712
    game_conditions = _game_scope_conditions(plan)
    if game_conditions:
        conditions.append(or_(*game_conditions))

    categories = plan.get("categories") or []

    conditions.extend(_content_visibility_conditions(plan))

    conditions.extend(_source_identity_filter_conditions(plan))
    conditions.extend(_metric_and_time_filter_conditions(plan))
    conditions.extend(_text_and_summary_filter_conditions(plan))

    conditions.extend(_keyword_and_category_filter_conditions(plan, categories))

    sort_field = plan.get("sort_field") or "relevance"
    sort_column = SORT_COLUMNS.get(sort_field, Mod.first_seen_at)
    sort_expr = sort_column.asc() if plan.get("sort_order") == "asc" else sort_column.desc()
    result_limit = _result_limit(plan)
    # 相关性排序需要先多取一批，再用 Python 结合摘要和身份分重排。
    query_limit = max(RELEVANCE_PREFETCH_LIMIT, result_limit) if sort_field == "relevance" else result_limit
    return (
        select(Mod)
        .outerjoin(ModSummary, ModSummary.mod_id == Mod.id)
        .where(*conditions)
        .distinct()
        .order_by(sort_expr, Mod.first_seen_at.desc())
        .limit(query_limit)
    )


def _db_fuzzy_keywords(plan: dict[str, Any], categories: list[str]) -> list[str]:
    """把 query_plan 关键词和语义扩展词合并成数据库模糊匹配词。"""
    keywords = [str(value).strip().lower() for value in (plan.get("keywords") or []) if str(value).strip()]
    semantic = semantic_query(" ".join(keywords), categories)
    return unique_terms([*keywords, *semantic.expanded_terms])


def _game_scope_conditions(plan: dict[str, Any]) -> list[Any]:
    game_values = _string_list(plan.get("games"))
    game_domain_values = _string_list(plan.get("game_domains"))
    if game_values and game_domain_values:
        values = list(dict.fromkeys([*game_values, *game_domain_values]))
        return [Mod.game.in_(values), Mod.game_domain.in_(values)]
    if game_domain_values:
        return [Mod.game.in_(game_domain_values), Mod.game_domain.in_(game_domain_values)]
    if game_values:
        return [Mod.game.in_(game_values)]
    return []


def _keyword_condition(keyword: str):
    """构造跨标题、作者、分类、标签、原摘要和生成摘要的模糊匹配。"""
    pattern = f"%{keyword}%"
    return or_(
        func.coalesce(Mod.title, "").ilike(pattern),
        func.coalesce(Mod.translated_title_zh, "").ilike(pattern),
        func.coalesce(Mod.author, "").ilike(pattern),
        func.coalesce(Mod.category, "").ilike(pattern),
        func.coalesce(Mod.tags_json, "").ilike(pattern),
        func.coalesce(Mod.original_summary, "").ilike(pattern),
        func.coalesce(ModSummary.content, "").ilike(pattern),
    )


def _requirement_condition(term: str):
    pattern = f"%{term}%"
    return or_(
        Mod.title.ilike(pattern),
        Mod.translated_title_zh.ilike(pattern),
        Mod.tags_json.ilike(pattern),
        Mod.original_summary.ilike(pattern),
        Mod.raw_json.ilike(pattern),
        ModSummary.content.ilike(pattern),
    )


def _compatibility_condition(term: str):
    return _requirement_condition(term)


def _identity_conditions(plan: dict[str, Any], sources: list[str]) -> list[Any]:
    conditions: list[Any] = []
    source_url = str(plan.get("source_url") or "").strip()
    if source_url:
        conditions.append(Mod.url == source_url)
        canonical_url = url_without_query(source_url)
        if canonical_url != source_url:
            conditions.append(Mod.url == canonical_url)
    external_id = str(plan.get("external_id") or "").strip()
    if not external_id:
        return conditions
    if sources:
        alias_values: list[str] = []
        suffix_conditions: list[Any] = []
        for source in sources:
            alias_values.extend(external_id_aliases(str(source), external_id, source_url))
            if str(source).strip().lower() == "loverslab" and re.fullmatch(r"\d{2,12}", external_id):
                suffix_conditions.append(Mod.external_id.ilike(f"%:{external_id}"))
        conditions.append(or_(Mod.external_id.in_(list(dict.fromkeys(alias_values))), *suffix_conditions))
    else:
        conditions.append(Mod.external_id == external_id)
    return conditions


def _identity_score(plan: dict[str, Any], mod: Mod) -> int:
    external_id = str(plan.get("external_id") or "").strip()
    source_url = str(plan.get("source_url") or "").strip()
    if not external_id and not source_url:
        return 0
    if source_url and source_url == (mod.url or ""):
        return 100
    if source_url and url_without_query(source_url) == (mod.url or ""):
        return 100
    source = str(mod.source or "").strip()
    if external_id and source:
        aliases = external_id_aliases(source, external_id, source_url)
        mod_external_id = str(mod.external_id or "").strip()
        if mod_external_id in aliases:
            return 100
        if source.lower() == "loverslab" and re.fullmatch(r"\d{2,12}", external_id) and mod_external_id.endswith(f":{external_id}"):
            return 100
        return 0
    return 100 if external_id and external_id == str(mod.external_id or "").strip() else 0


def validate_agent_sql(statement: Any, session: Session) -> str:
    """验证 Agent 生成/拼装的 SQL 仍是只读 mods 查询。"""
    compiled = statement.compile(bind=session.get_bind(), compile_kwargs={"literal_binds": False})
    sql = str(compiled).strip()
    normalized = re.sub(r"--.*?\n|/\*.*?\*/", "", sql, flags=re.DOTALL)
    normalized = re.sub(r"\s+", " ", normalized).strip().lower()
    forbidden = [" insert ", " update ", " delete ", " drop ", " alter ", " pragma "]
    if not re.match(r"^select\b", normalized) or " from mods" not in normalized or any(token in normalized for token in forbidden):
        raise HTTPException(status_code=500, detail="Agent SQL validation failed")
    return sql


def query_mods_with_plan(session: Session, query: str, plan: dict[str, Any]) -> list[tuple[int, Mod]]:
    """先走 FTS 召回，再用结构化 SQL 兜底并合并重排。"""
    retrieval_plan = build_open_discovery_retrieval_plan(plan, query)
    fts_results = _query_mods_with_fts(session, retrieval_plan)
    if fts_results:
        logger.info(
            "agent.retrieval.fts status=succeeded evidence_id=%s count=%s keywords=%s excluded_keywords=%s excluded_sources=%s games=%s game_domains=%s sources=%s categories=%s tags=%s summary_languages=%s excluded_summary_languages=%s requirement_terms=%s compatibility_terms=%s has_thumbnail=%s adult_content=%s min_downloads=%s min_endorsements=%s min_views=%s min_likes=%s updated_after=%s updated_before=%s published_after=%s published_before=%s created_after=%s created_before=%s external_id=%s source_url=%s",
            retrieval_plan.get("evidence_id"),
            len(fts_results),
            retrieval_plan.get("keywords") or [],
            retrieval_plan.get("excluded_keywords") or [],
            retrieval_plan.get("excluded_sources") or [],
            retrieval_plan.get("games") or [],
            retrieval_plan.get("game_domains") or [],
            retrieval_plan.get("sources") or [],
            retrieval_plan.get("categories") or [],
            retrieval_plan.get("tags") or [],
            retrieval_plan.get("summary_languages") or [],
            retrieval_plan.get("excluded_summary_languages") or [],
            retrieval_plan.get("requirement_terms") or [],
            retrieval_plan.get("compatibility_terms") or [],
            retrieval_plan.get("has_thumbnail"),
            retrieval_plan.get("adult_content"),
            retrieval_plan.get("min_downloads"),
            retrieval_plan.get("min_endorsements"),
            retrieval_plan.get("min_views"),
            retrieval_plan.get("min_likes"),
            retrieval_plan.get("updated_after"),
            retrieval_plan.get("updated_before"),
            retrieval_plan.get("published_after"),
            retrieval_plan.get("published_before"),
            retrieval_plan.get("created_after"),
            retrieval_plan.get("created_before"),
            retrieval_plan.get("external_id"),
            retrieval_plan.get("source_url"),
        )
    else:
        logger.info(
            "agent.retrieval.fts status=skipped evidence_id=%s count=0 keywords=%s excluded_keywords=%s excluded_sources=%s games=%s game_domains=%s sources=%s categories=%s tags=%s summary_languages=%s excluded_summary_languages=%s requirement_terms=%s compatibility_terms=%s has_thumbnail=%s adult_content=%s min_downloads=%s min_endorsements=%s min_views=%s min_likes=%s updated_after=%s updated_before=%s published_after=%s published_before=%s created_after=%s created_before=%s external_id=%s source_url=%s",
            retrieval_plan.get("evidence_id"),
            retrieval_plan.get("keywords") or [],
            retrieval_plan.get("excluded_keywords") or [],
            retrieval_plan.get("excluded_sources") or [],
            retrieval_plan.get("games") or [],
            retrieval_plan.get("game_domains") or [],
            retrieval_plan.get("sources") or [],
            retrieval_plan.get("categories") or [],
            retrieval_plan.get("tags") or [],
            retrieval_plan.get("summary_languages") or [],
            retrieval_plan.get("excluded_summary_languages") or [],
            retrieval_plan.get("requirement_terms") or [],
            retrieval_plan.get("compatibility_terms") or [],
            retrieval_plan.get("has_thumbnail"),
            retrieval_plan.get("adult_content"),
            retrieval_plan.get("min_downloads"),
            retrieval_plan.get("min_endorsements"),
            retrieval_plan.get("min_views"),
            retrieval_plan.get("min_likes"),
            retrieval_plan.get("updated_after"),
            retrieval_plan.get("updated_before"),
            retrieval_plan.get("published_after"),
            retrieval_plan.get("published_before"),
            retrieval_plan.get("created_after"),
            retrieval_plan.get("created_before"),
            retrieval_plan.get("external_id"),
            retrieval_plan.get("source_url"),
        )
    statement = _build_mod_query_from_plan(retrieval_plan)
    validate_agent_sql(statement, session)
    mods = session.exec(statement).all()
    logger.info(
        "agent.retrieval.sql status=succeeded evidence_id=%s count=%s sort=%s/%s excluded_keywords=%s excluded_sources=%s games=%s game_domains=%s sources=%s categories=%s tags=%s summary_languages=%s excluded_summary_languages=%s requirement_terms=%s compatibility_terms=%s has_thumbnail=%s adult_content=%s min_downloads=%s min_endorsements=%s min_views=%s min_likes=%s updated_after=%s updated_before=%s published_after=%s published_before=%s created_after=%s created_before=%s external_id=%s source_url=%s",
        retrieval_plan.get("evidence_id"),
        len(mods),
        retrieval_plan.get("sort_field") or "relevance",
        retrieval_plan.get("sort_order") or "desc",
        retrieval_plan.get("excluded_keywords") or [],
        retrieval_plan.get("excluded_sources") or [],
        retrieval_plan.get("games") or [],
        retrieval_plan.get("game_domains") or [],
        retrieval_plan.get("sources") or [],
        retrieval_plan.get("categories") or [],
        retrieval_plan.get("tags") or [],
        retrieval_plan.get("summary_languages") or [],
        retrieval_plan.get("excluded_summary_languages") or [],
        retrieval_plan.get("requirement_terms") or [],
        retrieval_plan.get("compatibility_terms") or [],
        retrieval_plan.get("has_thumbnail"),
        retrieval_plan.get("adult_content"),
        retrieval_plan.get("min_downloads"),
        retrieval_plan.get("min_endorsements"),
        retrieval_plan.get("min_views"),
        retrieval_plan.get("min_likes"),
        retrieval_plan.get("updated_after"),
        retrieval_plan.get("updated_before"),
        retrieval_plan.get("published_after"),
        retrieval_plan.get("published_before"),
        retrieval_plan.get("created_after"),
        retrieval_plan.get("created_before"),
        retrieval_plan.get("external_id"),
        retrieval_plan.get("source_url"),
    )
    search_text_by_mod = build_search_text_map(session, [mod.id for mod in mods if mod.id is not None])
    if retrieval_plan.get("sort_field") == "relevance":
        scored = [
            (
                max(score_mod(query, mod, search_text_by_mod.get(mod.id or 0, "")), 1)
                + _identity_score(plan, mod)
                + _category_hint_score(retrieval_plan, mod),
                mod,
            )
            for mod in mods
            if mod.id is not None
        ]
        scored.sort(key=lambda item: (item[0], item[1].first_seen_at), reverse=True)
        return _merge_scored_results(fts_results, scored, _result_limit(plan))
    scored = [
        (
            max(score_mod(query, mod, search_text_by_mod.get(mod.id or 0, "")), 1)
            + _identity_score(plan, mod)
            + _category_hint_score(retrieval_plan, mod),
            mod,
        )
        for mod in mods
        if mod.id is not None
    ]
    return _merge_scored_results(fts_results, scored, _result_limit(plan))


def _result_limit(plan: dict[str, Any]) -> int:
    """开放发现会扩大候选池，普通检索则使用 Agent 默认结果数。"""
    return open_discovery_result_limit(plan, default_limit=DEFAULT_AGENT_LIMIT)


def _category_hint_score(plan: dict[str, Any], mod: Mod) -> int:
    """给软分类提示一个小加分，不让它压过文本相关性和身份命中。"""
    hints = {str(value).strip().lower() for value in (plan.get("category_hints") or []) if str(value).strip()}
    if not hints:
        return 0
    category = str(mod.category or "").strip().lower()
    return 2 if category in hints else 0


def _merge_scored_results(
    primary: list[tuple[int, Mod]],
    secondary: list[tuple[int, Mod]],
    limit: int,
) -> list[tuple[int, Mod]]:
    """合并 FTS 和 SQL 结果，同一个 Mod 保留最高分。"""
    if not primary:
        return secondary[:limit]
    merged: dict[int, tuple[int, Mod]] = {}
    for score, mod in [*primary, *secondary]:
        if mod.id is None:
            continue
        existing = merged.get(mod.id)
        if existing is None or score > existing[0]:
            merged[mod.id] = (score, mod)
    return sorted(merged.values(), key=lambda item: (item[0], item[1].first_seen_at), reverse=True)[:limit]


def _query_mods_with_fts(session: Session, plan: dict[str, Any]) -> list[tuple[int, Mod]]:
    """仅在相关性排序时启用 FTS，避免破坏用户显式指定的排序字段。"""
    if plan.get("sort_field") not in {None, "relevance"}:
        return []
    keywords = [str(value).strip() for value in (plan.get("keywords") or []) if str(value).strip()]
    if not keywords:
        return []
    results = query_mods_fts(
        session,
        keywords=keywords,
        filters=plan,
        limit=_result_limit(plan),
    )
    return [(item.score, item.mod) for item in results if item.mod.id is not None]


def _title_key(value: str | None) -> str:
    """标题精确匹配使用折叠空白和小写后的 key。"""
    return " ".join(str(value or "").lower().split())


def build_summary_map(session: Session, mod_ids: list[int]) -> dict[int, str]:
    """读取每个 Mod 首选的简短摘要，供回答生成展示。"""
    return load_preferred_brief_summary_map(session, mod_ids)


def build_search_text_map(session: Session, mod_ids: list[int]) -> dict[int, str]:
    """拼接 brief/introduction 摘要，供 Python 相关性重排补充搜索文本。"""
    if not mod_ids:
        return {}
    rows = session.exec(
        select(ModSummary.mod_id, ModSummary.content)
        .where(
            ModSummary.mod_id.in_(mod_ids),
            ModSummary.summary_type.in_(["brief", "introduction"]),
        )
        .order_by(ModSummary.id.desc())
    ).all()
    text_parts: dict[int, list[str]] = {}
    for mod_id, content in rows:
        if not content:
            continue
        text_parts.setdefault(mod_id, []).append(content)
    return {mod_id: " ".join(parts) for mod_id, parts in text_parts.items()}
