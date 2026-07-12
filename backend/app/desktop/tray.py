from __future__ import annotations

import importlib
import threading
from collections.abc import Callable
from typing import Any
from urllib.parse import urlparse

import httpx

_API_TIMEOUT_SECONDS = 5.0
_LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}


class TrayController:
    """Run the pystray icon on its own thread and expose local API actions."""

    def __init__(
        self,
        paths: object,
        base_url: str,
        *,
        pystray_module: Any | None = None,
        image_module: Any | None = None,
        image_draw_module: Any | None = None,
        dependency_loader: Callable[[], tuple[Any, Any, Any]] | None = None,
        client_factory: Callable[..., Any] = httpx.Client,
        startup_timeout: float = 5.0,
        join_timeout: float = 5.0,
    ) -> None:
        parsed_url = urlparse(base_url)
        if parsed_url.scheme != "http" or parsed_url.hostname not in _LOOPBACK_HOSTS:
            raise ValueError("Tray API base URL must use an HTTP loopback host")

        self.paths = paths
        self.base_url = base_url.rstrip("/")
        self._pystray = pystray_module
        self._image = image_module
        self._image_draw = image_draw_module
        self._dependency_loader = dependency_loader
        self._client_factory = client_factory
        self.startup_timeout = startup_timeout
        self.join_timeout = join_timeout

        self.available = False
        self.startup_error: BaseException | None = None
        self.last_action_error: BaseException | None = None
        self._startup_succeeded = False
        self._startup_complete = threading.Event()
        self._state_lock = threading.RLock()
        self._thread: threading.Thread | None = None
        self._icon: Any | None = None
        self._stop_started = False
        self._exit_started = False
        self._on_show: Callable[..., object] | None = None
        self._on_exit: Callable[..., object] | None = None
        self._on_unavailable: Callable[..., object] | None = None

    @property
    def thread(self) -> threading.Thread:
        thread = self._thread
        if thread is None:
            raise RuntimeError("Tray has not been started")
        return thread

    def start(
        self,
        *,
        on_show: Callable[..., object],
        on_exit: Callable[..., object],
        on_unavailable: Callable[..., object] | None = None,
    ) -> bool:
        with self._state_lock:
            if self._thread is not None:
                return self._startup_succeeded
            self._on_show = on_show
            self._on_exit = on_exit
            self._on_unavailable = on_unavailable
            thread = threading.Thread(
                target=self._run,
                name="mod-watcher-tray",
                daemon=True,
            )
            self._thread = thread
            try:
                thread.start()
            except BaseException as exc:
                self.startup_error = exc
                self.available = False
                self._startup_complete.set()
                return False

        if not self._startup_complete.wait(max(self.startup_timeout, 0)):
            self.startup_error = TimeoutError("System tray did not initialize in time")
            self.available = False
            self.stop()
            return False
        with self._state_lock:
            startup_succeeded = self._startup_succeeded
        if (
            not startup_succeeded
            and thread is not threading.current_thread()
            and thread.ident is not None
        ):
            thread.join(max(self.join_timeout, 0))
        return startup_succeeded

    def stop(self) -> None:
        with self._state_lock:
            if self._stop_started:
                return
            self._stop_started = True
            icon = self._icon
            thread = self._thread
            self.available = False

        try:
            if icon is not None:
                icon.stop()
        finally:
            if (
                thread is not None
                and thread is not threading.current_thread()
                and thread.ident is not None
            ):
                thread.join(max(self.join_timeout, 0))

    def check_now(self) -> bool:
        return self._post("/api/jobs/discover-all")

    def check_favorites(self) -> bool:
        return self._post("/api/jobs/check-favorites")

    def toggle_scheduler(self) -> bool:
        try:
            with self._new_client() as client:
                response = client.get("/api/jobs/status")
                response.raise_for_status()
                endpoint = (
                    "/api/jobs/pause"
                    if bool(response.json().get("running"))
                    else "/api/jobs/resume"
                )
                toggled = client.post(endpoint)
                toggled.raise_for_status()
            self.last_action_error = None
            return True
        except Exception as exc:
            self.last_action_error = exc
            return False

    def open_logs(self) -> bool:
        return self._post("/api/logs/open-dir")

    def _run(self) -> None:
        runtime_error: BaseException | None = None
        try:
            pystray, image_module, image_draw_module = self._load_dependencies()
            image = self._create_icon_image(image_module, image_draw_module)
            menu = pystray.Menu(
                pystray.MenuItem("打开主界面", self._show_window, default=True),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("立即检查新 Mod", self._check_now),
                pystray.MenuItem("检查收藏更新", self._check_favorites),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("暂停/恢复定时任务", self._toggle_scheduler),
                pystray.MenuItem("打开日志目录", self._open_logs),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("退出", self._exit),
            )
            icon = pystray.Icon("mod-watcher-agent", image, "Mod Watcher Agent", menu)
            with self._state_lock:
                self._icon = icon
                stop_requested = self._stop_started
            if stop_requested:
                return
            icon.run(setup=self._mark_ready)
        except BaseException as exc:
            runtime_error = exc
            with self._state_lock:
                if not self._startup_succeeded:
                    self.startup_error = exc
                    self._startup_complete.set()
        finally:
            with self._state_lock:
                notify_unavailable = self._startup_succeeded and not self._stop_started
                callback = self._on_unavailable if notify_unavailable else None
                self.available = False
            if callback is not None:
                callback(runtime_error)

    def _mark_ready(self, icon: Any) -> None:
        with self._state_lock:
            if self._stop_started:
                self.available = False
                self._startup_complete.set()
                return
        try:
            icon.visible = True
        except BaseException as exc:
            with self._state_lock:
                self.startup_error = exc
                self.available = False
                self._startup_complete.set()
            self.stop()
            return
        with self._state_lock:
            if self._stop_started:
                self.available = False
            else:
                self.available = True
                self._startup_succeeded = True
        self._startup_complete.set()

    def _load_dependencies(self) -> tuple[Any, Any, Any]:
        if self._dependency_loader is not None:
            return self._dependency_loader()
        pystray = self._pystray or importlib.import_module("pystray")
        image_module = self._image or importlib.import_module("PIL.Image")
        image_draw_module = self._image_draw or importlib.import_module("PIL.ImageDraw")
        return pystray, image_module, image_draw_module

    @staticmethod
    def _create_icon_image(image_module: Any, image_draw_module: Any) -> Any:
        image = image_module.new("RGBA", (64, 64), "#f8fafc")
        draw = image_draw_module.Draw(image)
        draw.rounded_rectangle((8, 8, 56, 56), radius=12, fill="#0ea5e9")
        draw.ellipse((22, 22, 42, 42), fill="#ffffff")
        return image

    def _new_client(self) -> Any:
        return self._client_factory(
            base_url=self.base_url,
            timeout=_API_TIMEOUT_SECONDS,
            trust_env=False,
        )

    def _post(self, path: str) -> bool:
        try:
            with self._new_client() as client:
                response = client.post(path)
                response.raise_for_status()
            self.last_action_error = None
            return True
        except Exception as exc:
            self.last_action_error = exc
            return False

    def _show_window(self, *_args: object) -> None:
        callback = self._on_show
        if callback is not None:
            callback()

    def _check_now(self, *_args: object) -> None:
        self.check_now()

    def _check_favorites(self, *_args: object) -> None:
        self.check_favorites()

    def _toggle_scheduler(self, *_args: object) -> None:
        self.toggle_scheduler()

    def _open_logs(self, *_args: object) -> None:
        self.open_logs()

    def _exit(self, *_args: object) -> None:
        with self._state_lock:
            if self._exit_started:
                return
            self._exit_started = True
            callback = self._on_exit

        self.stop()
        if callback is None:
            return
        shutdown_worker = threading.Thread(
            target=callback,
            args=("tray",),
            name="mod-watcher-shutdown",
            daemon=False,
        )
        try:
            shutdown_worker.start()
        except BaseException as exc:
            self.last_action_error = exc
            callback("tray")
