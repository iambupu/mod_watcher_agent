"""Job: Generate an LLM report for recently discovered mods."""

from sqlmodel import Session

from app.db import engine
from app.jobs.tracked_jobs import run_tracked_job
from app.services.llm_client import create_llm_client
from app.services.summary_report_service import (
    generate_summary_report_payload,
    notify_summary_report_complete,
)
from app.services.system_notification_service import SystemNotificationService


async def generate_summary_report(*, force: bool = False) -> dict:
    """生成摘要报告并在成功生成时发送系统通知。"""
    async def handler(session: Session) -> dict:
        """在 tracked job 会话中生成摘要报告 payload。"""
        return await generate_summary_report_payload(session, force=force, create_client=create_llm_client)

    result = await run_tracked_job("llm_summary_report", handler)
    if result.get("generated"):
        with Session(engine) as session:
            notify_summary_report_complete(
                session,
                result,
                notification_service_cls=SystemNotificationService,
            )
    return result
