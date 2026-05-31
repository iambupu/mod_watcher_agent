import logging
import re
from collections.abc import Iterable

from app.models.mod import Mod
from app.services.agent.list_utils import string_list
from app.services.agent.ranking.fusion import fuse_duplicate_results
from app.services.agent.search_types import SearchPlan, SearchResult
from app.services.agent.semantic_search import distinctive_query_terms
from app.utils.boolean import parse_bool
from app.utils.numeric import safe_nonnegative_int

logger = logging.getLogger(__name__)


def merge_results(*groups: Iterable[SearchResult]) -> list[SearchResult]:
    materialized_groups = [list(group) for group in groups]
    by_key: dict[tuple[str, str], list[SearchResult]] = {}
    for group in materialized_groups:
        for item in group:
            key = _merge_key(item)
            by_key.setdefault(key, []).append(item)
    merged = [fuse_duplicate_results(items) for items in by_key.values()]
    logger.info(
        "agent.fusion status=succeeded input=%s output=%s duplicate_groups=%s",
        sum(len(group) for group in materialized_groups),
        len(merged),
        sum(1 for items in by_key.values() if len(items) > 1),
    )
    return merged


def _merge_key(item: SearchResult) -> tuple[str, str]:
    source = str(item.mod.source or "").strip().lower()
    external_id = str(item.mod.external_id or "").strip()
    if external_id:
        return (source, f"id:{external_id}")
    url = str(item.mod.url or "").strip()
    if url:
        return (source, f"url:{url}")
    return (source, f"title:{_title_key(item.mod.title)}")


def sort_results(results: list[SearchResult], plan: SearchPlan, query_plan: dict | None = None) -> list[SearchResult]:
    reverse = plan.sort_order != "asc"
    logger.info("agent.ranking status=succeeded strategy=%s order=%s input=%s", plan.sort_field, plan.sort_order, len(results))
    if plan.sort_field == "downloads":
        return sorted(results, key=lambda item: (safe_nonnegative_int(item.mod.downloads), item.score), reverse=reverse)
    if plan.sort_field == "endorsements":
        return sorted(results, key=lambda item: (safe_nonnegative_int(item.mod.endorsements), item.score), reverse=reverse)
    if plan.sort_field == "relevance":
        return sorted(
            results,
            key=lambda item: (
                item.score + _category_hint_score(item, plan) + _semantic_hint_score(item.mod, query_plan),
                item.mod.first_seen_at,
            ),
            reverse=reverse,
        )
    return sorted(results, key=lambda item: ((item.mod.updated_at_remote or ""), item.score), reverse=reverse)


def filter_by_distinctive_terms(
    results: list[SearchResult],
    query: str,
    *,
    fallback_terms: list[str] | None = None,
) -> list[SearchResult]:
    terms = distinctive_query_terms(query)
    if not terms:
        fallback = [
            term
            for term in (fallback_terms or [])
            if re.fullmatch(r"[a-z0-9][a-z0-9_-]*", term)
        ]
        if not fallback:
            return results
        return [item for item in results if _mod_contains_any_term(item.mod, fallback)]
    if not terms:
        return results
    min_hits = _required_term_hits(len(terms))
    return [item for item in results if _mod_term_hit_count(item.mod, terms) >= min_hits]


def filter_excluded_titles(results: list[SearchResult], excluded_titles: list[str] | None) -> list[SearchResult]:
    excluded = {_title_key(title) for title in (excluded_titles or []) if _title_key(title)}
    if not excluded:
        return results
    return [item for item in results if _title_key(item.mod.title) not in excluded]


def filter_excluded_keywords(results: list[SearchResult], excluded_keywords: list[str] | None) -> list[SearchResult]:
    terms = [str(term).strip().lower() for term in (excluded_keywords or []) if str(term).strip()]
    if not terms:
        return results
    return [item for item in results if not any(term in _mod_haystack(item.mod) for term in terms)]


def filter_by_adult_content(results: list[SearchResult], plan: SearchPlan) -> list[SearchResult]:
    if not isinstance(plan.adult_content, bool):
        return results
    return [item for item in results if parse_bool(item.mod.adult_content) == plan.adult_content]


def filter_semantic_soft_rejects(results: list[SearchResult], query_plan: dict | None) -> list[SearchResult]:
    if len(results) <= 1 or not isinstance(query_plan, dict):
        return results
    anchors = {
        value.lower()
        for value in [
            *string_list(query_plan.get("_agent_ranking_semantic_anchors")),
            *string_list(query_plan.get("_agent_semantic_anchors")),
        ]
    }
    domains = {
        value.lower()
        for value in [
            *string_list(query_plan.get("_agent_ranking_semantic_domains")),
            *string_list(query_plan.get("_agent_semantic_domains")),
        ]
    }
    if "roleplay" not in anchors and "mechanics" not in domains:
        return results
    core = [item for item in results if _roleplay_semantic_score(item.mod) > 0]
    if not core:
        return results
    return [item for item in results if not _looks_like_visual_support_without_roleplay(item.mod)]


def filter_by_exact_title(results: list[SearchResult], exact_title: str | None) -> list[SearchResult]:
    expected = _title_key(exact_title)
    if not expected:
        return results
    filtered = [
        item
        for item in results
        if expected in {_title_key(item.mod.title), _title_key(item.mod.translated_title_zh)}
    ]
    logger.info(
        "agent.filter.exact_title status=succeeded exact_title=%s input=%s output=%s",
        exact_title,
        len(results),
        len(filtered),
    )
    return filtered


def _roleplay_semantic_score(mod: Mod) -> int:
    haystack = _mod_haystack(mod)
    score = _term_bonus(haystack, ["roleplay", "role play", "character progression", "identity route"], 2)
    score += _term_bonus(haystack, ["framework", "gameplay", "mechanic", "system"], 1)
    return score


def _looks_like_visual_support_without_roleplay(mod: Mod) -> bool:
    haystack = _mod_haystack(mod)
    visual = any(term in haystack for term in ["outfit", "clothing", "armor", "armour", "dress", "bodysuit"])
    if not visual:
        return False
    return not any(
        term in haystack
        for term in ["roleplay", "role play", "character progression", "identity route", "roleplaying framework"]
    )


def _mod_haystack(mod: Mod) -> str:
    return " ".join(
        str(value or "")
        for value in [
            mod.title,
            mod.author,
            mod.category,
            mod.game,
            mod.game_domain,
            mod.tags_json,
            mod.original_summary,
        ]
    ).lower()


def _category_hint_score(result: SearchResult, plan: SearchPlan) -> int:
    hints = {str(value).strip().lower() for value in (plan.category_hints or []) if str(value).strip()}
    if not hints:
        return 0
    category = str(result.mod.category or "").strip().lower()
    return 2 if category in hints else 0


def _semantic_hint_score(mod: Mod, query_plan: dict | None) -> int:
    """用语义锚点做轻量排序加权；强相关判断仍交给 Candidate Semantic Judge。"""
    if not isinstance(query_plan, dict):
        return 0
    anchors = {
        value.lower()
        for value in [
            *string_list(query_plan.get("_agent_ranking_semantic_anchors")),
            *string_list(query_plan.get("_agent_semantic_anchors")),
        ]
    }
    domains = {
        value.lower()
        for value in [
            *string_list(query_plan.get("_agent_ranking_semantic_domains")),
            *string_list(query_plan.get("_agent_semantic_domains")),
        ]
    }
    if not anchors and not domains:
        return 0
    haystack = _mod_haystack(mod)
    category = str(mod.category or "").strip().lower()
    score = 0
    if "roleplay" in anchors or "mechanics" in domains:
        score += _term_bonus(haystack, ["roleplay", "role play", "rp", "character progression", "scenario", "quest"], 6)
        score += _term_bonus(haystack, ["framework", "gameplay", "mechanic", "system"], 3)
        if category in {"gameplay", "quests and adventures"}:
            score += 4
    if "pregnancy" in anchors:
        score += _term_bonus(haystack, ["pregnancy", "pregnant", "fertility", "breeding", "birth"], 6)
    if "framework" in anchors:
        score += _term_bonus(haystack, ["framework", "system", "core"], 5)
    if "content_type" in domains or anchors & {"outfit", "clothing", "armor"}:
        score += _term_bonus(haystack, ["outfit", "clothing", "armor", "armour", "dress", "bodysuit"], 5)
        if category in {"armor", "armour", "clothing"}:
            score += 3
    return score


def _term_bonus(haystack: str, terms: list[str], value: int) -> int:
    return value if any(term in haystack for term in terms) else 0


def _mod_contains_any_term(mod: Mod, terms: list[str]) -> bool:
    haystack = _mod_haystack(mod)
    return any(term in haystack for term in terms)


def _mod_term_hit_count(mod: Mod, terms: list[str]) -> int:
    haystack = _mod_haystack(mod)
    return sum(1 for term in terms if term in haystack)


def _required_term_hits(term_count: int) -> int:
    if term_count <= 1:
        return 1
    if term_count <= 3:
        return term_count
    return 2


def _title_key(title: str | None) -> str:
    return " ".join(str(title or "").lower().split())
