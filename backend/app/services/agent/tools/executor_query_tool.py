import logging
from dataclasses import dataclass
from typing import Any

from sqlmodel import Session

from app.services.agent.list_utils import string_list as _string_list
from app.services.agent.planning.context_plan_merge import (
    merge_context_query_plan,
)
from app.services.agent.planning.executor_query_plan import build_executor_query_plan
from app.services.agent.query_planner import (
    load_slot_options,
    normalize_query_plan,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ExecutorQueryInput:
    query: str
    context_query_plan: dict[str, Any] | None = None
    evidence_id: str = ""


@dataclass(frozen=True)
class ExecutorQueryOutput:
    query_plan: dict[str, Any]
    evidence_id: str | None


class ExecutorQueryTool:
    """把用户问题转成 executor 兼容 query_plan；LLM 语义判断由 SemanticStrategyTool 承担。"""

    name = "executor_query"

    def __init__(self, session: Session):
        self.session = session

    async def run(self, tool_input: ExecutorQueryInput) -> ExecutorQueryOutput:
        slot_options = load_slot_options(self.session)
        role = "executor_query"
        seed_plan = build_executor_query_plan(tool_input.query)
        seed_plan = merge_context_query_plan(seed_plan, tool_input.context_query_plan)
        raw_evidence_id = str((seed_plan or {}).get("evidence_id") or "").strip()
        evidence_id = str(tool_input.evidence_id or raw_evidence_id).strip() or None
        context_signal = seed_plan.get("_agent_context_signal") if isinstance(seed_plan, dict) else None
        query_plan = normalize_query_plan(
            seed_plan,
            tool_input.query,
            slot_options,
        )
        if isinstance(context_signal, dict):
            query_plan["_agent_context_signal"] = context_signal
        context_used = bool(tool_input.context_query_plan)
        if evidence_id:
            query_plan["evidence_id"] = evidence_id
        if raw_evidence_id and raw_evidence_id != evidence_id:
            query_plan["_agent_context_evidence_id"] = raw_evidence_id
        semantic_anchors = _string_list(seed_plan.get("semantic_anchors"))
        semantic_domains = _string_list(seed_plan.get("semantic_domains"))
        if semantic_anchors:
            query_plan["_agent_semantic_anchors"] = semantic_anchors
            query_plan["_agent_semantic_source"] = role
        if semantic_domains:
            query_plan["_agent_semantic_domains"] = semantic_domains
        query_plan["_agent_query_plan_role"] = role
        query_plan["_agent_context_plan_used"] = context_used
        _log_query_plan(query_plan, evidence_id=evidence_id, context_used=bool(tool_input.context_query_plan))
        logger.info(
            "agent.tool name=executor_query status=succeeded role=%s intent=%s keywords=%s evidence_id=%s context_used=%s",
            role,
            query_plan.get("intent"),
            query_plan.get("keywords", []),
            evidence_id,
            bool(tool_input.context_query_plan),
        )
        return ExecutorQueryOutput(
            query_plan=query_plan,
            evidence_id=evidence_id,
        )


def _log_query_plan(query_plan: dict[str, Any], *, evidence_id: str | None, context_used: bool) -> None:
    logger.info(
        "agent.chat.plan evidence_id=%s query_plan_role=%s intent=%s open_discovery=%s retrieval_mode=%s keywords=%s excluded_keywords=%s exclude_titles=%s excluded_sources=%s keyword_match_mode=%s exact_title=%s version=%s external_id=%s source_url=%s games=%s sources=%s categories=%s category_hints=%s tags=%s summary_languages=%s excluded_summary_languages=%s requirement_terms=%s compatibility_terms=%s has_thumbnail=%s author=%s adult_content=%s min_downloads=%s min_endorsements=%s min_views=%s min_likes=%s updated_since_days=%s updated_after=%s updated_before=%s published_after=%s published_before=%s created_after=%s created_before=%s sort=%s/%s context_used=%s",
        evidence_id,
        query_plan.get("_agent_query_plan_role"),
        query_plan.get("intent"),
        query_plan.get("open_discovery"),
        query_plan.get("retrieval_mode"),
        query_plan.get("keywords", []),
        query_plan.get("excluded_keywords", []),
        query_plan.get("exclude_titles", []),
        query_plan.get("excluded_sources", []),
        query_plan.get("keyword_match_mode"),
        query_plan.get("exact_title"),
        query_plan.get("version"),
        query_plan.get("external_id"),
        query_plan.get("source_url"),
        query_plan.get("games", []),
        query_plan.get("sources", []),
        query_plan.get("categories", []),
        query_plan.get("category_hints", []),
        query_plan.get("tags", []),
        query_plan.get("summary_languages", []),
        query_plan.get("excluded_summary_languages", []),
        query_plan.get("requirement_terms", []),
        query_plan.get("compatibility_terms", []),
        query_plan.get("has_thumbnail"),
        query_plan.get("author"),
        query_plan.get("adult_content"),
        query_plan.get("min_downloads"),
        query_plan.get("min_endorsements"),
        query_plan.get("min_views"),
        query_plan.get("min_likes"),
        query_plan.get("updated_since_days"),
        query_plan.get("updated_after"),
        query_plan.get("updated_before"),
        query_plan.get("published_after"),
        query_plan.get("published_before"),
        query_plan.get("created_after"),
        query_plan.get("created_before"),
        query_plan.get("sort_field"),
        query_plan.get("sort_order"),
        context_used,
    )
    logger.info(
        "agent.chat.plan intent=%s evidence_id=%s",
        query_plan.get("intent"),
        evidence_id,
    )
