import subprocess


def send_windows_notification(title: str, message: str) -> bool:
    """Send a Windows toast notification via PowerShell.

    Title and message are passed as separate command-line arguments (not
    interpolated into the script string) to prevent command injection via
    $() and other PowerShell interpolation syntax.
    """
    title = title.strip() or "Mod Watcher"
    message = message.strip() or "New notification"

    script = (
        "$ErrorActionPreference='Stop';"
        "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null;"
        "$xml = New-Object Windows.Data.Xml.Dom.XmlDocument;"
        "$title = [System.Security.SecurityElement]::Escape($args[0]);"
        "$msg = [System.Security.SecurityElement]::Escape($args[1]);"
        "$xml.LoadXml(\"<toast><visual><binding template='ToastText02'>"
        "<text id='1'>\" + $title + \"</text><text id='2'>\" + $msg + \"</text>"
        "</binding></visual></toast>\");"
        "$toast=[Windows.UI.Notifications.ToastNotification]::new($xml);"
        "$notifier=[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('ModWatcherAgent');"
        "$notifier.Show($toast);"
    )
    try:
        completed = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script, title, message],
            capture_output=True,
            text=True,
            timeout=8,
        )
    except Exception:
        return False
    return completed.returncode == 0
