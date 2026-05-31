from app.utils.ids import positive_integer_id, positive_integer_ids


def test_positive_integer_id_rejects_bool_and_non_positive_values():
    assert positive_integer_id(True) is None
    assert positive_integer_id(False) is None
    assert positive_integer_id(0) is None
    assert positive_integer_id(-1) is None
    assert positive_integer_id(1) == 1


def test_positive_integer_id_optionally_accepts_numeric_strings():
    assert positive_integer_id("2") is None
    assert positive_integer_id("2", allow_string=True) == 2
    assert positive_integer_id(" 2 ", allow_string=True) == 2
    assert positive_integer_id("2.0", allow_string=True) is None


def test_positive_integer_ids_dedupes_strict_integer_values():
    assert positive_integer_ids([1, True, 1, 2, 0, "3"]) == [1, 2]
