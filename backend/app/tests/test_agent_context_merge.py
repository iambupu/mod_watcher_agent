from app.services.agent.planning.context_inheritance_application import merge_context_keywords
from app.services.agent.planning.context_plan_merge import merge_context_query_plan


def test_merge_context_keywords_keeps_context_anchor_and_current_constraints():
    merged = merge_context_keywords(
        current_keywords=["curvy", "body", "mod"],
        context_keywords=["bimbo", "style", "mods"],
    )

    assert merged[:3] == ["bimbo", "curvy", "body"]
    assert "mod" not in merged
    assert "style" not in merged


def test_merge_context_keywords_drops_source_alias_and_similar_result_terms():
    merged = merge_context_keywords(
        current_keywords=["ll", "的结果"],
        context_keywords=["bimbo"],
    )

    assert merged == ["bimbo"]


def test_merge_context_query_plan_preserves_current_negative_constraints():
    merged = merge_context_query_plan(
        {
            "keywords": ["outfit"],
            "excluded_sources": ["nexusmods"],
            "exclude_titles": ["Shown Current"],
            "keyword_match_mode": "all",
        },
        {
            "keywords": ["bimbo"],
            "excluded_sources": ["loverslab"],
            "exclude_titles": ["Shown Context"],
            "keyword_match_mode": "any",
        },
    )

    assert merged["excluded_sources"] == ["nexusmods"]
    assert merged["exclude_titles"] == ["Shown Current"]
    assert merged["keyword_match_mode"] == "all"


def test_merge_context_query_plan_does_not_inherit_keyword_mode_without_context_keywords():
    merged = merge_context_query_plan(
        {"keywords": ["related"]},
        {
            "excluded_sources": ["loverslab"],
            "exclude_titles": ["Shown Context"],
            "keyword_match_mode": "all",
        },
    )

    assert merged["excluded_sources"] == ["loverslab"]
    assert merged["exclude_titles"] == ["Shown Context"]
    assert "keyword_match_mode" not in merged


def test_merge_context_query_plan_keeps_keyword_mode_when_context_keywords_are_inherited():
    merged = merge_context_query_plan(
        {"keywords": []},
        {
            "keywords": ["doll", "face", "preset"],
            "keyword_match_mode": "all",
        },
    )

    assert merged["keywords"] == ["doll", "face", "preset"]
    assert merged["keyword_match_mode"] == "all"


def test_merge_context_query_plan_does_not_leak_all_mode_into_new_scoped_query():
    merged = merge_context_query_plan(
        {
            "keywords": ["female", "outfit"],
            "game_domains": ["skyrimspecialedition"],
            "categories": ["Clothing and Accessories", "Outfits"],
            "sources": ["nexusmods"],
            "adult_content": True,
        },
        {
            "keywords": ["doll", "face", "preset"],
            "keyword_match_mode": "all",
            "exclude_titles": ["Shown Context"],
        },
    )

    assert merged["keywords"] == ["female", "outfit"]
    assert "keyword_match_mode" not in merged
    assert merged["exclude_titles"] == ["Shown Context"]
