import logging

from app.logger import ThirdPartyNoiseFilter, redact_sensitive_text


def test_redact_sensitive_text_masks_common_patterns() -> None:
    text = (
        "Authorization: Bearer abc123token\n"
        "api_key=sk-abcdef1234567890\n"
        "url=https://api.telegram.org/bot12345:abc/sendMessage\n"
        "discord=https://discord.com/api/webhooks/123/secret\n"
        "password: hunter2"
    )

    redacted = redact_sensitive_text(text)

    assert "abc123token" not in redacted
    assert "sk-abcdef1234567890" not in redacted
    assert "bot12345:abc" not in redacted
    assert "/secret" not in redacted
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
