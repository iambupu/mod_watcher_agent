from __future__ import annotations

import sys
import types
from pathlib import Path

from app.services import windows_autostart_service

set_windows_auto_start = windows_autostart_service.set_windows_auto_start


class _WindowsPlatform:
    @staticmethod
    def system() -> str:
        return "Windows"


def _fake_winreg(calls: list[tuple[str, str]]) -> types.SimpleNamespace:
    return types.SimpleNamespace(
        HKEY_CURRENT_USER=object(),
        KEY_SET_VALUE=1,
        REG_SZ=1,
        OpenKey=lambda *args: "registry-key",
        SetValueEx=lambda key, name, reserved, reg_type, value: calls.append((name, value)),
        CloseKey=lambda key: None,
        DeleteValue=lambda key, name: None,
    )


def test_frozen_auto_start_registers_packaged_executable(
    monkeypatch,
    tmp_path: Path,
) -> None:
    calls: list[tuple[str, str]] = []
    executable = tmp_path / "安装 目录" / "ModWatcherAgent.exe"
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(executable))
    monkeypatch.setitem(sys.modules, "winreg", _fake_winreg(calls))

    result = set_windows_auto_start(True, platform_module=_WindowsPlatform)

    assert result == {"success": True, "enabled": True}
    assert calls == [("ModWatcherAgent", f'"{executable.resolve()}"')]


def test_source_auto_start_keeps_powershell_launcher(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.setitem(sys.modules, "winreg", _fake_winreg(calls))

    result = set_windows_auto_start(True, platform_module=_WindowsPlatform)

    assert result == {"success": True, "enabled": True}
    launcher = Path(windows_autostart_service.__file__).resolve().parents[3] / "start.ps1"
    assert launcher.is_absolute()
    assert calls == [
        (
            "ModWatcherAgent",
            f'powershell.exe -WindowStyle Hidden -File "{launcher}" -Tray',
        )
    ]
