from typing import Any

from sqlmodel import Session

from app.db import engine
from app.jobs.tracked_jobs import run_tracked_job
from app.services.agent.memory.profile_refresh_service import (
    refresh_agent_preferences as refresh_profile,
)


async def refresh_agent_preferences(record_job: bool = True) -> dict[str, Any]:
    """Refresh the user profile used by agent and dashboard recommendations."""

    async def handler(session: Session) -> dict[str, Any]:
        result = refresh_profile(session)
        favorite_summary = result.get("favorite_summary") if isinstance(result, dict) else {}
        conversation_summary = result.get("conversation_summary") if isinstance(result, dict) else {}
        favorite_count = int((favorite_summary or {}).get("favorite_count", 0) or 0)
        message_count = int((conversation_summary or {}).get("message_count", 0) or 0)
        return {
            **result,
            "items_scanned": favorite_count + message_count,
            "items_matched": len((favorite_summary or {}).get("top_games", []) or [])
            + len((conversation_summary or {}).get("top_games", []) or []),
        }

    if record_job:
        return await run_tracked_job("agent_profile_refresh", handler)
    with Session(engine) as session:
        return await handler(session)
