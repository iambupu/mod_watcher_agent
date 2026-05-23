"""Jobs: generate and send daily/weekly LLM digest notifications."""

from sqlmodel import Session

from app.db import engine
from app.jobs.tracked_jobs import run_tracked_job
from app.services.digest_service import (
    DigestPeriod,
    send_digest_for_window,
)
from app.services.digest_service import (
    generate_digest_text as _generate_digest_text,
)
from app.services.digest_service import (
    scheduled_window as _scheduled_window,
)


async def _send_digest_for_window(
    session: Session,
    period: DigestPeriod,
    window_start,
    window_end,
    *,
    force: bool = False,
) -> dict:
    """发送内部通知或外部请求。"""
    return await send_digest_for_window(
        session,
        period,
        window_start,
        window_end,
        force=force,
        generate_text=_generate_digest_text,
    )


async def send_digest(period: DigestPeriod = "daily", *, force: bool = False) -> dict:
    """发送通知或外部请求。"""
    window = _scheduled_window(period)
    if window is None:
        return {
            "generated": False,
            "reason": "not_due",
            "period": period,
            "items_scanned": 0,
            "items_matched": 0,
        }
    with Session(engine) as session:
        return await _send_digest_for_window(session, period, window[0], window[1], force=force)


async def send_daily_digest() -> dict:
    """发送通知或外部请求。"""
    return await send_digest("daily")


async def send_weekly_digest() -> dict:
    """发送通知或外部请求。"""
    return await send_digest("weekly")


async def run_digest_catchup(trigger: str = "scheduled") -> dict:
    """执行任务流程并返回结果。"""
    async def handler(session: Session) -> dict:
        """处理当前模块的业务逻辑并返回结果。"""
        results: list[dict] = []
        for period in ("daily", "weekly"):
            window = _scheduled_window(period)
            if window is None:
                continue
            result = await _send_digest_for_window(session, period, window[0], window[1])
            if result.get("generated") or result.get("reason") != "already_sent":
                results.append(result)
        return {
            "checked": True,
            "trigger": trigger,
            "results": results,
            "items_scanned": sum(int(item.get("items_scanned", 0) or 0) for item in results),
            "items_matched": sum(int(item.get("items_matched", 0) or 0) for item in results),
        }

    return await run_tracked_job(
        "digest_catchup",
        handler,
        metadata={"trigger": trigger},
    )
