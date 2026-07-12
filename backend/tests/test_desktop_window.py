from __future__ import annotations

import importlib
import threading
from collections.abc import Callable
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest


def _desktop_window_module() -> ModuleType:
    try:
        return importlib.import_module("app.desktop.window")
    except ModuleNotFoundError:
        pytest.fail("app.desktop.window is not implemented", pytrace=False)


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
