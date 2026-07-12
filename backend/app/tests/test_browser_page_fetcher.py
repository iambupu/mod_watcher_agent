# 中文注释：说明 backend/app/tests/test_browser_page_fetcher.py 的模块职责，便于后续维护定位。

import asyncio
import subprocess
from pathlib import Path

import pytest

from app import runtime_paths
from app.services.browser import page_fetcher
from app.services.browser.page_fetcher import (
    BrowserLaunchChoice,
    BrowserPageFetcher,
)


@pytest.fixture(autouse=True)
def reset_browser_lock(monkeypatch):
    monkeypatch.setattr(page_fetcher, "LOVERSLAB_BROWSER_LOCK", asyncio.Lock())


def test_profile_exists_accepts_browser_specific_profile_dirs(monkeypatch):
    monkeypatch.setattr(
        BrowserPageFetcher, "_profile_dir", staticmethod(lambda profile_name: Path("loverslab"))
    )
    monkeypatch.setattr(Path, "exists", lambda self: self.name == "loverslab-chrome")

    assert BrowserPageFetcher.profile_exists("loverslab") is True


def test_install_chromium_is_disabled_in_frozen_runtime(monkeypatch):
    monkeypatch.setattr(runtime_paths, "is_frozen", lambda: True)

    def fail_subprocess(*_args, **_kwargs):
        pytest.fail("frozen desktop must not launch the Playwright installer")

    monkeypatch.setattr(subprocess, "run", fail_subprocess)

    result = BrowserPageFetcher.install_chromium()

    assert result == {
        "success": False,
        "status": "unsupported_in_packaged_app",
        "message": "打包版不支持在线安装 Chromium，请使用系统 Edge 或 Chrome。",
        "stdout": "",
        "stderr": "",
    }


class _FakeAsyncPlaywrightFactory:
    def __init__(self, playwright):
        self._playwright = playwright

    async def start(self):
        return self._playwright


class _FailingChromium:
    executable_path = "missing-playwright-chromium"

    async def launch_persistent_context(self, **kwargs):
        raise RuntimeError("launch failed")


class _FakePlaywright:
    def __init__(self):
        self.chromium = _FailingChromium()
        self.stopped = False

    async def stop(self):
        self.stopped = True


@pytest.mark.asyncio
async def test_open_login_cleans_partial_playwright_on_launch_failure(monkeypatch):
    fake_playwright = _FakePlaywright()
    monkeypatch.setattr(
        BrowserPageFetcher, "_profile_dir", staticmethod(lambda profile_name: Path("profile"))
    )
    monkeypatch.setattr(Path, "mkdir", lambda self, **kwargs: None)
    monkeypatch.setattr(
        BrowserPageFetcher,
        "_load_playwright_api",
        staticmethod(
            lambda: {
                "async_playwright": lambda: _FakeAsyncPlaywrightFactory(fake_playwright),
                "timeout_error": TimeoutError,
            }
        ),
    )

    fetcher = BrowserPageFetcher()
    result = await fetcher.open_login(profile_name="loverslab")

    assert result.status == "unknown_error"
    assert "launch failed" in (result.error or "")
    assert fake_playwright.stopped is True
    assert fetcher._login_playwright is None
    assert fetcher._login_context is None
    assert fetcher._login_profile_name is None


class _SuccessfulPage:
    url = "https://www.loverslab.com/"

    async def goto(self, *args, **kwargs):
        return None

    async def title(self):
        return "LoversLab"

    async def content(self):
        return "<html>ok</html>"


class _SuccessfulContext:
    def __init__(self):
        self.closed = False

    async def new_page(self):
        return _SuccessfulPage()

    async def close(self):
        self.closed = True


class _FakeAsyncPlaywrightContextManager:
    def __init__(self, playwright):
        self._playwright = playwright

    async def __aenter__(self):
        return self._playwright

    async def __aexit__(self, exc_type, exc, traceback):
        return None


class _FailingNewPageContext:
    def __init__(self):
        self.closed = False

    async def new_page(self):
        raise RuntimeError("new page failed")

    async def close(self):
        self.closed = True


@pytest.mark.asyncio
async def test_fetch_html_closes_temporary_context_when_new_page_fails(monkeypatch):
    context = _FailingNewPageContext()
    fake_playwright = _FakePlaywright()

    async def fake_launch(self, playwright, *, profile_dir, headless):
        return context

    monkeypatch.setattr(
        BrowserPageFetcher, "_profile_dir", staticmethod(lambda profile_name: Path("profile"))
    )
    monkeypatch.setattr(BrowserPageFetcher, "_launch_persistent_context", fake_launch)
    monkeypatch.setattr(
        BrowserPageFetcher,
        "_load_playwright_api",
        staticmethod(
            lambda: {
                "async_playwright": lambda: _FakeAsyncPlaywrightContextManager(fake_playwright),
                "timeout_error": TimeoutError,
            }
        ),
    )

    result = await BrowserPageFetcher().fetch_html("https://example.com/")

    assert result.status == "unknown_error"
    assert result.error == "new page failed"
    assert context.closed is True


@pytest.mark.asyncio
async def test_open_login_waits_for_browser_lock(monkeypatch):
    fake_playwright = _FakePlaywright()
    launched = False

    async def fake_launch(self, playwright, *, profile_dir, headless):
        nonlocal launched
        launched = True
        return _SuccessfulContext()

    monkeypatch.setattr(
        BrowserPageFetcher, "_profile_dir", staticmethod(lambda profile_name: Path("profile"))
    )
    monkeypatch.setattr(BrowserPageFetcher, "_launch_persistent_context", fake_launch)
    monkeypatch.setattr(
        BrowserPageFetcher,
        "_load_playwright_api",
        staticmethod(
            lambda: {
                "async_playwright": lambda: _FakeAsyncPlaywrightFactory(fake_playwright),
                "timeout_error": TimeoutError,
            }
        ),
    )

    fetcher = BrowserPageFetcher()
    async with page_fetcher.LOVERSLAB_BROWSER_LOCK:
        task = asyncio.create_task(fetcher.open_login(profile_name="loverslab"))
        await asyncio.sleep(0)
        assert launched is False

    result = await task

    assert result.status == "ok"
    assert launched is True


@pytest.mark.asyncio
async def test_close_login_waits_for_browser_lock():
    context = _SuccessfulContext()
    fetcher = BrowserPageFetcher()
    fetcher._login_context = context
    fetcher._login_playwright = _FakePlaywright()
    fetcher._login_profile_name = "loverslab"

    async with page_fetcher.LOVERSLAB_BROWSER_LOCK:
        task = asyncio.create_task(fetcher.close_login())
        await asyncio.sleep(0)
        assert context.closed is False

    await task

    assert context.closed is True
    assert fetcher._login_context is None
    assert fetcher._login_playwright is None
    assert fetcher._login_profile_name is None


class _FailingCloseContext:
    def __init__(self, fetcher):
        self._fetcher = fetcher
        self.close_attempted = False
        self.observed_detached_state = False

    async def close(self):
        self.close_attempted = True
        self.observed_detached_state = (
            self._fetcher._login_context is None
            and self._fetcher._login_playwright is None
            and self._fetcher._login_profile_name is None
        )
        raise RuntimeError("context close failed")


class _FailingStopPlaywright(_FakePlaywright):
    def __init__(self):
        super().__init__()
        self.stop_attempted = False

    async def stop(self):
        self.stop_attempted = True
        raise RuntimeError("playwright stop failed")


class _CancelledCloseContext:
    async def close(self):
        raise asyncio.CancelledError


@pytest.mark.asyncio
async def test_close_login_detaches_state_and_stops_runtime_when_context_close_fails():
    fetcher = BrowserPageFetcher()
    context = _FailingCloseContext(fetcher)
    playwright = _FakePlaywright()
    fetcher._login_context = context
    fetcher._login_playwright = playwright
    fetcher._login_profile_name = "loverslab"

    with pytest.raises(RuntimeError, match="context close failed"):
        await fetcher.close_login()

    assert context.close_attempted is True
    assert context.observed_detached_state is True
    assert playwright.stopped is True
    assert fetcher._login_context is None
    assert fetcher._login_playwright is None
    assert fetcher._login_profile_name is None


@pytest.mark.asyncio
async def test_close_login_reports_both_context_and_runtime_cleanup_failures():
    fetcher = BrowserPageFetcher()
    context = _FailingCloseContext(fetcher)
    playwright = _FailingStopPlaywright()
    fetcher._login_context = context
    fetcher._login_playwright = playwright
    fetcher._login_profile_name = "loverslab"

    with pytest.raises(ExceptionGroup) as exc_info:
        await fetcher.close_login()

    assert [str(error) for error in exc_info.value.exceptions] == [
        "context close failed",
        "playwright stop failed",
    ]
    assert context.close_attempted is True
    assert playwright.stop_attempted is True
    assert fetcher._login_context is None
    assert fetcher._login_playwright is None
    assert fetcher._login_profile_name is None


@pytest.mark.asyncio
async def test_close_login_stops_runtime_before_propagating_context_cancellation():
    fetcher = BrowserPageFetcher()
    playwright = _FakePlaywright()
    fetcher._login_context = _CancelledCloseContext()
    fetcher._login_playwright = playwright
    fetcher._login_profile_name = "loverslab"

    with pytest.raises(asyncio.CancelledError):
        await fetcher.close_login()

    assert playwright.stopped is True
    assert fetcher._login_context is None
    assert fetcher._login_playwright is None
    assert fetcher._login_profile_name is None


class _RecordingChromium:
    executable_path = "missing-playwright-chromium"

    def __init__(self):
        self.kwargs = None

    async def launch_persistent_context(self, **kwargs):
        self.kwargs = kwargs
        return object()


class _RecordingPlaywright:
    def __init__(self):
        self.chromium = _RecordingChromium()


@pytest.mark.asyncio
async def test_launch_persistent_context_uses_system_browser_channel_when_playwright_chromium_missing(
    monkeypatch,
):
    monkeypatch.setattr(
        BrowserPageFetcher,
        "_system_browser_choices",
        classmethod(lambda cls: [BrowserLaunchChoice("Google Chrome", "chrome", "system")]),
    )
    monkeypatch.setattr(Path, "mkdir", lambda self, **kwargs: None)
    playwright = _RecordingPlaywright()

    context = await BrowserPageFetcher()._launch_persistent_context(
        playwright,
        profile_dir=Path("fake-profile"),
        headless=True,
    )

    assert context is not None
    assert playwright.chromium.kwargs["channel"] == "chrome"
    assert playwright.chromium.kwargs["user_data_dir"] == "fake-profile-chrome"
    assert playwright.chromium.kwargs["headless"] is True
