from __future__ import annotations

import importlib
import io
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


def _desktop_handler(logger: logging.Logger) -> logging.handlers.RotatingFileHandler:
    return next(
        handler
        for handler in logger.handlers
        if isinstance(handler, logging.handlers.RotatingFileHandler)
        and getattr(handler, "_mod_watcher_desktop_handler", False)
    )


class _FailingWriteStream:
    def seek(self, *_args: object) -> int:
        return 0

    def tell(self) -> int:
        return 0

    def write(self, _value: str) -> None:
        raise OSError("simulated desktop log write failure")

    def flush(self) -> None:
        return None

    def close(self) -> None:
        return None


class _FailingFlushStream:
    def __init__(self) -> None:
        self.closed = False

    def flush(self) -> None:
        raise OSError("simulated desktop log flush failure")

    def close(self) -> None:
        self.closed = True


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


def test_desktop_log_redacts_structured_args_tracebacks_and_multiline_profiles(
    tmp_path: Path,
) -> None:
    module = _desktop_logging_module()
    paths = _paths(tmp_path)
    logger = module.configure_desktop_logging(paths)
    secrets = (
        "cookie-arg-secret",
        "api-arg-secret",
        "token-arg-secret",
        "profile-arg-secret",
        "cookie-json-secret",
        "api-json-secret",
        "token-json-secret",
        "bearer-suffix-secret",
        "multiline-profile-secret",
        "traceback-profile-secret",
    )

    try:
        logger.error(
            "structured=%r",
            {
                "Cookie": "cookie-arg-secret",
                "api_key": "api-arg-secret",
                "token": "token-arg-secret",
                "profile_data": {"cookies": [{"value": "profile-arg-secret"}]},
            },
        )
        logger.error(
            'json={"Cookie":"cookie-json-secret","api_key":"api-json-secret",'
            '"token":"token-json-secret"}'
        )
        logger.error("Authorization: Bearer abc+bearer-suffix-secret/=")
        logger.error('profile_content={\n  "cookies":[{"value":"multiline-profile-secret"}]\n}')
        try:
            raise RuntimeError('metadata={"profile_content":{"Cookie":"traceback-profile-secret"}}')
        except RuntimeError:
            logger.exception("structured traceback")

        for handler in logger.handlers:
            handler.flush()
        content = (paths.log_dir / "desktop.log").read_text(encoding="utf-8")
    finally:
        module.close_desktop_logging(logger)

    for secret in secrets:
        assert secret not in content


def test_crash_log_redacts_structured_traceback_and_metadata(tmp_path: Path) -> None:
    module = _desktop_logging_module()
    paths = _paths(tmp_path)
    exception = _exception_with_traceback(
        'metadata={"profile_data":{"Cookie":"traceback-cookie-secret",'
        '"api_key":"traceback-api-secret","token":"traceback-token-secret"}}\n'
        'profile_content={\n  "cookies":[{"value":"traceback-multiline-secret"}]\n}'
    )

    assert module.write_crash_log(
        paths.log_dir,
        exception,
        state="metadata={'profile_data': {'Cookie': 'state-profile-secret'}}",
        thread_name='worker {"Cookie":"thread-cookie-secret"}',
        app_version="Bearer abc+version-bearer-secret/=",
        platform_name='metadata={"api_key":"platform-api-secret"}',
        frozen=False,
        user_data_dir=paths.user_root,
    )

    content = (paths.log_dir / "crash.log").read_text(encoding="utf-8")
    for secret in (
        "traceback-cookie-secret",
        "traceback-api-secret",
        "traceback-token-secret",
        "traceback-multiline-secret",
        "state-profile-secret",
        "thread-cookie-secret",
        "version-bearer-secret",
        "platform-api-secret",
    ):
        assert secret not in content


def test_desktop_log_redacts_quoted_authorization_webhook_and_prefixed_credentials(
    tmp_path: Path,
) -> None:
    module = _desktop_logging_module()
    paths = _paths(tmp_path)
    logger = module.configure_desktop_logging(paths)
    secrets = (
        "authorization-field-secret",
        "webhook-field-secret",
        "proxy-password-secret",
        "primary-api-key-secret",
        "access-token-secret",
    )

    try:
        logger.error(
            "credentials=%r",
            {
                "authorization": "authorization-field-secret",
                "webhook": "webhook-field-secret",
                "proxy_password": "proxy-password-secret",
                "primary_api_key": "primary-api-key-secret",
                "access_token": "access-token-secret",
            },
        )
        for handler in logger.handlers:
            handler.flush()
        content = (paths.log_dir / "desktop.log").read_text(encoding="utf-8")
    finally:
        module.close_desktop_logging(logger)

    for secret in secrets:
        assert secret not in content


def test_desktop_log_sanitizes_record_before_io_and_never_dumps_raw_args(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    module = _desktop_logging_module()
    logger = module.configure_desktop_logging(_paths(tmp_path))
    handler = _desktop_handler(logger)
    observed_records: list[tuple[object, object]] = []

    class ObserveSanitizedRecord(logging.Filter):
        def filter(self, record: logging.LogRecord) -> bool:
            observed_records.append((record.msg, record.args))
            return True

    handler.addFilter(ObserveSanitizedRecord())
    assert handler.stream is not None
    handler.stream.close()
    handler.stream = _FailingWriteStream()
    original_raise_exceptions = logging.raiseExceptions
    logging.raiseExceptions = True
    try:
        logger.error("token=%s", "write-failure-arg-secret")
    finally:
        logging.raiseExceptions = original_raise_exceptions
        handler.stream = None
        module.close_desktop_logging(logger)

    captured = capsys.readouterr()
    assert observed_records == [("token=********", ())]
    assert "write-failure-arg-secret" not in captured.err


def test_desktop_log_sanitizes_records_before_preexisting_handlers(tmp_path: Path) -> None:
    module = _desktop_logging_module()
    logger = logging.getLogger("mod_watcher.desktop")
    observed_records: list[tuple[object, object]] = []

    class PreexistingHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            observed_records.append((record.msg, record.args))

    preexisting_handler = PreexistingHandler()
    logger.addHandler(preexisting_handler)
    try:
        configured_logger = module.configure_desktop_logging(_paths(tmp_path))
        configured_logger.error("access_token=%s", "preexisting-handler-secret")
    finally:
        logger.removeHandler(preexisting_handler)
        preexisting_handler.close()
        module.close_desktop_logging(logger)

    assert observed_records == [("access_token=********", ())]


def test_desktop_log_sanitizes_exception_before_preexisting_handlers(tmp_path: Path) -> None:
    module = _desktop_logging_module()
    logger = logging.getLogger("mod_watcher.desktop")
    preexisting_output = io.StringIO()
    preexisting_handler = logging.StreamHandler(preexisting_output)
    preexisting_handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(preexisting_handler)
    paths = _paths(tmp_path)

    try:
        configured_logger = module.configure_desktop_logging(paths)
        try:
            raise RuntimeError(
                'metadata={"profile_data":{"Cookie":"preexisting-traceback-secret"}}'
            )
        except RuntimeError:
            configured_logger.exception("ordinary handler traceback")
        preexisting_handler.flush()
        for handler in configured_logger.handlers:
            handler.flush()
        desktop_content = (paths.log_dir / "desktop.log").read_text(encoding="utf-8")
    finally:
        logger.removeHandler(preexisting_handler)
        preexisting_handler.close()
        module.close_desktop_logging(logger)

    for content in (preexisting_output.getvalue(), desktop_content):
        assert "preexisting-traceback-secret" not in content
        assert content.count("Traceback (most recent call last)") == 1
        assert "RuntimeError:" in content


def test_close_desktop_logging_contains_handler_flush_failures(tmp_path: Path) -> None:
    module = _desktop_logging_module()
    logger = module.configure_desktop_logging(_paths(tmp_path))
    handler = _desktop_handler(logger)
    assert handler.stream is not None
    handler.stream.close()
    failing_stream = _FailingFlushStream()
    handler.stream = failing_stream

    module.close_desktop_logging(logger)
    module.close_desktop_logging(logger)

    assert handler not in logger.handlers
    assert failing_stream.closed is True


def test_switching_log_directory_continues_when_old_handler_close_fails(
    tmp_path: Path,
) -> None:
    module = _desktop_logging_module()
    first_paths = _paths(tmp_path / "first")
    second_paths = _paths(tmp_path / "second")
    logger = module.configure_desktop_logging(first_paths)
    first_handler = _desktop_handler(logger)
    assert first_handler.stream is not None
    first_handler.stream.close()
    failing_stream = _FailingFlushStream()
    first_handler.stream = failing_stream

    try:
        same_logger = module.configure_desktop_logging(second_paths)
        second_handler = _desktop_handler(logger)
    finally:
        module.close_desktop_logging(logger)

    assert same_logger is logger
    assert first_handler not in logger.handlers
    assert failing_stream.closed is True
    assert Path(second_handler.baseFilename) == (second_paths.log_dir / "desktop.log").resolve()


def test_exception_hooks_reinstall_when_the_active_hooks_were_replaced(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _desktop_logging_module()
    first_paths = _paths(tmp_path / "first")
    second_paths = _paths(tmp_path / "second")
    third_party_sys_calls: list[object] = []
    third_party_thread_calls: list[object] = []

    def original_sys_hook(*_args: object) -> None:
        return None

    def original_thread_hook(_args: object) -> None:
        return None

    def third_party_sys_hook(*args: object) -> None:
        third_party_sys_calls.append(args)

    def third_party_thread_hook(args: object) -> None:
        third_party_thread_calls.append(args)

    monkeypatch.setattr(sys, "excepthook", original_sys_hook)
    monkeypatch.setattr(threading, "excepthook", original_thread_hook)
    first_installation = module.install_exception_hooks(
        first_paths,
        state_provider=lambda: "first-state",
        app_version="0.2.2",
        platform_name="Windows-test",
        frozen=False,
    )
    monkeypatch.setattr(sys, "excepthook", third_party_sys_hook)
    monkeypatch.setattr(threading, "excepthook", third_party_thread_hook)
    second_installation = None
    try:
        second_installation = module.install_exception_hooks(
            second_paths,
            state_provider=lambda: "second-state",
            app_version="0.2.2",
            platform_name="Windows-test",
            frozen=False,
        )
        exception = _exception_with_traceback("reinstalled-hook-error")
        sys.excepthook(type(exception), exception, exception.__traceback__)
        args = SimpleNamespace(
            exc_type=type(exception),
            exc_value=exception,
            exc_traceback=exception.__traceback__,
            thread=SimpleNamespace(name="reinstalled-worker"),
        )
        threading.excepthook(args)
    finally:
        if second_installation is not None:
            second_installation.restore()
        first_installation.restore()

    assert second_installation is not first_installation
    assert len(third_party_sys_calls) == 1
    assert third_party_thread_calls == [args]
    assert not (first_paths.log_dir / "crash.log").exists()
    content = (second_paths.log_dir / "crash.log").read_text(encoding="utf-8")
    assert content.count("=== Uncaught desktop exception ===") == 2
    assert "state=second-state" in content


def test_exception_hooks_unwrap_a_retired_wrapper_restored_by_a_third_party(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _desktop_logging_module()
    first_paths = _paths(tmp_path / "first")
    second_paths = _paths(tmp_path / "second")
    original_sys_calls: list[object] = []

    def original_sys_hook(*args: object) -> None:
        original_sys_calls.append(args)

    def original_thread_hook(_args: object) -> None:
        return None

    monkeypatch.setattr(sys, "excepthook", original_sys_hook)
    monkeypatch.setattr(threading, "excepthook", original_thread_hook)
    first_installation = module.install_exception_hooks(
        first_paths,
        state_provider=lambda: "retired-state",
        app_version="0.2.2",
        platform_name="Windows-test",
        frozen=False,
    )
    captured_sys_hook = sys.excepthook
    captured_thread_hook = threading.excepthook

    def third_party_sys_hook(*args: object) -> object:
        return captured_sys_hook(*args)

    def third_party_thread_hook(args: object) -> object:
        return captured_thread_hook(args)

    monkeypatch.setattr(sys, "excepthook", third_party_sys_hook)
    monkeypatch.setattr(threading, "excepthook", third_party_thread_hook)
    first_installation.restore()
    monkeypatch.setattr(sys, "excepthook", captured_sys_hook)
    monkeypatch.setattr(threading, "excepthook", captured_thread_hook)

    second_installation = module.install_exception_hooks(
        second_paths,
        state_provider=lambda: "current-state",
        app_version="0.2.2",
        platform_name="Windows-test",
        frozen=False,
    )
    try:
        exception = _exception_with_traceback("current-hook-error")
        sys.excepthook(type(exception), exception, exception.__traceback__)
    finally:
        second_installation.restore()

    assert not (first_paths.log_dir / "crash.log").exists()
    content = (second_paths.log_dir / "crash.log").read_text(encoding="utf-8")
    assert content.count("=== Uncaught desktop exception ===") == 1
    assert "state=current-state" in content
    assert len(original_sys_calls) == 1
    assert sys.excepthook is original_sys_hook
    assert threading.excepthook is original_thread_hook


def test_retired_exception_hooks_only_delegate_when_a_third_party_still_chains_them(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _desktop_logging_module()
    first_paths = _paths(tmp_path / "first")
    second_paths = _paths(tmp_path / "second")
    original_sys_calls: list[object] = []
    original_thread_calls: list[object] = []

    def original_sys_hook(*args: object) -> None:
        original_sys_calls.append(args)

    def original_thread_hook(args: object) -> None:
        original_thread_calls.append(args)

    monkeypatch.setattr(sys, "excepthook", original_sys_hook)
    monkeypatch.setattr(threading, "excepthook", original_thread_hook)
    first_installation = module.install_exception_hooks(
        first_paths,
        state_provider=lambda: "retired-state",
        app_version="0.2.2",
        platform_name="Windows-test",
        frozen=False,
    )
    captured_sys_hook = sys.excepthook
    captured_thread_hook = threading.excepthook

    def third_party_sys_hook(*args: object) -> object:
        return captured_sys_hook(*args)

    def third_party_thread_hook(args: object) -> object:
        return captured_thread_hook(args)

    monkeypatch.setattr(sys, "excepthook", third_party_sys_hook)
    monkeypatch.setattr(threading, "excepthook", third_party_thread_hook)
    second_installation = module.install_exception_hooks(
        second_paths,
        state_provider=lambda: "current-state",
        app_version="0.2.2",
        platform_name="Windows-test",
        frozen=False,
    )
    try:
        exception = _exception_with_traceback("chained-hook-error")
        sys.excepthook(type(exception), exception, exception.__traceback__)
        args = SimpleNamespace(
            exc_type=type(exception),
            exc_value=exception,
            exc_traceback=exception.__traceback__,
            thread=SimpleNamespace(name="chained-worker"),
        )
        threading.excepthook(args)
    finally:
        second_installation.restore()
        first_installation.restore()

    assert not (first_paths.log_dir / "crash.log").exists()
    content = (second_paths.log_dir / "crash.log").read_text(encoding="utf-8")
    assert content.count("=== Uncaught desktop exception ===") == 2
    assert "state=current-state" in content
    assert len(original_sys_calls) == 1
    assert original_thread_calls == [args]


def test_desktop_logging_resolves_both_handler_paths_for_idempotency(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _desktop_logging_module()
    paths = _paths(tmp_path)
    log_path = paths.log_dir / "desktop.log"
    aliased_path = tmp_path / "resolved-target" / "desktop.log"
    original_resolve = Path.resolve

    def resolve_alias(path: Path, *args: object, **kwargs: object) -> Path:
        if path == log_path:
            return aliased_path
        return original_resolve(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", resolve_alias)
    logger = module.configure_desktop_logging(paths)
    first_handler = _desktop_handler(logger)
    try:
        same_logger = module.configure_desktop_logging(paths)
        second_handler = _desktop_handler(logger)
    finally:
        module.close_desktop_logging(logger)

    assert same_logger is logger
    assert second_handler is first_handler
