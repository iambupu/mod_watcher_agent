from dataclasses import dataclass, field
from typing import Any

from sqlmodel import Session

from app.services.agent.judging.candidate_semantic_judge import (
    CandidateSemanticJudgeInput,
    CandidateSemanticJudgeTool,
    build_candidate_semantic_judge_evidence,
)
from app.services.agent.planning.open_discovery_policy import (
    is_open_discovery_plan,
    judge_candidate_pool_limit,
)
from app.services.agent.planning.query_plan_contract import semantic_strategy
from app.services.agent.search_types import SearchPlan
from app.services.agent.tools.candidate_recovery_tool import (
    CandidateRecoveryInput,
    CandidateRecoveryTool,
)
from app.services.agent.tools.llm_candidate_validator_tool import (
    LlmCandidateValidatorInput,
    LlmCandidateValidatorOutput,
    LlmCandidateValidatorTool,
)
from app.services.agent.tools.match_materializer_tool import (
    MatchMaterializerInput,
    MatchMaterializerTool,
)
from app.services.agent.tools.result_fusion_ranker_tool import (
    ResultFusionRankerInput,
    ResultFusionRankerTool,
)


@dataclass(frozen=True)
class CandidateRankingInput:
    query: str
    query_plan: dict[str, Any]
    staged_results: list = field(default_factory=list)
    online_results: list = field(default_factory=list)
    prior_evidence: list[dict[str, object]] = field(default_factory=list)
    llm_available: bool = False
    provider: str = ""
    api_key: str = ""
    base_url: str = ""
    model: str = ""
    evidence_id: str = ""


@dataclass(frozen=True)
class CandidateRankingOutput:
    matches: list
    evidence: list[dict[str, object]]
    match_count: int
    validator_status: str
    query_plan: dict[str, Any] = field(default_factory=dict)
    semantic_judge_status: str = "skipped"


class CandidateRankingTool:
    """融合多路候选，物化为前端结果，并在需要时做 LLM 校验和恢复检索。"""

    name = "candidate_ranking"

    def __init__(self, session: Session, *, validator=None, semantic_judge=None):
        self.session = session
        self.validator = validator
        self.semantic_judge = semantic_judge

    async def run(self, tool_input: CandidateRankingInput) -> CandidateRankingOutput:
        query_plan = dict(tool_input.query_plan or {})
        evidence_id = tool_input.evidence_id or str(query_plan.get("evidence_id") or "").strip()
        plan = SearchPlan.from_query_plan(query_plan)
        open_discovery_with_llm = bool(tool_input.llm_available and is_open_discovery_plan(query_plan))
        semantic_judge_with_llm = bool(tool_input.llm_available and _should_use_semantic_judge(query_plan))
        materialize_limit = (
            judge_candidate_pool_limit(query_plan, display_limit=plan.limit)
            if open_discovery_with_llm
            else plan.limit
        )
        # fusion 只处理 SearchResult 排名和去重；物化后才进入前端响应模型。
        fusion_output = ResultFusionRankerTool().run(
            ResultFusionRankerInput(
                query=tool_input.query,
                query_plan=query_plan,
                plan=plan,
                staged_results=tool_input.staged_results,
                online_results=tool_input.online_results,
                evidence_id=evidence_id,
                apply_distinctive_filter=not open_discovery_with_llm,
            )
        )
        matches = MatchMaterializerTool(self.session).run(
            MatchMaterializerInput(results=fusion_output.results, limit=materialize_limit, evidence_id=evidence_id)
        ).matches
        # 旧 validator 自己会跳过开放发现，避免在 Candidate Semantic Judge 前误删候选。
        validator_output = await self._validate(tool_input, query_plan, matches, evidence_id)
        matches = validator_output.matches
        use_semantic_judge = bool(semantic_judge_with_llm and matches)
        semantic_judge_evidence: list[dict[str, object]] = []
        semantic_judge_status = "skipped"
        semantic_judge_no_direct_match = False
        if use_semantic_judge:
            # 开放发现的智能点放在候选裁判：检索阶段尽量别误杀，排序阶段再让 LLM 判断相关性。
            judge_output, matches = await self._judge_open_discovery(
                tool_input=tool_input,
                query_plan=query_plan,
                matches=matches,
                prior_evidence=[*tool_input.prior_evidence, *fusion_output.evidence],
                evidence_id=evidence_id,
            )
            matches = matches[: plan.limit]
            semantic_judge_no_direct_match = _requires_direct_match_only(query_plan) and not any(
                item.fit_type == "direct_match" for item in judge_output.judgements
            )
            semantic_judge_status = judge_output.status
            semantic_judge_evidence = [
                build_candidate_semantic_judge_evidence(
                    judge_output,
                    input_count=len(validator_output.matches),
                    output_count=len(matches),
                    evidence_id=evidence_id,
                )
            ]
            query_plan["_agent_candidate_semantic_judge"] = _judge_summary(judge_output)
        recovery_evidence: list[dict[str, object]] = []
        if (
            not matches
            and not semantic_judge_no_direct_match
            and not _requires_direct_match_only(query_plan)
        ):
            # 校验后为空时才触发恢复检索，避免正常结果被额外搜索扰动排序。
            recovery_output = await CandidateRecoveryTool(self.session).run(
                CandidateRecoveryInput(
                    query=tool_input.query,
                    search_query=tool_input.query,
                    query_plan=query_plan,
                    plan=plan,
                    evidence_id=evidence_id,
                )
            )
            matches = recovery_output.matches
            recovery_evidence = recovery_output.evidence
        evidence = [
            *tool_input.prior_evidence,
            *fusion_output.evidence,
            *semantic_judge_evidence,
            *recovery_evidence,
        ]
        return CandidateRankingOutput(
            matches=matches,
            evidence=evidence,
            match_count=len(matches),
            validator_status=validator_output.status,
            query_plan=query_plan,
            semantic_judge_status=semantic_judge_status,
        )

    async def _validate(
        self,
        tool_input: CandidateRankingInput,
        query_plan: dict[str, Any],
        matches: list,
        evidence_id: str,
    ) -> LlmCandidateValidatorOutput:
        validator_tool = (
            LlmCandidateValidatorTool(validator=self.validator)
            if self.validator is not None
            else LlmCandidateValidatorTool()
        )
        return await validator_tool.run(
            LlmCandidateValidatorInput(
                query=tool_input.query,
                matches=matches,
                llm_available=tool_input.llm_available,
                provider=tool_input.provider,
                api_key=tool_input.api_key,
                base_url=tool_input.base_url,
                model=tool_input.model,
                query_plan=query_plan,
                evidence_id=evidence_id,
            )
        )

    async def _judge_open_discovery(
        self,
        *,
        tool_input: CandidateRankingInput,
        query_plan: dict[str, Any],
        matches: list,
        prior_evidence: list[dict[str, object]],
        evidence_id: str,
    ):
        judge_tool = CandidateSemanticJudgeTool(judge=self.semantic_judge)
        judge_output = await judge_tool.run(
            CandidateSemanticJudgeInput(
                query=tool_input.query,
                semantic_strategy=semantic_strategy(query_plan),
                candidates=matches,
                retrieval_evidence=prior_evidence,
                llm_available=tool_input.llm_available,
                provider=tool_input.provider,
                api_key=tool_input.api_key,
                base_url=tool_input.base_url,
                model=tool_input.model,
                evidence_id=evidence_id,
            )
        )
        return judge_output, _apply_semantic_judgements(matches, judge_output, query_plan=query_plan)


def _should_use_semantic_judge(query_plan: dict[str, Any]) -> bool:
    if is_open_discovery_plan(query_plan):
        return True
    strategy = semantic_strategy(query_plan)
    if not strategy:
        return False
    contract_fields = (
        "direct_match_definition",
        "support_context_definition",
        "reject_as_primary",
        "answer_policy",
    )
    return any(bool(strategy.get(field)) for field in contract_fields)


def _apply_semantic_judgements(matches: list, judge_output, *, query_plan: dict[str, Any] | None = None) -> list:
    judgement_by_id = {item.candidate_id: item for item in judge_output.judgements}
    rejected_ids = {item.candidate_id for item in judge_output.rejected}
    rejected_ids.update(item.candidate_id for item in judge_output.judgements if item.relevance == "reject")
    rejected_ids.update(item.candidate_id for item in judge_output.judgements if item.fit_type == "off_scope")
    direct_match_only = _requires_direct_match_only(query_plan)
    direct_ids = {item.candidate_id for item in judge_output.judgements if item.fit_type == "direct_match"}
    if direct_match_only and direct_ids:
        rejected_ids.update(item.candidate_id for item in judge_output.judgements if item.fit_type != "direct_match")
    if direct_match_only and not direct_ids:
        return []
    ranked = []
    for index, match in enumerate(matches):
        match_id = getattr(match, "id", None)
        judgement = judgement_by_id.get(match_id)
        if match_id in rejected_ids:
            continue
        ranked.append((_judgement_sort_key(judgement, index), _with_judge_reason(match, judgement)))
    ranked.sort(key=lambda item: item[0])
    return [item[1] for item in ranked]


def _requires_direct_match_only(query_plan: dict[str, Any] | None) -> bool:
    if not isinstance(query_plan, dict):
        return False
    strategy = query_plan.get("_agent_semantic_strategy")
    if not isinstance(strategy, dict):
        return False
    policy = strategy.get("answer_policy")
    if not isinstance(policy, dict):
        return False
    return str(policy.get("main_results") or "").strip().lower() in {"only_direct_match", "direct_match_only"}


def _judgement_sort_key(judgement, index: int) -> tuple[int, int, int]:
    order = {"high": 0, "medium": 1, "low": 2, "reject": 3}
    if judgement is None:
        return (2, 2, index)
    fit_order = {"direct_match": 0, "support_context": 1, "uncertain": 2, "off_scope": 3}
    return (fit_order.get(judgement.fit_type, 2), order.get(judgement.relevance, 2), index)


def _with_judge_reason(match, judgement):
    if judgement is None:
        return match
    group_label = _group_label(judgement.group)
    fit_label = _fit_type_label(judgement.fit_type)
    reason = f"语义裁判：{judgement.relevance} / {fit_label} / {group_label}"
    category_label = _category_compatibility_label(getattr(judgement, "category_semantic_compatibility", ""))
    if category_label:
        reason = f"{reason} / 分类语义：{category_label}"
    if judgement.reason:
        reason = f"{reason}；{judgement.reason}"
    category_reason = str(getattr(judgement, "category_compatibility_reason", "") or "").strip()
    if category_reason:
        reason = f"{reason}；分类依据：{category_reason}"
    if judgement.violations:
        reason = f"{reason}；违例：{', '.join(judgement.violations[:3])}"
    previous = str(getattr(match, "rank_reason", "") or "").strip()
    rank_reason = f"{reason}；{previous}" if previous else reason
    return match.model_copy(update={"rank_reason": rank_reason[:500]})


def _group_label(group: str) -> str:
    labels = {
        "core_gameplay": "核心玩法",
        "visual_support": "外观配套",
        "follower_or_npc": "随从/NPC",
        "requirement_or_patch": "前置/补丁",
        "related_addon": "相关扩展",
        "other_related": "相关候选",
        "off_topic": "偏离主题",
    }
    return labels.get(str(group), str(group))


def _fit_type_label(fit_type: str) -> str:
    labels = {
        "direct_match": "直接命中",
        "support_context": "辅助上下文",
        "off_scope": "偏离主目标",
        "uncertain": "证据不足",
    }
    return labels.get(str(fit_type), str(fit_type))


def _category_compatibility_label(value: str) -> str:
    labels = {
        "compatible": "兼容",
        "ambiguous": "不确定",
        "incompatible": "不兼容",
        "not_applicable": "",
    }
    return labels.get(str(value), "")


def _judge_summary(judge_output) -> dict[str, object]:
    fit_counts = {"direct_match": 0, "support_context": 0, "off_scope": 0, "uncertain": 0}
    category_compatibility_counts = {
        "compatible": 0,
        "ambiguous": 0,
        "incompatible": 0,
        "not_applicable": 0,
    }
    judgements = []
    for item in judge_output.judgements:
        fit_counts[item.fit_type] = fit_counts.get(item.fit_type, 0) + 1
        category_compatibility_counts[item.category_semantic_compatibility] = (
            category_compatibility_counts.get(item.category_semantic_compatibility, 0) + 1
        )
        judgements.append(
            {
                "candidate_id": item.candidate_id,
                "relevance": item.relevance,
                "fit_type": item.fit_type,
                "group": item.group,
                "category_semantic_compatibility": item.category_semantic_compatibility,
                "category_compatibility_reason": item.category_compatibility_reason,
                "reason": item.reason,
                "evidence": item.evidence,
                "violations": item.violations,
            }
        )
    return {
        "status": judge_output.status,
        "used_llm": judge_output.used_llm,
        "fit_counts": fit_counts,
        "category_compatibility_counts": category_compatibility_counts,
        "judgements": judgements,
        "groups": [
            {
                "name": group.name,
                "label": group.label or _group_label(group.name),
                "candidate_ids": group.candidate_ids,
                "reason": group.reason,
            }
            for group in judge_output.groups
        ],
        "gaps": judge_output.gaps,
        "fallback_reason": judge_output.fallback_reason,
    }
