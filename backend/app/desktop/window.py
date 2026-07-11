from __future__ import annotations

import importlib
import threading
from collections.abc import Callable
from typing import Any


class PyWebViewWindow:
    """Lazy pywebview adapter kept on the process main thread."""

    def __init__(
        self,
        paths: object,
        url: str,
        *,
        webview_module: Any | None = None,
        title: str = "Mod Watcher Agent",
    ) -> None:
        self.paths = paths
        self.url = url
        self.title = title
        self._webview = webview_module
        self._window: Any | None = None
        self._on_minimized: Callable[..., object] | None = None
        self._on_closing: Callable[..., object] | None = None
        self._events_bound = False
        self._destroy_lock = threading.Lock()
        self._destroyed = False

    def bind(
        self,
        *,
        on_minimized: Callable[..., object],
        on_closing: Callable[..., object],
    ) -> None:
        self._on_minimized = on_minimized
        self._on_closing = on_closing
        self._bind_events()

    def create(self) -> None:
        with self._destroy_lock:
            if self._window is not None or self._destroyed:
                return
        webview = self._load_webview()
        webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = True
        native_window = webview.create_window(
            title=self.title,
            url=self.url,
            width=1440,
            height=900,
            min_size=(1024, 700),
            resizable=True,
            frameless=False,
            confirm_close=False,
            background_color="#f8fafc",
        )
        with self._destroy_lock:
            if self._destroyed:
                native_window.destroy()
                return
            self._window = native_window
            self._events_bound = False
        self._bind_events()

    def run(self) -> None:
        if threading.current_thread() is not threading.main_thread():
            raise RuntimeError("pywebview must run on the main thread")
        self.create()
        with self._destroy_lock:
            if self._window is None or self._destroyed:
                return
        webview = self._load_webview()
        webview.start(
            gui="edgechromium",
            private_mode=False,
            storage_path=str(self.paths.webview_dir),
        )

    def hide(self) -> None:
        window = self._window
        if window is not None:
            window.hide()

    def show(self) -> None:
        window = self._window
        if window is not None:
            window.show()

    def restore(self) -> None:
        window = self._window
        if window is not None:
            window.restore()

    def destroy(self) -> None:
        with self._destroy_lock:
            window = self._window
            if window is None:
                return
            self._window = None
            self._events_bound = False
            self._destroyed = True
        window.destroy()

    def _load_webview(self) -> Any:
        if self._webview is None:
            self._webview = importlib.import_module("webview")
        return self._webview

    def _bind_events(self) -> None:
        window = self._window
        if window is None or self._events_bound:
            return
        if self._on_minimized is not None:
            window.events.minimized += self._on_minimized
        if self._on_closing is not None:
            window.events.closing += self._on_closing
        self._events_bound = True
