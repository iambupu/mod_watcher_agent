import base64
import os
import subprocess


def _run_powershell_script(script: str, env: dict[str, str], *, sta: bool = False, timeout: int = 8) -> bool:
    encoded_script = base64.b64encode(script.encode("utf-16le")).decode("ascii")
    args = ["powershell", "-NoProfile", "-NonInteractive"]
    if sta:
        args.append("-STA")
    args.extend(["-EncodedCommand", encoded_script])
    try:
        completed = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
    except Exception:
        return False
    return completed.returncode == 0


def _send_tray_balloon(env: dict[str, str]) -> bool:
    script = "\n".join(
        [
            "$ErrorActionPreference='Stop'",
            "Add-Type -AssemblyName System.Windows.Forms",
            "Add-Type -AssemblyName System.Drawing",
            "$title = [Environment]::GetEnvironmentVariable('MW_TOAST_TITLE','Process')",
            "$msg = [Environment]::GetEnvironmentVariable('MW_TOAST_MESSAGE','Process')",
            "$notify = New-Object System.Windows.Forms.NotifyIcon",
            "$notify.Icon = [System.Drawing.SystemIcons]::Information",
            "$notify.Visible = $true",
            "$notify.BalloonTipTitle = $title",
            "$notify.BalloonTipText = $msg",
            "$notify.ShowBalloonTip(5000)",
            "Start-Sleep -Seconds 6",
            "$notify.Dispose()",
        ]
    )
    return _run_powershell_script(script, env, sta=True, timeout=10)


def _send_windows_toast(env: dict[str, str]) -> bool:
    script = "\n".join(
        [
            "$ErrorActionPreference='Stop'",
            "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null",
            "[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] > $null",
            "$xml = New-Object Windows.Data.Xml.Dom.XmlDocument",
            "$title = [System.Security.SecurityElement]::Escape([Environment]::GetEnvironmentVariable('MW_TOAST_TITLE','Process'))",
            "$msg = [System.Security.SecurityElement]::Escape([Environment]::GetEnvironmentVariable('MW_TOAST_MESSAGE','Process'))",
            "$xml.LoadXml(\"<toast><visual><binding template='ToastText02'><text id='1'>\" + $title + \"</text><text id='2'>\" + $msg + \"</text></binding></visual></toast>\")",
            "$toast=[Windows.UI.Notifications.ToastNotification]::new($xml)",
            "$notifier=[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('ModWatcherAgent')",
            "$notifier.Show($toast)",
        ]
    )
    return _run_powershell_script(script, env)


def send_windows_notification(title: str, message: str) -> bool:
    """Send a Windows notification via PowerShell.

    Prefer the NotifyIcon balloon path because unregistered AppUserModelID toast
    notifications can return success but stay invisible on some Windows setups.
    Title and message are passed through process environment variables instead
    of being interpolated into PowerShell source.
    """
    title = title.strip() or "Mod Watcher"
    message = message.strip() or "New notification"

    env = os.environ.copy()
    env["MW_TOAST_TITLE"] = title
    env["MW_TOAST_MESSAGE"] = message
    return _send_tray_balloon(env) or _send_windows_toast(env)
