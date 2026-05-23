from app.models.mod import Mod
from app.services.agent.result_merger import (
    filter_by_distinctive_terms,
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


def test_filter_by_distinctive_terms_removes_unrelated_results():
    results = [_result("XXTB Suit", "1", 5), _result("Kawaii Dress", "2", 9)]

    filtered = filter_by_distinctive_terms(results, "XXTB的mod")

    assert [item.mod.title for item in filtered] == ["XXTB Suit"]


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
