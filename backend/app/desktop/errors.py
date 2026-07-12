from __future__ import annotations

import sys
from collections.abc import Callable

_MB_OK = 0x00000000
_MB_ICONERROR = 0x00000010
_MB_SETFOREGROUND = 0x00010000
WEBVIEW2_RUNTIME_DOWNLOAD_URL = "https://developer.microsoft.com/microsoft-edge/webview2/"
_WEBVIEW2_ERROR_MARKERS = (
    "webview2",
    "edgechromium",
    "edge chromium",
)


def format_desktop_startup_error(error: BaseException | str) -> str:
    """Format startup failures without importing any desktop GUI dependency."""

    detail = str(error).strip() or type(error).__name__
    message = f"桌面客户端启动失败：{detail}"
    if any(marker in detail.casefold() for marker in _WEBVIEW2_ERROR_MARKERS):
        message += (
            "\n\n未检测到可用的 Microsoft Edge WebView2 Runtime。"
            "请从 Microsoft 官方页面安装后重新启动应用：\n"
            f"{WEBVIEW2_RUNTIME_DOWNLOAD_URL}"
        )
    return message


def show_native_error(
    title: str,
    message: str,
    *,
    platform_name: str | None = None,
    message_box: Callable[[str, str, int], object] | None = None,
) -> None:
    """Show an error without importing the desktop GUI toolkits."""

    current_platform = platform_name or sys.platform
    flags = _MB_OK | _MB_ICONERROR | _MB_SETFOREGROUND
    if message_box is not None:
        message_box(title, message, flags)
        return

    if current_platform == "win32":
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, message, title, flags)
        return

    print(f"{title}: {message}", file=sys.stderr)
