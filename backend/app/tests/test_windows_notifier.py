import subprocess

from app.services.windows_notifier import send_windows_notification


def test_windows_notification_prefers_sta_tray_balloon(monkeypatch):
    calls = []

    def fake_run(args, capture_output, text, timeout, env):  # noqa: ARG001
        calls.append({"args": args, "timeout": timeout, "env": env})
        return subprocess.CompletedProcess(args=args, returncode=0)

    monkeypatch.setattr("app.services.windows_notifier.subprocess.run", fake_run)

    assert send_windows_notification("Title", "Message") is True
    assert len(calls) == 1
    assert "-STA" in calls[0]["args"]
    assert calls[0]["env"]["MW_TOAST_TITLE"] == "Title"
    assert calls[0]["env"]["MW_TOAST_MESSAGE"] == "Message"


def test_windows_notification_falls_back_to_toast(monkeypatch):
    calls = []

    def fake_run(args, capture_output, text, timeout, env):  # noqa: ARG001
        calls.append({"args": args, "timeout": timeout, "env": env})
        return subprocess.CompletedProcess(args=args, returncode=1 if len(calls) == 1 else 0)

    monkeypatch.setattr("app.services.windows_notifier.subprocess.run", fake_run)

    assert send_windows_notification("Title", "Message") is True
    assert len(calls) == 2
    assert "-STA" in calls[0]["args"]
    assert "-STA" not in calls[1]["args"]
