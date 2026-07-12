from __future__ import annotations

import importlib
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest


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


def test_desktop_entry_follows_required_initialization_order(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _desktop_entry_module()
    history: list[str] = []
    paths = SimpleNamespace(runtime_dir=tmp_path / "runtime", log_dir=tmp_path / "logs")
    guard_holder: list[FakeEntryGuard] = []
    controller = FakeEntryController(
        history,
        on_start=lambda: guard_holder[0].release(),
    )

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
    monkeypatch.setattr(module, "SingleInstanceGuard", guard_factory)
    monkeypatch.setattr(
        module,
        "migrate_legacy_database",
        lambda value: history.append("database.migrate") if value is paths else None,
    )
    monkeypatch.setattr(
        module,
        "build_desktop_controller",
        lambda *, paths, guard: (
            history.append("controller.build") or controller
            if paths is not None and guard is not None
            else None
        ),
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
        "guard.construct",
        "guard.acquire",
        "database.migrate",
        "controller.build",
        "controller.start",
        "guard.release",
    ]
    assert guard_holder[0].lock_path == paths.runtime_dir / "desktop.lock"
    assert guard_holder[0].release_calls == 1


def test_entry_does_not_release_guard_again_after_controller_owns_lifecycle(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _desktop_entry_module()
    paths = SimpleNamespace(runtime_dir=tmp_path / "runtime", log_dir=tmp_path / "logs")
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
    paths = SimpleNamespace(runtime_dir=tmp_path / "runtime", log_dir=tmp_path / "logs")
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
    paths = SimpleNamespace(runtime_dir=tmp_path / "runtime", log_dir=tmp_path / "logs")
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


def test_entry_migration_failure_releases_guard_without_building_controller(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _desktop_entry_module()
    paths = SimpleNamespace(runtime_dir=tmp_path / "runtime", log_dir=tmp_path / "logs")
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
