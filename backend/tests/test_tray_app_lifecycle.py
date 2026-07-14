import os
import threading

import tray_app


class _FakeJob:
    def __init__(self, order: list[str] | None = None) -> None:
        self.order = order
        self.close_calls = 0

    def close(self) -> None:
        self.close_calls += 1
        if self.order is not None:
            self.order.append("job.close")


class _FakeIcon:
    def __init__(self, order: list[str]) -> None:
        self.order = order
        self.stop_calls = 0

    def stop(self) -> None:
        self.stop_calls += 1
        self.order.append("icon.stop")


class _FakeProc:
    def __init__(self, pid: int) -> None:
        self.pid = pid


def _make_app() -> tray_app.TrayApp:
    app = tray_app.TrayApp.__new__(tray_app.TrayApp)
    app.backend_proc = None
    app.frontend_proc = None
    app.icon = None
    app.scheduler_paused = False
    app.use_tray = True
    app.open_browser = False
    app.frontend_mode = "static"
    app.frontend_port = tray_app.BACKEND_PORT
    app.frontend_url = f"http://{tray_app.BACKEND_HOST}:{app.frontend_port}"
    app.app_title = "Mod Watcher Agent"
    app.service_job = _FakeJob()
    app._stop_lock = threading.Lock()
    app._cleanup_lock = threading.Lock()
    app._stop_started = False
    app._services_cleaned = False
    app._exit_thread = None
    return app


def test_tray_exit_request_runs_once_when_clicked_repeatedly(monkeypatch):
    app = _make_app()
    entered = threading.Event()
    release = threading.Event()
    calls = []

    def fake_stop_impl() -> None:
        calls.append(threading.current_thread().name)
        entered.set()
        assert release.wait(2)

    monkeypatch.setattr(app, "_stop_impl", fake_stop_impl)

    app._exit_app(None, None)
    assert entered.wait(2)

    app._exit_app(None, None)

    release.set()
    app._exit_thread.join(timeout=2)

    assert calls == ["ModWatcherTrayExit"]


def test_stop_impl_stops_icon_first_and_cleans_services_once(monkeypatch):
    app = _make_app()
    order = []
    app.icon = _FakeIcon(order)
    app.backend_proc = _FakeProc(101)
    app.frontend_proc = _FakeProc(202)
    app.service_job = _FakeJob(order)

    monkeypatch.setattr(
        tray_app,
        "_terminate_process_tree",
        lambda pid, name: order.append(f"terminate:{name}:{pid}"),
    )
    monkeypatch.setattr(
        tray_app,
        "_kill_port_owners",
        lambda port, label, managed_pids=None: order.append(f"kill-port:{label}:{port}"),
    )
    monkeypatch.setattr(tray_app, "_write_state", lambda state: None)
    monkeypatch.setattr(tray_app, "_read_state", lambda: {"manager_pid": os.getpid()})
    monkeypatch.setattr(tray_app, "_clear_state", lambda: order.append("clear-state"))

    app._stop_impl()
    app._cleanup_services()

    assert order == [
        "icon.stop",
        "terminate:backend:101",
        "terminate:frontend:202",
        "job.close",
        "clear-state",
    ]
    assert app.icon is None
    assert app.backend_proc is None
    assert app.frontend_proc is None
    assert app.service_job.close_calls == 1
