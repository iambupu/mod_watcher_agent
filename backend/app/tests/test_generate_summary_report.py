import json
from datetime import UTC, datetime

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.jobs.generate_summary_report import generate_summary_report
from app.models.mod import Mod
from app.services.settings_service import SettingsService


def _make_engine():
    return create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


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
