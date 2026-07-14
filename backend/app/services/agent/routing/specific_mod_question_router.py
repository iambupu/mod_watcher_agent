import json
import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from sqlalchemy import func, or_
from sqlmodel import Session, select

from app.models.mod import Mod
from app.services.agent.llm_config_service import get_llm_config
from app.services.agent.routing.question_policy import has_specific_mod_question_marker
from app.services.agent.schemas import AgentHistoryItem
from app.services.llm_client import LLMClient, create_llm_client
from app.services.llm_provider_config import provider_has_credentials
from app.services.settings_service import SettingsService
from app.utils.json import json_object_from_text

logger = logging.getLogger(__name__)
SPECIFIC_MOD_ROUTER_TIMEOUT_SECONDS = 12.0

RouteKind = Literal["mod_detail", "search"]
ReviewerCallable = Callable[
    [str, list["SpecificModCandidate"]],
    Awaitable[dict[str, Any]],
]
ClientFactory = Callable[[str, str, str | None], LLMClient]


@dataclass(frozen=True)
class SpecificModCandidate:
    mod_id: int
    title: str
    source: str = ""
    game: str = ""
    category: str = ""
    summary: str = ""


@dataclass(frozen=True)
class SpecificModRouteResult:
    route: RouteKind = "search"
    mod_id: int | None = None
    confidence: float = 0.0
    reason: str = ""
    used_llm: bool = False
    candidate_count: int = 0


@dataclass(frozen=True)
class SpecificModRouteInput:
    message: str
    history: list[AgentHistoryItem] = field(default_factory=list)
    provider_override: str | None = None
    model_override: str | None = None


class SpecificModQuestionRouter:
    """Route ambiguous chat turns between a specific Mod detail question and broad search."""

    def __init__(
        self,
        session: Session,
        *,
        reviewer: ReviewerCallable | None = None,
        client_factory: ClientFactory = create_llm_client,
    ):
        self.session = session
        self.reviewer = reviewer
        self.client_factory = client_factory

    async def route(self, route_input: SpecificModRouteInput) -> SpecificModRouteResult:
        message = str(route_input.message or "").strip()
        if not _should_ask_llm(message, route_input.history):
            return SpecificModRouteResult()
        candidates = _candidate_mods(self.session, message, route_input.history)
        if not candidates:
            return SpecificModRouteResult(candidate_count=len(candidates))

        raw: dict[str, Any] | None = None
        try:
            if self.reviewer is not None:
                raw = await self.reviewer(message, candidates)
            else:
                raw = await self._ask_llm(route_input, candidates)
        except Exception as exc:
            logger.warning(
                "agent.routing specific_mod status=degraded reason=%s candidates=%s",
                type(exc).__name__,
                len(candidates),
            )
            return SpecificModRouteResult(
                route="search",
                confidence=0.0,
                reason=f"router_degraded:{type(exc).__name__}",
                used_llm=False,
                candidate_count=len(candidates),
            )
        result = _coerce_route_result(raw, candidates)
        logger.info(
            "agent.routing specific_mod status=%s used_llm=%s confidence=%.3f candidates=%s mod_id=%s",
            result.route,
            result.used_llm,
            result.confidence,
            result.candidate_count,
            result.mod_id,
        )
        return result

    async def _ask_llm(
        self,
        route_input: SpecificModRouteInput,
        candidates: list[SpecificModCandidate],
    ) -> dict[str, Any] | None:
        settings = SettingsService(self.session)
        provider, api_key, base_url, model = get_llm_config(
            settings,
            provider_override=route_input.provider_override,
            model_override=route_input.model_override,
        )
        if not provider_has_credentials(provider, api_key):
            return None
        prompt = _build_route_prompt(route_input.message, route_input.history, candidates)
        client = self.client_factory(provider, api_key, base_url)
        content = await client.chat(
            prompt,
            model=model,
            max_tokens=260,
            request_timeout=SPECIFIC_MOD_ROUTER_TIMEOUT_SECONDS,
        )
        payload = json_object_from_text(content)
        if not isinstance(payload, dict):
            return None
        payload["used_llm"] = True
        return payload


def _candidate_mods(
    session: Session,
    message: str,
    history: list[AgentHistoryItem],
) -> list[SpecificModCandidate]:
    if not hasattr(session, "exec"):
        return []
    mods: list[Mod] = []
    seen_ids: set[int] = set()
    for title in _history_titles(history):
        mod = _mod_by_exact_title(session, title)
        if mod is not None and mod.id is not None and mod.id not in seen_ids:
            seen_ids.add(mod.id)
            mods.append(mod)
    for mod in _mods_by_message_tokens(session, message):
        if mod.id is not None and mod.id not in seen_ids:
            seen_ids.add(mod.id)
            mods.append(mod)
    return [_candidate_from_mod(mod) for mod in mods[:12]]


def _mod_by_exact_title(session: Session, title: str) -> Mod | None:
    normalized = _normalize(title)
    if not normalized:
        return None
    statement = (
        select(Mod)
        .where(
            (func.lower(func.trim(Mod.title)) == normalized)
            | (func.lower(func.trim(func.coalesce(Mod.translated_title_zh, ""))) == normalized)
        )
        .order_by(Mod.ignored.asc(), Mod.id.desc())
        .limit(1)
    )
    return session.exec(statement).first()


def _mods_by_message_tokens(session: Session, message: str) -> list[Mod]:
    tokens = _distinctive_tokens(message)
    if not tokens:
        return []
    conditions = []
    for token in tokens[:6]:
        like_value = f"%{token}%"
        conditions.append(Mod.title.ilike(like_value))
        conditions.append(Mod.translated_title_zh.ilike(like_value))
    statement = (
        select(Mod)
        .where(or_(*conditions))
        .order_by(Mod.ignored.asc(), Mod.id.desc())
        .limit(12)
    )
    return list(session.exec(statement).all())


def _candidate_from_mod(mod: Mod) -> SpecificModCandidate:
    return SpecificModCandidate(
        mod_id=int(mod.id or 0),
        title=mod.title,
        source=mod.source,
        game=mod.game,
        category=mod.category or "",
        summary=(mod.original_summary or "")[:260],
    )


def _history_titles(history: list[AgentHistoryItem]) -> list[str]:
    titles: list[str] = []
    for item in history:
        if item.role != "assistant":
            continue
        text = str(item.text or "")
        for match in re.finditer(r"title\s*=\s*([^;\n\r]+)", text, flags=re.IGNORECASE):
            title = _clean_title(match.group(1))
            if title and title not in titles:
                titles.append(title)
        for match in re.finditer(r"\d+\.\s+\*\*([^*\n\r]+)\*\*", text):
            title = _clean_title(match.group(1))
            if title and title not in titles:
                titles.append(title)
    return titles[:12]


def _should_ask_llm(message: str, history: list[AgentHistoryItem]) -> bool:
    text = _normalize(message)
    if not text:
        return False
    if _has_broad_search_marker(text) and not has_specific_mod_question_marker(text):
        return False
    return has_specific_mod_question_marker(text) or bool(
        _history_titles(history) and _has_reference_marker(text)
    )


def _has_reference_marker(text: str) -> bool:
    return bool(re.search(r"(这个|那个|刚才|上面|第\s*\d+|第[一二三四五六七八九十]+|this|that)", text, flags=re.IGNORECASE))


def _has_broad_search_marker(text: str) -> bool:
    return bool(re.search(r"(找|推荐|有哪些|只看|最近|热门|类似|替代|筛选|列表|给我)", text, flags=re.IGNORECASE))


def _distinctive_tokens(message: str) -> list[str]:
    tokens: list[str] = []
    stop_words = {
        "mod",
        "with",
        "and",
        "the",
        "for",
        "outfit",
        "body",
        "physics",
        "bodyslide",
        "cbbe",
        "unp",
        "sse",
        "skyrim",
    }
    for token in re.findall(r"[a-zA-Z][a-zA-Z0-9'_-]{2,}", message):
        normalized = token.lower().strip("_-'")
        if normalized and normalized not in stop_words and normalized not in tokens:
            tokens.append(normalized)
    return tokens[:10]


def _build_route_prompt(
    message: str,
    history: list[AgentHistoryItem],
    candidates: list[SpecificModCandidate],
) -> str:
    recent_history = [
        {"role": item.role, "text": str(item.text or "")[:500]}
        for item in history[-4:]
    ]
    candidate_payload = [candidate.__dict__ for candidate in candidates]
    return "\n".join(
        [
            "你是 Agent 路由裁判，只判断本轮用户是在问一个明确具体的 Mod，还是要发散搜索/泛化推荐。",
            "只能输出 JSON 对象，不要输出 Markdown。",
            "规则：",
            "1) 如果用户询问某个候选 Mod 的属性、安装、兼容、物理效果、风险、版本或详情，route=mod_detail。",
            "2) 如果用户在找一类 Mod、要求推荐、类似、替代、最近、热门、只看某类，route=search。",
            "3) selected_mod_id 只能来自候选列表；不能编造标题或 id。",
            "4) 指代如“这个/第二个/刚才那个”只有能从历史和候选唯一定位时才 route=mod_detail。",
            "5) 不确定时 route=search。",
            'JSON schema: {"route":"mod_detail|search","selected_mod_id":123|null,"confidence":0.0,"reason":"short"}',
            "",
            f"本轮用户问题：{message}",
            "最近历史：",
            json.dumps(recent_history, ensure_ascii=False),
            "候选 Mod：",
            json.dumps(candidate_payload, ensure_ascii=False),
        ]
    )


def _coerce_route_result(
    raw: dict[str, Any] | None,
    candidates: list[SpecificModCandidate],
) -> SpecificModRouteResult:
    candidate_ids = {candidate.mod_id for candidate in candidates}
    if not isinstance(raw, dict):
        return SpecificModRouteResult(candidate_count=len(candidates))
    route = str(raw.get("route") or "").strip().lower()
    confidence = _safe_confidence(raw.get("confidence"))
    selected_id = _safe_int(raw.get("selected_mod_id"))
    reason = str(raw.get("reason") or "").strip()[:300]
    if route == "mod_detail" and selected_id in candidate_ids and confidence >= 0.65:
        return SpecificModRouteResult(
            route="mod_detail",
            mod_id=selected_id,
            confidence=confidence,
            reason=reason,
            used_llm=bool(raw.get("used_llm")),
            candidate_count=len(candidates),
        )
    return SpecificModRouteResult(
        route="search",
        confidence=confidence,
        reason=reason,
        used_llm=bool(raw.get("used_llm")),
        candidate_count=len(candidates),
    )


def _safe_confidence(value: object) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


def _safe_int(value: object) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _clean_title(value: str) -> str:
    return str(value or "").strip().strip(" \t\r\n\"'“”‘’`。，.：:")


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).lower()
