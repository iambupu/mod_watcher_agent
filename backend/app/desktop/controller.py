from __future__ import annotations

import threading
from enum import StrEnum
from typing import Protocol


class DesktopStartupError(RuntimeError):
    """Raised when the desktop application cannot become usable."""


class DesktopState(StrEnum):
    CREATED = "created"
    STARTING_BACKEND = "starting_backend"
    BACKEND_READY = "backend_ready"
    WINDOW_VISIBLE = "window_visible"
    WINDOW_HIDDEN = "window_hidden"
    EXITING = "exiting"
    STOPPED = "stopped"
    FAILED = "failed"


class _Server(Protocol):
    error: BaseException | None

    def start(self) -> None: ...

    def wait_ready(self, timeout: float) -> bool: ...

    def stop(self) -> None: ...


class _Window(Protocol):
    def bind(self, *, on_minimized: object, on_closing: object) -> None: ...

    def create(self) -> None: ...

    def run(self) -> None: ...

    def hide(self) -> None: ...

    def show(self) -> None: ...

    def restore(self) -> None: ...

    def destroy(self) -> None: ...


class _Tray(Protocol):
    def start(self, *, on_show: object, on_exit: object) -> bool: ...

    def stop(self) -> None: ...


class _Guard(Protocol):
    def release(self) -> None: ...


class DesktopController:
    """Own and coordinate the complete desktop process lifecycle."""

    def __init__(
        self,
        server: _Server,
        window: _Window,
        tray: _Tray,
        guard: _Guard,
        paths: object,
        *,
        ready_timeout: float = 30.0,
    ) -> None:
        self.server = server
        self.window = window
        self.tray = tray
        self.guard = guard
        self.paths = paths
        self.ready_timeout = ready_timeout

        self.state = DesktopState.CREATED
        self.tray_available = False
        self.error: BaseException | None = None
        self.shutdown_complete = threading.Event()
        self._state_lock = threading.RLock()
        self._shutdown_started = False

    @property
    def is_exiting(self) -> bool:
        with self._state_lock:
            return self.state in {
                DesktopState.EXITING,
                DesktopState.STOPPED,
                DesktopState.FAILED,
            }

    def start(self) -> int:
        with self._state_lock:
            if self.state is not DesktopState.CREATED:
                raise RuntimeError(f"Desktop controller cannot start from {self.state}")
            self.state = DesktopState.STARTING_BACKEND

        try:
            self.server.start()
            if not self.server.wait_ready(self.ready_timeout):
                detail = "Embedded backend did not become ready"
                server_error = self.server.error
                if server_error is not None:
                    raise DesktopStartupError(detail) from server_error
                raise DesktopStartupError(detail)

            with self._state_lock:
                self.state = DesktopState.BACKEND_READY

            self.window.bind(
                on_minimized=self.on_window_minimized,
                on_closing=self.on_window_closing,
            )
            self.window.create()
            tray_available = self.tray.start(
                on_show=self.restore_window,
                on_exit=self.shutdown,
            )

            with self._state_lock:
                self.tray_available = tray_available
                run_window = not self._shutdown_started
                if run_window:
                    self.state = DesktopState.WINDOW_VISIBLE
            if not run_window:
                self.shutdown_complete.wait()
                return 1 if self.state is DesktopState.FAILED else 0
            self.window.run()

            if not self.shutdown_complete.is_set():
                self.shutdown("window")
            return 1 if self.state is DesktopState.FAILED else 0
        except BaseException as exc:
            with self._state_lock:
                self.error = exc
                self.state = DesktopState.FAILED
            self._cleanup(preserve_failure=True)
            if isinstance(exc, DesktopStartupError):
                raise
            raise DesktopStartupError(f"Desktop application failed to start: {exc}") from exc

    def on_window_minimized(self, *_args: object) -> None:
        with self._state_lock:
            if not self._tray_is_healthy() or self.is_exiting:
                return
            self.state = DesktopState.WINDOW_HIDDEN
        self.window.hide()

    def on_window_closing(self, *_args: object) -> bool:
        with self._state_lock:
            if self.is_exiting or not self._tray_is_healthy():
                return True
            self.state = DesktopState.WINDOW_HIDDEN
        self.window.hide()
        return False

    def restore_window(self, *_args: object) -> None:
        with self._state_lock:
            if self.is_exiting:
                return
        self.window.show()
        self.window.restore()
        with self._state_lock:
            if not self.is_exiting:
                self.state = DesktopState.WINDOW_VISIBLE

    def shutdown(self, _reason: str = "unknown", *_args: object) -> None:
        self._cleanup(preserve_failure=False)

    def _tray_is_healthy(self) -> bool:
        live_available = bool(getattr(self.tray, "available", self.tray_available))
        if not live_available:
            self.tray_available = False
        return self.tray_available and live_available

    def _cleanup(self, *, preserve_failure: bool) -> None:
        with self._state_lock:
            if self._shutdown_started:
                return
            self._shutdown_started = True
            failed_before_cleanup = preserve_failure or self.state is DesktopState.FAILED
            if not failed_before_cleanup:
                self.state = DesktopState.EXITING

        cleanup_error: BaseException | None = None
        try:
            for cleanup in (
                self.server.stop,
                self.tray.stop,
                self.window.destroy,
                self.guard.release,
            ):
                try:
                    cleanup()
                except BaseException as exc:
                    if cleanup_error is None:
                        cleanup_error = exc
        finally:
            with self._state_lock:
                if cleanup_error is not None:
                    if self.error is None:
                        self.error = cleanup_error
                    self.state = DesktopState.FAILED
                elif failed_before_cleanup:
                    self.state = DesktopState.FAILED
                else:
                    self.state = DesktopState.STOPPED
                self.shutdown_complete.set()
