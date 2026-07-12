from __future__ import annotations

import importlib.metadata
import logging
import logging.handlers
import platform
import re
import sys
import threading
import traceback
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType
from typing import Any

from app import runtime_paths
from app.logger import redact_sensitive_text

_DESKTOP_LOGGER_NAME = "mod_watcher.desktop"
_DESKTOP_LOG_MAX_BYTES = 5 * 1024 * 1024
_DESKTOP_LOG_BACKUP_COUNT = 3
_DESKTOP_SECRET_PATTERNS = (
    (
        re.compile(r"(?i)\bBearer\s+[^\s,\"']+"),
        "Bearer ********",
    ),
    (
        re.compile(
            r"""(?ix)
            (?P<prefix>["']?\b(?:
                authorization
                |webhook
                |(?:[a-z0-9]+_)*(?:api_key|token|password)
            )\b["']?\s*[:=]\s*)
            (?:"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|[^\s,}\]]+)
            """
        ),
        r"\g<prefix>********",
    ),
    (
        re.compile(r"(?im)(?P<prefix>[\"']?\bCookie\b[\"']?\s*[:=]\s*)[^\r\n]+"),
        r"\g<prefix>********",
    ),
    (
        re.compile(
            r"(?is)(?P<prefix>[\"']?\b(?:profile_content|profile_data)\b[\"']?\s*[:=]\s*).*\Z"
        ),
        r"\g<prefix>********",
    ),
)
_HOOK_INSTALLATION_ATTRIBUTE = "_mod_watcher_exception_hook_installation"

_configuration_lock = threading.Lock()
_hook_lock = threading.Lock()
_active_hook_installation: ExceptionHookInstallation | None = None


def _redact_desktop_text(text: str) -> str:
    redacted = redact_sensitive_text(text)
    for pattern, replacement in _DESKTOP_SECRET_PATTERNS:
        redacted = pattern.sub(replacement, redacted)
    return redacted


class _RedactingFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return _redact_desktop_text(super().format(record))


class _RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except BaseException:
            message = "<unformattable log message>"
        record.msg = _redact_desktop_text(message)
        record.args = ()
        if record.exc_text:
            record.exc_text = _redact_desktop_text(record.exc_text)
        if record.stack_info:
            record.stack_info = _redact_desktop_text(record.stack_info)
        return True


class _SafeRotatingFileHandler(logging.handlers.RotatingFileHandler):
    def handleError(self, record: logging.LogRecord) -> None:  # noqa: N802
        # The stdlib implementation dumps raw msg/args to stderr when enabled.
        # A log-media failure must neither expose those values nor recurse.
        return None


def _resolve_log_path(path: Path) -> Path:
    try:
        return path.resolve()
    except (OSError, RuntimeError):
        return path.absolute()


def _close_handler_safely(handler: logging.Handler) -> None:
    try:
        handler.close()
    except BaseException:
        return


def configure_desktop_logging(paths: object) -> logging.Logger:
    """Configure one rotating, fully redacted desktop log handler."""

    logger = logging.getLogger(_DESKTOP_LOGGER_NAME)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    log_path = Path(paths.log_dir)  # type: ignore[attr-defined]
    log_path /= "desktop.log"
    resolved_log_path = _resolve_log_path(log_path)

    with _configuration_lock:
        if not any(
            isinstance(current_filter, _RedactingFilter) for current_filter in logger.filters
        ):
            logger.addFilter(_RedactingFilter())
        matching_handler = next(
            (
                handler
                for handler in logger.handlers
                if getattr(handler, "_mod_watcher_desktop_handler", False)
                and _resolve_log_path(Path(getattr(handler, "baseFilename", "")))
                == resolved_log_path
            ),
            None,
        )
        if matching_handler is not None:
            return logger

        for handler in list(logger.handlers):
            if not getattr(handler, "_mod_watcher_desktop_handler", False):
                continue
            logger.removeHandler(handler)
            _close_handler_safely(handler)

        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            handler = _SafeRotatingFileHandler(
                log_path,
                maxBytes=_DESKTOP_LOG_MAX_BYTES,
                backupCount=_DESKTOP_LOG_BACKUP_COUNT,
                encoding="utf-8",
            )
        except OSError:
            return logger

        handler._mod_watcher_desktop_handler = True  # type: ignore[attr-defined]
        handler.addFilter(_RedactingFilter())
        handler.setFormatter(
            _RedactingFormatter(
                "[%(asctime)s] %(levelname)-7s %(name)s - %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
        logger.addHandler(handler)
    return logger


def close_desktop_logging(logger: logging.Logger | None = None) -> None:
    """Close desktop file handlers so isolated smoke directories can be removed."""

    target = logger or logging.getLogger(_DESKTOP_LOGGER_NAME)
    with _configuration_lock:
        for handler in list(target.handlers):
            if not getattr(handler, "_mod_watcher_desktop_handler", False):
                continue
            target.removeHandler(handler)
            _close_handler_safely(handler)


def _application_version() -> str:
    try:
        return importlib.metadata.version("mod-watcher-agent")
    except importlib.metadata.PackageNotFoundError:
        return "unknown"


def write_crash_log(
    log_dir: Path,
    exception: BaseException,
    *,
    state: str,
    thread_name: str,
    app_version: str | None = None,
    platform_name: str | None = None,
    frozen: bool | None = None,
    user_data_dir: Path | None = None,
    traceback_object: TracebackType | None = None,
) -> bool:
    """Append a redacted crash record and contain all write failures."""

    try:
        resolved_log_dir = Path(log_dir)
        resolved_log_dir.mkdir(parents=True, exist_ok=True)
        trace = "".join(
            traceback.format_exception(
                type(exception),
                exception,
                traceback_object if traceback_object is not None else exception.__traceback__,
            )
        )
        record = "\n".join(
            (
                "=== Uncaught desktop exception ===",
                f"timestamp={datetime.now(UTC).isoformat()}",
                f"application_version={app_version or _application_version()}",
                f"platform={platform_name or platform.platform()}",
                f"frozen={str(runtime_paths.is_frozen() if frozen is None else frozen).lower()}",
                f"user_data_dir={user_data_dir or resolved_log_dir.parent}",
                f"thread={thread_name}",
                f"state={state}",
                f"exception_type={type(exception).__name__}",
                trace.rstrip(),
                "",
            )
        )
        with (resolved_log_dir / "crash.log").open("a", encoding="utf-8") as handle:
            handle.write(_redact_desktop_text(record))
        return True
    except BaseException:
        return False


class ExceptionHookInstallation:
    def __init__(
        self,
        *,
        original_sys_hook: Callable[
            [type[BaseException], BaseException, TracebackType | None], Any
        ],
        original_thread_hook: Callable[[Any], Any],
        sys_hook: Callable[[type[BaseException], BaseException, TracebackType | None], Any],
        thread_hook: Callable[[Any], Any],
    ) -> None:
        self.original_sys_hook = original_sys_hook
        self.original_thread_hook = original_thread_hook
        self.sys_hook = sys_hook
        self.thread_hook = thread_hook
        self._restored = False

    def restore(self) -> None:
        global _active_hook_installation
        with _hook_lock:
            if self._restored:
                return
            self._restored = True
            if sys.excepthook is self.sys_hook:
                sys.excepthook = self.original_sys_hook
            if threading.excepthook is self.thread_hook:
                threading.excepthook = self.original_thread_hook
            if _active_hook_installation is self:
                _active_hook_installation = None


def _unwrap_retired_hook(hook: Callable[..., Any], *, is_thread_hook: bool) -> Callable[..., Any]:
    seen: set[int] = set()
    while id(hook) not in seen:
        seen.add(id(hook))
        installation = getattr(hook, _HOOK_INSTALLATION_ATTRIBUTE, None)
        if not isinstance(installation, ExceptionHookInstallation) or not installation._restored:
            return hook
        if is_thread_hook and hook is installation.thread_hook:
            hook = installation.original_thread_hook
            continue
        if not is_thread_hook and hook is installation.sys_hook:
            hook = installation.original_sys_hook
            continue
        return hook
    return hook


def install_exception_hooks(
    paths: object,
    *,
    state_provider: Callable[[], object],
    app_version: str | None = None,
    platform_name: str | None = None,
    frozen: bool | None = None,
) -> ExceptionHookInstallation:
    """Install idempotent crash hooks that preserve the process' original hooks."""

    global _active_hook_installation
    with _hook_lock:
        if _active_hook_installation is not None:
            if (
                sys.excepthook is _active_hook_installation.sys_hook
                and threading.excepthook is _active_hook_installation.thread_hook
            ):
                return _active_hook_installation
            _active_hook_installation._restored = True
            _active_hook_installation = None

        original_sys_hook = _unwrap_retired_hook(sys.excepthook, is_thread_hook=False)
        original_thread_hook = _unwrap_retired_hook(
            threading.excepthook,
            is_thread_hook=True,
        )
        log_dir = Path(paths.log_dir)  # type: ignore[attr-defined]
        user_data_dir = Path(paths.user_root)  # type: ignore[attr-defined]

        def current_state() -> str:
            try:
                return str(state_provider())
            except BaseException:
                return "unknown"

        def sys_hook(
            exc_type: type[BaseException],
            exc_value: BaseException,
            exc_traceback: TracebackType | None,
        ) -> Any:
            if not installation._restored:
                write_crash_log(
                    log_dir,
                    exc_value,
                    state=current_state(),
                    thread_name=threading.current_thread().name,
                    app_version=app_version,
                    platform_name=platform_name,
                    frozen=frozen,
                    user_data_dir=user_data_dir,
                    traceback_object=exc_traceback,
                )
            return original_sys_hook(exc_type, exc_value, exc_traceback)

        def thread_hook(args: Any) -> Any:
            thread = getattr(args, "thread", None)
            if not installation._restored:
                write_crash_log(
                    log_dir,
                    args.exc_value,
                    state=current_state(),
                    thread_name=getattr(thread, "name", "unknown-thread"),
                    app_version=app_version,
                    platform_name=platform_name,
                    frozen=frozen,
                    user_data_dir=user_data_dir,
                    traceback_object=args.exc_traceback,
                )
            return original_thread_hook(args)

        installation = ExceptionHookInstallation(
            original_sys_hook=original_sys_hook,
            original_thread_hook=original_thread_hook,
            sys_hook=sys_hook,
            thread_hook=thread_hook,
        )
        setattr(sys_hook, _HOOK_INSTALLATION_ATTRIBUTE, installation)
        setattr(thread_hook, _HOOK_INSTALLATION_ATTRIBUTE, installation)
        sys.excepthook = sys_hook
        threading.excepthook = thread_hook
        _active_hook_installation = installation
        return installation
