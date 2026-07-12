from __future__ import annotations

import importlib
import threading
from collections.abc import Callable
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest


def _desktop_tray_module() -> ModuleType:
    try:
        return importlib.import_module("app.desktop.tray")
    except ModuleNotFoundError:
        pytest.fail("app.desktop.tray is not implemented", pytrace=False)


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
    losses: list[BaseException | None] = []
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
            on_unavailable=losses.append,
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
    assert losses == []


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


def test_failed_tray_start_waits_for_worker_epilogue_before_returning(
    tmp_path: Path,
) -> None:
    module = _desktop_tray_module()
    event_published = threading.Event()
    release_epilogue = threading.Event()
    start_finished = threading.Event()
    result: list[bool] = []

    class BlockingSetEvent:
        def __init__(self) -> None:
            self._event = threading.Event()

        def set(self) -> None:
            self._event.set()
            event_published.set()
            assert release_epilogue.wait(1)

        def wait(self, timeout: float | None = None) -> bool:
            return self._event.wait(timeout)

    def fail_dependencies() -> tuple[object, object, object]:
        raise ImportError("pystray is unavailable")

    tray = module.TrayController(
        paths=SimpleNamespace(log_dir=tmp_path),
        base_url="http://127.0.0.1:17500",
        dependency_loader=fail_dependencies,
        startup_timeout=0.5,
        join_timeout=0.5,
    )
    tray._startup_complete = BlockingSetEvent()

    def start_tray() -> None:
        try:
            result.append(tray.start(on_show=lambda: None, on_exit=lambda *_args: None))
        finally:
            start_finished.set()

    starter = threading.Thread(target=start_tray, name="tray-start-caller")
    starter.start()
    assert event_published.wait(1)
    try:
        assert not start_finished.wait(0.1)
    finally:
        release_epilogue.set()
        starter.join(1)

    assert not starter.is_alive()
    assert result == [False]
    assert not tray.thread.is_alive()


def test_tray_notifies_when_the_native_loop_exits_after_startup(
    tmp_path: Path,
) -> None:
    module = _desktop_tray_module()
    losses: list[BaseException | None] = []
    lost = threading.Event()
    allow_exit = threading.Event()

    class UnexpectedExitIcon(FakeIcon):
        def run(self, setup: Callable[[FakeIcon], None]) -> None:
            self.run_thread = threading.current_thread()
            setup(self)
            self.ready.set()
            assert allow_exit.wait(1)

    pystray = SimpleNamespace(Menu=FakeMenu, MenuItem=FakeMenuItem, Icon=UnexpectedExitIcon)
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
            on_exit=lambda *_args: None,
            on_unavailable=lambda error=None: (losses.append(error), lost.set()),
        )
        is True
    )
    allow_exit.set()
    assert lost.wait(1)
    tray.thread.join(1)

    assert not tray.thread.is_alive()
    assert tray.available is False
    assert losses == [None]


def test_tray_reports_runtime_failure_after_successful_startup(
    tmp_path: Path,
) -> None:
    module = _desktop_tray_module()
    failures: list[BaseException | None] = []
    failed = threading.Event()
    allow_failure = threading.Event()

    class RuntimeFailureIcon(FakeIcon):
        def run(self, setup: Callable[[FakeIcon], None]) -> None:
            self.run_thread = threading.current_thread()
            setup(self)
            self.ready.set()
            assert allow_failure.wait(1)
            raise RuntimeError("native tray loop failed")

    pystray = SimpleNamespace(Menu=FakeMenu, MenuItem=FakeMenuItem, Icon=RuntimeFailureIcon)
    tray = module.TrayController(
        paths=SimpleNamespace(log_dir=tmp_path),
        base_url="http://127.0.0.1:17500",
        pystray_module=pystray,
        image_module=FakeImageModule,
        image_draw_module=FakeImageDrawModule,
        startup_timeout=0.5,
    )

    def record_failure(error: BaseException | None = None) -> None:
        failures.append(error)
        failed.set()

    assert (
        tray.start(
            on_show=lambda: None,
            on_exit=lambda *_args: None,
            on_unavailable=record_failure,
        )
        is True
    )
    allow_failure.set()
    assert failed.wait(1)
    tray.thread.join(1)

    assert not tray.thread.is_alive()
    assert tray.available is False
    assert len(failures) == 1
    assert isinstance(failures[0], RuntimeError)
    assert str(failures[0]) == "native tray loop failed"


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


def test_tray_exit_stops_icon_before_blocked_server_shutdown_and_returns(
    tmp_path: Path,
) -> None:
    module = _desktop_tray_module()
    callback_returned = threading.Event()
    server_stop_entered = threading.Event()
    release_server_stop = threading.Event()
    stop_threads: list[threading.Thread] = []

    class BlockingServer:
        def stop(self) -> None:
            stop_threads.append(threading.current_thread())
            server_stop_entered.set()
            assert release_server_stop.wait(1)

    class ExitCallbackIcon(FakeIcon):
        def run(self, setup: Callable[[FakeIcon], None]) -> None:
            self.run_thread = threading.current_thread()
            setup(self)
            self.ready.set()
            item = next(
                entry
                for entry in self.menu.items
                if isinstance(entry, FakeMenuItem) and entry.text == "退出"
            )
            item.action(self, item)
            callback_returned.set()
            self.stopped.wait(1)

    server = BlockingServer()
    pystray = SimpleNamespace(Menu=FakeMenu, MenuItem=FakeMenuItem, Icon=ExitCallbackIcon)
    tray = module.TrayController(
        paths=SimpleNamespace(log_dir=tmp_path),
        base_url="http://127.0.0.1:17500",
        pystray_module=pystray,
        image_module=FakeImageModule,
        image_draw_module=FakeImageDrawModule,
        startup_timeout=0.5,
    )

    try:
        assert (
            tray.start(
                on_show=lambda: None,
                on_exit=lambda *_args: server.stop(),
                on_unavailable=lambda *_args: None,
            )
            is True
        )
        assert server_stop_entered.wait(1)
        icon = ExitCallbackIcon.instances[-1]
        assert icon.stopped.is_set()
        assert callback_returned.wait(0.2)
        assert len(stop_threads) == 1
        assert stop_threads[0].name == "mod-watcher-shutdown"
        assert stop_threads[0].daemon is False
    finally:
        release_server_stop.set()
        tray.stop()
        for thread in stop_threads:
            if thread is not threading.current_thread():
                thread.join(1)

    assert not tray.thread.is_alive()
    assert all(not thread.is_alive() for thread in stop_threads)


def test_tray_exit_still_shuts_down_if_the_worker_cannot_start(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _desktop_tray_module()
    shutdown_called = threading.Event()
    shutdown_threads: list[threading.Thread] = []
    real_start = threading.Thread.start

    def controlled_start(thread: threading.Thread) -> None:
        if thread.name == "mod-watcher-shutdown":
            raise RuntimeError("shutdown worker could not start")
        real_start(thread)

    class ExitOnRunIcon(FakeIcon):
        def __init__(self, *args: object, **kwargs: object) -> None:
            super().__init__(*args, **kwargs)
            self.action_on_run = "退出"

    def record_shutdown(*_args: object) -> None:
        shutdown_threads.append(threading.current_thread())
        shutdown_called.set()

    monkeypatch.setattr(threading.Thread, "start", controlled_start)
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
            on_exit=record_shutdown,
            on_unavailable=lambda *_args: None,
        )
        is True
    )
    tray.thread.join(1)

    assert not tray.thread.is_alive()
    assert shutdown_called.is_set()
    assert shutdown_threads == [tray.thread]
    assert isinstance(tray.last_action_error, RuntimeError)
    assert str(tray.last_action_error) == "shutdown worker could not start"


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


def test_task5_lifecycle_tests_leave_no_live_non_daemon_workers() -> None:
    leaked = [
        thread
        for thread in threading.enumerate()
        if thread.name.startswith("mod-watcher-") and thread.is_alive() and not thread.daemon
    ]

    assert leaked == []
