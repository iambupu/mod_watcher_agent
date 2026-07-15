from __future__ import annotations

import argparse
import logging
import multiprocessing
import os
import socket
import sys
import tempfile
import threading
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager, suppress
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx

from app.desktop.database_migration import migrate_legacy_database
from app.desktop.errors import format_desktop_startup_error, show_native_error
from app.desktop.single_instance import SingleInstanceGuard
from app.runtime_paths import (
    RuntimePaths,
    build_runtime_paths,
    configure_desktop_environment,
    ensure_runtime_directories,
    migrate_legacy_database_path_setting,
)

_APPLICATION_TITLE = "Mod Watcher Agent"
_DEFAULT_BACKEND_PORT = 17500
_SMOKE_HOST = "127.0.0.1"
_SMOKE_READY_TIMEOUT_SECONDS = 30.0
_SMOKE_HTTP_TIMEOUT_SECONDS = 5.0
_SMOKE_STOP_TIMEOUT_SECONDS = 10
_SMOKE_PORT_ENVIRONMENT_VARIABLE = "MW_SMOKE_PORT"
_SMOKE_PORT_MARKER_NAME = "smoke-port-used.txt"
_DESKTOP_ENVIRONMENT_KEYS = (
    "MW_DESKTOP_MODE",
    "MW_USER_DATA_DIR",
    "DATABASE_URL",
    "LOG_DIR",
    "MW_ENV_FILE",
    "GAME_ALIAS_FILE",
    _SMOKE_PORT_ENVIRONMENT_VARIABLE,
    "MW_BIND_HOST",
    "MW_ALLOW_LAN",
    "LOCAL_ONLY_API",
)


class DesktopSmokeError(RuntimeError):
    """Raised when the isolated desktop smoke check cannot complete."""


class DesktopBackendPortError(RuntimeError):
    """Raised before migration when the fixed desktop backend port is occupied."""


class _ReactIndexParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.has_root = False
        self.assets: list[str] = []
        self._seen_assets: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {name.casefold(): value for name, value in attrs}
        if attributes.get("id") == "root":
            self.has_root = True

        asset: str | None = None
        if tag.casefold() == "script":
            asset = attributes.get("src")
        elif tag.casefold() == "link":
            relationships = (attributes.get("rel") or "").casefold().split()
            if "stylesheet" in relationships:
                asset = attributes.get("href")
        if not asset:
            return

        parsed = urlsplit(asset)
        if parsed.scheme or parsed.netloc:
            return
        local_path = urljoin("/", asset)
        if local_path not in self._seen_assets:
            self._seen_assets.add(local_path)
            self.assets.append(local_path)


def configure_desktop_logging(paths: RuntimePaths) -> Any:
    from app.desktop.logging import configure_desktop_logging as configure

    return configure(paths)


def load_desktop_runtime_settings() -> Any:
    """Load the configured desktop .env before resolving bootstrap values."""

    from app.config import settings

    return settings


def close_desktop_logging(logger: Any) -> None:
    from app.desktop.logging import close_desktop_logging as close

    close(logger)


def install_desktop_exception_hooks(
    paths: RuntimePaths,
    state_provider: Callable[[], object],
) -> Any:
    from app.desktop.logging import install_exception_hooks

    return install_exception_hooks(paths, state_provider=state_provider)


def write_desktop_crash(paths: RuntimePaths, exception: BaseException, state: str) -> bool:
    from app.desktop.logging import write_crash_log

    return write_crash_log(
        paths.log_dir,
        exception,
        state=state,
        thread_name=threading.current_thread().name,
        user_data_dir=paths.user_root,
    )


def select_available_loopback_port() -> int:
    """Ask Windows for an unused loopback port instead of assuming 17500 is free."""

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind((_SMOKE_HOST, 0))
        return int(listener.getsockname()[1])


def desktop_backend_address() -> tuple[str, int]:
    raw_port = os.getenv("MW_BACKEND_PORT", str(_DEFAULT_BACKEND_PORT))
    try:
        port = int(raw_port, 10)
    except ValueError as exc:
        raise DesktopBackendPortError(
            "MW_BACKEND_PORT must be an integer between 1 and 65535"
        ) from exc
    if not 1 <= port <= 65535:
        raise DesktopBackendPortError("MW_BACKEND_PORT must be between 1 and 65535")
    return _SMOKE_HOST, port


@contextmanager
def reserve_desktop_backend_socket(host: str, port: int) -> Iterator[socket.socket]:
    """Hold the production port across migration and transfer it to Uvicorn."""

    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        listener.bind((host, port))
        listener.listen()
    except OSError as exc:
        listener.close()
        raise DesktopBackendPortError(
            f"Desktop backend port {host}:{port} is already in use; "
            "stop the existing Mod Watcher Agent service before starting the desktop client"
        ) from exc

    try:
        yield listener
    finally:
        listener.close()


def select_smoke_port() -> int:
    """Use the explicit packaged-smoke port when supplied, otherwise pick one."""
    raw_port = os.getenv(_SMOKE_PORT_ENVIRONMENT_VARIABLE)
    if raw_port is None:
        return select_available_loopback_port()
    if not raw_port or not raw_port.isascii() or not raw_port.isdecimal():
        raise DesktopSmokeError(
            "MW_SMOKE_PORT must be an ASCII decimal integer between 1 and 65535"
        )
    port = int(raw_port, 10)
    if not 1 <= port <= 65535:
        raise DesktopSmokeError("MW_SMOKE_PORT must be between 1 and 65535")
    return port


def build_smoke_server(host: str, port: int) -> Any:
    from app.desktop.backend_server import EmbeddedBackendServer

    return EmbeddedBackendServer(host=host, port=port)


def _record_smoke_port(paths: RuntimePaths, port: int) -> None:
    marker = f"MW_SMOKE_PORT_USED={port}"
    runtime_dir = Path(getattr(paths, "runtime_dir", Path(paths.user_root) / "runtime"))
    runtime_dir.mkdir(parents=True, exist_ok=True)
    (runtime_dir / _SMOKE_PORT_MARKER_NAME).write_text(
        f"{marker}\n",
        encoding="ascii",
    )
    stdout = getattr(sys, "stdout", None)
    if stdout is not None:
        print(marker, file=stdout, flush=True)


def release_smoke_runtime_resources(paths: RuntimePaths) -> None:
    """Release source-process database and file handles before temp cleanup."""

    user_root = Path(paths.user_root).resolve()
    db_module = sys.modules.get("app.db")
    engine = getattr(db_module, "engine", None) if db_module is not None else None
    database_name = getattr(getattr(engine, "url", None), "database", None)
    if engine is not None and database_name:
        try:
            database_path = Path(str(database_name)).resolve()
            database_path.relative_to(user_root)
        except (OSError, ValueError):
            pass
        else:
            with suppress(BaseException):
                engine.dispose()

    known_loggers = [logging.getLogger()]
    known_loggers.extend(
        logger
        for logger in logging.Logger.manager.loggerDict.values()
        if isinstance(logger, logging.Logger)
    )
    seen_handlers: set[int] = set()
    for logger in known_loggers:
        for handler in list(logger.handlers):
            if (
                id(handler) in seen_handlers
                or not isinstance(handler, logging.FileHandler)
                or handler.__dict__.get("_mod_watcher_desktop_handler", False)
            ):
                continue
            seen_handlers.add(id(handler))
            try:
                handler_path = Path(handler.baseFilename).resolve()
                handler_path.relative_to(user_root)
            except (OSError, ValueError):
                continue
            logger.removeHandler(handler)
            with suppress(BaseException):
                handler.close()


def _force_exit_after_smoke_stop_timeout(
    paths: RuntimePaths,
    error: BaseException,
) -> None:
    with suppress(BaseException):
        write_desktop_crash(paths, error, "smoke-stop-timeout")
    with suppress(BaseException):
        logging.getLogger("mod_watcher.desktop").critical(
            "Forcing process exit after desktop smoke backend shutdown timeout: %s",
            error,
        )
    try:
        logging.shutdown()
    finally:
        os._exit(1)


def run_smoke_test(
    paths: RuntimePaths,
    *,
    server_factory: Callable[[str, int], Any] | None = None,
    client_factory: Callable[..., Any] | None = None,
    port_selector: Callable[[], int] | None = None,
) -> int:
    """Start the real embedded backend and verify health plus the SPA root."""

    choose_port = port_selector or select_smoke_port
    make_server = server_factory or build_smoke_server
    make_client = client_factory or httpx.Client
    port = choose_port()
    server = make_server(_SMOKE_HOST, port)
    primary_error: BaseException | None = None

    try:
        server.start()
        if not server.wait_ready(_SMOKE_READY_TIMEOUT_SECONDS):
            detail = (
                str(server.error) if server.error is not None else "backend did not become ready"
            )
            raise DesktopSmokeError(f"Desktop smoke backend was not ready: {detail}")

        with make_client(
            base_url=f"http://{_SMOKE_HOST}:{port}",
            timeout=_SMOKE_HTTP_TIMEOUT_SECONDS,
            trust_env=False,
        ) as client:
            health_response = client.get("/api/health")
            try:
                health_payload = health_response.json()
            except ValueError as exc:
                raise DesktopSmokeError("Desktop smoke health returned invalid JSON") from exc
            if (
                health_response.status_code != 200
                or not isinstance(health_payload, dict)
                or health_payload.get("status") != "ok"
            ):
                raise DesktopSmokeError("Desktop smoke health check failed")
            if health_payload.get("frontend") != "ready":
                raise DesktopSmokeError("Desktop smoke frontend is not ready")

            root_response = client.get("/")
            content_type = root_response.headers.get("content-type", "").casefold()
            if root_response.status_code != 200 or not content_type.startswith("text/html"):
                raise DesktopSmokeError("Desktop smoke root did not return React HTML")
            root_html = root_response.text
            parser = _ReactIndexParser()
            parser.feed(root_html)
            if not root_html.strip() or not parser.has_root or not parser.assets:
                raise DesktopSmokeError("Desktop smoke root did not contain the React HTML shell")
            for asset_path in parser.assets:
                asset_response = client.get(asset_path)
                if asset_response.status_code != 200 or not asset_response.content:
                    raise DesktopSmokeError(f"Desktop smoke React asset failed: {asset_path}")
        _record_smoke_port(paths, port)
        return 0
    except BaseException as exc:
        primary_error = exc
        raise
    finally:
        cleanup_error: BaseException | None = None
        try:
            server.stop(timeout=_SMOKE_STOP_TIMEOUT_SECONDS)
        except BaseException as exc:
            cleanup_error = exc

        try:
            server_thread = server.thread
            server_thread.join(_SMOKE_STOP_TIMEOUT_SECONDS)
            if server_thread.is_alive() and cleanup_error is None:
                cleanup_error = DesktopSmokeError("Desktop smoke backend thread did not stop")
        except BaseException as exc:
            if cleanup_error is None:
                cleanup_error = exc

        if cleanup_error is not None and bool(
            getattr(cleanup_error, "requires_forced_exit", False)
        ):
            _force_exit_after_smoke_stop_timeout(paths, cleanup_error)
            raise cleanup_error

        release_smoke_runtime_resources(paths)
        if primary_error is None and cleanup_error is not None:
            raise cleanup_error


@contextmanager
def _isolated_smoke_environment() -> Iterator[Path]:
    original_environment = {key: os.environ.get(key) for key in _DESKTOP_ENVIRONMENT_KEYS}
    provided = os.getenv("MW_USER_DATA_DIR")
    temporary_directory: tempfile.TemporaryDirectory[str] | None = None

    if provided:
        user_root = Path(provided).expanduser()
        if not user_root.is_absolute():
            raise DesktopSmokeError("MW_USER_DATA_DIR must be an absolute smoke-test path")
        if user_root.exists() and (not user_root.is_dir() or any(user_root.iterdir())):
            raise DesktopSmokeError("MW_USER_DATA_DIR must be an empty smoke-test directory")
    else:
        temporary_directory = tempfile.TemporaryDirectory(prefix="mod-watcher-smoke-")
        user_root = Path(temporary_directory.name)

    os.environ["MW_USER_DATA_DIR"] = str(user_root)
    try:
        yield user_root
    finally:
        for key, value in original_environment.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        if temporary_directory is not None:
            temporary_directory.cleanup()


def build_desktop_controller(
    *,
    paths: RuntimePaths,
    guard: SingleInstanceGuard,
    backend_socket: socket.socket | None = None,
    backend_address: tuple[str, int] | None = None,
    admin_token: str | None = None,
) -> Any:
    """Build desktop adapters only after runtime setup and migration finish."""

    from app.desktop.backend_server import EmbeddedBackendServer
    from app.desktop.controller import DesktopController
    from app.desktop.tray import TrayController
    from app.desktop.window import PyWebViewWindow

    if backend_address is None or admin_token is None:
        settings = load_desktop_runtime_settings()
        if backend_address is None:
            backend_address = desktop_backend_address()
        if admin_token is None:
            admin_token = settings.MW_ADMIN_TOKEN

    host, port = backend_address
    base_url = f"http://{host}:{port}"
    server = EmbeddedBackendServer(
        host=host,
        port=port,
        prebound_socket=backend_socket,
    )
    window = PyWebViewWindow(paths=paths, url=base_url)
    tray = TrayController(
        paths=paths,
        base_url=base_url,
        admin_token=admin_token,
    )
    return DesktopController(
        server=server,
        window=window,
        tray=tray,
        guard=guard,
        paths=paths,
    )


def _run_normal_desktop() -> int:
    guard: SingleInstanceGuard | None = None
    controller: Any | None = None
    paths: RuntimePaths | None = None
    desktop_logger: Any | None = None
    logging_configured = False
    hook_installation: Any | None = None
    lifecycle_state = "starting"

    def current_state() -> object:
        if controller is not None:
            return getattr(controller, "state", lifecycle_state)
        return lifecycle_state

    try:
        paths = build_runtime_paths()
        ensure_runtime_directories(paths)
        if migrate_legacy_database_path_setting(paths):
            paths = build_runtime_paths()
            ensure_runtime_directories(paths)
        configure_desktop_environment(paths)
        runtime_settings = load_desktop_runtime_settings()
        desktop_logger = configure_desktop_logging(paths)
        logging_configured = True
        desktop_logger.info("Desktop startup mode=normal")
        desktop_logger.info("Runtime directories ready: %s", paths.user_root)
        hook_installation = install_desktop_exception_hooks(paths, current_state)

        guard = SingleInstanceGuard(paths.runtime_dir / "desktop.lock")
        if not guard.acquire():
            desktop_logger.warning("Single desktop instance already active")
            show_native_error(
                _APPLICATION_TITLE,
                "程序已在运行，请从系统托盘打开。",
            )
            return 0
        desktop_logger.info("Single desktop instance acquired")

        host, port = desktop_backend_address()
        with reserve_desktop_backend_socket(host, port) as backend_socket:
            desktop_logger.info("Desktop backend port reserved: %s:%s", host, port)
            migrate_legacy_database(paths)
            desktop_logger.info("Legacy database migration completed")
            controller = build_desktop_controller(
                paths=paths,
                guard=guard,
                backend_socket=backend_socket,
                backend_address=(host, port),
                admin_token=runtime_settings.MW_ADMIN_TOKEN,
            )
            lifecycle_state = "running"
            desktop_logger.info("Desktop controller starting")
            result = int(controller.start())
            desktop_logger.info("Desktop controller finished with result=%s", result)
            if result != 0:
                error = getattr(controller, "error", None)
                detail = str(error) if error is not None else "桌面生命周期未正常结束"
                show_native_error(
                    _APPLICATION_TITLE,
                    format_desktop_startup_error(detail),
                )
                desktop_logger.error("Desktop controller reported failure: %s", detail)
            return result
    except BaseException as exc:
        lifecycle_state = "failed"
        if controller is not None:
            with suppress(BaseException):
                controller.shutdown("startup-error")
        if paths is not None:
            write_desktop_crash(paths, exc, lifecycle_state)
        if desktop_logger is not None:
            desktop_logger.exception("Desktop application failed")
        show_native_error(
            _APPLICATION_TITLE,
            format_desktop_startup_error(exc),
        )
        return 1
    finally:
        if guard is not None and controller is None:
            guard.release()
        if hook_installation is not None:
            hook_installation.restore()
        if logging_configured:
            desktop_logger.info("Desktop shutdown complete")
            close_desktop_logging(desktop_logger)


def _run_smoke_mode() -> int:
    try:
        with _isolated_smoke_environment():
            paths = build_runtime_paths()
            desktop_logger: Any | None = None
            logging_configured = False
            hook_installation: Any | None = None
            lifecycle_state = "smoke-starting"

            try:
                ensure_runtime_directories(paths)
                configure_desktop_environment(paths)
                desktop_logger = configure_desktop_logging(paths)
                logging_configured = True
                desktop_logger.info("Desktop startup mode=smoke-test")
                desktop_logger.info("Runtime directories ready: %s", paths.user_root)
                hook_installation = install_desktop_exception_hooks(
                    paths,
                    lambda: lifecycle_state,
                )
                lifecycle_state = "smoke-running"
                desktop_logger.info("Desktop smoke test starting")
                result = int(run_smoke_test(paths))
                desktop_logger.info("Desktop smoke test succeeded")
                return result
            except BaseException as exc:
                lifecycle_state = "smoke-failed"
                write_desktop_crash(paths, exc, lifecycle_state)
                if desktop_logger is not None:
                    desktop_logger.exception("Desktop smoke test failed")
                return 1
            finally:
                if hook_installation is not None:
                    hook_installation.restore()
                if logging_configured:
                    desktop_logger.info("Desktop smoke shutdown complete")
                    close_desktop_logging(desktop_logger)
    except BaseException:
        return 1


def main(argv: Sequence[str] | None = None) -> int:
    multiprocessing.freeze_support()
    parser = argparse.ArgumentParser(prog="ModWatcherAgent")
    parser.add_argument("--smoke-test", action="store_true")
    args = parser.parse_args(list(argv or ()))
    if args.smoke_test:
        return _run_smoke_mode()
    return _run_normal_desktop()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
