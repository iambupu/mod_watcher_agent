from dataclasses import dataclass, field

from fastapi import Request
from sqlmodel import Session

from app.models.mod import Mod
from app.services.agent.answer_service import AgentAnswerService, build_detail_fallback
from app.services.agent.llm_config_service import get_llm_config
from app.services.agent.mod_search_service import build_summary_map
from app.services.agent.rate_limiter import build_rate_limit_key, enforce_rate_limit
from app.services.agent.response_builder import (
    build_detail_response_cards,
    build_status_response_cards,
    match_from_mod,
)
from app.services.agent.schemas import AgentChatResponse, AgentHistoryItem
from app.services.agent.tools.llm_output import is_empty_or_error_content
from app.services.llm_provider_config import provider_has_credentials
from app.services.settings_service import SettingsService


@dataclass(frozen=True)
class ModDetailAnswerInput:
    mod_id: int
    question: str | None = None
    history: list[AgentHistoryItem] = field(default_factory=list)
    provider_override: str | None = None
    model_override: str | None = None
    request: Request | None = None


class ModDetailAnswerTool:
    """生成指定 MOD 的详情问答响应，不走普通搜索排序链路。"""

    name = "mod_detail_answer"

    def __init__(self, session: Session):
        self.session = session

    async def run(self, tool_input: ModDetailAnswerInput) -> AgentChatResponse:
        mod = self.session.get(Mod, tool_input.mod_id)
        if mod is None:
            return AgentChatResponse(
                answer="未找到该 Mod。",
                used_llm=False,
                matches=[],
                response_cards=build_status_response_cards(
                    analysis=f"任务分析：请求查看 Mod #{tool_input.mod_id} 的详情。",
                    evidence="证据：本地数据库未找到对应 Mod。",
                    conclusion="结论：当前无法生成可靠详情。",
                    understanding="未找到对应 Mod。",
                    result="当前没有可展示的详情结果。",
                    next_step="我想回到结果列表重新选一个 Mod",
                ),
            )

        summary_by_mod = build_summary_map(self.session, [tool_input.mod_id])
        match = match_from_mod(mod, 1, summary_by_mod)
        fallback = build_detail_fallback(mod, match)

        settings = SettingsService(self.session)
        if tool_input.request is not None:
            await enforce_rate_limit(build_rate_limit_key(tool_input.request, settings))
        provider, api_key, base_url, model = get_llm_config(
            settings,
            provider_override=tool_input.provider_override,
            model_override=tool_input.model_override,
        )
        llm_available = provider_has_credentials(provider, api_key)
        if not llm_available:
            return AgentChatResponse(
                answer=fallback,
                used_llm=False,
                matches=[match],
                response_cards=_detail_response_cards(mod, generated=False),
            )

        content = await AgentAnswerService().answer_detail(
            mod=mod,
            match=match,
            question=(tool_input.question or "").strip()
            or "请详细介绍这个 Mod 的特点、适用人群、安装关注点和潜在风险。",
            provider=provider,
            api_key=api_key,
            base_url=base_url,
            model=model,
            history=tool_input.history,
        )
        if is_empty_or_error_content(content):
            return AgentChatResponse(
                answer=fallback,
                used_llm=False,
                matches=[match],
                response_cards=_detail_response_cards(mod, generated=False),
            )
        return AgentChatResponse(
            answer=content.strip(),
            used_llm=True,
            matches=[match],
            response_cards=_detail_response_cards(mod, generated=True),
            llm_provider=provider,
            llm_model=model,
        )


def _detail_response_cards(mod: Mod, generated: bool) -> dict[str, list[str]]:
    return build_detail_response_cards(
        title=mod.title,
        source=mod.source,
        game=mod.game,
        generated=generated,
    )
