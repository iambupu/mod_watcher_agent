from __future__ import annotations

import importlib
import threading
from collections.abc import Callable
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest


def _desktop_controller_module() -> ModuleType:
    try:
        return importlib.import_module("app.desktop.controller")
    except ModuleNotFoundError:
        pytest.fail("app.desktop.controller is not implemented", pytrace=False)


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
        self.on_unavailable: Callable[..., object] | None = None
        self.stop_calls = 0

    def start(
        self,
        *,
        on_show: Callable[..., object],
        on_exit: Callable[..., object],
        on_unavailable: Callable[..., object] | None = None,
    ) -> bool:
        self.history.append("tray.start")
        self.on_show = on_show
        self.on_exit = on_exit
        self.on_unavailable = on_unavailable
        return self.available

    def stop(self) -> None:
        self.stop_calls += 1
        self.history.append("tray.stop")

    def lose_runtime(self, error: BaseException | None = None) -> None:
        self.available = False
        if self.on_unavailable is not None:
            self.on_unavailable(error)


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


@pytest.mark.parametrize(
    ("callback_name", "expected_result"),
    [
        ("on_window_minimized", None),
        ("on_window_closing", False),
    ],
)
def test_tray_loss_restore_cannot_be_overwritten_by_a_late_hide(
    tmp_path: Path,
    callback_name: str,
    expected_result: object,
) -> None:
    module = _desktop_controller_module()
    controller, _server, window, tray, _guard, history = _make_controller(tmp_path)
    controller.tray_available = True
    tray.on_unavailable = controller.on_tray_unavailable
    hide_entered = threading.Event()
    allow_tray_loss = threading.Event()
    tray_loss_restored = threading.Event()
    window_visible = True
    results: list[object] = []

    def blocking_hide() -> None:
        nonlocal window_visible
        window.hide_calls += 1
        history.append("window.hide.enter")
        hide_entered.set()
        assert allow_tray_loss.wait(1)
        tray.lose_runtime(RuntimeError("native tray loop exited during hide"))
        assert window.show_calls == 1
        assert window.restore_calls == 1
        tray_loss_restored.set()
        window_visible = False
        history.append("window.hide.complete")

    def visible_show() -> None:
        nonlocal window_visible
        window.show_calls += 1
        window_visible = True
        history.append("window.show")

    def visible_restore() -> None:
        nonlocal window_visible
        window.restore_calls += 1
        window_visible = True
        history.append("window.restore")

    window.hide = blocking_hide  # type: ignore[method-assign]
    window.show = visible_show  # type: ignore[method-assign]
    window.restore = visible_restore  # type: ignore[method-assign]

    callback = getattr(controller, callback_name)
    transition = threading.Thread(target=lambda: results.append(callback()))
    transition.start()
    assert hide_entered.wait(1)
    assert controller.state is module.DesktopState.WINDOW_HIDDEN
    allow_tray_loss.set()
    transition.join(1)

    assert not transition.is_alive()
    assert tray_loss_restored.is_set()
    assert results == [expected_result]
    assert window_visible is True
    assert controller.state is module.DesktopState.WINDOW_VISIBLE
    assert history[-3:] == ["window.hide.complete", "window.show", "window.restore"]


def test_shutdown_serializes_destroy_after_an_in_progress_hide(tmp_path: Path) -> None:
    controller, _server, window, _tray, _guard, history = _make_controller(tmp_path)
    controller.tray_available = True
    hide_entered = threading.Event()
    release_hide = threading.Event()
    destroy_entered = threading.Event()

    def blocking_hide() -> None:
        window.hide_calls += 1
        history.append("window.hide")
        hide_entered.set()
        assert release_hide.wait(1)

    def observed_destroy() -> None:
        window.destroy_calls += 1
        history.append("window.destroy")
        destroy_entered.set()

    window.hide = blocking_hide  # type: ignore[method-assign]
    window.destroy = observed_destroy  # type: ignore[method-assign]
    hide = threading.Thread(target=controller.on_window_minimized)
    shutdown = threading.Thread(target=controller.shutdown, args=("test",))
    hide.start()
    assert hide_entered.wait(1)
    shutdown.start()
    try:
        assert not destroy_entered.wait(0.2)
    finally:
        release_hide.set()
        hide.join(1)
        shutdown.join(1)

    assert not hide.is_alive()
    assert not shutdown.is_alive()
    assert destroy_entered.is_set()
    assert history.index("window.hide") < history.index("window.destroy")


@pytest.mark.parametrize(
    ("callback_name", "expected_result"),
    [
        ("on_window_minimized", None),
        ("on_window_closing", True),
    ],
)
def test_hide_failure_enters_failed_cleanup(
    tmp_path: Path,
    callback_name: str,
    expected_result: object,
) -> None:
    module = _desktop_controller_module()
    controller, server, window, tray, guard, _history = _make_controller(tmp_path)
    controller.tray_available = True

    def failing_hide() -> None:
        window.hide_calls += 1
        raise RuntimeError("native window could not be hidden")

    window.hide = failing_hide  # type: ignore[method-assign]

    result = getattr(controller, callback_name)()

    assert result is expected_result
    assert controller.state is module.DesktopState.FAILED
    assert isinstance(controller.error, RuntimeError)
    assert str(controller.error) == "native window could not be hidden"
    assert controller.shutdown_complete.is_set()
    assert server.stop_calls == 1
    assert tray.stop_calls == 1
    assert window.destroy_calls == 1
    assert guard.release_calls == 1


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
            on_unavailable: Callable[..., object] | None = None,
        ) -> bool:
            super().start(
                on_show=on_show,
                on_exit=on_exit,
                on_unavailable=on_unavailable,
            )
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


def test_controller_stops_tray_before_waiting_for_blocked_server_cleanup(
    tmp_path: Path,
) -> None:
    controller, server, _window, tray, _guard, history = _make_controller(tmp_path)
    server_stop_entered = threading.Event()
    release_server_stop = threading.Event()

    def blocking_server_stop() -> None:
        server.stop_calls += 1
        history.append("server.stop")
        server_stop_entered.set()
        assert release_server_stop.wait(1)

    server.stop = blocking_server_stop  # type: ignore[method-assign]
    shutdown = threading.Thread(target=controller.shutdown, args=("test",))
    shutdown.start()
    try:
        assert server_stop_entered.wait(1)
        assert tray.stop_calls == 1
        assert history.index("tray.stop") < history.index("server.stop")
    finally:
        release_server_stop.set()
        shutdown.join(1)

    assert not shutdown.is_alive()


def test_concurrent_shutdown_caller_waits_for_the_cleanup_owner(
    tmp_path: Path,
) -> None:
    controller, server, _window, _tray, _guard, history = _make_controller(tmp_path)
    server_stop_entered = threading.Event()
    release_server_stop = threading.Event()
    waiter_started = threading.Event()
    waiter_returned = threading.Event()

    def blocking_server_stop() -> None:
        server.stop_calls += 1
        history.append("server.stop")
        server_stop_entered.set()
        assert release_server_stop.wait(1)

    def wait_for_shutdown() -> None:
        waiter_started.set()
        controller.shutdown("waiter")
        waiter_returned.set()

    server.stop = blocking_server_stop  # type: ignore[method-assign]
    owner = threading.Thread(target=controller.shutdown, args=("owner",))
    waiter = threading.Thread(target=wait_for_shutdown)
    owner.start()
    assert server_stop_entered.wait(1)
    waiter.start()
    try:
        assert waiter_started.wait(1)
        assert not waiter_returned.wait(0.2)
        assert not controller.shutdown_complete.is_set()
    finally:
        release_server_stop.set()
        owner.join(1)
        waiter.join(1)

    assert not owner.is_alive()
    assert not waiter.is_alive()
    assert waiter_returned.is_set()
    assert controller.shutdown_complete.is_set()


def test_cleanup_owner_does_not_wait_for_its_own_reentrant_shutdown(
    tmp_path: Path,
) -> None:
    controller, _server, _window, tray, _guard, history = _make_controller(tmp_path)
    reentrant_returned = threading.Event()

    def reentrant_tray_stop() -> None:
        tray.stop_calls += 1
        history.append("tray.stop")
        controller.shutdown("reentrant")
        reentrant_returned.set()

    tray.stop = reentrant_tray_stop  # type: ignore[method-assign]
    owner = threading.Thread(target=controller.shutdown, args=("owner",))
    owner.start()
    owner.join(1)

    assert not owner.is_alive()
    assert reentrant_returned.is_set()
    assert controller.shutdown_complete.is_set()


def test_start_waits_for_in_progress_shutdown_after_window_loop_returns(
    tmp_path: Path,
) -> None:
    module = _desktop_controller_module()
    history: list[str] = []
    window_run_entered = threading.Event()
    window_destroyed = threading.Event()
    guard_release_entered = threading.Event()
    release_guard = threading.Event()
    start_returned = threading.Event()
    results: list[int] = []
    errors: list[BaseException] = []

    class DestroyReleasesWindow(FakeWindow):
        def run(self) -> None:
            self.history.append("window.run")
            window_run_entered.set()
            assert window_destroyed.wait(1)

        def destroy(self) -> None:
            super().destroy()
            window_destroyed.set()

    class BlockingGuard(FakeGuard):
        def release(self) -> None:
            self.release_calls += 1
            self.history.append("guard.release")
            guard_release_entered.set()
            assert release_guard.wait(1)

    server = FakeServer(history)
    window = DestroyReleasesWindow(history)
    tray = FakeTray(history)
    guard = BlockingGuard(history)
    controller = module.DesktopController(
        server=server,
        window=window,
        tray=tray,
        guard=guard,
        paths=SimpleNamespace(log_dir=tmp_path),
    )

    def start_controller() -> None:
        try:
            results.append(controller.start())
        except BaseException as exc:
            errors.append(exc)
        finally:
            start_returned.set()

    start_thread = threading.Thread(target=start_controller)
    shutdown_thread = threading.Thread(target=controller.shutdown, args=("test",))
    start_thread.start()
    assert window_run_entered.wait(1)
    shutdown_thread.start()
    try:
        assert guard_release_entered.wait(1)
        assert not start_returned.wait(0.2)
        assert controller.state is module.DesktopState.EXITING
    finally:
        release_guard.set()
        shutdown_thread.join(1)
        start_thread.join(1)

    assert not shutdown_thread.is_alive()
    assert not start_thread.is_alive()
    assert errors == []
    assert results == [0]
    assert controller.state is module.DesktopState.STOPPED
    assert controller.shutdown_complete.is_set()


def test_cleanup_does_not_overwrite_a_concurrent_runtime_failure(
    tmp_path: Path,
) -> None:
    module = _desktop_controller_module()
    controller, server, window, tray, guard, history = _make_controller(tmp_path)
    restore_entered = threading.Event()
    release_restore = threading.Event()
    server_stop_entered = threading.Event()
    release_server_stop = threading.Event()
    failure_cleanup_called = threading.Event()
    real_cleanup = controller._cleanup

    def failing_restore() -> None:
        window.restore_calls += 1
        history.append("window.restore")
        restore_entered.set()
        assert release_restore.wait(1)
        raise RuntimeError("window cannot be restored")

    def blocking_server_stop() -> None:
        server.stop_calls += 1
        history.append("server.stop")
        server_stop_entered.set()
        assert release_server_stop.wait(1)

    def observed_cleanup(*, preserve_failure: bool) -> None:
        if preserve_failure:
            failure_cleanup_called.set()
        real_cleanup(preserve_failure=preserve_failure)

    window.restore = failing_restore  # type: ignore[method-assign]
    server.stop = blocking_server_stop  # type: ignore[method-assign]
    controller._cleanup = observed_cleanup  # type: ignore[method-assign]
    controller.state = module.DesktopState.WINDOW_HIDDEN
    controller.tray_available = True

    runtime_loss = threading.Thread(
        target=controller.on_tray_unavailable,
        args=(RuntimeError("native tray loop exited"),),
    )
    owner = threading.Thread(target=controller.shutdown, args=("owner",))
    runtime_loss.start()
    assert restore_entered.wait(1)
    owner.start()
    assert server_stop_entered.wait(1)
    release_restore.set()
    try:
        assert failure_cleanup_called.wait(1)
    finally:
        release_server_stop.set()
        owner.join(1)
        runtime_loss.join(1)

    assert not owner.is_alive()
    assert not runtime_loss.is_alive()
    assert controller.state is module.DesktopState.FAILED
    assert isinstance(controller.error, RuntimeError)
    assert str(controller.error) == "window cannot be restored"
    assert tray.stop_calls == 1
    assert server.stop_calls == 1
    assert window.destroy_calls == 1
    assert guard.release_calls == 1
    assert controller.shutdown_complete.is_set()


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


def test_runtime_tray_loss_restores_a_window_hidden_before_the_loop_exits(
    tmp_path: Path,
) -> None:
    module = _desktop_controller_module()
    controller, _server, window, tray, _guard, _history = _make_controller(tmp_path)
    recovery_states: list[object] = []

    def terminate_tray_after_hiding() -> None:
        controller.on_window_minimized()
        assert controller.state is module.DesktopState.WINDOW_HIDDEN
        tray.lose_runtime(RuntimeError("native tray loop exited"))
        recovery_states.append(controller.state)

    window.on_run = terminate_tray_after_hiding

    assert controller.start() == 0

    assert controller.tray_available is False
    assert window.hide_calls == 1
    assert window.show_calls == 1
    assert window.restore_calls == 1
    assert recovery_states == [module.DesktopState.WINDOW_VISIBLE]


def test_runtime_tray_loss_restore_failure_uses_failed_shutdown_path(
    tmp_path: Path,
) -> None:
    module = _desktop_controller_module()
    controller, server, window, tray, guard, history = _make_controller(tmp_path)

    def fail_restore() -> None:
        window.restore_calls += 1
        history.append("window.restore")
        raise RuntimeError("window cannot be restored")

    def terminate_tray_after_hiding() -> None:
        controller.on_window_minimized()
        tray.lose_runtime(RuntimeError("native tray loop exited"))

    window.restore = fail_restore  # type: ignore[method-assign]
    window.on_run = terminate_tray_after_hiding

    assert controller.start() == 1

    assert controller.state is module.DesktopState.FAILED
    assert isinstance(controller.error, RuntimeError)
    assert str(controller.error) == "window cannot be restored"
    assert server.stop_calls == 1
    assert tray.stop_calls == 1
    assert window.destroy_calls == 1
    assert guard.release_calls == 1
