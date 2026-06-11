# 中文注释：定义 Agent 图工作流状态和阶段编排。

from typing import Any

from sqlmodel import Session

from app.services.agent.tools.bounded_react_retrieval_tool import (
    BoundedReactRetrievalInput,
    BoundedReactRetrievalTool,
)
from app.services.agent.tools.candidate_ranking_tool import (
    CandidateRankingInput,
    CandidateRankingTool,
)
from app.services.agent.tools.chat_answer_tool import ChatAnswerInput, ChatAnswerTool
from app.services.agent.tools.tool_executor_tool import ToolExecutorInput, ToolExecutorTool


async def execute_retrieval_stage(
    session: Session,
    *,
    query: str,
    query_plan: dict[str, Any],
    tool_plan: dict[str, Any],
    evidence_id: str,
) -> dict[str, Any]:
    output = await ToolExecutorTool(session).run(
        ToolExecutorInput(
            query=query,
            query_plan=query_plan,
            tool_plan=tool_plan,
            evidence_id=evidence_id,
        )
    )
    return {
        "retrieval_summary": {
            "stage": "tool_executor",
            "planned_groups": [group["name"] for group in (tool_plan or {}).get("parallel_groups", [])],
            "staged_count": len(output.staged_results),
            "online_count": len(output.online_results),
        },
        "retrieval_evidence": output.evidence,
        "staged_results": output.staged_results,
        "online_results": output.online_results,
    }


async def bounded_react_retrieval_stage(
    session: Session,
    *,
    query: str,
    query_plan: dict[str, Any],
    tool_plan: dict[str, Any],
    staged_results: list,
    online_results: list,
    retrieval_evidence: list[dict[str, object]],
    evidence_id: str,
) -> dict[str, Any]:
    output = await BoundedReactRetrievalTool(session).run(
        BoundedReactRetrievalInput(
            query=query,
            query_plan=query_plan,
            tool_plan=tool_plan,
            staged_results=staged_results,
            online_results=online_results,
            retrieval_evidence=retrieval_evidence,
            evidence_id=evidence_id,
        )
    )
    return {
        "retrieval_summary": {
            "stage": "bounded_react_retrieval",
            "strategy": output.react_summary.get("strategy"),
            "react_triggered": output.react_summary.get("triggered"),
            "react_round_count": output.react_summary.get("round_count"),
            "react_stop_reason": output.react_summary.get("stop_reason"),
            "staged_count": len(output.staged_results),
            "online_count": len(output.online_results),
        },
        "retrieval_evidence": output.retrieval_evidence,
        "staged_results": output.staged_results,
        "online_results": output.online_results,
        "react_summary": output.react_summary,
        "react_trace": output.react_trace,
    }


async def rank_candidates_stage(
    session: Session,
    *,
    query: str,
    query_plan: dict[str, Any],
    staged_results: list,
    online_results: list,
    retrieval_evidence: list[dict[str, object]],
    llm: dict[str, Any],
    evidence_id: str,
) -> dict[str, Any]:
    output = await CandidateRankingTool(session).run(
        CandidateRankingInput(
            query=query,
            query_plan=dict(query_plan or {}),
            staged_results=staged_results,
            online_results=online_results,
            prior_evidence=retrieval_evidence,
            llm_available=bool(llm.get("available")),
            provider=str(llm.get("provider") or ""),
            api_key=str(llm.get("api_key") or ""),
            base_url=str(llm.get("base_url") or ""),
            model=str(llm.get("model") or ""),
            evidence_id=evidence_id,
        )
    )
    return {
        "ranking_summary": {
            "strategy": CandidateRankingTool.name,
            "match_count": output.match_count,
            "validator_status": output.validator_status,
            "semantic_judge_status": output.semantic_judge_status,
        },
        "query_plan": output.query_plan,
        "retrieval_evidence": output.evidence,
        "matches": output.matches,
    }


async def generate_chat_answer_stage(
    *,
    query: str,
    query_plan: dict[str, Any],
    matches: list,
    retrieval_evidence: list[dict[str, object]],
    history: list,
    llm: dict[str, Any],
    evidence_id: str,
) -> dict[str, Any]:
    output = await ChatAnswerTool().run(
        ChatAnswerInput(
            query=query,
            query_plan=dict(query_plan or {}),
            matches=matches,
            retrieval_evidence=retrieval_evidence,
            llm_available=bool(llm.get("available")),
            provider=str(llm.get("provider") or ""),
            api_key=str(llm.get("api_key") or ""),
            base_url=str(llm.get("base_url") or ""),
            model=str(llm.get("model") or ""),
            history=history,
            evidence_id=evidence_id,
        )
    )
    return {
        "response": output.response,
        "answer_summary": {
            "match_count": output.match_count,
            "used_llm": output.used_llm,
        },
    }
