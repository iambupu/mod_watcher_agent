from __future__ import annotations

import importlib
import subprocess
import sys
import threading
from collections.abc import Callable
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest


def _desktop_controller_module() -> ModuleType:
    try:
        return importlib.import_module("app.desktop.controller")
    except ModuleNotFoundError:
        pytest.fail("app.desktop.controller is not implemented", pytrace=False)


def _desktop_window_module() -> ModuleType:
    try:
        return importlib.import_module("app.desktop.window")
    except ModuleNotFoundError:
        pytest.fail("app.desktop.window is not implemented", pytrace=False)


def _desktop_tray_module() -> ModuleType:
    try:
        return importlib.import_module("app.desktop.tray")
    except ModuleNotFoundError:
        pytest.fail("app.desktop.tray is not implemented", pytrace=False)


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


class FakeServer:
    def __init__(
        self,
        history: list[str],
        *,
        ready: bool = True,
        stop_error: BaseException | None = None,
    ) -> None:
        self.history = history
        self.ready = ready
        self.stop_error = stop_error
        self.error: BaseException | None = None
        self.start_calls = 0
        self.stop_calls = 0

    def start(self) -> None:
        self.start_calls += 1
        self.history.append("server.start")

    def wait_ready(self, timeout: float) -> bool:
        assert timeout > 0
        self.history.append("server.ready")
        return self.ready

    def stop(self) -> None:
        self.stop_calls += 1
        self.history.append("server.stop")
        if self.stop_error is not None:
            raise self.stop_error


class FakeWindow:
    def __init__(self, history: list[str]) -> None:
        self.history = history
        self.on_minimized: Callable[..., object] | None = None
        self.on_closing: Callable[..., object] | None = None
        self.on_run: Callable[[], None] | None = None
        self.hide_calls = 0
        self.show_calls = 0
        self.restore_calls = 0
        self.destroy_calls = 0

    def bind(
        self,
        *,
        on_minimized: Callable[..., object],
        on_closing: Callable[..., object],
    ) -> None:
        self.history.append("window.bind")
        self.on_minimized = on_minimized
        self.on_closing = on_closing

    def create(self) -> None:
        self.history.append("window.create")

    def run(self) -> None:
        self.history.append("window.run")
        if self.on_run is not None:
            self.on_run()

    def hide(self) -> None:
        self.hide_calls += 1
        self.history.append("window.hide")

    def show(self) -> None:
        self.show_calls += 1
        self.history.append("window.show")

    def restore(self) -> None:
        self.restore_calls += 1
        self.history.append("window.restore")

    def destroy(self) -> None:
        self.destroy_calls += 1
        self.history.append("window.destroy")


class FakeTray:
    def __init__(self, history: list[str], *, available: bool = True) -> None:
        self.history = history
        self.available = available
        self.on_show: Callable[..., object] | None = None
        self.on_exit: Callable[..., object] | None = None
        self.stop_calls = 0

    def start(
        self,
        *,
        on_show: Callable[..., object],
        on_exit: Callable[..., object],
    ) -> bool:
        self.history.append("tray.start")
        self.on_show = on_show
        self.on_exit = on_exit
        return self.available

    def stop(self) -> None:
        self.stop_calls += 1
        self.history.append("tray.stop")


class FakeGuard:
    def __init__(self, history: list[str]) -> None:
        self.history = history
        self.release_calls = 0

    def release(self) -> None:
        self.release_calls += 1
        self.history.append("guard.release")


def _make_controller(
    tmp_path: Path,
    *,
    ready: bool = True,
    tray_available: bool = True,
    stop_error: BaseException | None = None,
) -> tuple[object, FakeServer, FakeWindow, FakeTray, FakeGuard, list[str]]:
    module = _desktop_controller_module()
    history: list[str] = []
    server = FakeServer(history, ready=ready, stop_error=stop_error)
    window = FakeWindow(history)
    tray = FakeTray(history, available=tray_available)
    guard = FakeGuard(history)
    paths = SimpleNamespace(log_dir=tmp_path / "logs")
    controller = module.DesktopController(
        server=server,
        window=window,
        tray=tray,
        guard=guard,
        paths=paths,
        ready_timeout=0.25,
    )
    return controller, server, window, tray, guard, history


def test_start_waits_for_http_readiness_before_creating_window(tmp_path: Path) -> None:
    module = _desktop_controller_module()
    controller, server, window, tray, guard, history = _make_controller(tmp_path)
    state_seen_in_run: list[object] = []
    window.on_run = lambda: state_seen_in_run.append(controller.state)

    assert controller.start() == 0

    assert history.index("server.ready") < history.index("window.create")
    assert history.index("window.create") < history.index("window.run")
    assert state_seen_in_run == [module.DesktopState.WINDOW_VISIBLE]
    assert controller.state is module.DesktopState.STOPPED
    assert server.start_calls == 1
    assert server.stop_calls == 1
    assert tray.stop_calls == 1
    assert window.destroy_calls == 1
    assert guard.release_calls == 1


def test_close_hides_and_restore_shows_when_tray_is_available(tmp_path: Path) -> None:
    module = _desktop_controller_module()
    controller, _server, window, _tray, _guard, history = _make_controller(tmp_path)
    controller.tray_available = True

    assert controller.on_window_closing() is False
    assert controller.state is module.DesktopState.WINDOW_HIDDEN
    assert window.hide_calls == 1

    controller.restore_window()

    assert history[-2:] == ["window.show", "window.restore"]
    assert controller.state is module.DesktopState.WINDOW_VISIBLE


def test_minimize_only_hides_when_tray_is_healthy(tmp_path: Path) -> None:
    module = _desktop_controller_module()
    controller, _server, window, _tray, _guard, _history = _make_controller(tmp_path)

    controller.tray_available = False
    controller.on_window_minimized()
    assert window.hide_calls == 0

    controller.tray_available = True
    controller.on_window_minimized()
    assert window.hide_calls == 1
    assert controller.state is module.DesktopState.WINDOW_HIDDEN


def test_close_exits_in_degraded_mode_or_during_shutdown(tmp_path: Path) -> None:
    module = _desktop_controller_module()
    controller, _server, window, _tray, _guard, _history = _make_controller(tmp_path)

    controller.tray_available = False
    assert controller.on_window_closing() is True
    assert window.hide_calls == 0

    controller.tray_available = True
    controller.state = module.DesktopState.EXITING
    assert controller.on_window_closing() is True
    assert window.hide_calls == 0


def test_close_uses_live_tray_health_instead_of_stale_startup_result(
    tmp_path: Path,
) -> None:
    controller, _server, window, tray, _guard, _history = _make_controller(tmp_path)
    controller.tray_available = True
    tray.available = False

    assert controller.on_window_closing() is True
    assert controller.tray_available is False
    assert window.hide_calls == 0


def test_tray_callbacks_restore_and_request_the_single_shutdown_path(tmp_path: Path) -> None:
    controller, server, window, tray, guard, _history = _make_controller(tmp_path)

    def exercise_tray_callbacks() -> None:
        assert tray.on_show is not None
        assert tray.on_exit is not None
        tray.on_show()
        tray.on_exit("tray")

    window.on_run = exercise_tray_callbacks

    assert controller.start() == 0

    assert window.show_calls == 1
    assert window.restore_calls == 1
    assert server.stop_calls == 1
    assert tray.stop_calls == 1
    assert window.destroy_calls == 1
    assert guard.release_calls == 1


def test_exit_during_tray_start_never_enters_window_loop(tmp_path: Path) -> None:
    module = _desktop_controller_module()
    history: list[str] = []
    server = FakeServer(history)
    window = FakeWindow(history)
    guard = FakeGuard(history)

    class ExitDuringStartTray(FakeTray):
        def start(
            self,
            *,
            on_show: Callable[..., object],
            on_exit: Callable[..., object],
        ) -> bool:
            super().start(on_show=on_show, on_exit=on_exit)
            on_exit("tray-during-start")
            return True

    tray = ExitDuringStartTray(history)
    controller = module.DesktopController(
        server=server,
        window=window,
        tray=tray,
        guard=guard,
        paths=SimpleNamespace(log_dir=tmp_path),
    )

    assert controller.start() == 0

    assert "window.run" not in history
    assert controller.state is module.DesktopState.STOPPED
    assert server.stop_calls == 1
    assert tray.stop_calls == 1
    assert window.destroy_calls == 1
    assert guard.release_calls == 1


def test_shutdown_is_thread_safe_idempotent_and_signals_completion(tmp_path: Path) -> None:
    controller, server, window, tray, guard, _history = _make_controller(tmp_path)
    callers = [
        threading.Thread(target=controller.shutdown, args=(f"caller-{index}",))
        for index in range(8)
    ]

    for caller in callers:
        caller.start()
    for caller in callers:
        caller.join(1)

    assert all(not caller.is_alive() for caller in callers)
    assert controller.shutdown_complete.is_set()
    assert server.stop_calls == 1
    assert tray.stop_calls == 1
    assert window.destroy_calls == 1
    assert guard.release_calls == 1


def test_cleanup_continues_when_one_component_stop_fails(tmp_path: Path) -> None:
    module = _desktop_controller_module()
    controller, server, window, tray, guard, _history = _make_controller(
        tmp_path,
        stop_error=RuntimeError("server would not stop"),
    )

    controller.shutdown("test")

    assert controller.state is module.DesktopState.FAILED
    assert isinstance(controller.error, RuntimeError)
    assert server.stop_calls == 1
    assert tray.stop_calls == 1
    assert window.destroy_calls == 1
    assert guard.release_calls == 1
    assert controller.shutdown_complete.is_set()


def test_backend_readiness_failure_never_creates_window_and_cleans_up(tmp_path: Path) -> None:
    module = _desktop_controller_module()
    controller, server, window, tray, guard, history = _make_controller(
        tmp_path,
        ready=False,
    )

    with pytest.raises(module.DesktopStartupError, match="ready"):
        controller.start()

    assert "window.create" not in history
    assert controller.state is module.DesktopState.FAILED
    assert server.stop_calls == 1
    assert tray.stop_calls == 1
    assert window.destroy_calls == 1
    assert guard.release_calls == 1


def test_window_startup_error_preserves_webview_detail_and_cleans_up(
    tmp_path: Path,
) -> None:
    module = _desktop_controller_module()
    history: list[str] = []
    server = FakeServer(history)

    class FailingWindow(FakeWindow):
        def create(self) -> None:
            self.history.append("window.create")
            raise RuntimeError("WebView2 Runtime unavailable")

    window = FailingWindow(history)
    tray = FakeTray(history)
    guard = FakeGuard(history)
    controller = module.DesktopController(
        server=server,
        window=window,
        tray=tray,
        guard=guard,
        paths=SimpleNamespace(log_dir=tmp_path),
    )

    with pytest.raises(module.DesktopStartupError, match="WebView2 Runtime unavailable"):
        controller.start()

    assert server.stop_calls == 1
    assert tray.stop_calls == 1
    assert window.destroy_calls == 1
    assert guard.release_calls == 1


def test_tray_startup_failure_keeps_window_usable_without_hide_to_tray(
    tmp_path: Path,
) -> None:
    controller, _server, window, _tray, _guard, _history = _make_controller(
        tmp_path,
        tray_available=False,
    )
    close_results: list[bool] = []

    def exercise_degraded_window() -> None:
        controller.on_window_minimized()
        close_results.append(controller.on_window_closing())

    window.on_run = exercise_degraded_window

    assert controller.start() == 0

    assert controller.tray_available is False
    assert window.hide_calls == 0
    assert close_results == [True]


class FakeEvent:
    def __init__(self) -> None:
        self.handlers: list[Callable[..., object]] = []

    def __iadd__(self, handler: Callable[..., object]) -> FakeEvent:
        self.handlers.append(handler)
        return self


class FakeNativeWindow:
    def __init__(self) -> None:
        self.events = SimpleNamespace(minimized=FakeEvent(), closing=FakeEvent())
        self.calls: list[str] = []

    def hide(self) -> None:
        self.calls.append("hide")

    def show(self) -> None:
        self.calls.append("show")

    def restore(self) -> None:
        self.calls.append("restore")

    def destroy(self) -> None:
        self.calls.append("destroy")


class FakeWebView:
    def __init__(self) -> None:
        self.settings: dict[str, object] = {}
        self.window = FakeNativeWindow()
        self.create_calls: list[dict[str, object]] = []
        self.start_calls: list[dict[str, object]] = []

    def create_window(self, **kwargs: object) -> FakeNativeWindow:
        self.create_calls.append(kwargs)
        return self.window

    def start(self, **kwargs: object) -> None:
        self.start_calls.append(kwargs)


def test_pywebview_window_uses_native_light_window_and_persistent_profile(
    tmp_path: Path,
) -> None:
    module = _desktop_window_module()
    webview = FakeWebView()
    paths = SimpleNamespace(webview_dir=tmp_path / "webview")

    def minimized() -> None:
        pass

    def closing() -> bool:
        return False

    window = module.PyWebViewWindow(
        paths=paths,
        url="http://127.0.0.1:17500",
        webview_module=webview,
    )
    window.bind(on_minimized=minimized, on_closing=closing)

    window.create()
    window.run()

    assert webview.create_calls == [
        {
            "title": "Mod Watcher Agent",
            "url": "http://127.0.0.1:17500",
            "width": 1440,
            "height": 900,
            "min_size": (1024, 700),
            "resizable": True,
            "frameless": False,
            "confirm_close": False,
            "background_color": "#f8fafc",
        }
    ]
    assert webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] is True
    assert webview.window.events.minimized.handlers == [minimized]
    assert webview.window.events.closing.handlers == [closing]
    assert webview.start_calls == [
        {
            "gui": "edgechromium",
            "private_mode": False,
            "storage_path": str(paths.webview_dir),
        }
    ]


def test_pywebview_is_loaded_only_when_the_window_is_created(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _desktop_window_module()
    webview = FakeWebView()
    imports: list[str] = []

    def fake_import(name: str) -> object:
        imports.append(name)
        assert name == "webview"
        return webview

    monkeypatch.setattr(module.importlib, "import_module", fake_import)
    window = module.PyWebViewWindow(
        paths=SimpleNamespace(webview_dir=tmp_path / "webview"),
        url="http://127.0.0.1:17500",
    )

    assert imports == []
    window.create()
    assert imports == ["webview"]


def test_pywebview_main_loop_rejects_a_worker_thread(tmp_path: Path) -> None:
    module = _desktop_window_module()
    webview = FakeWebView()
    window = module.PyWebViewWindow(
        paths=SimpleNamespace(webview_dir=tmp_path / "webview"),
        url="http://127.0.0.1:17500",
        webview_module=webview,
    )
    errors: list[BaseException] = []

    def run_window() -> None:
        try:
            window.run()
        except BaseException as exc:
            errors.append(exc)

    worker = threading.Thread(target=run_window)
    worker.start()
    worker.join(1)

    assert len(errors) == 1
    assert isinstance(errors[0], RuntimeError)
    assert "main thread" in str(errors[0])
    assert webview.start_calls == []


def test_pywebview_window_methods_are_safe_and_destroy_is_idempotent(
    tmp_path: Path,
) -> None:
    module = _desktop_window_module()
    webview = FakeWebView()
    window = module.PyWebViewWindow(
        paths=SimpleNamespace(webview_dir=tmp_path / "webview"),
        url="http://127.0.0.1:17500",
        webview_module=webview,
    )

    window.destroy()
    window.create()
    window.hide()
    window.show()
    window.restore()
    window.destroy()
    window.destroy()

    assert webview.window.calls == ["hide", "show", "restore", "destroy"]


def test_destroyed_pywebview_window_is_never_recreated_by_a_late_run(
    tmp_path: Path,
) -> None:
    module = _desktop_window_module()
    webview = FakeWebView()
    window = module.PyWebViewWindow(
        paths=SimpleNamespace(webview_dir=tmp_path / "webview"),
        url="http://127.0.0.1:17500",
        webview_module=webview,
    )
    window.create()
    window.destroy()

    window.run()

    assert len(webview.create_calls) == 1
    assert webview.start_calls == []


class FakeMenuItem:
    def __init__(
        self,
        text: str,
        action: Callable[..., object],
        *,
        default: bool = False,
    ) -> None:
        self.text = text
        self.action = action
        self.default = default


class FakeMenu:
    SEPARATOR = object()

    def __init__(self, *items: object) -> None:
        self.items = list(items)


class FakeIcon:
    instances: list[FakeIcon] = []

    def __init__(self, name: str, image: object, title: str, menu: FakeMenu) -> None:
        self.name = name
        self.image = image
        self.title = title
        self.menu = menu
        self.stop_calls = 0
        self.visible = False
        self.ready = threading.Event()
        self.stopped = threading.Event()
        self.run_thread: threading.Thread | None = None
        self.action_on_run: str | None = None
        type(self).instances.append(self)

    def run(self, setup: Callable[[FakeIcon], None]) -> None:
        self.run_thread = threading.current_thread()
        setup(self)
        self.ready.set()
        if self.action_on_run is not None:
            item = next(
                entry
                for entry in self.menu.items
                if isinstance(entry, FakeMenuItem) and entry.text == self.action_on_run
            )
            item.action(self, item)
        self.stopped.wait(1)

    def stop(self) -> None:
        self.stop_calls += 1
        self.stopped.set()


class FakeImageModule:
    @staticmethod
    def new(mode: str, size: tuple[int, int], color: str) -> object:
        return (mode, size, color)


class FakeDraw:
    def rounded_rectangle(self, *_args: object, **_kwargs: object) -> None:
        pass

    def ellipse(self, *_args: object, **_kwargs: object) -> None:
        pass


class FakeImageDrawModule:
    @staticmethod
    def Draw(_image: object) -> FakeDraw:  # noqa: N802 - mirrors Pillow's API
        return FakeDraw()


class FakeResponse:
    def __init__(self, payload: dict[str, object] | None = None) -> None:
        self.payload = payload or {}

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict[str, object]:
        return self.payload


class FakeHttpClient:
    def __init__(self, calls: list[tuple[str, str]]) -> None:
        self.calls = calls

    def __enter__(self) -> FakeHttpClient:
        return self

    def __exit__(self, *_args: object) -> None:
        pass

    def get(self, path: str) -> FakeResponse:
        self.calls.append(("GET", path))
        return FakeResponse({"running": True})

    def post(self, path: str) -> FakeResponse:
        self.calls.append(("POST", path))
        return FakeResponse()


def _fake_tray_dependencies() -> tuple[object, object, object]:
    pystray = SimpleNamespace(Menu=FakeMenu, MenuItem=FakeMenuItem, Icon=FakeIcon)
    return pystray, FakeImageModule, FakeImageDrawModule


def test_tray_reports_ready_from_an_independent_thread_and_has_required_menu(
    tmp_path: Path,
) -> None:
    module = _desktop_tray_module()
    FakeIcon.instances.clear()
    pystray, image, image_draw = _fake_tray_dependencies()
    shown: list[str] = []
    exited: list[str] = []
    tray = module.TrayController(
        paths=SimpleNamespace(log_dir=tmp_path),
        base_url="http://127.0.0.1:17500",
        pystray_module=pystray,
        image_module=image,
        image_draw_module=image_draw,
        startup_timeout=0.5,
    )

    assert (
        tray.start(
            on_show=lambda *_args: shown.append("show"),
            on_exit=lambda reason="": exited.append(reason),
        )
        is True
    )

    icon = FakeIcon.instances[0]
    assert icon.ready.wait(1)
    assert icon.run_thread is not threading.current_thread()
    assert icon.visible is True
    menu_items = [item for item in icon.menu.items if isinstance(item, FakeMenuItem)]
    assert [item.text for item in menu_items] == [
        "打开主界面",
        "立即检查新 Mod",
        "检查收藏更新",
        "暂停/恢复定时任务",
        "打开日志目录",
        "退出",
    ]
    assert menu_items[0].default is True
    menu_items[0].action(icon, menu_items[0])
    assert shown == ["show"]

    tray.stop()
    assert icon.stop_calls == 1
    assert not tray.thread.is_alive()
    assert exited == []


def test_tray_reports_dependency_initialization_failure_without_hanging(
    tmp_path: Path,
) -> None:
    module = _desktop_tray_module()

    def fail_dependencies() -> tuple[object, object, object]:
        raise ImportError("pystray is unavailable")

    tray = module.TrayController(
        paths=SimpleNamespace(log_dir=tmp_path),
        base_url="http://127.0.0.1:17500",
        dependency_loader=fail_dependencies,
        startup_timeout=0.5,
    )

    assert tray.start(on_show=lambda: None, on_exit=lambda *_args: None) is False
    assert tray.available is False
    assert isinstance(tray.startup_error, ImportError)
    assert not tray.thread.is_alive()


def test_tray_reports_native_icon_visibility_failure(tmp_path: Path) -> None:
    module = _desktop_tray_module()

    class VisibilityFailureIcon(FakeIcon):
        @property
        def visible(self) -> bool:
            return self._visible

        @visible.setter
        def visible(self, value: bool) -> None:
            if value:
                raise RuntimeError("native tray icon failed")
            self._visible = value

    pystray = SimpleNamespace(
        Menu=FakeMenu,
        MenuItem=FakeMenuItem,
        Icon=VisibilityFailureIcon,
    )
    tray = module.TrayController(
        paths=SimpleNamespace(log_dir=tmp_path),
        base_url="http://127.0.0.1:17500",
        pystray_module=pystray,
        image_module=FakeImageModule,
        image_draw_module=FakeImageDrawModule,
        startup_timeout=0.5,
    )

    assert tray.start(on_show=lambda: None, on_exit=lambda *_args: None) is False
    assert isinstance(tray.startup_error, RuntimeError)
    assert tray.available is False
    tray.stop()


def test_tray_http_actions_use_loopback_without_environment_proxies(tmp_path: Path) -> None:
    module = _desktop_tray_module()
    calls: list[tuple[str, str]] = []
    client_options: list[dict[str, Any]] = []

    def client_factory(**kwargs: Any) -> FakeHttpClient:
        client_options.append(kwargs)
        return FakeHttpClient(calls)

    tray = module.TrayController(
        paths=SimpleNamespace(log_dir=tmp_path),
        base_url="http://127.0.0.1:17500",
        client_factory=client_factory,
    )

    assert tray.check_now() is True
    assert tray.check_favorites() is True
    assert tray.toggle_scheduler() is True
    assert tray.open_logs() is True

    assert calls == [
        ("POST", "/api/jobs/discover-all"),
        ("POST", "/api/jobs/check-favorites"),
        ("GET", "/api/jobs/status"),
        ("POST", "/api/jobs/pause"),
        ("POST", "/api/logs/open-dir"),
    ]
    assert (
        client_options
        == [
            {
                "base_url": "http://127.0.0.1:17500",
                "timeout": 5.0,
                "trust_env": False,
            }
        ]
        * 4
    )

    with pytest.raises(ValueError, match="loopback"):
        module.TrayController(
            paths=SimpleNamespace(log_dir=tmp_path),
            base_url="https://example.com",
        )


def test_tray_stop_called_on_its_own_thread_does_not_self_join(tmp_path: Path) -> None:
    module = _desktop_tray_module()
    FakeIcon.instances.clear()

    class ExitOnRunIcon(FakeIcon):
        def __init__(self, *args: object, **kwargs: object) -> None:
            super().__init__(*args, **kwargs)
            self.action_on_run = "退出"

    pystray = SimpleNamespace(Menu=FakeMenu, MenuItem=FakeMenuItem, Icon=ExitOnRunIcon)
    tray = module.TrayController(
        paths=SimpleNamespace(log_dir=tmp_path),
        base_url="http://127.0.0.1:17500",
        pystray_module=pystray,
        image_module=FakeImageModule,
        image_draw_module=FakeImageDrawModule,
        startup_timeout=0.5,
    )

    assert (
        tray.start(
            on_show=lambda: None,
            on_exit=lambda *_args: tray.stop(),
        )
        is True
    )
    tray.thread.join(1)

    assert not tray.thread.is_alive()
    assert tray.startup_error is None
    assert FakeIcon.instances[0].stop_calls == 1


def test_tray_thread_start_failure_degrades_without_raising(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _desktop_tray_module()
    real_start = threading.Thread.start

    def fail_tray_start(thread: threading.Thread) -> None:
        if thread.name == "mod-watcher-tray":
            raise RuntimeError("thread creation failed")
        real_start(thread)

    monkeypatch.setattr(threading.Thread, "start", fail_tray_start)
    tray = module.TrayController(
        paths=SimpleNamespace(log_dir=tmp_path),
        base_url="http://127.0.0.1:17500",
    )

    assert tray.start(on_show=lambda: None, on_exit=lambda *_args: None) is False
    assert isinstance(tray.startup_error, RuntimeError)
    assert tray.available is False
    tray.stop()


def test_tray_timeout_does_not_leave_a_late_initialized_icon_thread(
    tmp_path: Path,
) -> None:
    module = _desktop_tray_module()
    loader_entered = threading.Event()
    release_loader = threading.Event()
    icons: list[FakeIcon] = []

    class BlockingIcon(FakeIcon):
        def __init__(self, *args: object, **kwargs: object) -> None:
            super().__init__(*args, **kwargs)
            icons.append(self)

        def run(self, setup: Callable[[FakeIcon], None]) -> None:
            self.run_thread = threading.current_thread()
            setup(self)
            self.stopped.wait(5)

    pystray = SimpleNamespace(Menu=FakeMenu, MenuItem=FakeMenuItem, Icon=BlockingIcon)

    def delayed_dependencies() -> tuple[object, object, object]:
        loader_entered.set()
        release_loader.wait(1)
        return pystray, FakeImageModule, FakeImageDrawModule

    tray = module.TrayController(
        paths=SimpleNamespace(log_dir=tmp_path),
        base_url="http://127.0.0.1:17500",
        dependency_loader=delayed_dependencies,
        startup_timeout=0.01,
        join_timeout=0.01,
    )

    assert tray.start(on_show=lambda: None, on_exit=lambda *_args: None) is False
    assert loader_entered.wait(1)
    release_loader.set()
    tray.thread.join(0.5)

    assert not tray.thread.is_alive()
    assert tray.available is False
    assert icons and icons[0].run_thread is None


def test_permanently_blocked_tray_initialization_cannot_keep_process_alive(
    tmp_path: Path,
) -> None:
    module = _desktop_tray_module()
    loader_entered = threading.Event()
    release_loader = threading.Event()

    def blocked_dependencies() -> tuple[object, object, object]:
        loader_entered.set()
        release_loader.wait()
        return _fake_tray_dependencies()

    tray = module.TrayController(
        paths=SimpleNamespace(log_dir=tmp_path),
        base_url="http://127.0.0.1:17500",
        dependency_loader=blocked_dependencies,
        startup_timeout=0.01,
        join_timeout=0.01,
    )

    try:
        assert tray.start(on_show=lambda: None, on_exit=lambda *_args: None) is False
        assert loader_entered.wait(1)
        assert tray.thread.is_alive()
        assert tray.thread.daemon is True
    finally:
        release_loader.set()
        tray.thread.join(1)


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


def test_task5_lifecycle_tests_leave_no_live_non_daemon_workers() -> None:
    leaked = [
        thread
        for thread in threading.enumerate()
        if thread.name.startswith("mod-watcher-") and thread.is_alive() and not thread.daemon
    ]

    assert leaked == []
