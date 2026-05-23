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
