import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from fastapi import HTTPException
from sqlalchemy import func, not_, or_
from sqlmodel import Session, select

from app.models.mod import Mod
from app.models.summary import ModSummary
from app.services.agent.planning.query_intent import detect_adult_constraint
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


@dataclass(frozen=True)
class InMemoryQueryPlan:
    """内存列表查询使用的精简计划，避免把数据库查询计划直接耦合到兜底搜索。"""

    intent: str
    keywords: list[str]
    tags: list[str]
    summary_languages: list[str]
    excluded_summary_languages: list[str]
    requirement_terms: list[str]
    compatibility_terms: list[str]
    exact_title: str
    version: str
    external_id: str
    source_url: str
    game: str
    author: str
    source: str
    sort: str
    limit: int
    adult_constraint: bool | None
    has_thumbnail: bool | None
    min_downloads: int | None
    min_endorsements: int | None
    min_views: int | None
    min_likes: int | None
    updated_since_days: int | None
    updated_after: str
    updated_before: str
    published_after: str
    published_before: str
    created_after: str
    created_before: str


def _query_without_scope(query: str) -> str:
    """内部辅助函数，用于拆分上层流程中的局部规则。"""
    return query.split("[scope]", 1)[0].strip()


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
    identity_conditions = _identity_conditions(plan, sources)
    if identity_conditions:
        conditions.append(or_(*identity_conditions))
    author = str(plan.get("author") or "").strip()
    if author:
        conditions.append(Mod.author.ilike(f"%{author}%"))
    min_downloads = _optional_min_metric(plan.get("min_downloads"))
    if min_downloads is not None:
        conditions.append(Mod.downloads >= min_downloads)
    min_endorsements = _optional_min_metric(plan.get("min_endorsements"))
    if min_endorsements is not None:
        conditions.append(Mod.endorsements >= min_endorsements)
    min_views = _optional_min_metric(plan.get("min_views"))
    if min_views is not None:
        conditions.append(Mod.views >= min_views)
    min_likes = _optional_min_metric(plan.get("min_likes"))
    if min_likes is not None:
        conditions.append(Mod.likes >= min_likes)
    updated_since_days = _optional_time_window(plan.get("updated_since_days"))
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
    category_conditions = [Mod.category.in_(categories)] if categories else []
    if category_conditions or keyword_conditions:
        if plan.get("category_match_mode") == "db_fuzzy" and category_conditions and keyword_conditions:
            conditions.append(or_(*(category_conditions + keyword_conditions)))
        else:
            if category_conditions:
                conditions.extend(category_conditions)
            if keyword_conditions:
                conditions.append(or_(*keyword_conditions))

    sort_field = plan.get("sort_field") or "relevance"
    sort_column = SORT_COLUMNS.get(sort_field, Mod.first_seen_at)
    sort_expr = sort_column.asc() if plan.get("sort_order") == "asc" else sort_column.desc()
    query_limit = RELEVANCE_PREFETCH_LIMIT if sort_field == "relevance" else int(plan["limit"])
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
    pattern = f"%{term}%"
    return or_(
        Mod.title.ilike(pattern),
        Mod.translated_title_zh.ilike(pattern),
        Mod.tags_json.ilike(pattern),
        Mod.original_summary.ilike(pattern),
        Mod.raw_json.ilike(pattern),
        ModSummary.content.ilike(pattern),
    )


def _identity_conditions(plan: dict[str, Any], sources: list[str]) -> list[Any]:
    conditions: list[Any] = []
    source_url = str(plan.get("source_url") or "").strip()
    if source_url:
        conditions.append(Mod.url == source_url)
        canonical_url = _url_without_query(source_url)
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
    if source_url and _url_without_query(source_url) == (mod.url or ""):
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
    fts_results = _query_mods_with_fts(session, plan)
    if fts_results:
        logger.info(
            "agent.retrieval.fts status=succeeded evidence_id=%s count=%s keywords=%s excluded_keywords=%s excluded_sources=%s games=%s game_domains=%s sources=%s categories=%s tags=%s summary_languages=%s excluded_summary_languages=%s requirement_terms=%s compatibility_terms=%s has_thumbnail=%s adult_content=%s min_downloads=%s min_endorsements=%s min_views=%s min_likes=%s updated_after=%s updated_before=%s published_after=%s published_before=%s created_after=%s created_before=%s external_id=%s source_url=%s",
            plan.get("evidence_id"),
            len(fts_results),
            plan.get("keywords") or [],
            plan.get("excluded_keywords") or [],
            plan.get("excluded_sources") or [],
            plan.get("games") or [],
            plan.get("game_domains") or [],
            plan.get("sources") or [],
            plan.get("categories") or [],
            plan.get("tags") or [],
            plan.get("summary_languages") or [],
            plan.get("excluded_summary_languages") or [],
            plan.get("requirement_terms") or [],
            plan.get("compatibility_terms") or [],
            plan.get("has_thumbnail"),
            plan.get("adult_content"),
            plan.get("min_downloads"),
            plan.get("min_endorsements"),
            plan.get("min_views"),
            plan.get("min_likes"),
            plan.get("updated_after"),
            plan.get("updated_before"),
            plan.get("published_after"),
            plan.get("published_before"),
            plan.get("created_after"),
            plan.get("created_before"),
            plan.get("external_id"),
            plan.get("source_url"),
        )
        return fts_results
    logger.info(
        "agent.retrieval.fts status=skipped evidence_id=%s count=0 keywords=%s excluded_keywords=%s excluded_sources=%s games=%s game_domains=%s sources=%s categories=%s tags=%s summary_languages=%s excluded_summary_languages=%s requirement_terms=%s compatibility_terms=%s has_thumbnail=%s adult_content=%s min_downloads=%s min_endorsements=%s min_views=%s min_likes=%s updated_after=%s updated_before=%s published_after=%s published_before=%s created_after=%s created_before=%s external_id=%s source_url=%s",
        plan.get("evidence_id"),
        plan.get("keywords") or [],
        plan.get("excluded_keywords") or [],
        plan.get("excluded_sources") or [],
        plan.get("games") or [],
        plan.get("game_domains") or [],
        plan.get("sources") or [],
        plan.get("categories") or [],
        plan.get("tags") or [],
        plan.get("summary_languages") or [],
        plan.get("excluded_summary_languages") or [],
        plan.get("requirement_terms") or [],
        plan.get("compatibility_terms") or [],
        plan.get("has_thumbnail"),
        plan.get("adult_content"),
        plan.get("min_downloads"),
        plan.get("min_endorsements"),
        plan.get("min_views"),
        plan.get("min_likes"),
        plan.get("updated_after"),
        plan.get("updated_before"),
        plan.get("published_after"),
        plan.get("published_before"),
        plan.get("created_after"),
        plan.get("created_before"),
        plan.get("external_id"),
        plan.get("source_url"),
    )
    statement = _build_mod_query_from_plan(plan)
    validate_agent_sql(statement, session)
    mods = session.exec(statement).all()
    logger.info(
        "agent.retrieval.sql status=succeeded evidence_id=%s count=%s sort=%s/%s excluded_keywords=%s excluded_sources=%s games=%s game_domains=%s sources=%s categories=%s tags=%s summary_languages=%s excluded_summary_languages=%s requirement_terms=%s compatibility_terms=%s has_thumbnail=%s adult_content=%s min_downloads=%s min_endorsements=%s min_views=%s min_likes=%s updated_after=%s updated_before=%s published_after=%s published_before=%s created_after=%s created_before=%s external_id=%s source_url=%s",
        plan.get("evidence_id"),
        len(mods),
        plan.get("sort_field") or "relevance",
        plan.get("sort_order") or "desc",
        plan.get("excluded_keywords") or [],
        plan.get("excluded_sources") or [],
        plan.get("games") or [],
        plan.get("game_domains") or [],
        plan.get("sources") or [],
        plan.get("categories") or [],
        plan.get("tags") or [],
        plan.get("summary_languages") or [],
        plan.get("excluded_summary_languages") or [],
        plan.get("requirement_terms") or [],
        plan.get("compatibility_terms") or [],
        plan.get("has_thumbnail"),
        plan.get("adult_content"),
        plan.get("min_downloads"),
        plan.get("min_endorsements"),
        plan.get("min_views"),
        plan.get("min_likes"),
        plan.get("updated_after"),
        plan.get("updated_before"),
        plan.get("published_after"),
        plan.get("published_before"),
        plan.get("created_after"),
        plan.get("created_before"),
        plan.get("external_id"),
        plan.get("source_url"),
    )
    search_text_by_mod = build_search_text_map(session, [mod.id for mod in mods if mod.id is not None])
    if plan.get("sort_field") == "relevance":
        scored = [
            (max(score_mod(query, mod, search_text_by_mod.get(mod.id or 0, "")), 1) + _identity_score(plan, mod), mod)
            for mod in mods
            if mod.id is not None
        ]
        scored.sort(key=lambda item: (item[0], item[1].first_seen_at), reverse=True)
        return scored[: int(plan["limit"])]
    return [
        (max(score_mod(query, mod, search_text_by_mod.get(mod.id or 0, "")), 1) + _identity_score(plan, mod), mod)
        for mod in mods
        if mod.id is not None
    ][: int(plan["limit"])]


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
        limit=int(plan.get("limit") or DEFAULT_AGENT_LIMIT),
    )
    return [(item.score, item.mod) for item in results if item.mod.id is not None]


def _coerce_in_memory_plan(query: str, plan: dict) -> InMemoryQueryPlan:
    """把前端或 LLM 传入的宽松 dict 收敛成内存过滤需要的稳定字段。"""

    try:
        limit = int(plan.get("limit") or 8)
    except (TypeError, ValueError):
        limit = 8
    return InMemoryQueryPlan(
        intent=str(plan.get("intent") or "").strip().lower(),
        keywords=[str(x).strip().lower() for x in (plan.get("keywords") or []) if str(x).strip()],
        tags=_string_list(plan.get("tags")),
        summary_languages=_string_list(plan.get("summary_languages")),
        excluded_summary_languages=_string_list(plan.get("excluded_summary_languages")),
        requirement_terms=_string_list(plan.get("requirement_terms")),
        compatibility_terms=_string_list(plan.get("compatibility_terms")),
        exact_title=str(plan.get("exact_title") or "").strip().lower(),
        version=str(plan.get("version") or "").strip().lower(),
        external_id=str(plan.get("external_id") or "").strip().lower(),
        source_url=str(plan.get("source_url") or "").strip().lower(),
        game=str(plan.get("game") or "").strip().lower(),
        author=str(plan.get("author") or "").strip().lower(),
        source=str(plan.get("source") or "").strip().lower(),
        sort=str(plan.get("sort") or "").strip().lower() or "relevance",
        limit=max(1, min(20, limit)),
        adult_constraint=detect_adult_constraint(query),
        has_thumbnail=plan.get("has_thumbnail") if isinstance(plan.get("has_thumbnail"), bool) else None,
        min_downloads=_optional_min_metric(plan.get("min_downloads")),
        min_endorsements=_optional_min_metric(plan.get("min_endorsements")),
        min_views=_optional_min_metric(plan.get("min_views")),
        min_likes=_optional_min_metric(plan.get("min_likes")),
        updated_since_days=_optional_time_window(plan.get("updated_since_days")),
        updated_after=str(plan.get("updated_after") or "").strip(),
        updated_before=str(plan.get("updated_before") or "").strip(),
        published_after=str(plan.get("published_after") or "").strip(),
        published_before=str(plan.get("published_before") or "").strip(),
        created_after=str(plan.get("created_after") or "").strip(),
        created_before=str(plan.get("created_before") or "").strip(),
    )


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


def _mod_haystack(mod: Mod, extra_text_by_mod: dict[int, str] | None = None) -> str:
    """合并 Mod 自身字段和摘要文本，供关键词过滤和加分共用。"""

    haystack = " ".join(
        [
            mod.title or "",
            mod.translated_title_zh or "",
            mod.game or "",
            mod.author or "",
            mod.category or "",
            mod.tags_json or "",
            mod.original_summary or "",
        ]
    ).lower()
    extra_text = (extra_text_by_mod or {}).get(mod.id or 0, "").lower()
    return f"{haystack} {extra_text}".strip()


def _has_explicit_constraints(plan: InMemoryQueryPlan) -> bool:
    """显式约束无命中时返回空，避免悄悄退回到全量结果造成误导。"""

    return bool(
        plan.game
        or plan.author
        or plan.source
        or plan.keywords
        or plan.tags
        or plan.summary_languages
        or plan.requirement_terms
        or plan.compatibility_terms
        or plan.exact_title
        or plan.version
        or plan.external_id
        or plan.source_url
        or plan.adult_constraint is not None
        or plan.has_thumbnail is not None
        or plan.min_downloads is not None
        or plan.min_endorsements is not None
        or plan.min_views is not None
        or plan.min_likes is not None
        or plan.updated_since_days is not None
        or plan.updated_after
        or plan.updated_before
        or plan.published_after
        or plan.published_before
        or plan.created_after
        or plan.created_before
    )


def _matches_in_memory_plan(
    mod: Mod,
    plan: InMemoryQueryPlan,
    extra_text_by_mod: dict[int, str] | None = None,
) -> bool:
    """判断单个 Mod 是否满足内存查询计划中的来源、游戏、作者和关键词约束。"""

    if mod.id is None:
        return False
    if plan.adult_constraint is not None and bool(mod.adult_content) != plan.adult_constraint:
        return False
    if plan.has_thumbnail is not None and bool((mod.thumbnail_url or "").strip()) != plan.has_thumbnail:
        return False
    if plan.game and plan.game not in (mod.game or "").lower():
        return False
    if plan.author and plan.author not in (mod.author or "").lower():
        return False
    if plan.source and plan.source not in (mod.source or "").lower():
        return False
    if plan.min_downloads is not None and (mod.downloads is None or mod.downloads < plan.min_downloads):
        return False
    if plan.min_endorsements is not None and (
        mod.endorsements is None or mod.endorsements < plan.min_endorsements
    ):
        return False
    if plan.min_views is not None and (mod.views is None or mod.views < plan.min_views):
        return False
    if plan.min_likes is not None and (mod.likes is None or mod.likes < plan.min_likes):
        return False
    if plan.updated_since_days is not None and not _mod_within_time_window(mod, plan.updated_since_days):
        return False
    if not _mod_matches_absolute_dates(mod, plan):
        return False
    if plan.tags and not _mod_matches_tags(mod, plan.tags):
        return False
    if plan.summary_languages and not _mod_has_summary_language(mod, plan.summary_languages, extra_text_by_mod):
        return False
    if plan.excluded_summary_languages and _mod_has_summary_language(
        mod,
        plan.excluded_summary_languages,
        extra_text_by_mod,
    ):
        return False
    if plan.requirement_terms and not _mod_matches_requirement_terms(mod, plan.requirement_terms, extra_text_by_mod):
        return False
    if plan.compatibility_terms and not _mod_matches_compatibility_terms(mod, plan.compatibility_terms, extra_text_by_mod):
        return False
    if plan.exact_title and plan.exact_title not in {_title_key(mod.title), _title_key(mod.translated_title_zh)}:
        return False
    if plan.version and plan.version not in (mod.version or "").lower():
        return False
    if (plan.external_id or plan.source_url) and not _matches_identity(mod, plan):
        return False
    haystack = _mod_haystack(mod, extra_text_by_mod)
    return not plan.keywords or any(keyword in haystack for keyword in plan.keywords)


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        values = [value]
    elif isinstance(value, list | tuple | set):
        values = list(value)
    else:
        return []
    return [str(item).strip() for item in values if str(item).strip()]


def _matches_identity(mod: Mod, plan: InMemoryQueryPlan) -> bool:
    mod_source = (mod.source or "").lower()
    mod_external_id = (mod.external_id or "").lower()
    mod_url = (mod.url or "").lower()
    if plan.source_url and plan.source_url == mod_url:
        return True
    if plan.source_url and _url_without_query(plan.source_url) == mod_url:
        return True
    if not plan.external_id:
        return False
    if mod_source:
        aliases = [value.lower() for value in external_id_aliases(mod_source, plan.external_id, plan.source_url)]
        return mod_external_id in aliases or (
            mod_source == "loverslab"
            and re.fullmatch(r"\d{2,12}", plan.external_id)
            and mod_external_id.endswith(f":{plan.external_id}")
        )
    return mod_external_id == plan.external_id


def _url_without_query(url: str) -> str:
    parsed = urlsplit(str(url or "").strip())
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def _mod_matches_tags(mod: Mod, tags: list[str]) -> bool:
    tag_text = str(mod.tags_json or "").lower()
    return all(str(tag).strip().lower() in tag_text for tag in tags if str(tag).strip())


def _title_key(value: str | None) -> str:
    return " ".join(str(value or "").lower().split())


def _mod_has_summary_language(
    mod: Mod,
    summary_languages: list[str],
    extra_text_by_mod: dict[int, str] | None = None,
) -> bool:
    if not summary_languages:
        return True
    # In-memory fallback cannot see ModSummary rows directly; callers pass
    # preferred summary text only for mods that have a matching summary.
    return bool((extra_text_by_mod or {}).get(mod.id or 0))


def _mod_matches_requirement_terms(
    mod: Mod,
    requirement_terms: list[str],
    extra_text_by_mod: dict[int, str] | None = None,
) -> bool:
    haystack = " ".join(
        [
            mod.title or "",
            mod.translated_title_zh or "",
            mod.tags_json or "",
            mod.original_summary or "",
            mod.raw_json or "",
            (extra_text_by_mod or {}).get(mod.id or 0, ""),
        ]
    ).lower()
    return all(str(term).strip().lower() in haystack for term in requirement_terms if str(term).strip())


def _mod_matches_compatibility_terms(
    mod: Mod,
    compatibility_terms: list[str],
    extra_text_by_mod: dict[int, str] | None = None,
) -> bool:
    haystack = " ".join(
        [
            mod.title or "",
            mod.translated_title_zh or "",
            mod.tags_json or "",
            mod.original_summary or "",
            mod.raw_json or "",
            (extra_text_by_mod or {}).get(mod.id or 0, ""),
        ]
    ).lower()
    return all(str(term).strip().lower() in haystack for term in compatibility_terms if str(term).strip())


def _mod_within_time_window(mod: Mod, days: int) -> bool:
    cutoff = datetime.now(UTC) - timedelta(days=days)
    for raw in [mod.updated_at_remote, mod.published_at_remote]:
        if not raw:
            continue
        try:
            parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except ValueError:
            continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        if parsed.astimezone(UTC) >= cutoff:
            return True
    return False


def _mod_matches_absolute_dates(mod: Mod, plan: InMemoryQueryPlan) -> bool:
    checks = [
        (mod.updated_at_remote, plan.updated_after, True),
        (mod.updated_at_remote, plan.updated_before, False),
        (mod.published_at_remote, plan.published_after, True),
        (mod.published_at_remote, plan.published_before, False),
        (mod.created_at_remote, plan.created_after, True),
        (mod.created_at_remote, plan.created_before, False),
    ]
    for raw_value, boundary, is_after in checks:
        if not boundary:
            continue
        if not raw_value:
            return False
        value = str(raw_value)
        if is_after and value < boundary:
            return False
        if not is_after and value > boundary:
            return False
    return True


def _filter_mods_for_plan(
    mods: list[Mod],
    plan: InMemoryQueryPlan,
    extra_text_by_mod: dict[int, str] | None = None,
) -> list[Mod]:
    """按查询计划过滤候选列表，调用方负责处理空结果是否允许兜底。"""

    return [mod for mod in mods if _matches_in_memory_plan(mod, plan, extra_text_by_mod)]


def _candidate_mods(mods: list[Mod], filtered: list[Mod], plan: InMemoryQueryPlan) -> list[Mod]:
    """根据是否存在显式约束决定空过滤结果能否回退到全量候选。"""

    if filtered:
        return filtered
    return [] if _has_explicit_constraints(plan) else mods


def _sort_recent_mods(mods: list[Mod], plan: InMemoryQueryPlan) -> list[tuple[int, Mod]]:
    """recent 意图只关心时间顺序，固定返回分数 1 保持旧响应结构。"""

    candidate_mods = sorted(
        mods,
        key=lambda mod: (mod.updated_at_remote or "", mod.first_seen_at or ""),
        reverse=True,
    )
    if plan.adult_constraint is not None:
        candidate_mods = [mod for mod in candidate_mods if bool(mod.adult_content) == plan.adult_constraint]
    return [(1, mod) for mod in candidate_mods[: plan.limit] if mod.id is not None]


def _score_candidate_mods(
    mods: list[Mod],
    query: str,
    plan: InMemoryQueryPlan,
    extra_text_by_mod: dict[int, str] | None = None,
) -> list[tuple[int, Mod]]:
    """对候选 Mod 打分；关键词命中摘要文本时也计入相关性。"""

    scored = []
    for mod in mods:
        score = score_mod(query, mod)
        if plan.keywords:
            haystack = _mod_haystack(mod, extra_text_by_mod)
            score += sum(1 for keyword in plan.keywords if keyword and keyword in haystack)
        if score <= 0 and plan.keywords:
            score = 1
        if score > 0:
            scored.append((score, mod))
    return scored


def _sort_scored_mods(scored: list[tuple[int, Mod]], plan: InMemoryQueryPlan) -> list[tuple[int, Mod]]:
    """按用户要求的排序方式裁剪结果；默认仍按相关性优先。"""

    if plan.sort == "updated":
        scored.sort(key=lambda item: ((item[1].updated_at_remote or ""), item[0]), reverse=True)
    elif plan.sort == "first_seen":
        scored.sort(key=lambda item: (item[1].first_seen_at, item[0]), reverse=True)
    else:
        scored.sort(key=lambda item: (item[0], item[1].first_seen_at), reverse=True)
    return scored[: plan.limit]


def apply_query_plan(
    mods: list[Mod],
    query: str,
    plan: dict | None,
    extra_text_by_mod: dict[int, str] | None = None,
) -> list[tuple[int, Mod]]:
    """处理当前模块的业务逻辑并返回结果。"""
    if not mods:
        return []
    adult_constraint = detect_adult_constraint(query)
    if not isinstance(plan, dict):
        scored = []
        for mod in mods:
            if mod.id is None:
                continue
            if adult_constraint is not None and bool(mod.adult_content) != adult_constraint:
                continue
            score = score_mod(query, mod)
            if score > 0:
                scored.append((score, mod))
        scored.sort(key=lambda item: (item[0], item[1].first_seen_at), reverse=True)
        return scored[:8]

    in_memory_plan = _coerce_in_memory_plan(query, plan)
    filtered = _filter_mods_for_plan(mods, in_memory_plan, extra_text_by_mod)
    candidate_mods = _candidate_mods(mods, filtered, in_memory_plan)

    if in_memory_plan.intent == "recent":
        return _sort_recent_mods(candidate_mods, in_memory_plan)

    scored = _score_candidate_mods(candidate_mods, query, in_memory_plan, extra_text_by_mod)
    return _sort_scored_mods(scored, in_memory_plan)


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
