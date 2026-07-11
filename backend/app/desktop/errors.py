from __future__ import annotations

import sys
from collections.abc import Callable

_MB_OK = 0x00000000
_MB_ICONERROR = 0x00000010
_MB_SETFOREGROUND = 0x00010000


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
