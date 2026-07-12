from __future__ import annotations

import importlib
import logging
import logging.handlers
import sys
import threading
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest


def _desktop_logging_module() -> ModuleType:
    try:
        return importlib.import_module("app.desktop.logging")
    except ModuleNotFoundError:
        pytest.fail("app.desktop.logging is not implemented", pytrace=False)


def _paths(tmp_path: Path) -> SimpleNamespace:
    return SimpleNamespace(log_dir=tmp_path / "logs", user_root=tmp_path / "user-data")


def _exception_with_traceback(message: str) -> BaseException:
    try:
        raise RuntimeError(message)
    except RuntimeError as exc:
        return exc


def test_desktop_log_is_rotating_idempotent_and_redacts_every_write(tmp_path: Path) -> None:
    module = _desktop_logging_module()
    paths = _paths(tmp_path)

    logger = module.configure_desktop_logging(paths)
    same_logger = module.configure_desktop_logging(paths)
    logger.error(
        "Bearer bearer-secret api_key=api-secret token=token-secret "
        "password=password-secret "
        "https://discord.com/api/webhooks/123/webhook-secret"
    )
    logger.error("Cookie=session-secret")
    logger.error('profile_content={"cookies":[{"value":"nested-profile-secret"}]}')
    for handler in logger.handlers:
        handler.flush()

    desktop_handlers = [
        handler
        for handler in logger.handlers
        if isinstance(handler, logging.handlers.RotatingFileHandler)
        and Path(handler.baseFilename).name == "desktop.log"
    ]
    content = (paths.log_dir / "desktop.log").read_text(encoding="utf-8")

    assert same_logger is logger
    assert len(desktop_handlers) == 1
    assert "bearer-secret" not in content
    assert "api-secret" not in content
    assert "token-secret" not in content
    assert "password-secret" not in content
    assert "session-secret" not in content
    assert "webhook-secret" not in content
    assert "nested-profile-secret" not in content
    assert "********" in content


def test_crash_log_contains_required_metadata_traceback_and_no_secrets(tmp_path: Path) -> None:
    module = _desktop_logging_module()
    paths = _paths(tmp_path)
    exception = _exception_with_traceback(
        "Bearer crash-secret api_key=api-secret token=token-secret "
        "password=password-secret Cookie=session-secret "
        "https://discord.com/api/webhooks/123/webhook-secret profile_content=profile-secret"
    )

    assert (
        module.write_crash_log(
            paths.log_dir,
            exception,
            state="starting_backend",
            thread_name="MainThread",
            app_version="0.2.2",
            platform_name="Windows-11-test",
            frozen=True,
            user_data_dir=paths.user_root,
        )
        is True
    )

    content = (paths.log_dir / "crash.log").read_text(encoding="utf-8")
    assert "timestamp=" in content
    assert "application_version=0.2.2" in content
    assert "platform=Windows-11-test" in content
    assert "frozen=true" in content
    assert f"user_data_dir={paths.user_root}" in content
    assert "thread=MainThread" in content
    assert "state=starting_backend" in content
    assert "exception_type=RuntimeError" in content
    assert "Traceback (most recent call last)" in content
    for secret in (
        "crash-secret",
        "api-secret",
        "token-secret",
        "password-secret",
        "session-secret",
        "webhook-secret",
        "profile-secret",
    ):
        assert secret not in content


def test_sys_exception_hook_writes_crash_and_delegates_then_restores(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _desktop_logging_module()
    paths = _paths(tmp_path)
    original_calls: list[tuple[object, object, object]] = []

    def original_hook(exc_type: object, exc_value: object, exc_traceback: object) -> None:
        original_calls.append((exc_type, exc_value, exc_traceback))

    monkeypatch.setattr(sys, "excepthook", original_hook)
    installation = module.install_exception_hooks(
        paths,
        state_provider=lambda: "window_hidden",
        app_version="0.2.2",
        platform_name="Windows-test",
        frozen=False,
    )
    same_installation = module.install_exception_hooks(
        paths,
        state_provider=lambda: "ignored-second-install",
        app_version="ignored",
        platform_name="ignored",
        frozen=True,
    )
    exception = _exception_with_traceback("Bearer sys-hook-secret")

    sys.excepthook(type(exception), exception, exception.__traceback__)

    assert same_installation is installation
    assert original_calls == [(type(exception), exception, exception.__traceback__)]
    content = (paths.log_dir / "crash.log").read_text(encoding="utf-8")
    assert "thread=MainThread" in content
    assert "state=window_hidden" in content
    assert "sys-hook-secret" not in content

    installation.restore()
    assert sys.excepthook is original_hook


def test_thread_exception_hook_writes_thread_name_delegates_and_restores(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _desktop_logging_module()
    paths = _paths(tmp_path)
    original_calls: list[object] = []

    def original_hook(args: object) -> None:
        original_calls.append(args)

    monkeypatch.setattr(threading, "excepthook", original_hook)
    installation = module.install_exception_hooks(
        paths,
        state_provider=lambda: "running",
        app_version="0.2.2",
        platform_name="Windows-test",
        frozen=False,
    )
    exception = _exception_with_traceback("token=thread-hook-secret")
    args = SimpleNamespace(
        exc_type=type(exception),
        exc_value=exception,
        exc_traceback=exception.__traceback__,
        thread=SimpleNamespace(name="mod-watcher-worker"),
    )

    threading.excepthook(args)

    assert original_calls == [args]
    content = (paths.log_dir / "crash.log").read_text(encoding="utf-8")
    assert "thread=mod-watcher-worker" in content
    assert "state=running" in content
    assert "thread-hook-secret" not in content

    installation.restore()
    assert threading.excepthook is original_hook


def test_crash_log_write_failure_is_contained(tmp_path: Path) -> None:
    module = _desktop_logging_module()
    blocked_log_dir = tmp_path / "not-a-directory"
    blocked_log_dir.write_text("occupied", encoding="utf-8")

    result = module.write_crash_log(
        blocked_log_dir,
        RuntimeError("Bearer must-not-recurse"),
        state="failed",
        thread_name="MainThread",
        app_version="0.2.2",
        platform_name="Windows-test",
        frozen=False,
        user_data_dir=tmp_path / "user-data",
    )

    assert result is False
