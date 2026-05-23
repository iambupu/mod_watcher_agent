from collections.abc import Iterable

from app.models.mod import Mod
from app.services.agent.search_types import SearchPlan, SearchResult
from app.services.agent.semantic_search import distinctive_query_terms


def merge_results(*groups: Iterable[SearchResult]) -> list[SearchResult]:
    by_key: dict[tuple[str, str], SearchResult] = {}
    for group in groups:
        for item in group:
            key = (item.mod.source, item.mod.external_id)
            current = by_key.get(key)
            if current is None or item.score > current.score:
                by_key[key] = item
    return list(by_key.values())


def sort_results(results: list[SearchResult], plan: SearchPlan) -> list[SearchResult]:
    reverse = plan.sort_order != "asc"
    if plan.sort_field == "downloads":
        return sorted(results, key=lambda item: (item.mod.downloads or 0, item.score), reverse=reverse)
    if plan.sort_field == "endorsements":
        return sorted(results, key=lambda item: (item.mod.endorsements or 0, item.score), reverse=reverse)
    if plan.sort_field == "relevance":
        return sorted(results, key=lambda item: (item.score, item.mod.first_seen_at), reverse=reverse)
    return sorted(results, key=lambda item: ((item.mod.updated_at_remote or ""), item.score), reverse=reverse)


def filter_by_distinctive_terms(results: list[SearchResult], query: str) -> list[SearchResult]:
    terms = distinctive_query_terms(query)
    if not terms:
        return results
    return [item for item in results if _mod_contains_terms(item.mod, terms)]


def filter_by_adult_content(results: list[SearchResult], plan: SearchPlan) -> list[SearchResult]:
    if not isinstance(plan.adult_content, bool):
        return results
    return [item for item in results if bool(item.mod.adult_content) == plan.adult_content]


def _mod_contains_terms(mod: Mod, terms: list[str]) -> bool:
    haystack = " ".join(
        str(value or "")
        for value in [
            mod.title,
            mod.author,
            mod.category,
            mod.game,
            mod.game_domain,
            mod.original_summary,
        ]
    ).lower()
    return all(term in haystack for term in terms)
