import logging
import re
from collections.abc import Iterable

from app.models.mod import Mod
from app.services.agent.ranking.fusion import fuse_duplicate_results
from app.services.agent.search_types import SearchPlan, SearchResult
from app.services.agent.semantic_search import distinctive_query_terms

logger = logging.getLogger(__name__)


def merge_results(*groups: Iterable[SearchResult]) -> list[SearchResult]:
    materialized_groups = [list(group) for group in groups]
    by_key: dict[tuple[str, str], list[SearchResult]] = {}
    for group in materialized_groups:
        for item in group:
            key = (item.mod.source, item.mod.external_id)
            by_key.setdefault(key, []).append(item)
    merged = [fuse_duplicate_results(items) for items in by_key.values()]
    logger.info(
        "agent.fusion status=succeeded input=%s output=%s duplicate_groups=%s",
        sum(len(group) for group in materialized_groups),
        len(merged),
        sum(1 for items in by_key.values() if len(items) > 1),
    )
    return merged


def sort_results(results: list[SearchResult], plan: SearchPlan) -> list[SearchResult]:
    reverse = plan.sort_order != "asc"
    logger.info("agent.ranking status=succeeded strategy=%s order=%s input=%s", plan.sort_field, plan.sort_order, len(results))
    if plan.sort_field == "downloads":
        return sorted(results, key=lambda item: (item.mod.downloads or 0, item.score), reverse=reverse)
    if plan.sort_field == "endorsements":
        return sorted(results, key=lambda item: (item.mod.endorsements or 0, item.score), reverse=reverse)
    if plan.sort_field == "relevance":
        return sorted(results, key=lambda item: (item.score, item.mod.first_seen_at), reverse=reverse)
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
    return [item for item in results if bool(item.mod.adult_content) == plan.adult_content]


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


def _mod_contains_terms(mod: Mod, terms: list[str]) -> bool:
    haystack = _mod_haystack(mod)
    return all(term in haystack for term in terms)


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
