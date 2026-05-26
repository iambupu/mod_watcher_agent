import logging
from dataclasses import dataclass
from typing import Any

from sqlmodel import Session

from app.services.agent.memory.memory_service import AgentMemoryService

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MemoryContextInput:
    short_term: dict[str, Any]
    evidence_id: str = ""


class MemoryContextTool:
    """Agent tool for loading short-term and long-term memory context."""

    name = "memory_context_loader"

    def __init__(self, session: Session | None):
        self.session = session

    def run(self, tool_input: MemoryContextInput) -> dict[str, Any]:
        memory_context = AgentMemoryService(self.session).load_memory_context(short_term=tool_input.short_term)
        merged = memory_context.get("merged", {}) if isinstance(memory_context, dict) else {}
        long_term = memory_context.get("long_term", {}) if isinstance(memory_context, dict) else {}
        logger.info(
            "agent.tool name=memory_context_loader status=succeeded short_term=%s long_term=%s merged=%s favorite_summary=%s evidence_id=%s",
            bool(memory_context.get("short_term")) if isinstance(memory_context, dict) else False,
            bool(long_term),
            bool(merged),
            bool((long_term or {}).get("favorite_summary")) if isinstance(long_term, dict) else False,
            tool_input.evidence_id,
        )
        return memory_context
