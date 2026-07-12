import asyncio
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from app import runtime_paths
from app.runtime_paths import build_runtime_paths

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


def browser_profile_root() -> Path:
    """Return the current browser profile root without caching environment overrides."""
    return build_runtime_paths().browser_profile_dir


class BrowserPageFetcher:
    """Fetch pages through a persistent browser profile managed by Playwright."""

    def __init__(self) -> None:
        """保存可复用的登录浏览器上下文，供手动登录和后续抓取共享 profile。"""
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
        """用持久化浏览器 profile 获取页面 HTML，并把失败原因规范化为状态码。"""
        async with LOVERSLAB_BROWSER_LOCK:
            try:
                playwright_api = self._load_playwright_api()
            except RuntimeError as exc:
                return BrowserFetchResult(url, url, "", "", "playwright_not_installed", str(exc))

            profile_dir = self._profile_dir(profile_name)
            try:
                if self._login_context is not None and self._login_profile_name == profile_name:
                    # 用户手动登录窗口还开着时复用同一个 context，避免登录态尚未落盘就丢失。
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
                        # 无手动登录窗口时短暂启动持久化 context，抓完立即关闭释放浏览器进程。
                        context = await self._launch_persistent_context(
                            playwright,
                            profile_dir=profile_dir,
                            headless=headless,
                        )
                        try:
                            page = await context.new_page()
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
        """打开可见浏览器让用户完成登录，并保留 context 供后续请求复用。"""
        async with LOVERSLAB_BROWSER_LOCK:
            return await self._open_login_unlocked(profile_name=profile_name, url=url)

    async def _open_login_unlocked(self, *, profile_name: str, url: str) -> BrowserFetchResult:
        """在已持有锁的前提下启动登录窗口，避免多个登录 profile 并发写入。"""
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
        """关闭当前保留的登录窗口和 Playwright 运行时。"""
        async with LOVERSLAB_BROWSER_LOCK:
            await self._close_login_unlocked()

    async def _close_login_unlocked(self) -> None:
        """在已持有锁的前提下清理登录 context，调用方负责串行化。"""
        context = self._login_context
        playwright = self._login_playwright

        self._login_context = None
        self._login_playwright = None
        self._login_profile_name = None

        cleanup_errors: list[BaseException] = []
        if context is not None:
            try:
                await context.close()
            except BaseException as exc:
                cleanup_errors.append(exc)
        if playwright is not None:
            try:
                await playwright.stop()
            except BaseException as exc:
                cleanup_errors.append(exc)

        if len(cleanup_errors) == 1:
            raise cleanup_errors[0]
        if cleanup_errors:
            raise BaseExceptionGroup("browser login cleanup failed", cleanup_errors)

    @classmethod
    def detect_status(cls, html: str) -> BrowserFetchStatus:
        """根据页面内容识别登录、Cloudflare、403 等可恢复/不可恢复状态。"""
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
        """检查默认 profile 以及按浏览器 channel 分裂出的 profile 是否存在。"""
        profile_dir = cls._profile_dir(profile_name)
        return profile_dir.exists() or any(
            profile_dir.with_name(f"{profile_dir.name}-{channel}").exists()
            for channel in ("msedge", "chrome", "chromium")
        )

    @classmethod
    def status_payload(cls, profile_name: str = "loverslab") -> dict:
        """返回前端设置页展示浏览器能力所需的安装/profile 状态。"""
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
        """通过 Playwright CLI 安装 Chromium，并裁剪过长输出给 API 返回。"""
        if runtime_paths.is_frozen():
            return {
                "success": False,
                "status": "unsupported_in_packaged_app",
                "message": "打包版不支持在线安装 Chromium，请使用系统 Edge 或 Chrome。",
                "stdout": "",
                "stderr": "",
            }
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
        """返回 UTC ISO 时间，供浏览器状态检查落库/回显使用。"""
        return datetime.now(UTC).isoformat()

    @staticmethod
    def _load_playwright_api():
        """延迟导入 Playwright，使未安装依赖时能返回明确的能力状态。"""
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
        """按系统浏览器优先、Playwright Chromium 兜底的顺序启动持久化 context。"""
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
        raise RuntimeError(
            f"Browser launch failed. Tried system Edge/Chrome before Chromium. {detail}"
        )

    @classmethod
    def _browser_launch_choice(cls, playwright) -> BrowserLaunchChoice | None:
        """返回当前机器优先使用的浏览器候选。"""
        choices = cls._browser_launch_choices(playwright)
        return choices[0] if choices else None

    @classmethod
    def _browser_launch_choices(cls, playwright) -> list[BrowserLaunchChoice]:
        """枚举可用浏览器：优先系统 Edge/Chrome，最后才使用 Playwright Chromium。"""
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
        """识别“浏览器缺失”错误，和普通启动失败分开展示。"""
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
        """按常见 Windows/macOS/Linux 安装路径探测系统 Edge/Chrome。"""
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
            (
                Path("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"),
                "Microsoft Edge",
                "msedge",
            ),
            (
                Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
                "Google Chrome",
                "chrome",
            ),
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
        """根据环境变量根目录拼出系统浏览器候选路径。"""
        paths = []
        for env_name, suffix in entries:
            root = os.environ.get(env_name)
            if root:
                paths.append(Path(root) / Path(suffix))
        return paths

    @staticmethod
    def _profile_dir(profile_name: str) -> Path:
        """清理 profile 名称，防止用户输入逃逸到 profile 根目录外。"""
        safe_name = "".join(ch for ch in profile_name if ch.isalnum() or ch in {"-", "_"})
        return browser_profile_root() / (safe_name or "default")

    @staticmethod
    def _profile_dir_for_choice(profile_dir: Path, choice: BrowserLaunchChoice) -> Path:
        """不同浏览器使用独立 profile，避免同一用户数据目录被多个 channel 锁住。"""
        if choice.source == "system" and choice.channel:
            return profile_dir.with_name(f"{profile_dir.name}-{choice.channel}")
        if choice.source == "playwright":
            return profile_dir.with_name(f"{profile_dir.name}-chromium")
        return profile_dir
