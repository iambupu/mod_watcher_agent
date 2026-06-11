# 中文注释：说明 backend/app/tests/test_config.py 的模块职责，便于后续维护定位。

from app.config import _env_bool, _env_int


def test_env_bool_uses_default_for_missing_and_unknown_values(monkeypatch):
    monkeypatch.delenv("TEST_BOOL_SETTING", raising=False)
    assert _env_bool("TEST_BOOL_SETTING", True) is True

    monkeypatch.setenv("TEST_BOOL_SETTING", "maybe")
    assert _env_bool("TEST_BOOL_SETTING", True) is True
    assert _env_bool("TEST_BOOL_SETTING", False) is False


def test_env_bool_accepts_shared_truthy_and_falsey_values(monkeypatch):
    monkeypatch.setenv("TEST_BOOL_SETTING", "on")
    assert _env_bool("TEST_BOOL_SETTING", False) is True

    monkeypatch.setenv("TEST_BOOL_SETTING", "off")
    assert _env_bool("TEST_BOOL_SETTING", True) is False


def test_env_int_defaults_and_clamps_invalid_values(monkeypatch):
    monkeypatch.setenv("TEST_INT_SETTING", "bad")
    assert _env_int("TEST_INT_SETTING", 60, minimum=1) == 60

    monkeypatch.setenv("TEST_INT_SETTING", "-5")
    assert _env_int("TEST_INT_SETTING", 60, minimum=1) == 1

    monkeypatch.setenv("TEST_INT_SETTING", "999")
    assert _env_int("TEST_INT_SETTING", 60, minimum=1, maximum=120) == 120
