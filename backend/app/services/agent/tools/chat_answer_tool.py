import logging
from dataclasses import dataclass, field
from typing import Any

from app.services.agent.schemas import AgentChatResponse, AgentHistoryItem, AgentModMatch
from app.services.agent.tools.answer_generation_tool import (
    AnswerGenerationInput,
    AnswerGenerationTool,
)
from app.services.agent.tools.response_card_builder_tool import (
    ResponseCardBuilderInput,
    ResponseCardBuilderTool,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ChatAnswerInput:
    query: str
    query_plan: dict[str, Any]
    matches: list[AgentModMatch] = field(default_factory=list)
    retrieval_evidence: list[dict[str, object]] = field(default_factory=list)
    llm_available: bool = False
    provider: str = ""
    api_key: str = ""
    base_url: str = ""
    model: str = ""
    history: list[AgentHistoryItem] = field(default_factory=list)
    evidence_id: str = ""


@dataclass(frozen=True)
class ChatAnswerOutput:
    response: AgentChatResponse
    used_llm: bool
    match_count: int


class ChatAnswerTool:
    """把候选结果、检索证据和 LLM 配置组合成最终聊天响应。"""

    name = "chat_answer"

    async def run(self, tool_input: ChatAnswerInput) -> ChatAnswerOutput:
        # 自然语言回答和结构化 response cards 分开生成，保持前端展示契约稳定。
        answer_output = await AnswerGenerationTool().run(
            AnswerGenerationInput(
                query=tool_input.query,
                query_plan=tool_input.query_plan,
                matches=tool_input.matches,
                llm_available=tool_input.llm_available,
                provider=tool_input.provider,
                api_key=tool_input.api_key,
                base_url=tool_input.base_url,
                model=tool_input.model,
                history=tool_input.history,
                evidence_id=tool_input.evidence_id,
            )
        )
        response_cards = ResponseCardBuilderTool().run(
            ResponseCardBuilderInput(
                query=tool_input.query,
                query_plan=tool_input.query_plan,
                matches=tool_input.matches,
                next_steps=answer_output.next_steps or None,
                evidence_id=tool_input.evidence_id,
            )
        ).cards
        response = AgentChatResponse(
            answer=answer_output.answer,
            used_llm=answer_output.used_llm,
            matches=tool_input.matches,
            response_cards=response_cards,
            retrieval_evidence=tool_input.retrieval_evidence,
            evidence_id=tool_input.evidence_id,
            llm_provider=tool_input.provider if answer_output.used_llm else None,
            llm_model=tool_input.model if answer_output.used_llm else None,
        )
        logger.info(
            "agent.tool name=chat_answer status=succeeded matches=%s used_llm=%s evidence_id=%s",
            len(tool_input.matches),
            answer_output.used_llm,
            tool_input.evidence_id,
        )
        return ChatAnswerOutput(
            response=response,
            used_llm=answer_output.used_llm,
            match_count=len(tool_input.matches),
        )
