from app.services.agent.slot_text_inference import (
    infer_author_constraint,
    infer_compatibility_terms,
    infer_excluded_keywords,
    infer_requirement_terms,
    infer_title_constraint,
    infer_version_constraint,
    query_without_compatibility_terms,
)


def test_slot_text_inference_extracts_title_version_and_author_constraints():
    assert infer_title_constraint('Skyrim mod named "Bimbo Body Morph"') == {"exact_title": "Bimbo Body Morph"}
    assert infer_version_constraint("Skyrim bimbo preset version 1.2.0") == {"version": "1.2.0"}
    assert infer_author_constraint("Skyrim body preset by Ousnius with BodySlide tag") == {"author": "Ousnius"}


def test_slot_text_inference_extracts_requirement_and_compatibility_terms():
    assert infer_requirement_terms("需要 SKSE 前置的 Skyrim utility mod") == {"requirement_terms": ["SKSE"]}
    assert infer_compatibility_terms("支持 AE 的 Skyrim body mod") == {"compatibility_terms": ["AE"]}

    cleaned = query_without_compatibility_terms("支持 AE 的 Skyrim body mod")
    assert "AE" not in cleaned
    assert "body" in cleaned


def test_slot_text_inference_extracts_negative_terms_without_adult_noise():
    assert infer_excluded_keywords("不要 SKSE 前置的 Skyrim utility mod") == {"excluded_keywords": ["skse"]}
    assert infer_excluded_keywords("Skyrim body mod no NSFW") == {}
