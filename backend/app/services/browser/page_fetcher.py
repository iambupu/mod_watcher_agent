import asyncio
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

BrowserFetchStatus = Literal[
    "ok",
    "login_required",
    "cloudflare_challenge",
    "forbidden",
    "timeout",
    "playwright_not_installed",
    "browser_not_installed",
    "structure_changed",
    "unknown_error",
]


@dataclass
class BrowserFetchResult:
    url: str
    final_url: str
    title: str
    html: str
    status: BrowserFetchStatus
    error: str | None = None


@dataclass(frozen=True)
class BrowserLaunchChoice:
    name: str
    channel: str | None
    source: Literal["playwright", "system"]


LOVERSLAB_BROWSER_LOCK = asyncio.Lock()
PROFILE_ROOT = Path("data") / "browser_profiles"


class BrowserPageFetcher:
    """Fetch pages through a persistent browser profile managed by Playwright."""

    def __init__(self) -> None:
        """初始化实例并保存运行所需的依赖。"""
        self._login_playwright = None
        self._login_context = None
        self._login_profile_name: str | None = None

    async def fetch_html(
        self,
        url: str,
        *,
        profile_name: str = "loverslab",
        wait_until: str = "networkidle",
        timeout_ms: int = 60000,
        headless: bool = False,
    ) -> BrowserFetchResult:
        """请求外部数据并返回标准化结果。"""
        async with LOVERSLAB_BROWSER_LOCK:
            try:
                playwright_api = self._load_playwright_api()
            except RuntimeError as exc:
                return BrowserFetchResult(url, url, "", "", "playwright_not_installed", str(exc))

            profile_dir = self._profile_dir(profile_name)
            try:
                if self._login_context is not None and self._login_profile_name == profile_name:
                    context = self._login_context
                    page = await context.new_page()
                    try:
                        await page.goto(url, wait_until=wait_until, timeout=timeout_ms)
                        html = await page.content()
                        title = await page.title()
                        final_url = page.url
                    finally:
                        await page.close()
                else:
                    async with playwright_api["async_playwright"]() as playwright:
                        context = await self._launch_persistent_context(
                            playwright,
                            profile_dir=profile_dir,
                            headless=headless,
                        )
                        page = await context.new_page()
                        try:
                            await page.goto(url, wait_until=wait_until, timeout=timeout_ms)
                            html = await page.content()
                            title = await page.title()
                            final_url = page.url
                        finally:
                            await context.close()
            except playwright_api["timeout_error"] as exc:
                return BrowserFetchResult(url, url, "", "", "timeout", str(exc))
            except Exception as exc:
                message = str(exc)
                status: BrowserFetchStatus = (
                    "browser_not_installed"
                    if "Executable doesn't exist" in message or "playwright install" in message
                    else "unknown_error"
                )
                return BrowserFetchResult(url, url, "", "", status, message)

            status = self.detect_status(html)
            return BrowserFetchResult(
                url=url,
                final_url=final_url,
                title=title,
                html=html,
                status=status,
            )

    async def open_login(
        self,
        *,
        profile_name: str = "loverslab",
        url: str = "https://www.loverslab.com/",
    ) -> BrowserFetchResult:
        """处理当前模块的业务逻辑并返回结果。"""
        async with LOVERSLAB_BROWSER_LOCK:
            return await self._open_login_unlocked(profile_name=profile_name, url=url)

    async def _open_login_unlocked(self, *, profile_name: str, url: str) -> BrowserFetchResult:
        """内部辅助函数，用于拆分上层流程中的局部规则。"""
        try:
            playwright_api = self._load_playwright_api()
        except RuntimeError as exc:
            return BrowserFetchResult(url, url, "", "", "playwright_not_installed", str(exc))
        profile_dir = self._profile_dir(profile_name)
        try:
            await self._close_login_unlocked()
            self._login_playwright = await playwright_api["async_playwright"]().start()
            self._login_context = await self._launch_persistent_context(
                self._login_playwright,
                profile_dir=profile_dir,
                headless=False,
            )
            self._login_profile_name = profile_name
            page = await self._login_context.new_page()
            await page.goto(url, wait_until="domcontentloaded", timeout=60000)
            title = await page.title()
            final_url = page.url
            html = await page.content()
        except Exception as exc:
            message = str(exc)
            try:
                await self._close_login_unlocked()
            except Exception as cleanup_exc:
                message = f"{message}; cleanup failed: {cleanup_exc}"
            status: BrowserFetchStatus = (
                "browser_not_installed"
                if "Executable doesn't exist" in message or "playwright install" in message
                else "unknown_error"
            )
            return BrowserFetchResult(url, url, "", "", status, message)
        return BrowserFetchResult(url, final_url, title, html, self.detect_status(html))

    async def close_login(self) -> None:
        """处理当前模块的业务逻辑并返回结果。"""
        async with LOVERSLAB_BROWSER_LOCK:
            await self._close_login_unlocked()

    async def _close_login_unlocked(self) -> None:
        """内部辅助函数，用于拆分上层流程中的局部规则。"""
        if self._login_context is not None:
            await self._login_context.close()
            self._login_context = None
        if self._login_playwright is not None:
            await self._login_playwright.stop()
            self._login_playwright = None
        self._login_profile_name = None

    @classmethod
    def detect_status(cls, html: str) -> BrowserFetchStatus:
        """处理当前模块的业务逻辑并返回结果。"""
        lowered = (html or "").lower()
        if not lowered:
            return "unknown_error"
        if "just a moment" in lowered and "cloudflare" in lowered:
            return "cloudflare_challenge"
        if "__cf_chl_" in lowered or "cf-chl" in lowered:
            return "cloudflare_challenge"
        if "ips4_login" in lowered or "sign in" in lowered and "forgot your password" in lowered:
            return "login_required"
        if "403 forbidden" in lowered or "access denied" in lowered:
            return "forbidden"
        return "ok"

    @classmethod
    def profile_exists(cls, profile_name: str = "loverslab") -> bool:
        """处理当前模块的业务逻辑并返回结果。"""
        profile_dir = cls._profile_dir(profile_name)
        return profile_dir.exists() or any(
            profile_dir.with_name(f"{profile_dir.name}-{channel}").exists()
            for channel in ("msedge", "chrome", "chromium")
        )

    @classmethod
    def status_payload(cls, profile_name: str = "loverslab") -> dict:
        """处理当前模块的业务逻辑并返回结果。"""
        playwright_installed = True
        browser_installed = False
        browser_name = ""
        browser_source = ""
        browser_channel = ""
        error = ""
        try:
            from playwright.sync_api import sync_playwright

            with sync_playwright() as playwright:
                choice = cls._browser_launch_choice(playwright)
                browser_installed = choice is not None
                if choice is not None:
                    browser_name = choice.name
                    browser_source = choice.source
                    browser_channel = choice.channel or "chromium"
        except Exception as exc:
            playwright_installed = "No module named" not in str(exc)
            error = str(exc)

        return {
            "profileExists": cls.profile_exists(profile_name),
            "playwrightInstalled": playwright_installed,
            "browserInstalled": browser_installed,
            "browserName": browser_name,
            "browserSource": browser_source,
            "browserChannel": browser_channel,
            "lastCheckStatus": None,
            "lastCheckAt": None,
            "error": error,
        }

    @classmethod
    def install_chromium(cls, timeout_seconds: int = 600) -> dict:
        """处理当前模块的业务逻辑并返回结果。"""
        try:
            completed = subprocess.run(
                [sys.executable, "-m", "playwright", "install", "chromium"],
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            return {
                "success": False,
                "status": "timeout",
                "message": str(exc),
                "stdout": exc.stdout or "",
                "stderr": exc.stderr or "",
            }
        except Exception as exc:
            return {
                "success": False,
                "status": "unknown_error",
                "message": str(exc),
                "stdout": "",
                "stderr": "",
            }

        success = completed.returncode == 0
        return {
            "success": success,
            "status": "ok" if success else "browser_not_installed",
            "message": "Chromium installed" if success else "Chromium install failed",
            "stdout": completed.stdout[-4000:],
            "stderr": completed.stderr[-4000:],
        }

    @staticmethod
    def now_iso() -> str:
        """处理当前模块的业务逻辑并返回结果。"""
        return datetime.now(UTC).isoformat()

    @staticmethod
    def _load_playwright_api():
        """加载内部流程需要的配置或数据。"""
        try:
            from playwright.async_api import TimeoutError as PlaywrightTimeoutError
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise RuntimeError(
                "Playwright is not installed. Install backend dependencies and run "
                "`python -m playwright install chromium`."
            ) from exc
        return {
            "async_playwright": async_playwright,
            "timeout_error": PlaywrightTimeoutError,
        }

    async def _launch_persistent_context(self, playwright, *, profile_dir: Path, headless: bool):
        """内部辅助函数，用于拆分上层流程中的局部规则。"""
        errors: list[str] = []
        for choice in self._browser_launch_choices(playwright):
            candidate_profile_dir = self._profile_dir_for_choice(profile_dir, choice)
            candidate_profile_dir.mkdir(parents=True, exist_ok=True)
            kwargs = {
                "user_data_dir": str(candidate_profile_dir),
                "headless": headless,
            }
            if choice.channel is not None:
                kwargs["channel"] = choice.channel
            try:
                return await playwright.chromium.launch_persistent_context(**kwargs)
            except Exception as exc:
                message = str(exc)
                errors.append(f"{choice.name}: {message}")
                continue
        detail = "; ".join(errors[-3:]) if errors else "No browser candidates found"
        if errors and all(self._is_missing_browser_error(error) for error in errors):
            raise RuntimeError(
                "Executable doesn't exist. Tried system Microsoft Edge, system Google Chrome, "
                f"and Playwright Chromium. {detail}"
            )
        raise RuntimeError(f"Browser launch failed. Tried system Edge/Chrome before Chromium. {detail}")

    @classmethod
    def _browser_launch_choice(cls, playwright) -> BrowserLaunchChoice | None:
        """内部辅助函数，用于拆分上层流程中的局部规则。"""
        choices = cls._browser_launch_choices(playwright)
        return choices[0] if choices else None

    @classmethod
    def _browser_launch_choices(cls, playwright) -> list[BrowserLaunchChoice]:
        """内部辅助函数，用于拆分上层流程中的局部规则。"""
        choices: list[BrowserLaunchChoice] = []
        system_choices = cls._system_browser_choices()
        choices.extend(system_choices)
        known_channels = {choice.channel for choice in choices}
        for choice in (
            BrowserLaunchChoice("Microsoft Edge", "msedge", "system"),
            BrowserLaunchChoice("Google Chrome", "chrome", "system"),
        ):
            if choice.channel not in known_channels:
                choices.append(choice)
                known_channels.add(choice.channel)
        executable = Path(playwright.chromium.executable_path)
        if executable.exists():
            choices.append(BrowserLaunchChoice("Playwright Chromium", None, "playwright"))
        return choices

    @staticmethod
    def _is_missing_browser_error(message: str) -> bool:
        """判断内部条件是否成立。"""
        lowered = message.lower()
        return (
            "executable doesn't exist" in lowered
            or "playwright install" in lowered
            or "browser is not installed" in lowered
            or "not found" in lowered
            or "cannot find" in lowered
        )

    @classmethod
    def _system_browser_choices(cls) -> list[BrowserLaunchChoice]:
        """内部辅助函数，用于拆分上层流程中的局部规则。"""
        choices: list[BrowserLaunchChoice] = []
        edge_paths = cls._candidate_paths(
            [
                ("PROGRAMFILES", "Microsoft/Edge/Application/msedge.exe"),
                ("PROGRAMFILES(X86)", "Microsoft/Edge/Application/msedge.exe"),
                ("LOCALAPPDATA", "Microsoft/Edge/Application/msedge.exe"),
            ]
        )
        if any(path.exists() for path in edge_paths):
            choices.append(BrowserLaunchChoice("Microsoft Edge", "msedge", "system"))

        chrome_paths = cls._candidate_paths(
            [
                ("PROGRAMFILES", "Google/Chrome/Application/chrome.exe"),
                ("PROGRAMFILES(X86)", "Google/Chrome/Application/chrome.exe"),
                ("LOCALAPPDATA", "Google/Chrome/Application/chrome.exe"),
            ]
        )
        if any(path.exists() for path in chrome_paths):
            choices.append(BrowserLaunchChoice("Google Chrome", "chrome", "system"))

        unix_paths = [
            (Path("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"), "Microsoft Edge", "msedge"),
            (Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"), "Google Chrome", "chrome"),
            (Path("/usr/bin/microsoft-edge"), "Microsoft Edge", "msedge"),
            (Path("/usr/bin/microsoft-edge-stable"), "Microsoft Edge", "msedge"),
            (Path("/usr/bin/google-chrome"), "Google Chrome", "chrome"),
        ]
        seen_channels = {choice.channel for choice in choices}
        for path, name, channel in unix_paths:
            if path.exists() and channel not in seen_channels:
                choices.append(BrowserLaunchChoice(name, channel, "system"))
                seen_channels.add(channel)
        return choices

    @staticmethod
    def _candidate_paths(entries: list[tuple[str, str]]) -> list[Path]:
        """内部辅助函数，用于拆分上层流程中的局部规则。"""
        paths = []
        for env_name, suffix in entries:
            root = os.environ.get(env_name)
            if root:
                paths.append(Path(root) / Path(suffix))
        return paths

    @staticmethod
    def _profile_dir(profile_name: str) -> Path:
        """内部辅助函数，用于拆分上层流程中的局部规则。"""
        safe_name = "".join(ch for ch in profile_name if ch.isalnum() or ch in {"-", "_"})
        return PROFILE_ROOT / (safe_name or "default")

    @staticmethod
    def _profile_dir_for_choice(profile_dir: Path, choice: BrowserLaunchChoice) -> Path:
        """内部辅助函数，用于拆分上层流程中的局部规则。"""
        if choice.source == "system" and choice.channel:
            return profile_dir.with_name(f"{profile_dir.name}-{choice.channel}")
        if choice.source == "playwright":
            return profile_dir.with_name(f"{profile_dir.name}-chromium")
        return profile_dir
