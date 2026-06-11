# 中文注释：封装Agent 偏好缓存刷新任务的调度入口和任务处理。

from typing import Any

from sqlmodel import Session

from app.db import engine
from app.jobs.tracked_jobs import run_tracked_job
from app.services.agent.memory.profile_refresh_service import (
    refresh_agent_preferences as refresh_profile,
)
from app.utils.numeric import safe_nonnegative_int


async def refresh_agent_preferences(record_job: bool = True) -> dict[str, Any]:
    """Refresh the user profile used by agent and dashboard recommendations."""

    async def handler(session: Session) -> dict[str, Any]:
        result = refresh_profile(session)
        return _profile_refresh_job_result(result)

    if record_job:
        return await run_tracked_job("agent_profile_refresh", handler)
    with Session(engine) as session:
        return await handler(session)


def _profile_refresh_job_result(result: dict[str, Any]) -> dict[str, Any]:
    """Add tracked-job counters without trusting optional summary payload shapes."""
    if not isinstance(result, dict):
        result = {}
    favorite_summary = result.get("favorite_summary")
    conversation_summary = result.get("conversation_summary")
    favorite_summary = favorite_summary if isinstance(favorite_summary, dict) else {}
    conversation_summary = conversation_summary if isinstance(conversation_summary, dict) else {}
    favorite_count = safe_nonnegative_int(favorite_summary.get("favorite_count"))
    message_count = safe_nonnegative_int(conversation_summary.get("message_count"))
    return {
        **result,
        "items_scanned": favorite_count + message_count,
        "items_matched": _list_count(favorite_summary.get("top_games"))
        + _list_count(conversation_summary.get("top_games")),
    }


def _list_count(value: Any) -> int:
    return len(value) if isinstance(value, list) else 0
