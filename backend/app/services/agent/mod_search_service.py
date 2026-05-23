import re
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException
from sqlalchemy import or_
from sqlmodel import Session, select

from app.models.mod import Mod
from app.models.summary import ModSummary
from app.services.agent.query_planner import (
    RELEVANCE_PREFETCH_LIMIT,
    SORT_COLUMNS,
    detect_adult_constraint,
)
from app.services.agent.semantic_search import semantic_query, text_score, unique_terms
from app.services.summary_service import load_preferred_brief_summary_map


@dataclass(frozen=True)
class InMemoryQueryPlan:
    """内存列表查询使用的精简计划，避免把数据库查询计划直接耦合到兜底搜索。"""

    intent: str
    keywords: list[str]
    game: str
    author: str
    source: str
    sort: str
    limit: int
    adult_constraint: bool | None


def _query_without_scope(query: str) -> str:
    """内部辅助函数，用于拆分上层流程中的局部规则。"""
    return query.split("[scope]", 1)[0].strip()


def score_mod(query: str, mod: Mod, extra_text: str = "") -> int:
    """处理当前模块的业务逻辑并返回结果。"""
    return text_score(
        query,
        [mod.title, mod.game, mod.author, mod.category, mod.original_summary, extra_text],
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

    sources = plan.get("sources") or []
    if sources:
        conditions.append(Mod.source.in_(sources))

    keywords = _db_fuzzy_keywords(plan, categories)
    keyword_conditions = [_keyword_condition(keyword) for keyword in keywords]
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
        Mod.title.ilike(pattern),
        Mod.author.ilike(pattern),
        Mod.category.ilike(pattern),
        Mod.original_summary.ilike(pattern),
        ModSummary.content.ilike(pattern),
    )


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
    statement = _build_mod_query_from_plan(plan)
    validate_agent_sql(statement, session)
    mods = session.exec(statement).all()
    search_text_by_mod = build_search_text_map(session, [mod.id for mod in mods if mod.id is not None])
    if plan.get("sort_field") == "relevance":
        scored = [
            (max(score_mod(query, mod, search_text_by_mod.get(mod.id or 0, "")), 1), mod)
            for mod in mods
            if mod.id is not None
        ]
        scored.sort(key=lambda item: (item[0], item[1].first_seen_at), reverse=True)
        return scored[: int(plan["limit"])]
    return [
        (max(score_mod(query, mod, search_text_by_mod.get(mod.id or 0, "")), 1), mod)
        for mod in mods
        if mod.id is not None
    ][: int(plan["limit"])]


def _coerce_in_memory_plan(query: str, plan: dict) -> InMemoryQueryPlan:
    """把前端或 LLM 传入的宽松 dict 收敛成内存过滤需要的稳定字段。"""

    try:
        limit = int(plan.get("limit") or 8)
    except (TypeError, ValueError):
        limit = 8
    return InMemoryQueryPlan(
        intent=str(plan.get("intent") or "").strip().lower(),
        keywords=[str(x).strip().lower() for x in (plan.get("keywords") or []) if str(x).strip()],
        game=str(plan.get("game") or "").strip().lower(),
        author=str(plan.get("author") or "").strip().lower(),
        source=str(plan.get("source") or "").strip().lower(),
        sort=str(plan.get("sort") or "").strip().lower() or "relevance",
        limit=max(1, min(20, limit)),
        adult_constraint=detect_adult_constraint(query),
    )


def _mod_haystack(mod: Mod, extra_text_by_mod: dict[int, str] | None = None) -> str:
    """合并 Mod 自身字段和摘要文本，供关键词过滤和加分共用。"""

    haystack = " ".join(
        [mod.title or "", mod.game or "", mod.author or "", mod.category or "", mod.original_summary or ""]
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
        or plan.adult_constraint is not None
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
    if plan.game and plan.game not in (mod.game or "").lower():
        return False
    if plan.author and plan.author not in (mod.author or "").lower():
        return False
    if plan.source and plan.source not in (mod.source or "").lower():
        return False
    haystack = _mod_haystack(mod, extra_text_by_mod)
    return not plan.keywords or any(keyword in haystack for keyword in plan.keywords)


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
