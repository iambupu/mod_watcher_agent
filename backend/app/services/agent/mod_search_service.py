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
    """处理当前模块的业务逻辑并返回结果。"""
    return text_score(
        query,
        [mod.title, mod.translated_title_zh, mod.game, mod.author, mod.category, mod.original_summary, extra_text],
        [mod.category] if mod.category else None,
    )


def _build_mod_query_from_plan(plan: dict[str, Any]):
    """构建内部流程需要的数据结构。"""
    conditions = [Mod.ignored == False]  # noqa: E712
    game_values = plan.get("games") or []
    game_domain_values = plan.get("game_domains") or []
    if game_values or game_domain_values:
        game_conditions = []
        if game_values:
            game_conditions.append(Mod.game.in_(game_values))
        if game_domain_values:
            game_conditions.append(Mod.game_domain.in_(game_domain_values))
        conditions.append(or_(*game_conditions))

    categories = plan.get("categories") or []

    adult_content = plan.get("adult_content")
    if isinstance(adult_content, bool):
        conditions.append(Mod.adult_content == adult_content)
    has_thumbnail = plan.get("has_thumbnail")
    if isinstance(has_thumbnail, bool):
        thumbnail_condition = Mod.thumbnail_url.is_not(None) if has_thumbnail else Mod.thumbnail_url.is_(None)
        if has_thumbnail:
            conditions.append(thumbnail_condition)
            conditions.append(Mod.thumbnail_url != "")
        else:
            conditions.append(or_(thumbnail_condition, Mod.thumbnail_url == ""))

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
    min_downloads = optional_min_metric(plan.get("min_downloads"))
    if min_downloads is not None:
        conditions.append(Mod.downloads >= min_downloads)
    min_endorsements = optional_min_metric(plan.get("min_endorsements"))
    if min_endorsements is not None:
        conditions.append(Mod.endorsements >= min_endorsements)
    min_views = optional_min_metric(plan.get("min_views"))
    if min_views is not None:
        conditions.append(Mod.views >= min_views)
    min_likes = optional_min_metric(plan.get("min_likes"))
    if min_likes is not None:
        conditions.append(Mod.likes >= min_likes)
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
        if not value:
            continue
        conditions.append(column >= value if key.endswith("_after") else column <= value)
    for tag in _string_list(plan.get("tags")):
        conditions.append(Mod.tags_json.ilike(f"%{tag}%"))
    summary_languages = _string_list(plan.get("summary_languages"))
    if summary_languages:
        conditions.append(ModSummary.language.in_(summary_languages))
        conditions.append(ModSummary.summary_type.in_(["brief", "introduction"]))
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
    if category_conditions or keyword_conditions:
        if plan.get("category_match_mode") == "db_fuzzy" and category_conditions and keyword_conditions:
            conditions.append(or_(*(category_conditions + keyword_conditions)))
        else:
            if category_conditions:
                conditions.extend(category_conditions)
            if keyword_conditions:
                if str(plan.get("keyword_match_mode") or "").strip().lower() == "all":
                    conditions.extend(keyword_conditions)
                else:
                    conditions.append(or_(*keyword_conditions))

    sort_field = plan.get("sort_field") or "relevance"
    sort_column = SORT_COLUMNS.get(sort_field, Mod.first_seen_at)
    sort_expr = sort_column.asc() if plan.get("sort_order") == "asc" else sort_column.desc()
    result_limit = _result_limit(plan)
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
    """内部辅助函数，用于拆分上层流程中的局部规则。"""
    keywords = [str(value).strip().lower() for value in (plan.get("keywords") or []) if str(value).strip()]
    semantic = semantic_query(" ".join(keywords), categories)
    return unique_terms([*keywords, *semantic.expanded_terms])


def _keyword_condition(keyword: str):
    """内部辅助函数，用于拆分上层流程中的局部规则。"""
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
    """校验输入是否符合业务约束。"""
    compiled = statement.compile(bind=session.get_bind(), compile_kwargs={"literal_binds": False})
    sql = str(compiled).strip()
    normalized = re.sub(r"--.*?\n|/\*.*?\*/", "", sql, flags=re.DOTALL)
    normalized = re.sub(r"\s+", " ", normalized).strip().lower()
    forbidden = [" insert ", " update ", " delete ", " drop ", " alter ", " pragma "]
    if not re.match(r"^select\b", normalized) or " from mods" not in normalized or any(token in normalized for token in forbidden):
        raise HTTPException(status_code=500, detail="Agent SQL validation failed")
    return sql


def query_mods_with_plan(session: Session, query: str, plan: dict[str, Any]) -> list[tuple[int, Mod]]:
    """处理当前模块的业务逻辑并返回结果。"""
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
    return open_discovery_result_limit(plan, default_limit=DEFAULT_AGENT_LIMIT)


def _category_hint_score(plan: dict[str, Any], mod: Mod) -> int:
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
    return " ".join(str(value or "").lower().split())


def build_summary_map(session: Session, mod_ids: list[int]) -> dict[int, str]:
    """构建后续流程需要的数据结构。"""
    return load_preferred_brief_summary_map(session, mod_ids)


def build_search_text_map(session: Session, mod_ids: list[int]) -> dict[int, str]:
    """构建后续流程需要的数据结构。"""
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
