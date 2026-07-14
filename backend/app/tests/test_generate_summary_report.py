import json
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.jobs.generate_summary_report import generate_summary_report
from app.models.mod import Mod
from app.services.settings_service import SettingsService
from app.services.summary_report_service import (
    generate_summary_report_payload,
    notify_summary_report_complete,
    summary_report_interval_minutes,
    summary_window_minutes,
)


def _make_engine():
    return create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


def test_summary_window_keeps_minimum_analysis_window_for_hourly_schedule():
    assert summary_window_minutes(60, force=False) == 360
    assert summary_window_minutes(720, force=False) == 720
    assert summary_window_minutes(0, force=True) == 10080
    assert summary_window_minutes(0, force=False) == 0


def test_summary_report_interval_recovers_from_legacy_bad_settings():
    assert summary_report_interval_minutes("bad") == 0
    assert summary_report_interval_minutes("-5") == 0
    assert summary_report_interval_minutes("20000") == 10080
    assert summary_report_interval_minutes("60") == 60


def test_summary_report_notification_tolerates_invalid_matched_count():
    events = []

    class FakeNotificationService:
        def __init__(self, session):  # noqa: ANN001
            self.session = session

        def create_event(self, **kwargs):  # noqa: ANN001
            events.append(kwargs)

    notify_summary_report_complete(
        session=object(),
        result={"generated": True, "items_matched": "bad", "report": "报告正文"},
        notification_service_cls=FakeNotificationService,
    )

    assert events[0]["message"].startswith("已生成摘要汇总报告，样本 0 个。")


@pytest.mark.asyncio
async def test_summary_report_uses_ui_language(monkeypatch):
    engine = _make_engine()
    SQLModel.metadata.create_all(engine)
    captured: dict[str, str] = {}

    class FakeClient:
        async def chat(self, prompt: str, model: str, max_tokens: int = 1024) -> str:  # noqa: ARG002
            captured["prompt"] = prompt
            captured["model"] = model
            return "English report"

    async def run_now(job_name, handler, metadata=None):  # noqa: ARG001
        with Session(engine) as session:
            return await handler(session)

    created_events = []
    monkeypatch.setattr("app.jobs.generate_summary_report.run_tracked_job", run_now)
    monkeypatch.setattr("app.jobs.generate_summary_report.create_llm_client", lambda *args: FakeClient())
    monkeypatch.setattr(
        "app.jobs.generate_summary_report.SystemNotificationService.create_event",
        lambda self, **kwargs: created_events.append(kwargs),
    )

    with Session(engine) as session:
        settings = SettingsService(session)
        settings.set("ui_language", "en-US")
        settings.set("summary_report_prompt", "Focus on popular adult mods")
        settings.set("summary_report_interval_minutes", "0")
        settings.set(
            "llm_providers_json",
            json.dumps(
                [
                    {
                        "provider": "ollama",
                        "enabled": True,
                        "priority": 1,
                        "model": "qwen3:8b",
                        "api_key": "",
                        "base_url": "http://localhost:11434/v1",
                    }
                ]
            ),
        )
        session.add(
            Mod(
                source="nexusmods",
                external_id="1",
                game="Stellar Blade",
                title="Recent Mod",
                url="https://example.com/mod/1",
                original_summary="A recent mod.",
                downloads=100,
                first_seen_at=datetime.now(UTC).isoformat(),
                last_seen_at=datetime.now(UTC).isoformat(),
            )
        )
        session.commit()

    result = await generate_summary_report(force=True)

    assert result["generated"] is True
    assert result["report"] == "English report"
    assert "输出语言：English" in captured["prompt"]
    assert "必须全篇使用该语言输出" in captured["prompt"]
    assert created_events == [
        {
            "event_type": "llm_summary_report_complete",
            "title": "摘要汇总报告完成",
            "message": "已生成摘要汇总报告，样本 1 个。English report",
        }
    ]


@pytest.mark.asyncio
async def test_summary_report_keeps_full_report_text(monkeypatch):
    engine = _make_engine()
    SQLModel.metadata.create_all(engine)
    full_report = "段落" * 1200

    class FakeClient:
        async def chat(self, prompt: str, model: str, max_tokens: int = 1024) -> str:  # noqa: ARG002
            return full_report

    async def run_now(job_name, handler, metadata=None):  # noqa: ARG001
        with Session(engine) as session:
            return await handler(session)

    monkeypatch.setattr("app.jobs.generate_summary_report.run_tracked_job", run_now)
    monkeypatch.setattr("app.jobs.generate_summary_report.create_llm_client", lambda *args: FakeClient())
    monkeypatch.setattr(
        "app.jobs.generate_summary_report.SystemNotificationService.create_event",
        lambda self, **kwargs: None,
    )

    with Session(engine) as session:
        settings = SettingsService(session)
        settings.set("ui_language", "zh-CN")
        settings.set("summary_report_prompt", "关注热点")
        settings.set("summary_report_interval_minutes", "0")
        settings.set(
            "llm_providers_json",
            json.dumps(
                [
                    {
                        "provider": "ollama",
                        "enabled": True,
                        "priority": 1,
                        "model": "qwen3:8b",
                        "api_key": "",
                        "base_url": "http://localhost:11434/v1",
                    }
                ]
            ),
        )
        session.add(
            Mod(
                source="nexusmods",
                external_id="1",
                game="Skyrim Special Edition",
                title="Recent Mod",
                url="https://example.com/mod/1",
                original_summary="A recent mod.",
                downloads=100,
                first_seen_at=datetime.now(UTC).isoformat(),
                last_seen_at=datetime.now(UTC).isoformat(),
            )
        )
        session.commit()

    result = await generate_summary_report(force=True)

    assert result["report"] == full_report
    assert len(result["report"]) > 2000


@pytest.mark.asyncio
async def test_summary_report_hourly_schedule_uses_minimum_analysis_window(monkeypatch):
    engine = _make_engine()
    SQLModel.metadata.create_all(engine)

    class FakeClient:
        async def chat(self, prompt: str, model: str, max_tokens: int = 1024) -> str:  # noqa: ARG002
            return "report"

    async def run_now(job_name, handler, metadata=None):  # noqa: ARG001
        with Session(engine) as session:
            return await handler(session)

    monkeypatch.setattr("app.jobs.generate_summary_report.run_tracked_job", run_now)
    monkeypatch.setattr("app.jobs.generate_summary_report.create_llm_client", lambda *args: FakeClient())
    monkeypatch.setattr(
        "app.jobs.generate_summary_report.SystemNotificationService.create_event",
        lambda self, **kwargs: None,
    )

    with Session(engine) as session:
        settings = SettingsService(session)
        settings.set("ui_language", "zh-CN")
        settings.set("summary_report_prompt", "关注热点")
        settings.set("summary_report_interval_minutes", "60")
        settings.set(
            "llm_providers_json",
            json.dumps(
                [
                    {
                        "provider": "ollama",
                        "enabled": True,
                        "priority": 1,
                        "model": "qwen3:8b",
                        "api_key": "",
                        "base_url": "http://localhost:11434/v1",
                    }
                ]
            ),
        )
        session.add(
            Mod(
                source="nexusmods",
                external_id="recent-but-older-than-hour",
                game="Skyrim Special Edition",
                title="Recent But Older Than Hour",
                url="https://example.com/mod/recent",
                original_summary="A mod discovered within the minimum summary window.",
                downloads=100,
                first_seen_at=(datetime.now(UTC) - timedelta(hours=2)).isoformat(),
                last_seen_at=(datetime.now(UTC) - timedelta(hours=2)).isoformat(),
            )
        )
        session.commit()

    result = await generate_summary_report()

    assert result["generated"] is True
    assert result["window_minutes"] == 360
    assert result["items_scanned"] == 1


@pytest.mark.asyncio
async def test_summary_report_does_not_notify_when_not_generated(monkeypatch):
    engine = _make_engine()
    SQLModel.metadata.create_all(engine)
    created_events = []

    async def run_now(job_name, handler, metadata=None):  # noqa: ARG001
        with Session(engine) as session:
            return await handler(session)

    monkeypatch.setattr("app.jobs.generate_summary_report.run_tracked_job", run_now)
    monkeypatch.setattr(
        "app.jobs.generate_summary_report.SystemNotificationService.create_event",
        lambda self, **kwargs: created_events.append(kwargs),
    )

    with Session(engine) as session:
        settings = SettingsService(session)
        settings.set("summary_report_prompt", "")
        settings.set("summary_report_interval_minutes", "0")
        session.commit()

    result = await generate_summary_report(force=True)

    assert result["generated"] is False
    assert result["reason"] == "missing_prompt"
    assert created_events == []


@pytest.mark.asyncio
async def test_summary_report_releases_transaction_before_llm_call():
    engine = _make_engine()
    SQLModel.metadata.create_all(engine)
    observed: dict[str, bool] = {}

    class FakeClient:
        async def chat(self, prompt: str, model: str, max_tokens: int = 1024) -> str:  # noqa: ARG002
            observed["in_transaction"] = session.in_transaction()
            return "摘要报告正文"

    with Session(engine) as session:
        settings = SettingsService(session)
        settings.set("ui_language", "zh-CN")
        settings.set("summary_report_prompt", "关注热点")
        settings.set("summary_report_interval_minutes", "0")
        settings.set(
            "llm_providers_json",
            json.dumps(
                [
                    {
                        "provider": "ollama",
                        "enabled": True,
                        "priority": 1,
                        "model": "qwen3:8b",
                        "api_key": "",
                        "base_url": "http://localhost:11434/v1",
                    }
                ]
            ),
        )
        session.add(
            Mod(
                source="nexusmods",
                external_id="transaction-report",
                game="Skyrim Special Edition",
                title="Recent Mod",
                url="https://example.com/mod/transaction-report",
                original_summary="A recent mod.",
                downloads=100,
                first_seen_at=datetime.now(UTC).isoformat(),
                last_seen_at=datetime.now(UTC).isoformat(),
            )
        )
        session.commit()

        result = await generate_summary_report_payload(
            session,
            force=True,
            create_client=lambda *args: FakeClient(),
        )

        assert observed == {"in_transaction": False}
        assert result["report"] == "摘要报告正文"
