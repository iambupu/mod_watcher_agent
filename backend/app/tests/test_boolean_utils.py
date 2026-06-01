from app.utils.boolean import parse_bool, parse_optional_bool


def test_parse_bool_handles_common_string_values():
    assert parse_bool("true") is True
    assert parse_bool("1") is True
    assert parse_bool("yes") is True
    assert parse_bool("false") is False
    assert parse_bool("0") is False
    assert parse_bool("no") is False


def test_parse_bool_uses_default_for_unknown_values():
    assert parse_bool(None) is False
    assert parse_bool("maybe") is False
    assert parse_bool("maybe", default=True) is True


def test_parse_optional_bool_preserves_unknown_values():
    assert parse_optional_bool("on") is True
    assert parse_optional_bool("off") is False
    assert parse_optional_bool(1) is True
    assert parse_optional_bool(0) is False
    assert parse_optional_bool("maybe") is None
