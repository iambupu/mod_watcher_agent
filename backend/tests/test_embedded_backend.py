from __future__ import annotations

import socket
import threading
import time
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from app.desktop.backend_server import EmbeddedBackendError, EmbeddedBackendServer


class _FakeUvicornServer:
    instances: list[_FakeUvicornServer] = []
    created = threading.Event()

    def __init__(self, config: Any) -> None:
        self.config = config
        self.should_exit = False
        self.started = False
        self.run_started = threading.Event()
        type(self).instances.append(self)
        type(self).created.set()

    def run(self) -> None:
        self.started = True
        self.run_started.set()
        while not self.should_exit:
            time.sleep(0.001)


class _DelayedFactory:
    def __init__(self) -> None:
        self.entered = threading.Event()
        self.release = threading.Event()
        self.instance: _FakeUvicornServer | None = None

    def __call__(self, config: Any) -> _FakeUvicornServer:
        self.entered.set()
        self.release.wait(1)
        self.instance = _FakeUvicornServer(config)
        return self.instance


class _StopAwareLock:
    def __init__(
        self,
        *,
        release_server_start: threading.Event,
        stop_observed: threading.Event,
    ) -> None:
        self._lock = threading.Lock()
        self._release_server_start = release_server_start
        self._stop_observed = stop_observed

    def __enter__(self) -> _StopAwareLock:
        if threading.current_thread().name == "controlled-stop":
            if self._lock.locked():
                self._release_server_start.set()
            self._stop_observed.set()
        self._lock.acquire()
        return self

    def __exit__(self, *_args: object) -> None:
        self._lock.release()


@pytest.fixture(autouse=True)
def clear_fake_instances() -> Iterator[None]:
    _FakeUvicornServer.instances.clear()
    _FakeUvicornServer.created.clear()
    yield


@pytest.fixture
def unused_port() -> Iterator[int]:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    yield port


def _health_app() -> FastAPI:
    app = FastAPI()

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "database": "ready", "frontend": "ready"}

    return app


def _port_accepts_connections(port: int) -> bool:
    with socket.socket() as probe:
        probe.settimeout(0.1)
        return probe.connect_ex(("127.0.0.1", port)) == 0


def test_server_starts_once_on_a_non_daemon_thread_and_stop_is_idempotent() -> None:
    server = EmbeddedBackendServer(
        "127.0.0.1",
        17500,
        app_factory=_health_app,
        server_factory=_FakeUvicornServer,
    )

    server.start()
    try:
        assert _FakeUvicornServer.created.wait(1)
        assert server.thread.daemon is False
        assert _FakeUvicornServer.instances[0].config.ws == "none"
        assert _FakeUvicornServer.instances[0].run_started.wait(1)
        with pytest.raises(RuntimeError, match="already started"):
            server.start()
    finally:
        server.stop()
    server.stop()

    assert _FakeUvicornServer.instances[0].should_exit is True
    assert not server.thread.is_alive()


def test_start_and_concurrent_stop_never_expose_an_unstarted_thread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release_server_start = threading.Event()
    server_start_entered = threading.Event()
    stop_observed = threading.Event()
    start_errors: list[BaseException] = []
    stop_errors: list[BaseException] = []
    real_thread_start = threading.Thread.start
    real_thread_join = threading.Thread.join

    server = EmbeddedBackendServer(
        "127.0.0.1",
        17500,
        app_factory=_health_app,
        server_factory=_FakeUvicornServer,
    )
    server._state_lock = _StopAwareLock(
        release_server_start=release_server_start,
        stop_observed=stop_observed,
    )

    def controlled_thread_start(thread: threading.Thread) -> None:
        if thread.name != "mod-watcher-backend":
            real_thread_start(thread)
            return
        server_start_entered.set()
        assert release_server_start.wait(1)
        real_thread_start(thread)

    def controlled_thread_join(
        thread: threading.Thread,
        timeout: float | None = None,
    ) -> None:
        if thread.name != "mod-watcher-backend":
            real_thread_join(thread, timeout)
            return
        try:
            real_thread_join(thread, timeout)
        finally:
            release_server_start.set()

    def call_start() -> None:
        try:
            server.start()
        except BaseException as exc:
            start_errors.append(exc)

    def call_stop() -> None:
        try:
            server.stop(timeout=1)
        except BaseException as exc:
            stop_errors.append(exc)

    monkeypatch.setattr(threading.Thread, "start", controlled_thread_start)
    monkeypatch.setattr(threading.Thread, "join", controlled_thread_join)

    starter = threading.Thread(target=call_start, name="controlled-start")
    stopper = threading.Thread(target=call_stop, name="controlled-stop")
    starter.start()
    assert server_start_entered.wait(1)
    stopper.start()
    assert stop_observed.wait(1)
    starter.join(2)
    stopper.join(2)
    release_server_start.set()
    server.stop()

    assert not starter.is_alive()
    assert not stopper.is_alive()
    assert start_errors == []
    assert stop_errors == []
    assert not server.thread.is_alive()


def test_thread_start_failure_rolls_back_state_and_allows_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_thread_start = threading.Thread.start
    backend_start_attempts = 0
    server = EmbeddedBackendServer(
        "127.0.0.1",
        17500,
        app_factory=_health_app,
        server_factory=_FakeUvicornServer,
    )

    def fail_first_backend_start(thread: threading.Thread) -> None:
        nonlocal backend_start_attempts
        if thread.name == "mod-watcher-backend":
            backend_start_attempts += 1
            if backend_start_attempts == 1:
                raise RuntimeError("synthetic thread start failure")
        real_thread_start(thread)

    monkeypatch.setattr(threading.Thread, "start", fail_first_backend_start)

    with pytest.raises(EmbeddedBackendError, match="failed to start") as error:
        server.start()

    assert isinstance(error.value.__cause__, RuntimeError)
    assert server._started is False
    assert server._thread is None

    server.start()
    try:
        assert _FakeUvicornServer.created.wait(1)
    finally:
        server.stop()

    assert backend_start_attempts == 2
    assert not server.thread.is_alive()


def test_thread_base_exception_is_exposed_and_stops_readiness_wait() -> None:
    class FatalServer:
        def __init__(self, config: Any) -> None:
            self.config = config
            self.should_exit = False

        def run(self) -> None:
            raise KeyboardInterrupt("fatal server failure")

    server = EmbeddedBackendServer(
        "127.0.0.1",
        17500,
        app_factory=_health_app,
        server_factory=FatalServer,
    )

    server.start()
    server.thread.join(1)

    assert isinstance(server.error, KeyboardInterrupt)
    assert server.wait_ready(timeout=1) is False


def test_wait_ready_requires_ok_json_health_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    responses = iter(
        [
            httpx.Response(200, json={"status": "starting"}),
            httpx.Response(503, json={"status": "ok"}),
            httpx.Response(200, content=b"not-json"),
            httpx.Response(
                200,
                json={"status": "ok", "database": "ready", "frontend": "ready"},
            ),
        ]
    )
    requested_urls: list[str] = []
    client_options: list[dict[str, object]] = []
    server = EmbeddedBackendServer(
        "127.0.0.1",
        17500,
        app_factory=_health_app,
        health_path="/ready",
        server_factory=_FakeUvicornServer,
    )

    class FakeClient:
        def __init__(self, **kwargs: object) -> None:
            client_options.append(kwargs)

        def __enter__(self) -> FakeClient:
            return self

        def __exit__(self, *_args: object) -> None:
            pass

        def get(self, url: str, *, timeout: float) -> httpx.Response:
            requested_urls.append(url)
            assert timeout > 0
            return next(responses)

    monkeypatch.setattr(httpx, "Client", FakeClient)
    server.start()
    try:
        assert server.wait_ready(timeout=1) is True
    finally:
        server.stop()

    assert requested_urls == ["http://127.0.0.1:17500/ready"] * 4
    assert client_options == [{"trust_env": False}]


def test_wait_ready_requires_database_and_frontend_ready(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    responses = iter(
        [
            httpx.Response(
                200,
                json={"status": "ok", "database": "starting", "frontend": "ready"},
            ),
            httpx.Response(
                200,
                json={"status": "ok", "database": "ready", "frontend": "missing"},
            ),
            httpx.Response(
                200,
                json={"status": "ok", "database": "ready", "frontend": "ready"},
            ),
        ]
    )
    requested_urls: list[str] = []
    server = EmbeddedBackendServer(
        "127.0.0.1",
        17500,
        app_factory=_health_app,
        server_factory=_FakeUvicornServer,
    )

    class FakeClient:
        def __enter__(self) -> FakeClient:
            return self

        def __exit__(self, *_args: object) -> None:
            pass

        def get(self, url: str, *, timeout: float) -> httpx.Response:
            requested_urls.append(url)
            assert timeout > 0
            return next(responses)

    monkeypatch.setattr(httpx, "Client", lambda **_kwargs: FakeClient())
    server.start()
    try:
        assert server.wait_ready(timeout=1) is True
    finally:
        server.stop()

    assert requested_urls == ["http://127.0.0.1:17500/api/health"] * 3


def test_wait_ready_rejects_health_from_a_foreign_listener() -> None:
    class ForeignHealthHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            body = b'{"status":"ok"}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args: object) -> None:
            return

    class NeverBoundOwnedServer:
        def __init__(self, config: Any) -> None:
            self.config = config
            self.should_exit = False
            self.started = False

        def run(self) -> None:
            while not self.should_exit:
                time.sleep(0.001)

    foreign = ThreadingHTTPServer(("127.0.0.1", 0), ForeignHealthHandler)
    foreign_thread = threading.Thread(target=foreign.serve_forever, daemon=True)
    foreign_thread.start()
    with httpx.Client(trust_env=False) as client:
        assert client.get(
            f"http://127.0.0.1:{foreign.server_port}/api/health",
            timeout=1,
        ).json() == {"status": "ok"}
    server = EmbeddedBackendServer(
        "127.0.0.1",
        foreign.server_port,
        app_factory=_health_app,
        server_factory=NeverBoundOwnedServer,
    )
    server.start()
    try:
        assert server.wait_ready(timeout=1) is False
    finally:
        server.stop()
        foreign.shutdown()
        foreign.server_close()
        foreign_thread.join(1)


def test_stop_waits_for_server_creation_race() -> None:
    delayed_factory = _DelayedFactory()
    server = EmbeddedBackendServer(
        "127.0.0.1",
        17500,
        app_factory=_health_app,
        server_factory=delayed_factory,
    )

    server.start()
    assert delayed_factory.entered.wait(1)

    stopper = threading.Thread(target=server.stop, kwargs={"timeout": 1})
    stopper.start()
    delayed_factory.release.set()
    stopper.join(1)

    assert not stopper.is_alive()
    assert delayed_factory.instance is not None
    assert delayed_factory.instance.should_exit is True
    assert not server.thread.is_alive()


def test_stop_raises_clear_error_when_thread_does_not_finish() -> None:
    release = threading.Event()

    class StubbornServer:
        def __init__(self, config: Any) -> None:
            self.config = config
            self.should_exit = False

        def run(self) -> None:
            release.wait()

    server = EmbeddedBackendServer(
        "127.0.0.1",
        17500,
        app_factory=_health_app,
        server_factory=StubbornServer,
    )
    server.start()

    try:
        with pytest.raises(EmbeddedBackendError, match="did not stop within"):
            server.stop(timeout=0.01)
    finally:
        release.set()
        server.thread.join(1)


def test_real_server_starts_reports_ready_stops_and_releases_port(unused_port: int) -> None:
    server = EmbeddedBackendServer(
        "127.0.0.1",
        unused_port,
        app_factory=_health_app,
    )

    server.start()
    try:
        assert server.wait_ready(timeout=5) is True
        assert _port_accepts_connections(unused_port)
    finally:
        server.stop()

    assert not server.thread.is_alive()
    assert not _port_accepts_connections(unused_port)


def test_real_server_accepts_a_prebound_socket_and_releases_it_on_stop() -> None:
    reserved_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    reserved_socket.bind(("127.0.0.1", 0))
    reserved_socket.listen()
    port = int(reserved_socket.getsockname()[1])
    server = EmbeddedBackendServer(
        "127.0.0.1",
        port,
        app_factory=_health_app,
        prebound_socket=reserved_socket,
    )

    server.start()
    try:
        assert server.wait_ready(timeout=5) is True
        assert _port_accepts_connections(port)
    finally:
        server.stop()

    assert reserved_socket.fileno() == -1
    assert not _port_accepts_connections(port)


def test_stop_before_start_releases_a_prebound_socket() -> None:
    reserved_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    reserved_socket.bind(("127.0.0.1", 0))
    port = int(reserved_socket.getsockname()[1])
    server = EmbeddedBackendServer(
        "127.0.0.1",
        port,
        app_factory=_health_app,
        prebound_socket=reserved_socket,
    )

    server.stop()

    assert reserved_socket.fileno() == -1
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as replacement:
        replacement.bind(("127.0.0.1", port))


def test_default_app_factory_imports_main_only_when_thread_runs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    imports: list[str] = []
    imported_app = object()

    def fake_import_module(name: str) -> Any:
        imports.append(name)
        return type("MainModule", (), {"app": imported_app})

    monkeypatch.setattr("importlib.import_module", fake_import_module)
    server = EmbeddedBackendServer(
        "127.0.0.1",
        17500,
        server_factory=_FakeUvicornServer,
    )

    assert imports == []
    server.start()
    try:
        assert _FakeUvicornServer.created.wait(1)
        assert _FakeUvicornServer.instances[0].run_started.wait(1)
    finally:
        server.stop()

    assert imports == ["app.main"]
    assert _FakeUvicornServer.instances[0].config.app is imported_app
