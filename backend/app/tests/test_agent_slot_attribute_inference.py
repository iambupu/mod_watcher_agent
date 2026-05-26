from app.services.agent.slot_attribute_inference import (
    infer_summary_language_constraints,
    infer_tag_constraints,
    infer_thumbnail_constraint,
    query_without_thumbnail_terms,
)


def test_slot_attribute_inference_extracts_explicit_tags():
    assert infer_tag_constraints("带 CBBE / 3BA 标签的 Skyrim body mod") == {"tags": ["CBBE", "3BA"]}


def test_slot_attribute_inference_extracts_summary_language_constraints():
    assert infer_summary_language_constraints("有中文摘要的 Skyrim body mod") == {"summary_languages": ["zh-CN"]}
    assert infer_summary_language_constraints("不要中文摘要的 Skyrim body mod") == {
        "excluded_summary_languages": ["zh-CN"]
    }


def test_slot_attribute_inference_extracts_thumbnail_constraints_and_cleans_terms():
    assert infer_thumbnail_constraint("有预览图的 bimbo mod") == {"has_thumbnail": True}
    assert infer_thumbnail_constraint("不要图片的 bimbo mod") == {"has_thumbnail": False}

    cleaned = query_without_thumbnail_terms("有预览图的 bimbo mod")
    assert "预览" not in cleaned
    assert "bimbo" in cleaned
