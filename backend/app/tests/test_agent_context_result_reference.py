from app.services.agent.planning.context_result_reference import (
    apply_result_reference_context,
    is_contextual_query_followup,
    referenced_title_keywords,
)


def test_result_reference_similarity_uses_referenced_title_keywords():
    raw = {"keywords": ["similar"]}

    apply_result_reference_context(
        raw,
        "找第2个类似的",
        ["Bimbo Body Morph", "Doll Face Preset"],
    )

    assert raw["keywords"] == ["doll", "face", "preset"]
    assert raw["keyword_match_mode"] == "all"


def test_result_reference_install_risk_targets_exact_title():
    raw = {"keywords": []}

    apply_result_reference_context(
        raw,
        "第二个安装风险高吗",
        ["Bimbo Body Morph", "Stable Bimbo Preset"],
    )

    assert raw["keywords"] == ["Stable Bimbo Preset"]
    assert raw["exact_title"] == "Stable Bimbo Preset"


def test_result_reference_alternative_excludes_prior_results():
    raw = {"keywords": []}

    apply_result_reference_context(
        raw,
        "这个有没有更稳的替代品",
        ["Bimbo Body Morph", "Stable Bimbo Preset"],
    )

    assert raw["keywords"] == ["bimbo", "body", "morph"]
    assert raw["exclude_titles"] == ["Bimbo Body Morph", "Stable Bimbo Preset"]


def test_contextual_query_followup_includes_reference_modes():
    assert is_contextual_query_followup("这个有没有更稳的替代品") is True
    assert is_contextual_query_followup("which one is safer") is True
    assert is_contextual_query_followup("cyberpunk vehicle overhaul mod") is False


def test_referenced_title_keywords_drops_generic_mod_terms():
    assert referenced_title_keywords("Bimbo Body Morph Mod") == ["bimbo", "body", "morph"]
