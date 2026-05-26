import logging

import app.logger as logger_module
from app.config import settings
from app.logger import ThirdPartyNoiseFilter, get_log_entries, redact_sensitive_text


def test_redact_sensitive_text_masks_common_patterns() -> None:
    text = (
        "Authorization: Bearer abc123token\n"
        "api_key=sk-abcdef1234567890\n"
        "url=https://api.telegram.org/bot12345:abc/sendMessage\n"
        "discord=https://discord.com/api/webhooks/123/secret\n"
        "gemini=https://generativelanguage.googleapis.com/v1/models/gemini:generateContent?key=AIza-secret-key\n"
        "password: hunter2"
    )

    redacted = redact_sensitive_text(text)

    assert "abc123token" not in redacted
    assert "sk-abcdef1234567890" not in redacted
    assert "bot12345:abc" not in redacted
    assert "/secret" not in redacted
    assert "AIza-secret-key" not in redacted
    assert "hunter2" not in redacted
    assert "********" in redacted


def test_third_party_noise_filter_hides_alembic_info_but_keeps_warnings() -> None:
    filter_ = ThirdPartyNoiseFilter()
    alembic_info = logging.LogRecord(
        name="alembic.runtime.plugins",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="setup plugin alembic.autogenerate",
        args=(),
        exc_info=None,
    )
    alembic_warning = logging.LogRecord(
        name="alembic.runtime.migration",
        level=logging.WARNING,
        pathname=__file__,
        lineno=1,
        msg="migration warning",
        args=(),
        exc_info=None,
    )
    app_info = logging.LogRecord(
        name="app.jobs.scheduler",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="Scheduler started successfully",
        args=(),
        exc_info=None,
    )

    assert filter_.filter(alembic_info) is False
    assert filter_.filter(alembic_warning) is True
    assert filter_.filter(app_info) is True


def test_get_log_entries_reads_backend_service_file_when_ring_buffer_is_empty(tmp_path, monkeypatch) -> None:
    log_file = tmp_path / "backend_service.log"
    log_file.write_text(
        "\n".join(
            [
                "=== starting backend service ===",
                "[2026-05-23 10:00:00] INFO    app.main:40 - Scheduler started successfully",
                "WARNI [apscheduler.executors.default] Run time of job was missed",
                "INFO:     Started server process [1234]",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(settings, "LOG_DIR", str(tmp_path))
    monkeypatch.setattr(logger_module, "_ring_buffer", None)

    entries = get_log_entries(limit=10)

    assert [entry["level"] for entry in entries] == ["INFO", "WARNING", "INFO"]
    assert entries[0]["name"] == "backend_service.log"
    assert entries[1]["name"] == "apscheduler.executors.default"
    assert entries[2]["name"] == "app.main"


def test_get_log_entries_filters_file_logs(tmp_path, monkeypatch) -> None:
    log_file = tmp_path / "mod_watcher.log"
    log_file.write_text(
        "\n".join(
            [
                "[2026-05-23 10:00:00] INFO    app.main:40 - Scheduler started successfully",
                "[2026-05-23 10:01:00] ERROR   app.jobs:12 - token=secret failed",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(settings, "LOG_DIR", str(tmp_path))

    entries = get_log_entries(level="ERROR", search="failed", limit=10)

    assert len(entries) == 1
    assert entries[0]["level"] == "ERROR"
    assert "secret" not in entries[0]["message"]
