from pathlib import Path

import tray_app


def test_kill_port_owners_only_terminates_recorded_managed_process(monkeypatch):
    terminated = []
    monkeypatch.setattr(tray_app, "_port_owner_pids", lambda port: {101, 202})
    monkeypatch.setattr(
        tray_app,
        "_terminate_process_tree",
        lambda pid, label: terminated.append((pid, label)),
    )

    tray_app._kill_port_owners(17500, "backend", managed_pids={202})

    assert terminated == [(202, "backend-port-17500")]


def test_launch_backend_closes_parent_log_handle(monkeypatch, tmp_path):
    app = tray_app.TrayApp.__new__(tray_app.TrayApp)
    app.backend_proc = None
    app.frontend_proc = None
    app.service_job = type("Job", (), {"add": lambda self, proc: None})()
    app._save_state = lambda: None
    closed = []

    class FakeLog:
        def write(self, value):
            return len(value)

        def flush(self):
            return None

        def close(self):
            closed.append(True)

    fake_log = FakeLog()
    monkeypatch.setattr(tray_app, "_check_port", lambda host, port: False)
    monkeypatch.setattr(tray_app, "_kill_port_owners", lambda *args, **kwargs: None)
    monkeypatch.setattr(tray_app, "_open_service_log", lambda path: fake_log, raising=False)
    monkeypatch.setattr(
        tray_app.subprocess,
        "Popen",
        lambda *args, **kwargs: type("Proc", (), {"pid": 123})(),
    )
    monkeypatch.setattr(tray_app, "LOG_DIR", Path(tmp_path))

    app.launch_backend()

    assert closed == [True]
