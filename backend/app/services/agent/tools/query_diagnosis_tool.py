import logging
from dataclasses import dataclass, field
from typing import Any

from app.services.agent.planning.query_diagnosis import QueryDiagnosis, diagnose_query
from app.utils.numeric import safe_float

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
    """把当前轮问题和上下文转换成意图、槽位和语义信号。"""

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
            safe_float(diagnosis.get("confidence")),
            diagnosis.get("should_clarify"),
            sorted((diagnosis.get("known_slots") or {}).keys()),
            evidence_id,
        )
        return diagnosis
