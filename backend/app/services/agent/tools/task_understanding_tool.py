import logging
from dataclasses import dataclass, field
from typing import Any

from fastapi import Request
from sqlmodel import Session

from app.services import llm_provider_config as llm_provider_config_module
from app.services.agent import llm_config_service as llm_config_module
from app.services.agent import rate_limiter as rate_limiter_module
from app.services.agent.context.memory_context_builder import load_agent_memory_context
from app.services.agent.planning.context_pipeline import prepare_contextual_query_plan
from app.services.agent.planning.llm_context_selection import select_last_query_context_with_llm
from app.services.agent.planning.query_diagnosis import QueryDiagnosis, diagnosis_log_fields
from app.services.agent.query_planner import load_slot_options, normalize_query_plan
from app.services.agent.schemas import AgentHistoryItem
from app.services.agent.semantic_brain.semantic_strategy_adapter import (
    attach_semantic_strategy_to_query_plan,
)
from app.services.agent.semantic_brain.semantic_strategy_tool import (
    SemanticStrategyInput,
    SemanticStrategyTool,
)
from app.services.agent.tools.executor_query_tool import ExecutorQueryInput, ExecutorQueryTool
from app.services.agent.tools.query_diagnosis_tool import QueryDiagnosisInput, QueryDiagnosisTool
from app.services.settings_service import SettingsService
from app.utils.numeric import safe_float

logger = logging.getLogger(__name__)


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
    semantic_strategy: dict[str, Any] = field(default_factory=dict)
    evidence_id: str = ""


class TaskUnderstandingTool:
    """结合上下文、长期记忆和可选 LLM，生成查询计划与任务诊断。"""

    name = "task_understanding"

    def __init__(self, session: Session | None):
        self.session = session

    async def run(self, tool_input: TaskUnderstandingInput) -> TaskUnderstandingOutput:
        evidence_id = str(tool_input.evidence_id or "").strip()
        # 记忆只参与补全和软偏好；本轮显式输入仍由 context pipeline 优先处理。
        memory_context = load_agent_memory_context(
            session=self.session,
            last_query_context=tool_input.last_query_context,
            active_constraints=tool_input.active_constraints,
            shown_mod_titles=tool_input.shown_mod_titles,
            evidence_id=evidence_id,
        )
        preferences = memory_context.get("merged", {})
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
        selected_last_query_context = tool_input.last_query_context
        if llm_available:
            llm_context = await select_last_query_context_with_llm(
                query=tool_input.query,
                history=tool_input.history,
                active_constraints=tool_input.active_constraints,
                short_last_query_context=tool_input.last_query_context,
                memory_context=memory_context,
                shown_mod_titles=tool_input.shown_mod_titles,
                provider=provider,
                api_key=api_key,
                base_url=base_url,
                model=model,
                evidence_id=evidence_id,
            )
            if llm_context.context:
                selected_last_query_context = llm_context.context
        semantic_strategy = await SemanticStrategyTool().run(
            SemanticStrategyInput(
                query=tool_input.query,
                history=tool_input.history,
                active_constraints=tool_input.active_constraints,
                last_query_context=selected_last_query_context,
                memory_context=memory_context,
                shown_mod_titles=tool_input.shown_mod_titles,
                llm_available=llm_available,
                provider=provider,
                api_key=api_key,
                base_url=base_url,
                model=model,
                evidence_id=evidence_id,
            )
        )
        context_result = prepare_contextual_query_plan(
            query=tool_input.query,
            active_constraints=tool_input.active_constraints,
            last_query_context=selected_last_query_context,
            shown_mod_titles=tool_input.shown_mod_titles,
            history=tool_input.history,
            memory_context=memory_context,
            session=self.session,
            evidence_id=evidence_id,
        )
        query_plan = context_result.query_plan
        if self.session is not None and hasattr(self.session, "exec"):
            # ExecutorQueryTool 只生成 executor 输入字段；LLM 只在 SemanticStrategyTool 中作为语义大脑使用。
            executor_query = await ExecutorQueryTool(self.session).run(
                ExecutorQueryInput(
                    query=tool_input.query,
                    context_query_plan=query_plan,
                    evidence_id=evidence_id,
                )
            )
            query_plan = executor_query.query_plan
            evidence_id = executor_query.evidence_id or evidence_id
            query_plan["evidence_id"] = evidence_id
        query_plan = attach_semantic_strategy_to_query_plan(query_plan, semantic_strategy)
        if self.session is not None and hasattr(self.session, "exec"):
            normalized_plan = normalize_query_plan(query_plan, tool_input.query, load_slot_options(self.session))
            query_plan = {**query_plan, **normalized_plan}
        _log_memory_context(memory_context, preferences)
        # 诊断层把 query_plan 转成可审计的 intent、slots 和语义信号，供工具规划使用。
        diagnosis = QueryDiagnosisTool().run(
            QueryDiagnosisInput(
                query=tool_input.query,
                query_plan=query_plan,
                active_constraints=tool_input.active_constraints,
                preferences=preferences,
                context_keywords=context_result.diagnosis_context_keywords,
                context_slots=context_result.diagnosis_context_slots,
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
            semantic_strategy=semantic_strategy.strategy.model_dump(mode="python"),
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
        safe_float(diagnosis.get("confidence")),
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
