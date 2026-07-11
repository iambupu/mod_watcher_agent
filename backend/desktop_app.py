from __future__ import annotations

import multiprocessing
import os
from contextlib import suppress
from typing import Any

from app.desktop.database_migration import migrate_legacy_database
from app.desktop.errors import show_native_error
from app.desktop.single_instance import SingleInstanceGuard
from app.runtime_paths import (
    RuntimePaths,
    build_runtime_paths,
    configure_desktop_environment,
    ensure_runtime_directories,
)

_APPLICATION_TITLE = "Mod Watcher Agent"
_DEFAULT_BACKEND_PORT = 17500


def build_desktop_controller(
    *,
    paths: RuntimePaths,
    guard: SingleInstanceGuard,
) -> Any:
    """Build desktop adapters only after runtime setup and migration finish."""

    from app.desktop.backend_server import EmbeddedBackendServer
    from app.desktop.controller import DesktopController
    from app.desktop.tray import TrayController
    from app.desktop.window import PyWebViewWindow

    host = "127.0.0.1"
    port = int(os.getenv("MW_BACKEND_PORT", str(_DEFAULT_BACKEND_PORT)))
    base_url = f"http://{host}:{port}"
    server = EmbeddedBackendServer(host=host, port=port)
    window = PyWebViewWindow(paths=paths, url=base_url)
    tray = TrayController(paths=paths, base_url=base_url)
    return DesktopController(
        server=server,
        window=window,
        tray=tray,
        guard=guard,
        paths=paths,
    )


def main() -> int:
    multiprocessing.freeze_support()
    guard: SingleInstanceGuard | None = None
    controller: Any | None = None

    try:
        paths = build_runtime_paths()
        ensure_runtime_directories(paths)
        configure_desktop_environment(paths)

        guard = SingleInstanceGuard(paths.runtime_dir / "desktop.lock")
        if not guard.acquire():
            show_native_error(
                _APPLICATION_TITLE,
                "程序已在运行，请从系统托盘打开。",
            )
            return 0

        migrate_legacy_database(paths)
        controller = build_desktop_controller(paths=paths, guard=guard)
        result = int(controller.start())
        if result != 0:
            error = getattr(controller, "error", None)
            detail = str(error) if error is not None else "桌面生命周期未正常结束"
            show_native_error(
                _APPLICATION_TITLE,
                f"桌面客户端启动失败：{detail}",
            )
        return result
    except BaseException as exc:
        if controller is not None:
            with suppress(BaseException):
                controller.shutdown("startup-error")
        show_native_error(
            _APPLICATION_TITLE,
            f"桌面客户端启动失败：{exc}",
        )
        return 1
    finally:
        if guard is not None and controller is None:
            guard.release()


if __name__ == "__main__":
    raise SystemExit(main())
