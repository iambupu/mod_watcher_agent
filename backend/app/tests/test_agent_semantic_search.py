from app.services.agent.semantic_search import (
    distinctive_query_terms,
    infer_categories,
    semantic_query,
    text_score,
)


def test_semantic_query_expands_chinese_female_outfit_terms():
    semantic = semantic_query("只看女性服装")

    assert "female" in semantic.expanded_terms
    assert "outfit" in semantic.expanded_terms
    assert "clothing" in semantic.expanded_terms
    assert "clothing" in semantic.category_aliases


def test_infer_categories_uses_available_category_names():
    categories = infer_categories(
        "最近更新了哪些玩法类的 mod",
        ["Clothing and Accessories", "Gameplay", "Visuals and Graphics"],
    )

    assert categories == ["Gameplay"]


def test_text_score_matches_semantic_terms_in_english_fields():
    score = text_score(
        "只看女性服装",
        ["Elegant CBBE Dress", "Skyrim Special Edition", "Clothing and Accessories"],
        ["Clothing and Accessories"],
    )

    assert score > 0


def test_semantic_query_extracts_chinese_related_mod_keyword():
    semantic = semantic_query("有什么和玻尿酸相关的mod")

    assert "玻尿酸" in semantic.base_keywords
    assert "botox" in semantic.expanded_terms


def test_semantic_query_extracts_ascii_token_from_mixed_chinese_query():
    semantic = semantic_query("XXTB的mod")

    assert semantic.base_keywords == ["xxtb"]
    assert distinctive_query_terms("XXTB的mod") == ["xxtb"]
    assert text_score("XXTB的mod", ["XXTB - Prototype Suit CNS"], None) > 0
    assert text_score("XXTB的mod", ["Kawaii War Dress TypeA"], None) == 0


def test_semantic_query_ignores_natural_language_intent_fillers():
    semantic = semantic_query("I want to make my character look like a bimbo style preset")

    assert semantic.base_keywords == ["bimbo", "preset"]
    assert distinctive_query_terms("I want to make my character look like a bimbo style preset") == [
        "bimbo",
        "preset",
    ]


def test_semantic_query_does_not_match_english_markers_inside_other_words():
    semantic = semantic_query("semantic bimbo")

    assert semantic.base_keywords == ["semantic", "bimbo"]
    assert "male" not in semantic.expanded_terms
    assert "men" not in semantic.expanded_terms


def test_semantic_query_does_not_expand_male_terms_from_female_marker():
    semantic = semantic_query("female outfit")

    assert "female" in semantic.expanded_terms
    assert "outfit" in semantic.expanded_terms
    assert "male" not in semantic.expanded_terms
    assert "men" not in semantic.expanded_terms


def test_semantic_query_keeps_core_token_from_long_chinese_request():
    semantic = semantic_query("我想让角色变成那种夸张的 bimbo 化审美，有没有相关 mod")

    assert "bimbo" in semantic.base_keywords
    assert "角色" not in semantic.base_keywords
    assert distinctive_query_terms("我想让角色变成那种夸张的 bimbo 化审美，有没有相关 mod") == ["bimbo"]


def test_semantic_query_treats_alternative_words_as_intent_fillers():
    semantic = semantic_query("有没有更稳的 bimbo 替代品")

    assert semantic.base_keywords == ["bimbo"]
    assert distinctive_query_terms("有没有更稳的 bimbo 替代品") == ["bimbo"]


def test_semantic_query_treats_comparison_words_as_intent_fillers():
    semantic = semantic_query("这两个哪个更适合新手 bimbo")

    assert semantic.base_keywords == ["bimbo"]
    assert distinctive_query_terms("这两个哪个更适合新手 bimbo") == ["bimbo"]


def test_semantic_query_treats_same_style_followup_words_as_intent_fillers():
    semantic = semantic_query("不要成人内容但保持同类效果 bimbo")

    assert semantic.base_keywords == ["bimbo"]
    assert distinctive_query_terms("不要成人内容但保持同类效果 bimbo") == ["bimbo"]
