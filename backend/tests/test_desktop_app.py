from __future__ import annotations

import importlib
import os
import socket
import subprocess
import sys
import threading
import tomllib
from collections.abc import Callable
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest


def test_pyproject_separates_desktop_runtime_and_packaging_extras() -> None:
    backend_dir = Path(__file__).resolve().parents[1]
    project = tomllib.loads((backend_dir / "pyproject.toml").read_text(encoding="utf-8"))
    dependencies = project["project"]["dependencies"]
    extras = project["project"]["optional-dependencies"]

    assert extras["desktop"] == [
        "pywebview>=6.0,<7",
        "pystray>=0.19.5",
        "Pillow>=10",
    ]
    assert extras["packaging"] == ["pyinstaller>=6,<7"]
    assert all(
        not dependency.lower().startswith(("pywebview", "pystray", "pillow"))
        for dependency in dependencies
    )
    assert {"pytest>=8.2.0", "ruff>=0.11.0"}.issubset(extras["dev"])


def test_source_launcher_installs_and_checks_desktop_tray_extra() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    launcher = (repo_root / "start.ps1").read_text(encoding="utf-8")

    assert '-e ".[desktop]"' in launcher
    assert '$requiredDesktopModules = @("pystray", "PIL")' in launcher
    assert "foreach ($desktopModule in $requiredDesktopModules)" in launcher


def _desktop_entry_module() -> ModuleType:
    try:
        return importlib.import_module("desktop_app")
    except ModuleNotFoundError:
        pytest.fail("backend.desktop_app is not implemented", pytrace=False)


def _desktop_errors_module() -> ModuleType:
    try:
        return importlib.import_module("app.desktop.errors")
    except ModuleNotFoundError:
        pytest.fail("app.desktop.errors is not implemented", pytrace=False)


class FakeEntryGuard:
    def __init__(
        self,
        history: list[str],
        lock_path: Path,
        *,
        acquired: bool = True,
    ) -> None:
        self.history = history
        self.lock_path = lock_path
        self.acquired = acquired
        self.release_calls = 0
        self.history.append("guard.construct")

    def acquire(self) -> bool:
        self.history.append("guard.acquire")
        return self.acquired

    def release(self) -> None:
        self.release_calls += 1
        self.history.append("guard.release")


class FakeEntryController:
    def __init__(
        self,
        history: list[str],
        *,
        result: int = 0,
        error: BaseException | None = None,
        on_start: Callable[[], None] | None = None,
    ) -> None:
        self.history = history
        self.result = result
        self.error = error
        self.on_start = on_start
        self.shutdown_calls = 0

    def start(self) -> int:
        self.history.append("controller.start")
        if self.on_start is not None:
            self.on_start()
        if self.error is not None:
            raise self.error
        return self.result

    def shutdown(self, reason: str) -> None:
        self.shutdown_calls += 1
        self.history.append(f"controller.shutdown:{reason}")


class FakeHookInstallation:
    def __init__(self, history: list[str]) -> None:
        self.history = history
        self.restore_calls = 0

    def restore(self) -> None:
        self.restore_calls += 1
        self.history.append("hooks.restore")


class RecordingDesktopLogger:
    def __init__(self, messages: list[str]) -> None:
        self.messages = messages

    @staticmethod
    def _format(message: str, args: tuple[object, ...]) -> str:
        return message % args if args else message

    def info(self, message: str, *args: object) -> None:
        self.messages.append(f"INFO {self._format(message, args)}")

    def warning(self, message: str, *args: object) -> None:
        self.messages.append(f"WARNING {self._format(message, args)}")

    def error(self, message: str, *args: object) -> None:
        self.messages.append(f"ERROR {self._format(message, args)}")

    def exception(self, message: str, *args: object) -> None:
        self.messages.append(f"EXCEPTION {self._format(message, args)}")


def test_desktop_entry_follows_required_initialization_order(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _desktop_entry_module()
    history: list[str] = []
    log_messages: list[str] = []
    paths = SimpleNamespace(
        user_root=tmp_path,
        runtime_dir=tmp_path / "runtime",
        log_dir=tmp_path / "logs",
    )
    guard_holder: list[FakeEntryGuard] = []
    hooks = FakeHookInstallation(history)
    desktop_logger = RecordingDesktopLogger(log_messages)
    controller = FakeEntryController(
        history,
        on_start=lambda: guard_holder[0].release(),
    )
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as available:
        available.bind(("127.0.0.1", 0))
        backend_port = int(available.getsockname()[1])
    monkeypatch.setenv("MW_BACKEND_PORT", "17500")
    reserved_sockets: list[socket.socket] = []

    def guard_factory(lock_path: Path) -> FakeEntryGuard:
        guard = FakeEntryGuard(history, lock_path)
        guard_holder.append(guard)
        return guard

    monkeypatch.setattr(module.multiprocessing, "freeze_support", lambda: history.append("freeze"))
    monkeypatch.setattr(
        module, "build_runtime_paths", lambda: history.append("paths.build") or paths
    )
    monkeypatch.setattr(
        module,
        "ensure_runtime_directories",
        lambda value: history.append("paths.ensure") if value is paths else None,
    )
    monkeypatch.setattr(
        module,
        "configure_desktop_environment",
        lambda value: history.append("env.configure") if value is paths else None,
    )

    def load_runtime_settings() -> object:
        history.append("settings.load")
        os.environ["MW_BACKEND_PORT"] = str(backend_port)
        return SimpleNamespace(MW_ADMIN_TOKEN="entry-secret")

    monkeypatch.setattr(module, "load_desktop_runtime_settings", load_runtime_settings)
    monkeypatch.setattr(
        module,
        "configure_desktop_logging",
        lambda value: (
            history.append("logging.configure") or desktop_logger if value is paths else None
        ),
        raising=False,
    )
    monkeypatch.setattr(
        module,
        "install_desktop_exception_hooks",
        lambda value, state_provider: (
            history.append("hooks.install") or hooks
            if value is paths and state_provider() == "starting"
            else None
        ),
        raising=False,
    )
    monkeypatch.setattr(
        module,
        "close_desktop_logging",
        lambda _logger: history.append("logging.close"),
        raising=False,
    )
    monkeypatch.setattr(module, "SingleInstanceGuard", guard_factory)

    def migrate_database(value: object) -> None:
        assert value is paths
        with socket.create_connection(("127.0.0.1", backend_port), timeout=1):
            pass
        with (
            socket.socket(socket.AF_INET, socket.SOCK_STREAM) as competing_listener,
            pytest.raises(OSError),
        ):
            competing_listener.bind(("127.0.0.1", backend_port))
        history.append("database.migrate")

    monkeypatch.setattr(module, "migrate_legacy_database", migrate_database)

    def build_controller(
        *,
        paths: object,
        guard: object,
        backend_socket: socket.socket,
        backend_address: tuple[str, int],
        admin_token: str,
    ):
        assert paths is not None
        assert guard is not None
        assert backend_socket.getsockname() == ("127.0.0.1", backend_port)
        assert backend_address == ("127.0.0.1", backend_port)
        assert admin_token == "entry-secret"
        reserved_sockets.append(backend_socket)
        history.append("controller.build")
        return controller

    monkeypatch.setattr(
        module,
        "build_desktop_controller",
        build_controller,
    )
    monkeypatch.setattr(
        module,
        "show_native_error",
        lambda *_args: pytest.fail("success path must not show an error"),
    )

    assert module.main() == 0

    assert history == [
        "freeze",
        "paths.build",
        "paths.ensure",
        "env.configure",
        "settings.load",
        "logging.configure",
        "hooks.install",
        "guard.construct",
        "guard.acquire",
        "database.migrate",
        "controller.build",
        "controller.start",
        "guard.release",
        "hooks.restore",
        "logging.close",
    ]
    assert guard_holder[0].lock_path == paths.runtime_dir / "desktop.lock"
    assert guard_holder[0].release_calls == 1
    assert hooks.restore_calls == 1
    assert len(reserved_sockets) == 1
    assert reserved_sockets[0].fileno() == -1
    assert log_messages == [
        "INFO Desktop startup mode=normal",
        f"INFO Runtime directories ready: {paths.user_root}",
        "INFO Single desktop instance acquired",
        f"INFO Desktop backend port reserved: 127.0.0.1:{backend_port}",
        "INFO Legacy database migration completed",
        "INFO Desktop controller starting",
        "INFO Desktop controller finished with result=0",
        "INFO Desktop shutdown complete",
    ]


def test_build_desktop_controller_wires_reserved_socket_and_admin_token(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from app.desktop import backend_server, controller, tray, window

    module = _desktop_entry_module()
    captured: dict[str, dict[str, object]] = {}
    sentinels = {
        "server": object(),
        "window": object(),
        "tray": object(),
        "controller": object(),
    }
    paths = SimpleNamespace(user_root=tmp_path)
    guard = object()

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as reserved_socket:
        reserved_socket.bind(("127.0.0.1", 0))
        port = int(reserved_socket.getsockname()[1])
        monkeypatch.setenv("MW_BACKEND_PORT", str(port))
        monkeypatch.setattr(
            module,
            "load_desktop_runtime_settings",
            lambda: pytest.fail("explicit bootstrap values must not be reloaded"),
        )

        def server_factory(**kwargs: object) -> object:
            captured["server"] = kwargs
            return sentinels["server"]

        def window_factory(**kwargs: object) -> object:
            captured["window"] = kwargs
            return sentinels["window"]

        def tray_factory(**kwargs: object) -> object:
            captured["tray"] = kwargs
            return sentinels["tray"]

        def controller_factory(**kwargs: object) -> object:
            captured["controller"] = kwargs
            return sentinels["controller"]

        monkeypatch.setattr(backend_server, "EmbeddedBackendServer", server_factory)
        monkeypatch.setattr(window, "PyWebViewWindow", window_factory)
        monkeypatch.setattr(tray, "TrayController", tray_factory)
        monkeypatch.setattr(controller, "DesktopController", controller_factory)

        result = module.build_desktop_controller(
            paths=paths,
            guard=guard,
            backend_socket=reserved_socket,
            backend_address=("127.0.0.1", port),
            admin_token="desktop-secret",
        )

    assert result is sentinels["controller"]
    assert captured["server"] == {
        "host": "127.0.0.1",
        "port": port,
        "prebound_socket": reserved_socket,
    }
    assert captured["window"] == {
        "paths": paths,
        "url": f"http://127.0.0.1:{port}",
    }
    assert captured["tray"] == {
        "paths": paths,
        "base_url": f"http://127.0.0.1:{port}",
        "admin_token": "desktop-secret",
    }
    assert captured["controller"] == {
        "server": sentinels["server"],
        "window": sentinels["window"],
        "tray": sentinels["tray"],
        "guard": guard,
        "paths": paths,
    }


def test_entry_does_not_release_guard_again_after_controller_owns_lifecycle(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _desktop_entry_module()
    paths = SimpleNamespace(
        user_root=tmp_path,
        runtime_dir=tmp_path / "runtime",
        log_dir=tmp_path / "logs",
    )
    history: list[str] = []
    guard = FakeEntryGuard(history, paths.runtime_dir / "desktop.lock")

    class OwningController:
        error = None

        def start(self) -> int:
            guard.release()
            return 0

    monkeypatch.setattr(module.multiprocessing, "freeze_support", lambda: None)
    monkeypatch.setattr(module, "build_runtime_paths", lambda: paths)
    monkeypatch.setattr(module, "ensure_runtime_directories", lambda _paths: None)
    monkeypatch.setattr(module, "configure_desktop_environment", lambda _paths: None)
    monkeypatch.setattr(module, "SingleInstanceGuard", lambda _path: guard)
    monkeypatch.setattr(module, "migrate_legacy_database", lambda _paths: None)
    monkeypatch.setattr(module, "build_desktop_controller", lambda **_kwargs: OwningController())
    monkeypatch.setattr(
        module,
        "show_native_error",
        lambda *_args: pytest.fail("success path must not show an error"),
    )

    assert module.main() == 0
    assert guard.release_calls == 1


def test_second_instance_returns_zero_without_migration_server_or_window(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _desktop_entry_module()
    history: list[str] = []
    messages: list[tuple[str, str]] = []
    paths = SimpleNamespace(
        user_root=tmp_path,
        runtime_dir=tmp_path / "runtime",
        log_dir=tmp_path / "logs",
    )
    guard = FakeEntryGuard(history, paths.runtime_dir / "desktop.lock", acquired=False)

    monkeypatch.setattr(module.multiprocessing, "freeze_support", lambda: history.append("freeze"))
    monkeypatch.setattr(
        module, "build_runtime_paths", lambda: history.append("paths.build") or paths
    )
    monkeypatch.setattr(
        module, "ensure_runtime_directories", lambda _paths: history.append("paths.ensure")
    )
    monkeypatch.setattr(
        module, "configure_desktop_environment", lambda _paths: history.append("env.configure")
    )
    monkeypatch.setattr(module, "SingleInstanceGuard", lambda _path: guard)
    monkeypatch.setattr(
        module,
        "migrate_legacy_database",
        lambda _paths: pytest.fail("second instance must not migrate data"),
    )
    monkeypatch.setattr(
        module,
        "build_desktop_controller",
        lambda **_kwargs: pytest.fail("second instance must not construct desktop services"),
    )
    monkeypatch.setattr(
        module, "show_native_error", lambda title, text: messages.append((title, text))
    )

    assert module.main() == 0

    assert history == [
        "guard.construct",
        "freeze",
        "paths.build",
        "paths.ensure",
        "env.configure",
        "guard.acquire",
        "guard.release",
    ]
    assert messages == [("Mod Watcher Agent", "程序已在运行，请从系统托盘打开。")]


def test_entry_start_failure_shows_native_error_and_releases_everything(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _desktop_entry_module()
    history: list[str] = []
    messages: list[tuple[str, str]] = []
    paths = SimpleNamespace(
        user_root=tmp_path,
        runtime_dir=tmp_path / "runtime",
        log_dir=tmp_path / "logs",
    )
    guard = FakeEntryGuard(history, paths.runtime_dir / "desktop.lock")
    controller = FakeEntryController(
        history,
        error=RuntimeError("WebView2 unavailable"),
        on_start=guard.release,
    )

    monkeypatch.setattr(module.multiprocessing, "freeze_support", lambda: history.append("freeze"))
    monkeypatch.setattr(module, "build_runtime_paths", lambda: paths)
    monkeypatch.setattr(module, "ensure_runtime_directories", lambda _paths: None)
    monkeypatch.setattr(module, "configure_desktop_environment", lambda _paths: None)
    monkeypatch.setattr(module, "SingleInstanceGuard", lambda _path: guard)
    monkeypatch.setattr(module, "migrate_legacy_database", lambda _paths: None)
    monkeypatch.setattr(module, "build_desktop_controller", lambda **_kwargs: controller)
    monkeypatch.setattr(
        module, "show_native_error", lambda title, text: messages.append((title, text))
    )

    assert module.main() == 1

    assert controller.shutdown_calls == 1
    assert guard.release_calls == 1
    assert messages and messages[0][0] == "Mod Watcher Agent"
    assert "WebView2 unavailable" in messages[0][1]
    assert "未检测到可用的 Microsoft Edge WebView2 Runtime" in messages[0][1]
    assert "https://developer.microsoft.com/microsoft-edge/webview2/" in messages[0][1]


def test_entry_migration_failure_releases_guard_without_building_controller(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _desktop_entry_module()
    paths = SimpleNamespace(
        user_root=tmp_path,
        runtime_dir=tmp_path / "runtime",
        log_dir=tmp_path / "logs",
    )
    history: list[str] = []
    messages: list[str] = []
    guard = FakeEntryGuard(history, paths.runtime_dir / "desktop.lock")

    monkeypatch.setattr(module.multiprocessing, "freeze_support", lambda: None)
    monkeypatch.setattr(module, "build_runtime_paths", lambda: paths)
    monkeypatch.setattr(module, "ensure_runtime_directories", lambda _paths: None)
    monkeypatch.setattr(module, "configure_desktop_environment", lambda _paths: None)
    monkeypatch.setattr(module, "SingleInstanceGuard", lambda _path: guard)
    monkeypatch.setattr(
        module,
        "migrate_legacy_database",
        lambda _paths: (_ for _ in ()).throw(RuntimeError("migration failed")),
    )
    monkeypatch.setattr(
        module,
        "build_desktop_controller",
        lambda **_kwargs: pytest.fail("controller must be lazy until migration succeeds"),
    )
    monkeypatch.setattr(module, "show_native_error", lambda _title, text: messages.append(text))

    assert module.main() == 1
    assert guard.release_calls == 1
    assert messages == ["桌面客户端启动失败：migration failed"]


def test_occupied_backend_port_aborts_before_database_migration(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _desktop_entry_module()
    paths = SimpleNamespace(
        user_root=tmp_path,
        runtime_dir=tmp_path / "runtime",
        log_dir=tmp_path / "logs",
    )
    history: list[str] = []
    messages: list[str] = []
    guard = FakeEntryGuard(history, paths.runtime_dir / "desktop.lock")
    logger = RecordingDesktopLogger([])
    hooks = FakeHookInstallation(history)

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as occupied:
        occupied.bind(("127.0.0.1", 0))
        port = int(occupied.getsockname()[1])
        monkeypatch.setenv("MW_BACKEND_PORT", str(port))
        monkeypatch.setattr(module.multiprocessing, "freeze_support", lambda: None)
        monkeypatch.setattr(module, "build_runtime_paths", lambda: paths)
        monkeypatch.setattr(module, "ensure_runtime_directories", lambda _paths: None)
        monkeypatch.setattr(module, "configure_desktop_environment", lambda _paths: None)
        monkeypatch.setattr(module, "configure_desktop_logging", lambda _paths: logger)
        monkeypatch.setattr(
            module,
            "install_desktop_exception_hooks",
            lambda _paths, _state_provider: hooks,
        )
        monkeypatch.setattr(module, "close_desktop_logging", lambda _logger: None)
        monkeypatch.setattr(module, "SingleInstanceGuard", lambda _path: guard)
        monkeypatch.setattr(
            module,
            "migrate_legacy_database",
            lambda _paths: history.append("database.migrate"),
        )
        monkeypatch.setattr(
            module,
            "build_desktop_controller",
            lambda **_kwargs: pytest.fail("occupied port must abort before controller build"),
        )
        monkeypatch.setattr(
            module,
            "show_native_error",
            lambda _title, text: messages.append(text),
        )

        assert module.main() == 1

    assert "database.migrate" not in history
    assert guard.release_calls == 1
    assert messages and "already in use" in messages[0]


def test_importing_desktop_entry_does_not_import_backend_app_or_gui_dependencies() -> None:
    backend_dir = Path(__file__).resolve().parents[1]
    probe = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; import desktop_app; "
                "forbidden={'app.main','webview','pystray','PIL'}; "
                "loaded=forbidden.intersection(sys.modules); "
                "assert not loaded, sorted(loaded)"
            ),
        ],
        cwd=backend_dir,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )

    assert probe.returncode == 0, probe.stderr


def test_runtime_settings_loader_honors_desktop_env_file_on_first_import(
    tmp_path: Path,
) -> None:
    backend_dir = Path(__file__).resolve().parents[1]
    env_file = tmp_path / "desktop.env"
    env_file.write_text(
        "MW_BACKEND_PORT=23456\nMW_ADMIN_TOKEN=fresh-desktop-token\n",
        encoding="utf-8",
    )
    environment = {
        key: value
        for key, value in os.environ.items()
        if key not in {"MW_BACKEND_PORT", "MW_ADMIN_TOKEN", "MW_ENV_FILE"}
    }
    probe = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import os, sys; import desktop_app; "
                "assert 'app.config' not in sys.modules; "
                "os.environ['MW_ENV_FILE'] = sys.argv[1]; "
                "settings = desktop_app.load_desktop_runtime_settings(); "
                "assert desktop_app.desktop_backend_address() == ('127.0.0.1', 23456); "
                "assert settings.MW_ADMIN_TOKEN == 'fresh-desktop-token'"
            ),
            str(env_file),
        ],
        cwd=backend_dir,
        env=environment,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )

    assert probe.returncode == 0, (probe.stdout, probe.stderr)


def test_native_error_adapter_uses_injected_windows_message_box() -> None:
    module = _desktop_errors_module()
    calls: list[tuple[str, str, int]] = []

    module.show_native_error(
        "Mod Watcher Agent",
        "WebView2 Runtime 缺失",
        platform_name="win32",
        message_box=lambda title, text, flags: calls.append((title, text, flags)),
    )

    assert len(calls) == 1
    assert calls[0][:2] == ("Mod Watcher Agent", "WebView2 Runtime 缺失")
    assert calls[0][2] & 0x10


@pytest.mark.parametrize(
    "detail",
    [
        "WebView2 Runtime unavailable",
        "EdgeChromium backend could not start",
    ],
)
def test_webview2_startup_error_formatter_is_native_actionable_and_gui_free(
    detail: str,
) -> None:
    module = _desktop_errors_module()

    message = module.format_desktop_startup_error(RuntimeError(detail))

    assert message.startswith("桌面客户端启动失败：")
    assert "未检测到可用的 Microsoft Edge WebView2 Runtime" in message
    assert "请从 Microsoft 官方页面安装" in message
    assert "https://developer.microsoft.com/microsoft-edge/webview2/" in message
    assert detail in message
    assert "webview" not in sys.modules


class FakeSmokeThread:
    def __init__(self, history: list[str]) -> None:
        self.history = history
        self.alive = True

    def join(self, timeout: float | None = None) -> None:
        self.history.append(f"thread.join:{timeout}")

    def is_alive(self) -> bool:
        return self.alive


class FakeSmokeServer:
    def __init__(self, history: list[str], *, ready: bool = True) -> None:
        self.history = history
        self.ready = ready
        self.thread = FakeSmokeThread(history)
        self.error: BaseException | None = None

    def start(self) -> None:
        self.history.append("server.start")

    def wait_ready(self, timeout: float) -> bool:
        self.history.append(f"server.ready:{timeout}")
        return self.ready

    def stop(self, timeout: float = 10) -> None:
        self.history.append(f"server.stop:{timeout}")
        self.thread.alive = False


class FakeSmokeResponse:
    def __init__(
        self,
        path: str,
        *,
        frontend: str = "ready",
        root_content_type: str = "text/html; charset=utf-8",
        missing_asset: str | None = None,
        empty_asset: str | None = None,
    ) -> None:
        self.path = path
        self.status_code = 404 if path == missing_asset else 200
        self.headers = {
            "content-type": root_content_type if path == "/" else "application/octet-stream"
        }
        if path == "/":
            self.text = (
                '<!doctype html><html><head><link rel="stylesheet" href="/assets/app.css"></head>'
                '<body><div id="root"></div><script type="module" src="/assets/app.js"></script>'
                "</body></html>"
                if root_content_type.startswith("text/html")
                else '{"service":"Mod Watcher Agent"}'
            )
        else:
            self.text = ""
        self.content = b"" if path in {empty_asset, "/", "/api/health"} else b"asset-content"
        self._frontend = frontend

    def json(self) -> dict[str, str]:
        return (
            {"status": "ok", "frontend": self._frontend}
            if self.path == "/api/health"
            else {"service": "ok"}
        )


class FakeSmokeClient:
    def __init__(
        self,
        history: list[str],
        *,
        frontend: str = "ready",
        root_content_type: str = "text/html; charset=utf-8",
        missing_asset: str | None = None,
        empty_asset: str | None = None,
        **options: object,
    ) -> None:
        self.history = history
        self.options = options
        self.frontend = frontend
        self.root_content_type = root_content_type
        self.missing_asset = missing_asset
        self.empty_asset = empty_asset

    def __enter__(self) -> FakeSmokeClient:
        self.history.append("client.enter")
        return self

    def __exit__(self, *_args: object) -> None:
        self.history.append("client.exit")

    def get(self, path: str) -> FakeSmokeResponse:
        self.history.append(f"client.get:{path}")
        return FakeSmokeResponse(
            path,
            frontend=self.frontend,
            root_content_type=self.root_content_type,
            missing_asset=self.missing_asset,
            empty_asset=self.empty_asset,
        )


def test_smoke_runner_uses_available_port_trust_env_false_and_stops_server(
    tmp_path: Path,
) -> None:
    module = _desktop_entry_module()
    history: list[str] = []
    servers: list[tuple[str, int, FakeSmokeServer]] = []
    client_options: list[dict[str, object]] = []
    paths = SimpleNamespace(user_root=tmp_path, log_dir=tmp_path / "logs")

    def server_factory(host: str, port: int) -> FakeSmokeServer:
        server = FakeSmokeServer(history)
        servers.append((host, port, server))
        return server

    def client_factory(**options: object) -> FakeSmokeClient:
        client_options.append(options)
        return FakeSmokeClient(history, **options)

    assert (
        module.run_smoke_test(
            paths,
            server_factory=server_factory,
            client_factory=client_factory,
            port_selector=lambda: 24680,
        )
        == 0
    )

    assert [(host, port) for host, port, _server in servers] == [("127.0.0.1", 24680)]
    assert client_options == [
        {
            "base_url": "http://127.0.0.1:24680",
            "timeout": 5.0,
            "trust_env": False,
        }
    ]
    assert history == [
        "server.start",
        "server.ready:30.0",
        "client.enter",
        "client.get:/api/health",
        "client.get:/",
        "client.get:/assets/app.css",
        "client.get:/assets/app.js",
        "client.exit",
        "server.stop:10",
        "thread.join:10",
    ]
    assert servers[0][2].thread.is_alive() is False


def test_smoke_runner_rejects_health_when_frontend_is_missing(tmp_path: Path) -> None:
    module = _desktop_entry_module()
    history: list[str] = []
    paths = SimpleNamespace(user_root=tmp_path, runtime_dir=tmp_path / "runtime")

    with pytest.raises(module.DesktopSmokeError, match="frontend is not ready"):
        module.run_smoke_test(
            paths,
            server_factory=lambda _host, _port: FakeSmokeServer(history),
            client_factory=lambda **options: FakeSmokeClient(
                history,
                frontend="missing",
                **options,
            ),
            port_selector=lambda: 24680,
        )

    assert "client.get:/" not in history
    assert not (tmp_path / "runtime" / "smoke-port-used.txt").exists()


def test_smoke_runner_rejects_json_root_fallback(tmp_path: Path) -> None:
    module = _desktop_entry_module()
    history: list[str] = []
    paths = SimpleNamespace(user_root=tmp_path, runtime_dir=tmp_path / "runtime")

    with pytest.raises(module.DesktopSmokeError, match="React HTML"):
        module.run_smoke_test(
            paths,
            server_factory=lambda _host, _port: FakeSmokeServer(history),
            client_factory=lambda **options: FakeSmokeClient(
                history,
                root_content_type="application/json",
                **options,
            ),
            port_selector=lambda: 24680,
        )


@pytest.mark.parametrize(
    ("missing_asset", "empty_asset"),
    [
        ("/assets/app.js", None),
        (None, "/assets/app.css"),
    ],
)
def test_smoke_runner_rejects_missing_or_empty_react_assets(
    tmp_path: Path,
    missing_asset: str | None,
    empty_asset: str | None,
) -> None:
    module = _desktop_entry_module()
    history: list[str] = []
    paths = SimpleNamespace(user_root=tmp_path, runtime_dir=tmp_path / "runtime")

    with pytest.raises(module.DesktopSmokeError, match="React asset"):
        module.run_smoke_test(
            paths,
            server_factory=lambda _host, _port: FakeSmokeServer(history),
            client_factory=lambda **options: FakeSmokeClient(
                history,
                missing_asset=missing_asset,
                empty_asset=empty_asset,
                **options,
            ),
            port_selector=lambda: 24680,
        )


def test_smoke_runner_uses_explicit_environment_port(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _desktop_entry_module()
    history: list[str] = []
    server_addresses: list[tuple[str, int]] = []
    paths = SimpleNamespace(user_root=tmp_path, log_dir=tmp_path / "logs")
    monkeypatch.setenv("MW_SMOKE_PORT", "25432")
    monkeypatch.setattr(module, "select_available_loopback_port", lambda: 12345)

    def server_factory(host: str, port: int) -> FakeSmokeServer:
        server_addresses.append((host, port))
        return FakeSmokeServer(history)

    assert (
        module.run_smoke_test(
            paths,
            server_factory=server_factory,
            client_factory=lambda **options: FakeSmokeClient(history, **options),
        )
        == 0
    )

    assert server_addresses == [("127.0.0.1", 25432)]


@pytest.mark.parametrize(
    "invalid_port",
    ["", " ", "0", "65536", "1.5", "+123", "-1", "１２３"],
)
def test_smoke_runner_rejects_invalid_environment_port_before_server_start(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    invalid_port: str,
) -> None:
    module = _desktop_entry_module()
    server_addresses: list[tuple[str, int]] = []
    paths = SimpleNamespace(user_root=tmp_path, log_dir=tmp_path / "logs")
    monkeypatch.setenv("MW_SMOKE_PORT", invalid_port)

    def server_factory(host: str, port: int) -> FakeSmokeServer:
        server_addresses.append((host, port))
        return FakeSmokeServer([])

    with pytest.raises(module.DesktopSmokeError, match="MW_SMOKE_PORT"):
        module.run_smoke_test(
            paths,
            server_factory=server_factory,
            client_factory=lambda **options: FakeSmokeClient([], **options),
        )

    assert server_addresses == []


def test_smoke_runner_records_machine_readable_used_port_marker(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    module = _desktop_entry_module()
    history: list[str] = []
    paths = SimpleNamespace(user_root=tmp_path, log_dir=tmp_path / "logs")

    assert (
        module.run_smoke_test(
            paths,
            server_factory=lambda _host, _port: FakeSmokeServer(history),
            client_factory=lambda **options: FakeSmokeClient(history, **options),
            port_selector=lambda: 24680,
        )
        == 0
    )

    marker = "MW_SMOKE_PORT_USED=24680"
    assert marker in capsys.readouterr().out.splitlines()
    assert (tmp_path / "runtime" / "smoke-port-used.txt").read_text(
        encoding="ascii"
    ).strip() == marker


def test_smoke_runner_failure_still_stops_and_joins_backend(tmp_path: Path) -> None:
    module = _desktop_entry_module()
    history: list[str] = []
    server = FakeSmokeServer(history, ready=False)
    paths = SimpleNamespace(user_root=tmp_path, log_dir=tmp_path / "logs")

    with pytest.raises(module.DesktopSmokeError, match="ready"):
        module.run_smoke_test(
            paths,
            server_factory=lambda _host, _port: server,
            client_factory=lambda **_options: pytest.fail("HTTP must wait for readiness"),
            port_selector=lambda: 24680,
        )

    assert history == [
        "server.start",
        "server.ready:30.0",
        "server.stop:10",
        "thread.join:10",
    ]
    assert server.thread.is_alive() is False


def test_smoke_runner_forces_exit_when_backend_stop_times_out_after_primary_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _desktop_entry_module()
    history: list[str] = []
    server = FakeSmokeServer(history, ready=False)
    paths = SimpleNamespace(user_root=tmp_path, log_dir=tmp_path / "logs")

    class ForcedStopTimeoutError(RuntimeError):
        requires_forced_exit = True

    def fail_stop(timeout: float = 10) -> None:
        history.append(f"server.stop:{timeout}")
        raise ForcedStopTimeoutError("backend thread did not stop")

    server.stop = fail_stop  # type: ignore[method-assign]
    monkeypatch.setattr(
        module,
        "write_desktop_crash",
        lambda _paths, exception, state: history.append(f"crash:{state}:{exception}"),
    )
    monkeypatch.setattr(module.logging, "shutdown", lambda: history.append("logging.flush"))
    monkeypatch.setattr(module.os, "_exit", lambda code: history.append(f"process.exit:{code}"))

    with pytest.raises(ForcedStopTimeoutError, match="backend thread did not stop"):
        module.run_smoke_test(
            paths,
            server_factory=lambda _host, _port: server,
            client_factory=lambda **_options: pytest.fail("HTTP must wait for readiness"),
            port_selector=lambda: 24680,
        )

    assert history[-3:] == [
        "crash:smoke-stop-timeout:backend thread did not stop",
        "logging.flush",
        "process.exit:1",
    ]


def test_smoke_stop_timeout_terminates_a_process_with_a_live_non_daemon_thread(
    tmp_path: Path,
) -> None:
    backend_dir = Path(__file__).resolve().parents[1]
    events_path = tmp_path / "events.txt"
    probe = subprocess.run(
        [
            sys.executable,
            "-c",
            r"""
import os
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import desktop_app

events_path = Path(sys.argv[1])

def record(event):
    with events_path.open("a", encoding="utf-8") as stream:
        stream.write(f"{event}\n")

class ForcedStopTimeout(RuntimeError):
    requires_forced_exit = True

class StubbornSmokeServer:
    def __init__(self):
        self.error = None
        self.release = threading.Event()
        self.thread = threading.Thread(target=self.release.wait, daemon=False)

    def start(self):
        self.thread.start()

    def wait_ready(self, _timeout):
        return False

    def stop(self, timeout=10):
        record(f"stop:{timeout}")
        raise ForcedStopTimeout("backend thread did not stop")

desktop_app._SMOKE_STOP_TIMEOUT_SECONDS = 0.01
desktop_app.write_desktop_crash = (
    lambda _paths, _exception, state: record(f"crash:{state}") or True
)
desktop_app.logging.shutdown = lambda: record("flush")

threading.Thread(
    target=lambda: (time.sleep(1), os._exit(23)),
    daemon=True,
).start()

desktop_app.run_smoke_test(
    SimpleNamespace(user_root=events_path.parent, log_dir=events_path.parent),
    server_factory=lambda _host, _port: StubbornSmokeServer(),
    client_factory=lambda **_options: None,
    port_selector=lambda: 24680,
)
""",
            str(events_path),
        ],
        cwd=backend_dir,
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )

    assert probe.returncode == 1, (probe.stdout, probe.stderr)
    assert events_path.read_text(encoding="utf-8").splitlines() == [
        "stop:0.01",
        "crash:smoke-stop-timeout",
        "flush",
    ]


def test_available_port_selector_avoids_an_occupied_loopback_port() -> None:
    module = _desktop_entry_module()
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as occupied:
        occupied.bind(("127.0.0.1", 0))
        occupied.listen(1)
        occupied_port = int(occupied.getsockname()[1])

        selected_port = module.select_available_loopback_port()

        assert selected_port != occupied_port
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind(("127.0.0.1", selected_port))


def test_smoke_cli_uses_and_cleans_isolated_temp_data_without_gui(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _desktop_entry_module()
    history: list[str] = []
    log_messages: list[str] = []
    captured_roots: list[Path] = []
    hooks = FakeHookInstallation(history)
    desktop_logger = RecordingDesktopLogger(log_messages)

    def build_paths() -> SimpleNamespace:
        user_root = Path(os.environ["MW_USER_DATA_DIR"])
        captured_roots.append(user_root)
        return SimpleNamespace(
            user_root=user_root,
            runtime_dir=user_root / "runtime",
            log_dir=user_root / "logs",
        )

    def ensure_paths(paths: SimpleNamespace) -> None:
        history.append("paths.ensure")
        paths.runtime_dir.mkdir(parents=True, exist_ok=True)
        paths.log_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.delenv("MW_USER_DATA_DIR", raising=False)
    monkeypatch.setattr(module.multiprocessing, "freeze_support", lambda: history.append("freeze"))
    monkeypatch.setattr(module, "build_runtime_paths", build_paths)
    monkeypatch.setattr(module, "ensure_runtime_directories", ensure_paths)
    monkeypatch.setattr(
        module,
        "configure_desktop_environment",
        lambda _paths: history.append("env.configure"),
    )
    monkeypatch.setattr(
        module,
        "configure_desktop_logging",
        lambda _paths: history.append("logging.configure") or desktop_logger,
        raising=False,
    )
    monkeypatch.setattr(
        module,
        "install_desktop_exception_hooks",
        lambda _paths, state_provider: history.append(f"hooks.install:{state_provider()}") or hooks,
        raising=False,
    )
    monkeypatch.setattr(
        module,
        "close_desktop_logging",
        lambda _logger: history.append("logging.close"),
        raising=False,
    )
    monkeypatch.setattr(
        module,
        "run_smoke_test",
        lambda _paths: history.append("smoke.run") or 0,
        raising=False,
    )
    monkeypatch.setattr(
        module,
        "SingleInstanceGuard",
        lambda *_args: pytest.fail("smoke mode must not create the UI instance guard"),
    )
    monkeypatch.setattr(
        module,
        "migrate_legacy_database",
        lambda *_args: pytest.fail("smoke mode must not migrate the user database"),
    )
    monkeypatch.setattr(
        module,
        "build_desktop_controller",
        lambda **_kwargs: pytest.fail("smoke mode must not build window or tray adapters"),
    )
    monkeypatch.setattr(
        module,
        "show_native_error",
        lambda *_args: pytest.fail("smoke mode must not open native UI"),
    )

    assert module.main(["--smoke-test"]) == 0

    assert len(captured_roots) == 1
    assert not captured_roots[0].exists()
    assert "MW_USER_DATA_DIR" not in os.environ
    assert history == [
        "freeze",
        "paths.ensure",
        "env.configure",
        "logging.configure",
        "hooks.install:smoke-starting",
        "smoke.run",
        "hooks.restore",
        "logging.close",
    ]
    assert log_messages == [
        "INFO Desktop startup mode=smoke-test",
        f"INFO Runtime directories ready: {captured_roots[0]}",
        "INFO Desktop smoke test starting",
        "INFO Desktop smoke test succeeded",
        "INFO Desktop smoke shutdown complete",
    ]


@pytest.mark.parametrize("original_value", [None, "C:/existing/game_aliases.json"])
def test_smoke_environment_restores_game_alias_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    original_value: str | None,
) -> None:
    module = _desktop_entry_module()
    monkeypatch.setenv("MW_USER_DATA_DIR", str(tmp_path / "empty-smoke-data"))
    if original_value is None:
        monkeypatch.delenv("GAME_ALIAS_FILE", raising=False)
    else:
        monkeypatch.setenv("GAME_ALIAS_FILE", original_value)

    with module._isolated_smoke_environment():
        os.environ["GAME_ALIAS_FILE"] = str(tmp_path / "runtime" / "game_aliases.json")

    if original_value is None:
        assert "GAME_ALIAS_FILE" not in os.environ
    else:
        assert os.environ["GAME_ALIAS_FILE"] == original_value


def test_smoke_cli_keeps_desktop_log_open_until_success_and_shutdown_are_written(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _desktop_entry_module()
    user_root = tmp_path / "smoke-user-data"
    paths = SimpleNamespace(
        user_root=user_root,
        runtime_dir=user_root / "runtime",
        log_dir=user_root / "logs",
    )
    hooks = FakeHookInstallation([])

    monkeypatch.setenv("MW_USER_DATA_DIR", str(user_root))
    monkeypatch.setattr(module.multiprocessing, "freeze_support", lambda: None)
    monkeypatch.setattr(module, "build_runtime_paths", lambda: paths)
    monkeypatch.setattr(
        module,
        "ensure_runtime_directories",
        lambda value: (
            value.runtime_dir.mkdir(parents=True, exist_ok=True),
            value.log_dir.mkdir(parents=True, exist_ok=True),
        ),
    )
    monkeypatch.setattr(module, "configure_desktop_environment", lambda _paths: None)
    monkeypatch.setattr(
        module,
        "install_desktop_exception_hooks",
        lambda _paths, _state_provider: hooks,
    )
    monkeypatch.setattr(
        module,
        "run_smoke_test",
        lambda value: module.release_smoke_runtime_resources(value) or 0,
    )

    assert module.main(["--smoke-test"]) == 0

    log_text = (paths.log_dir / "desktop.log").read_text(encoding="utf-8")
    assert "Desktop smoke test succeeded" in log_text
    assert "Desktop smoke shutdown complete" in log_text


def test_smoke_cli_failure_records_crash_without_opening_native_ui(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _desktop_entry_module()
    history: list[str] = []
    log_messages: list[str] = []
    crash_calls: list[tuple[Path, BaseException, str]] = []
    hooks = FakeHookInstallation(history)

    def build_paths() -> SimpleNamespace:
        user_root = Path(os.environ["MW_USER_DATA_DIR"])
        return SimpleNamespace(
            user_root=user_root,
            runtime_dir=user_root / "runtime",
            log_dir=user_root / "logs",
        )

    desktop_logger = RecordingDesktopLogger(log_messages)

    monkeypatch.delenv("MW_USER_DATA_DIR", raising=False)
    monkeypatch.setattr(module.multiprocessing, "freeze_support", lambda: None)
    monkeypatch.setattr(module, "build_runtime_paths", build_paths)
    monkeypatch.setattr(
        module,
        "ensure_runtime_directories",
        lambda paths: (paths.log_dir.mkdir(parents=True), paths.runtime_dir.mkdir(parents=True)),
    )
    monkeypatch.setattr(module, "configure_desktop_environment", lambda _paths: None)
    monkeypatch.setattr(
        module,
        "configure_desktop_logging",
        lambda _paths: desktop_logger,
        raising=False,
    )
    monkeypatch.setattr(
        module,
        "install_desktop_exception_hooks",
        lambda _paths, _state_provider: hooks,
        raising=False,
    )
    monkeypatch.setattr(
        module,
        "close_desktop_logging",
        lambda _logger: history.append("logging.close"),
        raising=False,
    )
    monkeypatch.setattr(
        module,
        "run_smoke_test",
        lambda _paths: (_ for _ in ()).throw(RuntimeError("smoke backend failed")),
        raising=False,
    )
    monkeypatch.setattr(
        module,
        "write_desktop_crash",
        lambda paths, exc, state: crash_calls.append((paths.log_dir, exc, state)),
        raising=False,
    )
    monkeypatch.setattr(
        module,
        "show_native_error",
        lambda *_args: pytest.fail("smoke failure must not open native UI"),
    )

    assert module.main(["--smoke-test"]) == 1

    assert len(crash_calls) == 1
    assert isinstance(crash_calls[0][1], RuntimeError)
    assert str(crash_calls[0][1]) == "smoke backend failed"
    assert crash_calls[0][2] == "smoke-failed"
    assert history == [
        "hooks.restore",
        "logging.close",
    ]
    assert log_messages[-2:] == [
        "EXCEPTION Desktop smoke test failed",
        "INFO Desktop smoke shutdown complete",
    ]


def test_smoke_cli_rejects_nonempty_user_data_directory_without_touching_database(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _desktop_entry_module()
    user_root = tmp_path / "real-user-data"
    database = user_root / "data" / "mod_watcher.db"
    database.parent.mkdir(parents=True)
    database.write_bytes(b"do-not-touch")

    monkeypatch.setenv("MW_USER_DATA_DIR", str(user_root))
    monkeypatch.setattr(module.multiprocessing, "freeze_support", lambda: None)
    monkeypatch.setattr(
        module,
        "run_smoke_test",
        lambda _paths: pytest.fail("unsafe smoke directory must be rejected before server start"),
        raising=False,
    )
    monkeypatch.setattr(
        module,
        "show_native_error",
        lambda *_args: pytest.fail("smoke validation must not open native UI"),
    )

    assert module.main(["--smoke-test"]) == 1
    assert database.read_bytes() == b"do-not-touch"


def test_smoke_tests_leave_no_live_mod_watcher_workers() -> None:
    leaked = [
        thread
        for thread in threading.enumerate()
        if thread.name.startswith("mod-watcher-") and thread.is_alive() and not thread.daemon
    ]

    assert leaked == []
