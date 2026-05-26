import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from fastapi import Request
from sqlmodel import Session

from app.services import llm_provider_config as llm_provider_config_module
from app.services.agent import llm_config_service as llm_config_module
from app.services.agent import query_planner as query_planner_module
from app.services.agent import rate_limiter as rate_limiter_module
from app.services.agent.context.memory_context_builder import load_agent_memory_context
from app.services.agent.planning.context_pipeline import prepare_contextual_query_plan
from app.services.agent.planning.query_diagnosis import QueryDiagnosis, diagnosis_log_fields
from app.services.agent.schemas import AgentHistoryItem
from app.services.agent.tools.query_diagnosis_tool import QueryDiagnosisInput, QueryDiagnosisTool
from app.services.agent.tools.query_planning_tool import QueryPlanningInput, QueryPlanningTool
from app.services.settings_service import SettingsService

logger = logging.getLogger(__name__)

QueryPlanner = Callable[..., Awaitable[dict[str, Any] | None]]


@dataclass(frozen=True)
class TaskUnderstandingInput:
    query: str
    history: list[AgentHistoryItem] = field(default_factory=list)
    active_constraints: dict[str, Any] = field(default_factory=dict)
    last_query_context: dict[str, Any] = field(default_factory=dict)
    shown_mod_titles: list[str] = field(default_factory=list)
    provider_override: str | None = None
    model_override: str | None = None
    request: Request | None = None
    evidence_id: str = ""


@dataclass(frozen=True)
class TaskUnderstandingOutput:
    query_plan: dict[str, Any]
    query_diagnosis: QueryDiagnosis
    preferences: dict[str, Any]
    memory_context: dict[str, Any]
    llm_available: bool = False
    llm_provider: str = ""
    llm_api_key: str = ""
    llm_base_url: str = ""
    llm_model: str = ""
    evidence_id: str = ""


class TaskUnderstandingTool:
    """Agent tool for memory-aware query planning and task diagnosis."""

    name = "task_understanding"

    def __init__(self, session: Session | None, *, planner: QueryPlanner | None = None):
        self.session = session
        self.planner = planner or query_planner_module.plan_query_with_llm

    async def run(self, tool_input: TaskUnderstandingInput) -> TaskUnderstandingOutput:
        evidence_id = str(tool_input.evidence_id or "").strip()
        memory_context = load_agent_memory_context(
            session=self.session,
            last_query_context=tool_input.last_query_context,
            active_constraints=tool_input.active_constraints,
            shown_mod_titles=tool_input.shown_mod_titles,
            evidence_id=evidence_id,
        )
        preferences = memory_context.get("merged", {})
        context_planning = prepare_contextual_query_plan(
            query=tool_input.query,
            active_constraints=tool_input.active_constraints,
            last_query_context=tool_input.last_query_context,
            shown_mod_titles=tool_input.shown_mod_titles,
            history=tool_input.history,
            memory_context=memory_context,
            session=self.session,
            evidence_id=evidence_id,
        )
        query_plan = context_planning.query_plan
        provider = api_key = base_url = model = ""
        llm_available = False
        if self.session is not None and hasattr(self.session, "exec"):
            settings = SettingsService(self.session)
            if tool_input.request is not None and _should_enforce_rate_limit(tool_input.request):
                await rate_limiter_module.enforce_rate_limit(
                    rate_limiter_module.build_rate_limit_key(tool_input.request, settings)
                )
            provider, api_key, base_url, model = llm_config_module.get_llm_config(
                settings,
                provider_override=tool_input.provider_override,
                model_override=tool_input.model_override,
            )
            llm_available = llm_provider_config_module.provider_has_credentials(provider, api_key)
            planning_output = await QueryPlanningTool(self.session, planner=self.planner).run(
                QueryPlanningInput(
                    query=tool_input.query,
                    history=tool_input.history,
                    context_query_plan=query_plan,
                    evidence_id=evidence_id,
                    llm_available=llm_available,
                    provider=provider,
                    api_key=api_key,
                    base_url=base_url,
                    model=model,
                )
            )
            query_plan = planning_output.query_plan
            evidence_id = planning_output.evidence_id or evidence_id
            query_plan["evidence_id"] = evidence_id
        _log_memory_context(memory_context, preferences)
        diagnosis = QueryDiagnosisTool().run(
            QueryDiagnosisInput(
                query=tool_input.query,
                query_plan=query_plan,
                active_constraints=tool_input.active_constraints,
                preferences=preferences,
                context_keywords=context_planning.diagnosis_context_keywords,
                context_slots=context_planning.diagnosis_context_slots,
            )
        )
        _log_diagnosis(query_plan, diagnosis)
        logger.info(
            "agent.tool name=task_understanding status=succeeded intent=%s evidence_id=%s llm_available=%s",
            diagnosis.get("intent"),
            evidence_id,
            llm_available,
        )
        return TaskUnderstandingOutput(
            query_plan=query_plan,
            query_diagnosis=diagnosis,
            preferences=preferences,
            memory_context=memory_context,
            llm_available=llm_available,
            llm_provider=provider,
            llm_api_key=api_key,
            llm_base_url=base_url,
            llm_model=model,
            evidence_id=evidence_id,
        )


def _log_memory_context(memory_context: dict[str, Any], preferences: dict[str, Any]) -> None:
    logger.info(
        "agent.memory short_term=%s long_term=%s merged=%s favorite_summary=%s",
        bool(memory_context.get("short_term")),
        bool(memory_context.get("long_term")),
        bool(preferences),
        bool((memory_context.get("long_term") or {}).get("favorite_summary")),
    )
    logger.info(
        "agent.memory loaded=%s favorite_summary=%s",
        bool(preferences),
        bool((memory_context.get("long_term") or {}).get("favorite_summary")),
    )


def _log_diagnosis(query_plan: dict[str, Any], diagnosis: QueryDiagnosis) -> None:
    diagnosis_log = diagnosis_log_fields(diagnosis)
    logger.info(
        "agent.diagnosis evidence_id=%s intent=%s confidence=%.2f should_clarify=%s missing_slots=%s known_slots=%s context_continuity_score=%s semantic_anchors=%s semantic_domains=%s",
        query_plan.get("evidence_id"),
        diagnosis.get("intent"),
        float(diagnosis.get("confidence") or 0),
        diagnosis.get("should_clarify"),
        diagnosis.get("missing_slots"),
        sorted((diagnosis.get("known_slots") or {}).keys()),
        diagnosis_log["context_continuity_score"],
        diagnosis_log["semantic_anchors"],
        diagnosis_log["semantic_domains"],
    )


def _should_enforce_rate_limit(request: Request) -> bool:
    if not hasattr(request, "client"):
        return False
    url = getattr(request, "url", None)
    hostname = getattr(url, "hostname", "")
    return str(hostname or "").lower() != "testserver"
