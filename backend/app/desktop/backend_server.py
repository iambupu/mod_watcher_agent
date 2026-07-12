from __future__ import annotations

import importlib
import threading
import time
from collections.abc import Callable
from typing import Any, Protocol

import httpx
import uvicorn

_READY_POLL_INTERVAL_SECONDS = 0.05
_HEALTH_REQUEST_TIMEOUT_SECONDS = 0.1


class EmbeddedBackendError(RuntimeError):
    """Raised when the embedded backend cannot complete its lifecycle."""


class EmbeddedBackendStopTimeoutError(EmbeddedBackendError):
    """Require process termination when the non-daemon backend thread survives."""

    requires_forced_exit = True


class _UvicornServer(Protocol):
    should_exit: bool
    started: bool

    def run(self) -> None: ...


AppFactory = Callable[[], Any]
ServerFactory = Callable[[uvicorn.Config], _UvicornServer]


def _load_default_app() -> Any:
    """Import the production ASGI app only when the server thread starts."""
    return importlib.import_module("app.main").app


class EmbeddedBackendServer:
    """Run Uvicorn in-process for the Windows desktop application."""

    def __init__(
        self,
        host: str,
        port: int,
        app_factory: AppFactory | None = None,
        health_path: str = "/api/health",
        server_factory: ServerFactory = uvicorn.Server,
    ) -> None:
        self.host = host
        self.port = port
        self.health_path = health_path if health_path.startswith("/") else f"/{health_path}"
        self._app_factory = app_factory or _load_default_app
        self._server_factory = server_factory
        self._server: _UvicornServer | None = None
        self._error: BaseException | None = None
        self._started = False
        self._stop_requested = threading.Event()
        self._state_lock = threading.Lock()
        self._thread: threading.Thread | None = None

    @property
    def thread(self) -> threading.Thread:
        with self._state_lock:
            thread = self._thread
        if thread is None:
            raise EmbeddedBackendError("Embedded backend server has not been started")
        return thread

    @property
    def error(self) -> BaseException | None:
        with self._state_lock:
            return self._error

    def start(self) -> None:
        with self._state_lock:
            if self._started:
                raise RuntimeError("Embedded backend server already started")
            try:
                thread = threading.Thread(
                    target=self._run,
                    name="mod-watcher-backend",
                    daemon=False,
                )
                self._thread = thread
                self._started = True
                thread.start()
            except BaseException as exc:
                self._started = False
                self._thread = None
                raise EmbeddedBackendError(
                    "Embedded backend server thread failed to start"
                ) from exc

    def wait_ready(self, timeout: float) -> bool:
        deadline = time.monotonic() + max(timeout, 0)
        health_url = f"http://{self.host}:{self.port}{self.health_path}"

        with httpx.Client(trust_env=False) as client:
            while time.monotonic() < deadline:
                with self._state_lock:
                    error = self._error
                    thread = self._thread
                    server = self._server
                if error is not None or thread is None or not thread.is_alive():
                    return False

                if server is None or not bool(server.started):
                    remaining = deadline - time.monotonic()
                    if remaining > 0:
                        time.sleep(min(_READY_POLL_INTERVAL_SECONDS, remaining))
                    continue

                remaining = deadline - time.monotonic()
                request_timeout = min(_HEALTH_REQUEST_TIMEOUT_SECONDS, remaining)
                try:
                    response = client.get(health_url, timeout=request_timeout)
                    payload = response.json()
                    if (
                        response.status_code == 200
                        and isinstance(payload, dict)
                        and payload.get("status") == "ok"
                    ):
                        return True
                except (httpx.HTTPError, ValueError):
                    pass

                remaining = deadline - time.monotonic()
                if remaining > 0:
                    time.sleep(min(_READY_POLL_INTERVAL_SECONDS, remaining))

        return False

    def stop(self, timeout: float = 10) -> None:
        with self._state_lock:
            if not self._started:
                return
            thread = self._thread
            if thread is None:
                raise EmbeddedBackendError("Embedded backend server thread is unavailable")
            self._stop_requested.set()
            server = self._server

        if server is not None:
            server.should_exit = True

        thread.join(max(timeout, 0))
        if thread.is_alive():
            raise EmbeddedBackendStopTimeoutError(
                f"Embedded backend server did not stop within {timeout:g} seconds"
            )

    def _run(self) -> None:
        try:
            app = self._app_factory()
            config = uvicorn.Config(
                app=app,
                host=self.host,
                port=self.port,
                log_config=None,
                access_log=False,
                ws="none",
            )
            server = self._server_factory(config)
            with self._state_lock:
                self._server = server
                stop_requested = self._stop_requested.is_set()
            if stop_requested:
                server.should_exit = True
            server.run()
        except BaseException as exc:
            with self._state_lock:
                self._error = exc
