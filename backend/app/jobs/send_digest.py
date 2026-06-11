"""Jobs: generate and send daily/weekly LLM digest notifications."""

from sqlmodel import Session

from app.db import engine
from app.jobs.tracked_jobs import run_tracked_job, safe_job_count
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
    """按指定窗口生成并发送 digest，调用方提供是否强制发送。"""
    return await send_digest_for_window(
        session,
        period,
        window_start,
        window_end,
        force=force,
        generate_text=_generate_digest_text,
    )


async def send_digest(period: DigestPeriod = "daily", *, force: bool = False) -> dict:
    """根据当前时间计算应发送窗口，到期才发送 digest。"""
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
    """发送每日 digest 的调度入口。"""
    return await send_digest("daily")


async def send_weekly_digest() -> dict:
    """发送每周 digest 的调度入口。"""
    return await send_digest("weekly")


async def run_digest_catchup(trigger: str = "scheduled") -> dict:
    """启动时或定时检查漏发 digest，并记录 catch-up 任务。"""
    async def handler(session: Session) -> dict:
        """逐个检查 daily/weekly 窗口，只保留实际处理过的结果。"""
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
            "items_scanned": sum(safe_job_count(item.get("items_scanned", 0)) for item in results),
            "items_matched": sum(safe_job_count(item.get("items_matched", 0)) for item in results),
        }

    return await run_tracked_job(
        "digest_catchup",
        handler,
        metadata={"trigger": trigger},
    )
