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


def test_filter_by_distinctive_terms_with_anchor_groups_prefers_more_relevant_groups():
    results = [
        _result("Bimbo Roleplay Expansion", "1", 9),
        _result("Bimbo Morph Pack", "2", 8),
        _result("Whistling in Skyrim CHS", "3", 7),
    ]
    results[0].mod.original_summary = "A roleplay companion package."
    results[1].mod.original_summary = "Pure body morph pack for Skyrim."
    results[2].mod.original_summary = "Chinese subtitles and translations for Skyrim whistling."
    query_plan = {
        "_agent_ranking_semantic_anchors": ["bimbo", "roleplay"],
        "_agent_semantic_anchors": [],
    }

    filtered = filter_by_distinctive_terms(results, "天际有什么扮演bimbo mod", query_plan=query_plan)

    assert [item.mod.title for item in filtered] == ["Bimbo Roleplay Expansion", "Bimbo Morph Pack", "Whistling in Skyrim CHS"]


def test_filter_by_distinctive_terms_with_anchor_groups_falls_back_when_no_group_full_coverage():
    results = [
        _result("Bimbo Morph Pack", "1", 8),
        _result("Whistling in Skyrim CHS", "2", 7),
        _result("Lore Expansion", "3", 6),
    ]
    results[0].mod.original_summary = "Body morph pack focused on bimbo style."
    results[1].mod.original_summary = "Chinese subtitles and translation patch."
    results[2].mod.original_summary = "Core quest framework."

    query_plan = {
        "_agent_ranking_semantic_anchors": ["bimbo", "framework", "roleplay"],
        "_agent_semantic_anchors": [],
    }

    filtered = filter_by_distinctive_terms(results, "天际有什么扮演bimbo mod", query_plan=query_plan)

    assert [item.mod.title for item in filtered] == ["Bimbo Morph Pack", "Lore Expansion", "Whistling in Skyrim CHS"]


def test_filter_by_distinctive_terms_drops_zero_semantic_hits_for_direct_match_contract():
    vehicle = _result("Cyber Vehicle Handling Overhaul", "vehicle", 10)
    vehicle.mod.category = "Vehicles"
    vehicle.mod.original_summary = "Improves vehicle steering, drift, and brake control."
    outfit = _result("Cyber Latex Outfit", "outfit", 9)
    outfit.mod.category = "Clothing"
    outfit.mod.original_summary = "Adds latex outfit for V."
    query_plan = {
        "_agent_ranking_semantic_anchors": ["vehicle"],
        "_agent_semantic_strategy": {
            "answer_policy": {
                "main_results": "only_direct_match",
            }
        },
    }

    filtered = filter_by_distinctive_terms(
        [outfit, vehicle],
        "只看 Cyberpunk 2077 载具操控 Mod",
        query_plan=query_plan,
    )

    assert [item.mod.title for item in filtered] == ["Cyber Vehicle Handling Overhaul"]


def test_filter_by_distinctive_terms_requires_semantic_fallback_hit_for_direct_match_contract():
    tracksuit = _result("Samurai Tracksuit - Cyberpunk 2077", "tracksuit", 10)
    tracksuit.mod.game = "Stellar Blade"
    tracksuit.mod.category = "Outfits"
    tracksuit.mod.original_summary = "A tracksuit retexture with Johnny Silverhand's band logo from Cyberpunk 2077."
    armor = _result("Cyberpunk 2077 X Skyrim Samurai Armor", "armor", 9)
    armor.mod.category = "Armor"
    armor.mod.original_summary = "Armor inspired by CD Projekt Red and Mike Pondsmith's Cyberpunk."
    vehicle = _result("Cyber Vehicle Handling Overhaul", "vehicle", 8)
    vehicle.mod.game = "Cyberpunk 2077"
    vehicle.mod.category = "Vehicles"
    vehicle.mod.original_summary = "Improves vehicle steering and handling."
    query_plan = {
        "_agent_semantic_strategy": {
            "answer_policy": {
                "main_results": "only_direct_match",
            }
        },
    }

    filtered = filter_by_distinctive_terms(
        [tracksuit, armor, vehicle],
        "只看 Cyberpunk 2077 载具操控 Mod",
        query_plan=query_plan,
        fallback_terms=["cyberpunk", "2077", "vehicle", "handling", "steering"],
    )

    assert [item.mod.title for item in filtered] == ["Cyber Vehicle Handling Overhaul"]


def test_filter_by_distinctive_terms_ignores_author_name_match_without_author_constraint():
    bimbo_roleplay = _result("Bimbo Roleplay Expansion", "1", 12)
    bimbo_roleplay.mod.original_summary = "Roleplay companion and quest updates."
    age_of_nirn = _result("The Age of Nirn - Revelations", "2", 11)
    age_of_nirn.mod.author = "Bimbovakiin"
    age_of_nirn.mod.original_summary = "A lightweight narrative layer for Skyrim's main quest."

    query_plan = {
        "_agent_ranking_semantic_anchors": ["bimbo", "roleplay"],
    }
    filtered = filter_by_distinctive_terms(
        [age_of_nirn, bimbo_roleplay],
        "天际有什么扮演bimbo mod",
        query_plan=query_plan,
    )

    assert [item.mod.title for item in filtered] == ["Bimbo Roleplay Expansion", "The Age of Nirn - Revelations"]


def test_filter_by_distinctive_terms_can_match_author_when_author_constraint_is_explicit():
    byline = _result("The Age of Nirn - Revelations", "1", 12)
    byline.mod.author = "Bimbovakiin"
    byline.mod.original_summary = "A lightweight narrative layer for Skyrim's main quest."
    other = _result("Outfit Pack", "2", 11)
    other.mod.original_summary = "A simple outfit pack."

    query_plan = {
        "author": "Bimbovakiin",
    }
    plan = SearchPlan.from_query_plan({"author": "Bimbovakiin"})
    filtered = filter_by_distinctive_terms(
        [other, byline],
        "Bimbovakiin",
        query_plan=query_plan,
        plan=plan,
    )

    assert [item.mod.title for item in filtered] == ["The Age of Nirn - Revelations"]


def test_filter_by_distinctive_terms_does_not_match_anchor_term_inside_longer_token():
    results = [
        _result("Bimbovakiin", "1", 10),
        _result("Bimbo Roleplay Expansion", "2", 9),
    ]
    results[1].mod.original_summary = "Roleplay companion and quest updates."
    query_plan = {
        "_agent_ranking_semantic_anchors": ["bimbo", "roleplay"],
        "_agent_semantic_anchors": [],
    }

    filtered = filter_by_distinctive_terms(results, "天际有什么扮演bimbo mod", query_plan=query_plan)

    assert [item.mod.title for item in filtered] == ["Bimbo Roleplay Expansion", "Bimbovakiin"]


def test_sort_results_boosts_results_matching_more_keyword_groups():
    high_relevance = _result("Bimbo Roleplay Expansion", "1", 5)
    high_relevance.mod.original_summary = "Roleplay framework and quests."
    medium_relevance = _result("Bimbo Morph Pack", "2", 5)
    medium_relevance.mod.original_summary = "Body morph preset focused on bimbo style."
    plan = SearchPlan.from_query_plan({"sort_field": "relevance", "sort_order": "desc", "limit": 8})
    query_plan = {
        "_agent_ranking_semantic_anchors": ["bimbo", "roleplay"],
        "_agent_semantic_anchors": [],
    }

    sorted_results = sort_results([medium_relevance, high_relevance], plan, query_plan)

    assert [item.mod.title for item in sorted_results] == ["Bimbo Roleplay Expansion", "Bimbo Morph Pack"]


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
