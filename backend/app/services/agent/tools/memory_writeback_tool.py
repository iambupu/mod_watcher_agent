import logging
from dataclasses import dataclass, field
from typing import Any

from sqlmodel import Session

from app.services.agent.memory.preference_service import AgentPreferenceService

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MemoryWritebackInput:
    query: str
    query_plan: dict[str, Any]
    understanding: dict[str, Any] = field(default_factory=dict)
    evidence_id: str = ""


class MemoryWritebackTool:
    """Agent tool for persisting the current turn's compact query context."""

    name = "memory_writeback"

    def __init__(self, session: Session | None):
        self.session = session

    def run(self, tool_input: MemoryWritebackInput) -> dict[str, Any]:
        context = _build_writeback_context(tool_input)
        if self.session is None:
            return _skipped(context, "missing_session", tool_input.evidence_id)
        if not context:
            return _skipped(context, "empty_context", tool_input.evidence_id)
        try:
            AgentPreferenceService(self.session).save_last_query_context(context)
        except Exception as exc:
            logger.info(
                "agent.tool name=memory_writeback status=degraded reason=%s fields=%s evidence_id=%s",
                type(exc).__name__,
                sorted(context.keys()),
                tool_input.evidence_id,
            )
            return {
                "status": "degraded",
                "reason": type(exc).__name__,
                "context": context,
                "evidence_id": tool_input.evidence_id,
            }
        logger.info(
            "agent.tool name=memory_writeback status=succeeded fields=%s evidence_id=%s",
            sorted(context.keys()),
            tool_input.evidence_id,
        )
        return {
            "status": "succeeded",
            "reason": "",
            "context": context,
            "evidence_id": tool_input.evidence_id,
        }


def _build_writeback_context(tool_input: MemoryWritebackInput) -> dict[str, Any]:
    plan = tool_input.query_plan or {}
    understanding = tool_input.understanding or {}
    slots = understanding.get("slots") if isinstance(understanding.get("slots"), dict) else {}
    evidence = understanding.get("evidence") if isinstance(understanding.get("evidence"), list) else []
    context: dict[str, Any] = {
        "source": "chat_turn",
        "query": tool_input.query.strip(),
    }
    _copy_list(context, "keywords", plan.get("keywords") or slots.get("keywords"))
    _copy_first(context, "game", plan.get("games") or slots.get("game"))
    _copy_first(context, "source_name", plan.get("sources") or slots.get("source"))
    _copy_first(context, "category", plan.get("categories") or slots.get("category"))
    for key in ("adult_content", "sort_field", "sort_order"):
        value = plan.get(key, slots.get(key))
        if value is not None:
            context[key] = value
    semantic_anchors = _evidence_value(evidence, "semantic_anchors")
    semantic_domains = _evidence_value(evidence, "semantic_domains")
    _copy_list(context, "semantic_anchors", semantic_anchors)
    _copy_list(context, "semantic_domains", semantic_domains)
    confidence = understanding.get("confidence")
    if isinstance(confidence, int | float):
        context["quality_score"] = round(max(0.0, min(1.0, float(confidence))), 3)
    return {key: value for key, value in context.items() if value not in (None, "", [])}


def _copy_list(target: dict[str, Any], key: str, raw: object) -> None:
    if isinstance(raw, list):
        values = [str(item).strip() for item in raw if str(item).strip()]
    elif isinstance(raw, str) and raw.strip():
        values = [raw.strip()]
    else:
        values = []
    if values:
        target[key] = values[:12]


def _copy_first(target: dict[str, Any], key: str, raw: object) -> None:
    if isinstance(raw, list):
        values = [str(item).strip() for item in raw if str(item).strip()]
        if values:
            target[key] = values[0]
    elif isinstance(raw, str) and raw.strip():
        target[key] = raw.strip()


def _evidence_value(evidence: list[object], field: str) -> object:
    for item in evidence:
        if isinstance(item, dict) and item.get("field") == field:
            return item.get("value")
    return None


def _skipped(context: dict[str, Any], reason: str, evidence_id: str) -> dict[str, Any]:
    logger.info(
        "agent.tool name=memory_writeback status=skipped reason=%s fields=%s evidence_id=%s",
        reason,
        sorted(context.keys()),
        evidence_id,
    )
    return {
        "status": "skipped",
        "reason": reason,
        "context": context,
        "evidence_id": evidence_id,
    }
