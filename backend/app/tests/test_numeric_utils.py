from app.utils.numeric import (
    bounded_int,
    is_plain_int,
    optional_bounded_int,
    optional_int,
    optional_nonnegative_int,
    safe_float,
    safe_nonnegative_int,
    safe_optional_float,
)


def test_safe_nonnegative_int_handles_bad_and_negative_values():
    assert safe_nonnegative_int("12") == 12
    assert safe_nonnegative_int("1,200") == 1200
    assert safe_nonnegative_int("-3") == 0
    assert safe_nonnegative_int("bad") == 0
    assert safe_nonnegative_int(None) == 0
    assert safe_nonnegative_int(True) == 0


def test_is_plain_int_rejects_bool():
    assert is_plain_int(0) is True
    assert is_plain_int(True) is False
    assert is_plain_int("1") is False


def test_optional_int_helpers_distinguish_missing_from_zero():
    assert optional_int(0) == 0
    assert optional_int("1,200") == 1200
    assert optional_int("") is None
    assert optional_int(None) is None
    assert optional_int(True) is None
    assert optional_int("bad") is None
    assert optional_nonnegative_int("-3") == 0
    assert optional_nonnegative_int(True) is None
    assert optional_bounded_int(False, minimum=1, maximum=365) is None
    assert optional_bounded_int("400", minimum=1, maximum=365) == 365


def test_bounded_int_clamps_and_defaults_invalid_values():
    assert bounded_int("12", default=8, minimum=1, maximum=20) == 12
    assert bounded_int("1,200", default=8, minimum=1, maximum=2000) == 1200
    assert bounded_int("99", default=8, minimum=1, maximum=20) == 20
    assert bounded_int("-3", default=8, minimum=1, maximum=20) == 1
    assert bounded_int("bad", default=8, minimum=1, maximum=20) == 8
    assert bounded_int("0", default=8, minimum=1, maximum=20, default_when_below_minimum=True) == 8


def test_safe_float_handles_bad_values_and_bounds():
    assert safe_float("0.75") == 0.75
    assert safe_float("1,200.5") == 1200.5
    assert safe_float("bad", default=0.6) == 0.6
    assert safe_float(None, minimum=0.0) == 0.0
    assert safe_float("-1", minimum=0.0) == 0.0
    assert safe_float("2", maximum=1.0) == 1.0


def test_safe_optional_float_returns_none_for_bad_values():
    assert safe_optional_float("0.75") == 0.75
    assert safe_optional_float("1,200.5") == 1200.5
    assert safe_optional_float("bad") is None
    assert safe_optional_float(None) is None
