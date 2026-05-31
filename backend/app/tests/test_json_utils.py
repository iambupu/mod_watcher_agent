from app.utils.json import (
    json_array,
    json_array_from_text,
    json_object,
    json_object_from_text,
    json_text,
    strip_json_fence,
)


def test_json_object_returns_empty_for_non_objects():
    assert json_object('{"ok": true}') == {"ok": True}
    assert json_object("[]") == {}
    assert json_object("{bad") == {}
    assert json_object(None) == {}


def test_json_array_returns_empty_for_non_arrays():
    assert json_array("[1, 2]") == [1, 2]
    assert json_array("{}") == []
    assert json_array("[bad") == []
    assert json_array(None) == []


def test_json_text_dumps_unicode_and_falls_back_to_string():
    assert json_text({"name": "中文"}) == '{"name": "中文"}'


def test_strip_json_fence_removes_optional_language_marker():
    assert strip_json_fence("```json\n{\"ok\": true}\n```") == '{"ok": true}'


def test_json_object_from_text_extracts_first_embedded_object():
    assert json_object_from_text('prefix {"ok": true} suffix {"ignored": true}') == {"ok": True}
    assert json_object_from_text('[{"not":"object"}]') is None


def test_json_array_from_text_extracts_first_embedded_array():
    assert json_array_from_text('["a"]\nextra text') == ["a"]
    assert json_array_from_text('{"not":"array"}') is None
