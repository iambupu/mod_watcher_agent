from fastapi import Request
from sqlmodel import Session

from app.models.mod import Mod
from app.services.agent.answer_service import (
    AgentAnswerService,
    build_detail_fallback,
    build_fallback_answer,
)
from app.services.agent.llm_config_service import get_llm_config
from app.services.agent.mod_search_service import build_summary_map
from app.services.agent.query_planner import (
    build_database_schema_text,
    build_fallback_query_plan,
    load_slot_options,
    normalize_query_plan,
    plan_query_with_llm,
)
from app.services.agent.rate_limiter import build_rate_limit_key, enforce_rate_limit
from app.services.agent.response_builder import build_response_cards
from app.services.agent.schemas import (
    AgentChatRequest,
    AgentChatResponse,
    AgentModDetailRequest,
    AgentModMatch,
)
from app.services.agent.search_orchestrator import AgentSearchOrchestrator
from app.services.llm_provider_config import provider_has_credentials
from app.services.settings_service import SettingsService


class AgentService:
    def __init__(self, session: Session):
        """初始化实例并保存运行所需的依赖。"""
        self.session = session

    async def chat(self, body: AgentChatRequest, request: Request) -> AgentChatResponse:
        """处理当前模块的业务逻辑并返回结果。"""
        query = body.message.strip()
        if not query:
            return AgentChatResponse(
                answer="请输入要查询的内容。",
                used_llm=False,
                matches=[],
                response_cards={
                    "understanding": ["请先输入你的查询需求。"],
                    "filters": [],
                    "results": ["当前没有可用结果。"],
                    "next_steps": ["例如：最近更新的 Stellar Blade 画面 Mod。"],
                },
            )

        settings = SettingsService(self.session)
        await enforce_rate_limit(build_rate_limit_key(request, settings))
        provider, api_key, base_url, model = get_llm_config(
            settings,
            provider_override=body.provider_override,
            model_override=body.model_override,
        )
        llm_available = provider_has_credentials(provider, api_key)

        slot_options = load_slot_options(self.session)
        raw_query_plan = None
        if llm_available:
            raw_query_plan = await plan_query_with_llm(
                query=query,
                provider=provider,
                api_key=api_key,
                base_url=base_url,
                model=model,
                history=body.history,
                database_schema=build_database_schema_text(self.session),
                slot_options=slot_options,
            )
        if raw_query_plan is None:
            raw_query_plan = build_fallback_query_plan(query)

        query_plan = normalize_query_plan(raw_query_plan, query, slot_options)
        matches = await AgentSearchOrchestrator(self.session).find_matches(
            query=query,
            query_plan=query_plan,
            llm_available=llm_available,
            provider=provider,
            api_key=api_key,
            base_url=base_url,
            model=model,
        )
        if not matches:
            return AgentChatResponse(
                answer="没有找到明确匹配。我可以先给你“最近更新”列表，或按游戏名/作者名筛选。比如：最近更新的 Skyrim Mod。",
                used_llm=False,
                matches=[],
                response_cards=build_response_cards(query=query, query_plan=query_plan, matches=[]),
            )
        fallback_answer = build_fallback_answer(matches)
        if not llm_available:
            return AgentChatResponse(
                answer=fallback_answer,
                used_llm=False,
                matches=matches,
                response_cards=build_response_cards(query=query, query_plan=query_plan, matches=matches),
            )

        answer_service = AgentAnswerService()
        content = await answer_service.answer_matches(
            query=query,
            matches=matches,
            provider=provider,
            api_key=api_key,
            base_url=base_url,
            model=model,
            history=body.history,
        )
        if _is_empty_or_error_content(content):
            return AgentChatResponse(
                answer=fallback_answer,
                used_llm=False,
                matches=matches,
                response_cards=build_response_cards(query=query, query_plan=query_plan, matches=matches),
            )
        try:
            next_steps = await answer_service.suggest_next_steps(
                query=query,
                answer=content.strip(),
                matches=matches,
                provider=provider,
                api_key=api_key,
                base_url=base_url,
                model=model,
            )
        except Exception:
            next_steps = []
        return AgentChatResponse(
            answer=content.strip(),
            used_llm=True,
            matches=matches,
            response_cards=build_response_cards(
                query=query,
                query_plan=query_plan,
                matches=matches,
                next_steps=next_steps or None,
            ),
            llm_provider=provider,
            llm_model=model,
        )

    async def ask_mod_detail(self, body: AgentModDetailRequest, request: Request) -> AgentChatResponse:
        """处理当前模块的业务逻辑并返回结果。"""
        mod = self.session.get(Mod, body.mod_id)
        if mod is None:
            return AgentChatResponse(
                answer="未找到该 Mod。",
                used_llm=False,
                matches=[],
                response_cards={
                    "understanding": ["未找到对应 Mod。"],
                    "filters": [],
                    "results": ["当前没有可展示的详情结果。"],
                    "next_steps": ["请返回结果列表重新选择一个 Mod。"],
                },
            )

        summary_by_mod = build_summary_map(self.session, [body.mod_id])
        match = _match_from_mod(mod, 1, summary_by_mod)
        fallback = build_detail_fallback(mod, match)

        settings = SettingsService(self.session)
        await enforce_rate_limit(build_rate_limit_key(request, settings))
        provider, api_key, base_url, model = get_llm_config(
            settings,
            provider_override=body.provider_override,
            model_override=body.model_override,
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
            question=(body.question or "").strip()
            or "请详细介绍这个 Mod 的特点、适用人群、安装关注点和潜在风险。",
            provider=provider,
            api_key=api_key,
            base_url=base_url,
            model=model,
            history=body.history,
        )
        if _is_empty_or_error_content(content):
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

def _match_from_mod(mod: Mod, score: int, summary_by_mod: dict[int, str]) -> AgentModMatch:
    """内部辅助函数，用于拆分上层流程中的局部规则。"""
    return AgentModMatch(
        id=mod.id or 0,
        title=mod.title,
        source=mod.source,
        game=mod.game,
        game_domain=mod.game_domain,
        category=mod.category,
        author=mod.author,
        version=mod.version,
        url=mod.url,
        updated_at_remote=mod.updated_at_remote,
        downloads=mod.downloads,
        endorsements=mod.endorsements,
        likes=mod.likes,
        adult_content=mod.adult_content,
        score=score,
        original_summary=mod.original_summary,
        translated_summary=summary_by_mod.get(mod.id or 0),
    )


def _detail_response_cards(mod: Mod, generated: bool) -> dict[str, list[str]]:
    """内部辅助函数，用于拆分上层流程中的局部规则。"""
    return {
        "understanding": [f"你希望我详细解析：{mod.title}"],
        "filters": [f"来源：{mod.source}", f"游戏：{mod.game}"],
        "results": [
            f"已{'生成' if generated else '提供'}该 Mod 的{'详细解析' if generated else '详细信息'}（{mod.title}）。"
        ],
        "next_steps": [
            "你可以继续问：安装步骤、前置依赖、同类替代 Mod。"
            if generated
            else "你可以继续问：兼容性、安装风险、适合人群。"
        ],
    }


def _is_empty_or_error_content(content: str) -> bool:
    """判断内部条件是否成立。"""
    normalized = str(content or "").strip().lower()
    return not normalized or normalized in {
        "failed to fetch",
        "fetch failed",
        "network error",
        "networkerror when attempting to fetch resource.",
    }
