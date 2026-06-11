# 中文注释：封装 Agent 服务层的Agent 服务层数据结构逻辑。

from collections.abc import KeysView
from typing import Literal

from pydantic import BaseModel, Field
from pydantic.config import ConfigDict


class AgentHistoryItem(BaseModel):
    role: Literal["user", "assistant"]
    text: str = Field(min_length=1, max_length=4000)


class AgentChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    history: list[AgentHistoryItem] = Field(default_factory=list)
    provider_override: str | None = Field(default=None, max_length=64)
    model_override: str | None = Field(default=None, max_length=128)


class AgentModDetailRequest(BaseModel):
    mod_id: int
    question: str | None = Field(default=None, max_length=4000)
    history: list[AgentHistoryItem] = Field(default_factory=list)
    provider_override: str | None = Field(default=None, max_length=64)
    model_override: str | None = Field(default=None, max_length=128)


class AgentModMatch(BaseModel):
    id: int
    title: str
    translated_title_zh: str | None = None
    source: str
    game: str
    game_domain: str | None = None
    category: str | None = None
    author: str | None
    version: str | None
    url: str
    updated_at_remote: str | None
    downloads: int | None = None
    endorsements: int | None = None
    likes: int | None = None
    adult_content: bool | None = None
    score: int
    score_breakdown: dict[str, int] | None = None
    rank_reason: str | None = None
    original_summary: str | None = None
    translated_summary: str | None = None


class AgentActionCandidate(BaseModel):
    id: str
    label: str


class AgentActionPayload(BaseModel):
    expand_online_candidates: list[AgentActionCandidate] | None = None
    narrow_scope_fields: list[str] | None = None
    review_targets: list[str] | None = None
    conflict_fields: list[str] | None = None
    requires_user_confirmation: bool | None = None


class AgentAuditConclusion(BaseModel):
    used_llm: bool | None = None
    match_count: int | None = None
    consistency_risk: Literal["low", "medium", "high"] | None = None
    tool_policy_confidence: Literal["low", "medium", "high", "unknown"] | None = None
    evidence_sufficiency: Literal["insufficient", "partial", "sufficient"] | None = None
    contract_status: Literal["ok", "violated"] | None = None
    contract_violations_count: int | None = None
    requires_clarification: bool | None = None
    recommended_action: str | None = None
    recommended_action_reason: str | None = None
    expand_online_candidates: list[str] | None = None
    expand_online_candidates_detail: list[AgentActionCandidate] | None = None
    action_payload: AgentActionPayload | None = None


class AgentWebSearchEvidence(BaseModel):
    enabled: bool
    queried: bool
    tools: list[str]
    tool_statuses: dict[str, str] = Field(default_factory=dict)
    tool_result_counts: dict[str, int] = Field(default_factory=dict)
    succeeded_count: int | None = None
    skipped_count: int | None = None
    degraded_count: int | None = None
    online_result_count: int | None = None
    adaptation_triggered: bool | None = None
    trigger_reasons: list[str] | None = None


class AgentRetrievalDecisionReasonGroups(BaseModel):
    context: list[str] = Field(default_factory=list)
    memory: list[str] = Field(default_factory=list)
    web: list[str] = Field(default_factory=list)
    semantic: list[str] = Field(default_factory=list)


class AgentRetrievalDecisionEvidence(BaseModel):
    mode: Literal["local_only", "web_adaptation_only", "local_plus_web"] | str
    web_enabled: bool
    web_queried: bool
    alignment_score: float | None = None
    context_quality_score: float | None = None
    context_inherit_score: float | None = None
    semantic_anchors: list[str] | None = None
    semantic_domains: list[str] | None = None
    reasons: list[str]
    reason_groups: AgentRetrievalDecisionReasonGroups


class AgentSemanticTraceEvidence(BaseModel):
    anchors: list[str] = Field(default_factory=list)
    context_anchors: list[str] = Field(default_factory=list)
    domains: list[str] = Field(default_factory=list)
    inherited_anchor_overlap: int = 0
    memory_fragment_count: int = 0


class AgentContextSignalEvidence(BaseModel):
    source: str | None = None
    quality_score: float | None = None
    inherit_score: float | None = None
    inherit_threshold: float | None = None
    followup_score: float | None = None
    inherited: bool | None = None
    topic_shift_detected: bool | None = None
    policy_reasons: list[str] = Field(default_factory=list)


class AgentMemoryContextAlignmentEvidence(BaseModel):
    score: float
    decision: str
    reasons: list[str] = Field(default_factory=list)


class AgentAnalysisEvidenceCoverage(BaseModel):
    required_fields: list[str] = Field(default_factory=list)
    covered_fields: int = 0
    coverage_ratio: float = 0.0
    missing_fields: list[str] = Field(default_factory=list)
    field_fragments: dict[str, list[str]] = Field(default_factory=dict)


class AgentToolPolicyEvidence(BaseModel):
    score: float | None = None
    strategy: str | None = None
    known_slot_count: int | None = None
    should_clarify: bool | None = None
    online_recall_mode: str | None = None
    semantic_anchors: list[str] = Field(default_factory=list)
    semantic_domains: list[str] = Field(default_factory=list)
    expand_online_candidates: list[str] = Field(default_factory=list)
    local_tools: list[str] = Field(default_factory=list)
    online_tools: list[str] = Field(default_factory=list)
    degraded_reasons: list[str] = Field(default_factory=list)


class AgentAuditAnalysis(BaseModel):
    model_config = ConfigDict(extra="allow")
    intent: str | None = None
    confidence: float | None = None
    slots: dict[str, object] = Field(default_factory=dict)
    semantic_anchors: list[str] = Field(default_factory=list)
    semantic_domains: list[str] = Field(default_factory=list)
    evidence_id: str | None = None


class AgentAuditEvidence(BaseModel):
    model_config = ConfigDict(extra="allow")
    fragments: list[str] = Field(default_factory=list)
    memory_count: int = 0
    retrieval_count: int = 0
    conflict_count: int = 0
    conflict_fields: list[str] = Field(default_factory=list)
    hard_conflict_count: int = 0
    soft_conflict_count: int = 0
    web_search: AgentWebSearchEvidence | None = None
    retrieval_decision: AgentRetrievalDecisionEvidence | None = None
    semantic_trace: AgentSemanticTraceEvidence | None = None
    context_signal: AgentContextSignalEvidence | None = None
    memory_context_alignment: AgentMemoryContextAlignmentEvidence | None = None
    analysis_evidence_coverage: AgentAnalysisEvidenceCoverage | None = None
    tool_policy: AgentToolPolicyEvidence | None = None
    action_evidence_consistent: bool | None = None
    action_evidence_consistency_reason: str | None = None
    audit_contract_passed: bool | None = None
    audit_contract_violations: list[str] = Field(default_factory=list)


class AgentAudit(BaseModel):
    analysis: AgentAuditAnalysis = Field(default_factory=AgentAuditAnalysis)
    evidence: AgentAuditEvidence = Field(default_factory=AgentAuditEvidence)
    conclusion: AgentAuditConclusion = Field(default_factory=AgentAuditConclusion)

    def __getitem__(self, key: str) -> object:
        return self.model_dump(mode="python")[key]

    def keys(self) -> KeysView[str]:
        return self.model_dump(mode="python").keys()


class AgentChatResponse(BaseModel):
    answer: str
    used_llm: bool
    matches: list[AgentModMatch]
    response_cards: dict[str, list[str]] | None = None
    understanding: dict[str, object] | None = None
    memory_evidence: list[dict[str, object]] | None = None
    retrieval_evidence: list[dict[str, object]] | None = None
    audit: AgentAudit = Field(default_factory=AgentAudit)
    evidence_id: str | None = None
    clarifying_question: str | None = None
    llm_provider: str | None = None
    llm_model: str | None = None


class AgentConversationMessage(BaseModel):
    id: str
    role: Literal["user", "assistant", "separator"]
    text: str
    session_id: str
    created_at: str | None = None
    matches: list[AgentModMatch] | None = None
    response_cards: dict[str, list[str]] | None = None
    audit: AgentAudit | None = None
    llm_provider: str | None = None
    llm_model: str | None = None


class AgentConversationState(BaseModel):
    messages: list[AgentConversationMessage]
    active_session_id: str


class AgentConversationStateSaveRequest(BaseModel):
    messages: list[AgentConversationMessage]
    active_session_id: str
    client_updated_at: str | None = None


class AgentConversationNewResponse(BaseModel):
    session_id: str
