import logging
import re
from collections.abc import Iterable

from app.models.mod import Mod
from app.services.agent.list_utils import string_list
from app.services.agent.ranking.fusion import fuse_duplicate_results
from app.services.agent.search_types import SearchPlan, SearchResult
from app.services.agent.semantic_search import distinctive_query_terms, semantic_query_from_anchors
from app.utils.boolean import parse_bool
from app.utils.numeric import safe_nonnegative_int

logger = logging.getLogger(__name__)

_ANCHOR_PRIMARY_TERM_SCORE = 6.0
_ANCHOR_SECONDARY_TERM_SCORE = 0.2
_ANCHOR_SOURCE_WEIGHT_RANKING = 2.0
_ANCHOR_SOURCE_WEIGHT_SEMANTIC = 1.0


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
        include_author_in_match = _should_include_author_in_matching(plan, query_plan)
        return sorted(
            results,
            key=lambda item: (
                item.score
                + _category_hint_score(item, plan)
                + _semantic_hint_score(item.mod, query_plan, include_author=include_author_in_match)
                + _keyword_group_score(item.mod, query_plan, include_author=include_author_in_match),
                item.mod.first_seen_at,
            ),
            reverse=reverse,
        )
    return sorted(results, key=lambda item: ((item.mod.updated_at_remote or ""), item.score), reverse=reverse)


def filter_by_distinctive_terms(
    results: list[SearchResult],
    query: str,
    query_plan: dict | None = None,
    *,
    fallback_terms: list[str] | None = None,
    plan: SearchPlan | None = None,
) -> list[SearchResult]:
    anchor_groups = _query_plan_anchor_groups(query_plan)
    include_author = _should_include_author_in_matching(plan, query_plan)
    if anchor_groups:
        results_with_scores = [
            (_query_group_match_count(item.mod, anchor_groups, include_author=include_author), idx, item)
            for idx, item in enumerate(results)
        ]
        if not any(score > 0 for score, *_ in results_with_scores):
            return _legacy_filter_by_distinctive_terms(
                results,
                query,
                fallback_terms=fallback_terms,
                include_author=include_author,
                require_fallback_semantic_hit=_requires_direct_semantic_filter(query_plan),
            )
        results_with_scores.sort(key=lambda item: (item[0], -item[1]), reverse=True)
        if _requires_direct_semantic_filter(query_plan):
            direct_results = [item for score, _, item in results_with_scores if score > 0]
            if direct_results:
                return direct_results
        return [item for _, _, item in results_with_scores]
    return _legacy_filter_by_distinctive_terms(
        results,
        query,
        fallback_terms=fallback_terms,
        include_author=include_author,
        require_fallback_semantic_hit=_requires_direct_semantic_filter(query_plan),
    )


def _legacy_filter_by_distinctive_terms(
    results: list[SearchResult],
    query: str,
    *,
    fallback_terms: list[str] | None = None,
    include_author: bool = False,
    require_fallback_semantic_hit: bool = False,
) -> list[SearchResult]:
    terms = distinctive_query_terms(query)
    if terms:
        min_hits = _required_term_hits(len(terms))
        matched = [
            item
            for item in results
            if _mod_term_hit_count(item.mod, terms, include_author=include_author) >= min_hits
        ]
        fallback = _fallback_filter_terms_for_matching(fallback_terms)
        semantic_fallback = [term for term in fallback if term not in terms]
        if semantic_fallback:
            direct = [
                item
                for item in matched
                if _mod_contains_any_term(item.mod, semantic_fallback, include_author=include_author)
            ]
            if direct or require_fallback_semantic_hit:
                return direct
        return matched
    fallback = _fallback_filter_terms_for_matching(fallback_terms)
    if not fallback:
        return results
    return [item for item in results if _mod_contains_any_term(item.mod, fallback, include_author=include_author)]


def _fallback_filter_terms_for_matching(fallback_terms: list[str] | None) -> list[str]:
    terms: list[str] = []
    for value in fallback_terms or []:
        term = str(value or "").strip().lower()
        if not term:
            continue
        if re.fullmatch(r"[a-z0-9][a-z0-9_-]*", term) or re.search(r"[\u4e00-\u9fff]", term):
            terms.append(term)
    return list(dict.fromkeys(terms))


def _query_plan_anchor_groups(query_plan: dict | None) -> list[tuple[tuple[str, ...], float]]:
    """
    Build weighted anchor term groups.
    Each group is `(ordered_terms, source_weight)`, where `ordered_terms[0]` is the anchor.
    """
    groups: list[tuple[tuple[str, ...], float]] = []
    groups.extend(
        _query_plan_anchor_groups_from_field(
            query_plan,
            field="_agent_ranking_semantic_anchors",
            source_weight=_ANCHOR_SOURCE_WEIGHT_RANKING,
        )
    )
    groups.extend(
        _query_plan_anchor_groups_from_field(
            query_plan,
            field="_agent_semantic_anchors",
            source_weight=_ANCHOR_SOURCE_WEIGHT_SEMANTIC,
        )
    )
    deduped: list[tuple[tuple[str, ...], float]] = []
    seen: set[str] = set()
    for terms, weight in groups:
        if not terms:
            continue
        anchor_term = terms[0]
        if anchor_term in seen:
            continue
        seen.add(anchor_term)
        deduped.append((terms, weight))
    return deduped


def _requires_direct_semantic_filter(query_plan: dict | None) -> bool:
    if not isinstance(query_plan, dict):
        return False
    strategy = query_plan.get("_agent_semantic_strategy")
    if not isinstance(strategy, dict):
        return False
    policy = strategy.get("answer_policy")
    if not isinstance(policy, dict):
        return False
    main_results = str(policy.get("main_results") or "").strip().lower()
    return main_results in {"only_direct_match", "direct_match_only"}


def _query_group_match_count(
    mod: Mod,
    term_groups: list[tuple[tuple[str, ...], float]],
    *,
    include_author: bool = False,
) -> float:
    return _query_group_match_score(mod, term_groups, include_author=include_author)


def _query_group_match_score(
    mod: Mod,
    term_groups: list[tuple[tuple[str, ...], float]],
    *,
    include_author: bool = False,
) -> float:
    if not term_groups:
        return 0.0
    haystack = _mod_haystack(mod, include_author=include_author)
    group_count = len(term_groups)
    return sum(
        _score_anchor_group(
            terms,
            haystack,
            group_index=group_index,
            group_count=group_count,
            source_weight=source_weight,
        )
        for group_index, (terms, source_weight) in enumerate(term_groups)
    )


def _should_include_author_in_matching(plan: SearchPlan | None, query_plan: dict | None) -> bool:
    if plan and plan.author:
        return True
    if not isinstance(query_plan, dict):
        return False
    if str(query_plan.get("author") or "").strip():
        return True
    return str(query_plan.get("intent") or "").strip().lower() == "author"


def _score_anchor_group(
    terms: tuple[str, ...],
    haystack: str,
    *,
    group_index: int,
    group_count: int,
    source_weight: float,
) -> float:
    if not terms:
        return 0.0
    anchor_term = terms[0]
    anchor_hit = _term_in_haystack(anchor_term, haystack)
    secondary_hits = [_term_in_haystack(term, haystack) for term in terms[1:]]
    if not anchor_hit and not any(secondary_hits):
        return 0.0
    group_term_score = 0.0
    if anchor_hit:
        group_term_score += _ANCHOR_PRIMARY_TERM_SCORE
    group_term_score += _ANCHOR_SECONDARY_TERM_SCORE * sum(1 for hit in secondary_hits if hit)
    if group_count <= 1:
        position_weight = 1.0
    else:
        position_weight = 1.0 + 0.6 * (group_count - group_index) / group_count
    return group_term_score * source_weight * position_weight


def _term_in_haystack(term: str, haystack: str) -> bool:
    if not term:
        return False
    if " " in term:
        return term in haystack
    if re.fullmatch(r"[a-z0-9]+", term):
        return re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", haystack) is not None
    return term in haystack


def _query_plan_anchor_groups_from_field(
    query_plan: dict | None,
    *,
    field: str,
    source_weight: float,
) -> list[tuple[tuple[str, ...], float]]:
    if not isinstance(query_plan, dict):
        return []
    normalized = [
        str(anchor or "").strip().lower()
        for anchor in string_list(query_plan.get(field))
        if str(anchor or "").strip()
    ]
    groups: list[tuple[tuple[str, ...], float]] = []
    seen: set[str] = set()
    for anchor in normalized:
        if anchor in seen:
            continue
        seen.add(anchor)
        signals = semantic_query_from_anchors("", [anchor])
        raw_terms = [
            anchor,
            *signals.expanded_terms,
            *signals.matched_concepts,
            *signals.category_aliases,
        ]
        terms = [str(term).strip().lower() for term in raw_terms if str(term).strip()]
        seen_terms: set[str] = set()
        ordered_terms: list[str] = []
        for term in terms:
            if term in seen_terms:
                continue
            seen_terms.add(term)
            ordered_terms.append(term)
        if ordered_terms:
            groups.append((tuple(ordered_terms), source_weight))
    return groups


def _keyword_group_score(
    mod: Mod,
    query_plan: dict | None = None,
    *,
    include_author: bool = False,
) -> int:
    if not isinstance(query_plan, dict):
        return 0
    term_groups = _query_plan_anchor_groups(query_plan)
    if not term_groups:
        return 0
    return int(_query_group_match_score(mod, term_groups, include_author=include_author))


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


def _mod_haystack(mod: Mod, *, include_author: bool = False) -> str:
    return " ".join(
        str(value or "")
        for value in [
            mod.title,
            *([mod.author] if include_author and str(mod.author or "").strip() else []),
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


def _semantic_hint_score(mod: Mod, query_plan: dict | None, *, include_author: bool = False) -> int:
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
    haystack = _mod_haystack(mod, include_author=include_author)
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


def _mod_contains_any_term(mod: Mod, terms: list[str], *, include_author: bool = False) -> bool:
    haystack = _mod_haystack(mod, include_author=include_author)
    return any(_term_in_haystack(term.strip().lower(), haystack) for term in terms)


def _mod_term_hit_count(mod: Mod, terms: list[str], *, include_author: bool = False) -> int:
    haystack = _mod_haystack(mod, include_author=include_author)
    return sum(1 for term in terms if _term_in_haystack(term.strip().lower(), haystack))


def _required_term_hits(term_count: int) -> int:
    if term_count <= 1:
        return 1
    if term_count <= 3:
        return term_count
    return 2


def _title_key(title: str | None) -> str:
    return " ".join(str(title or "").lower().split())
