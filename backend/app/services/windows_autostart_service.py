import platform
import sys
from pathlib import Path


class AutoStartUnsupportedError(Exception):
    status_code = 501
    detail = "/api/settings/auto-start is only supported on Windows"


def _auto_start_command() -> str:
    if bool(getattr(sys, "frozen", False)):
        executable = Path(sys.executable).resolve()
        return f'"{executable}"'

    root = Path(__file__).resolve().parent.parent.parent.parent
    launcher = root / "start.ps1"
    return f'powershell.exe -WindowStyle Hidden -File "{launcher}" -Tray'


def set_windows_auto_start(enabled: bool, *, platform_module=platform) -> dict:
    """写入或删除 HKCU Run 启动项，只在 Windows 可用。"""
    if platform_module.system().lower() != "windows":
        raise AutoStartUnsupportedError()

    import winreg

    key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"

    try:
        if enabled:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE)
            winreg.SetValueEx(
                key,
                "ModWatcherAgent",
                0,
                winreg.REG_SZ,
                _auto_start_command(),
            )
            winreg.CloseKey(key)
        else:
            try:
                key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE)
                winreg.DeleteValue(key, "ModWatcherAgent")
                winreg.CloseKey(key)
            except FileNotFoundError:
                pass
        return {"success": True, "enabled": enabled}
    except Exception as exc:
        return {"success": False, "error": str(exc)}
