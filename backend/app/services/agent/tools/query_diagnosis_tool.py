import logging
from dataclasses import dataclass, field
from typing import Any

from app.services.agent.planning.query_diagnosis import QueryDiagnosis, diagnose_query

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class QueryDiagnosisInput:
    query: str
    query_plan: dict[str, Any]
    active_constraints: dict[str, Any] = field(default_factory=dict)
    preferences: dict[str, Any] = field(default_factory=dict)
    context_keywords: list[str] = field(default_factory=list)
    context_slots: dict[str, Any] = field(default_factory=dict)


class QueryDiagnosisTool:
    """Agent tool for converting a user turn and context into task understanding."""

    name = "query_diagnosis"

    def run(self, tool_input: QueryDiagnosisInput) -> QueryDiagnosis:
        diagnosis = diagnose_query(
            query=tool_input.query,
            query_plan=tool_input.query_plan,
            active_constraints=tool_input.active_constraints,
            preferences=tool_input.preferences,
            context_keywords=tool_input.context_keywords,
            context_slots=tool_input.context_slots,
        )
        evidence_id = str(tool_input.query_plan.get("evidence_id") or "").strip()
        logger.info(
            "agent.tool name=query_diagnosis status=succeeded intent=%s confidence=%.2f should_clarify=%s known_slots=%s evidence_id=%s",
            diagnosis.get("intent"),
            float(diagnosis.get("confidence") or 0),
            diagnosis.get("should_clarify"),
            sorted((diagnosis.get("known_slots") or {}).keys()),
            evidence_id,
        )
        return diagnosis
