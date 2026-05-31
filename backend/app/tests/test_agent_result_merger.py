from app.models.mod import Mod
from app.services.agent.result_merger import (
    filter_by_adult_content,
    filter_by_distinctive_terms,
    filter_excluded_titles,
    merge_results,
    sort_results,
)
from app.services.agent.search_types import SearchPlan, SearchResult


def _result(title: str, external_id: str, score: int, updated: str = ""):
    mod = Mod(
        source="nexusmods",
        external_id=external_id,
        game="Stellar Blade",
        game_domain="stellarblade",
        title=title,
        url=f"https://example.com/{external_id}",
        updated_at_remote=updated,
    )
    return SearchResult(score=score, mod=mod, tool_name="test")


def test_merge_results_keeps_highest_score_per_source_external_id():
    low = _result("XXTB low", "1", 1)
    high = _result("XXTB high", "1", 5)

    merged = merge_results([low], [high])

    assert [item.score for item in merged] == [5]
    assert merged[0].mod.title == "XXTB high"


def test_merge_results_does_not_merge_blank_external_ids_with_different_urls():
    first = _result("First Result", "", 3)
    first.mod.url = "https://example.com/first"
    second = _result("Second Result", "", 7)
    second.mod.url = "https://example.com/second"

    merged = merge_results([first], [second])

    assert {item.mod.title for item in merged} == {"First Result", "Second Result"}


def test_merge_results_adds_explainable_fusion_score_breakdown():
    local = _result("Ocean String", "1", 12)
    local = SearchResult(score=12, mod=local.mod, tool_name="sqlite_fts")
    online = _result("Ocean String", "1", 4)
    online = SearchResult(score=4, mod=online.mod, tool_name="nexusmods_search")

    merged = merge_results([local], [online])

    assert merged[0].score >= 12
    assert merged[0].score_breakdown["keyword_score"] > 0
    assert merged[0].score_breakdown["source_confidence"] > 0
    assert "sqlite_fts" in merged[0].rank_reason
    assert "nexusmods_search" in merged[0].rank_reason


def test_filter_by_distinctive_terms_removes_unrelated_results():
    results = [_result("XXTB Suit", "1", 5), _result("Kawaii Dress", "2", 9)]

    filtered = filter_by_distinctive_terms(results, "XXTB的mod")

    assert [item.mod.title for item in filtered] == ["XXTB Suit"]


def test_filter_by_distinctive_terms_uses_fallback_terms_for_contextual_followup():
    results = [_result("Bimbo Body Morph", "1", 5), _result("Kawaii Dress", "2", 9)]

    filtered = filter_by_distinctive_terms(results, "还有其他类似的mod", fallback_terms=["bimbo"])

    assert [item.mod.title for item in filtered] == ["Bimbo Body Morph"]


def test_filter_by_distinctive_terms_treats_fallback_expansions_as_alternatives():
    results = [_result("Stellar Lace Combat Suit", "1", 5), _result("Realistic Armor", "2", 9)]
    results[0].mod.category = "Outfits"
    results[0].mod.original_summary = "An adult outfit mod for Stellar Blade."
    results[1].mod.category = "Armor"
    results[1].mod.original_summary = "A protective armor overhaul."

    filtered = filter_by_distinctive_terms(
        results,
        "帮我找最近比较火的剑星成人服装 Mod",
        fallback_terms=["outfit", "clothing", "dress", "robe", "bikini", "lingerie", "costume", "suit"],
    )

    assert [item.mod.title for item in filtered] == ["Stellar Lace Combat Suit"]


def test_filter_by_distinctive_terms_allows_partial_match_for_long_term_sets():
    results = [_result("Script Extender Utility Patch", "1", 5), _result("Casual Armor Pack", "2", 9)]
    results[0].mod.original_summary = "Requires SKSE and Address Library before installation."
    results[1].mod.original_summary = "No dependency and no utility tooling."

    filtered = filter_by_distinctive_terms(
        results,
        "utility framework fix patch performance bugfix",
    )

    assert [item.mod.title for item in filtered] == ["Script Extender Utility Patch"]


def test_filter_excluded_titles_removes_previously_shown_results():
    results = [_result("Bimbo Body Morph", "1", 5), _result("Bimbo Body Preset", "2", 9)]

    filtered = filter_excluded_titles(results, ["Bimbo Body Morph"])

    assert [item.mod.title for item in filtered] == ["Bimbo Body Preset"]


def test_sort_results_uses_plan_sort_field():
    older = _result("older", "1", 8, "2026-01-01T00:00:00+08:00")
    newer = _result("newer", "2", 1, "2026-05-01T00:00:00+08:00")
    plan = SearchPlan.from_query_plan({"sort_field": "updated_at_remote", "sort_order": "desc", "limit": 8})

    sorted_results = sort_results([older, newer], plan)

    assert [item.mod.title for item in sorted_results] == ["newer", "older"]


def test_sort_results_respects_ascending_download_order():
    high = _result("high", "1", 10)
    high.mod.downloads = 100
    low = _result("low", "2", 20)
    low.mod.downloads = 5
    plan = SearchPlan.from_query_plan({"sort_field": "downloads", "sort_order": "asc", "limit": 8})

    sorted_results = sort_results([high, low], plan)

    assert [item.mod.title for item in sorted_results] == ["low", "high"]


def test_sort_results_tolerates_string_download_values():
    high = _result("high", "1", 10)
    high.mod.downloads = "100"
    low = _result("low", "2", 20)
    low.mod.downloads = "not-a-number"
    plan = SearchPlan.from_query_plan({"sort_field": "downloads", "sort_order": "desc", "limit": 8})

    sorted_results = sort_results([low, high], plan)

    assert [item.mod.title for item in sorted_results] == ["high", "low"]


def test_filter_by_adult_content_parses_string_flags():
    clean = _result("clean", "1", 10)
    clean.mod.adult_content = "false"
    adult = _result("adult", "2", 20)
    adult.mod.adult_content = "true"
    plan = SearchPlan.from_query_plan({"adult_content": False, "limit": 8})

    filtered = filter_by_adult_content([clean, adult], plan)

    assert [item.mod.title for item in filtered] == ["clean"]
