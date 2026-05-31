import logging
from dataclasses import dataclass, field
from typing import Any

from app.services.agent.context.context_utils import has_query_context_signal
from app.services.agent.history import compress_history
from app.services.agent.list_utils import unique_text
from app.services.agent.schemas import AgentHistoryItem
from app.services.llm_client import create_llm_client
from app.utils.json import json_object_from_text, json_text
from app.utils.numeric import safe_float

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LlmContextSelection:
    context: dict[str, Any] = field(default_factory=dict)
    status: str = "skipped"
    reason: str = ""


async def select_last_query_context_with_llm(
    *,
    query: str,
    history: list[AgentHistoryItem],
    active_constraints: dict[str, Any],
    short_last_query_context: dict[str, Any],
    memory_context: dict[str, Any],
    shown_mod_titles: list[str],
    provider: str,
    api_key: str,
    base_url: str,
    model: str,
    evidence_id: str,
) -> LlmContextSelection:
    """让 LLM 结合完整对话和记忆选择本轮最合适的可继承查询上下文。"""
    if not provider or not model:
        return LlmContextSelection(status="skipped", reason="missing_llm_config")
    prompt = _build_prompt(
        query=query,
        history=history,
        active_constraints=active_constraints,
        short_last_query_context=short_last_query_context,
        memory_context=memory_context,
        shown_mod_titles=shown_mod_titles,
    )
    try:
        # 上下文选择是辅助语义层，LLM 配置不可用时必须降级，不能中断主查询链路。
        client = create_llm_client(provider=provider, api_key=api_key, base_url=base_url)
        content = await client.chat(prompt, model=model, max_tokens=650, request_timeout=20.0)
    except Exception as exc:
        logger.info(
            "agent.context.llm_selection status=degraded reason=%s evidence_id=%s",
            type(exc).__name__,
            evidence_id,
        )
        return LlmContextSelection(status="degraded", reason=type(exc).__name__)
    parsed = json_object_from_text(content)
    if not isinstance(parsed, dict):
        logger.info(
            "agent.context.llm_selection status=degraded reason=invalid_json evidence_id=%s",
            evidence_id,
        )
        return LlmContextSelection(status="degraded", reason="invalid_json")
    selected = _normalize_selection(parsed, evidence_id=evidence_id)
    if not selected:
        logger.info(
            "agent.context.llm_selection status=skipped reason=no_context confidence=%s evidence_id=%s",
            parsed.get("confidence"),
            evidence_id,
        )
        return LlmContextSelection(status="skipped", reason="no_context")
    logger.info(
        "agent.context.llm_selection status=succeeded source=%s confidence=%s fields=%s evidence_id=%s",
        selected.get("source"),
        selected.get("llm_confidence"),
        sorted(selected.keys()),
        evidence_id,
    )
    return LlmContextSelection(context=selected, status="succeeded", reason="llm_selected")


def _build_prompt(
    *,
    query: str,
    history: list[AgentHistoryItem],
    active_constraints: dict[str, Any],
    short_last_query_context: dict[str, Any],
    memory_context: dict[str, Any],
    shown_mod_titles: list[str],
) -> str:
    history_summary, recent_history = compress_history(history, max_items=12, max_chars=2400)
    long_term = memory_context.get("long_term") if isinstance(memory_context, dict) else {}
    short_term = memory_context.get("short_term") if isinstance(memory_context, dict) else {}
    lines = [
        "你是 Mod 查询上下文选择器。请结合完整对话、短期上下文、长期写回和本轮输入，判断本轮是否应该继承某个上一轮查询状态。",
        "目标：选择最适合本轮继续使用的 last_query_context，而不是简单选择最近或分数最高的历史项。",
        "",
        "输出规则：",
        "1) 只输出 JSON 对象，不要解释。",
        "2) 如果本轮是独立新问题或主题明显切换，输出 {\"should_inherit\": false, \"reason\": \"...\", \"confidence\": 0.0~1.0}。",
        "3) 如果应该继承，输出字段：",
        "{ \"should_inherit\": true, \"keywords\": [string], \"semantic_anchors\": [string], \"semantic_domains\": [string], \"game\": string|null, \"source_name\": string|null, \"category\": string|null, \"adult_content\": true|false|null, \"sort_field\": string|null, \"sort_order\": \"asc\"|\"desc\"|null, \"confidence\": 0.0~1.0, \"reason\": string }",
        "4) 当前用户显式指定的游戏、来源、成人/非成人、分类、排序优先；不要用旧上下文覆盖当前显式条件。",
        "5) 只有当本轮包含“继续、类似、相关、这个、同类、more、similar、related”等追问/细化意图，或本轮信息不足但明显承接上一轮时，才继承。",
        "6) keywords 只放真正需要继续检索的核心词；semantic_anchors/semantic_domains 表示玩法、风格、来源范围等高层语义。",
        "",
        f"本轮用户输入：{query}",
        "",
        "短期 active_constraints：",
        json_text(active_constraints),
        "",
        "短期 last_query_context：",
        json_text(short_last_query_context),
        "",
        "短期记忆：",
        json_text(short_term),
        "",
        "长期记忆：",
        json_text(long_term),
        "",
        "已展示 MOD 标题：",
        json_text(shown_mod_titles[:30]),
    ]
    if history_summary:
        lines.extend(["", "较早对话摘要：", history_summary])
    if recent_history:
        lines.append("")
        lines.append("最近对话：")
        for index, item in enumerate(recent_history, start=1):
            prefix = "用户" if item.role == "user" else "助手"
            lines.append(f"{index}. {prefix}: {item.text[:400]}")
    return "\n".join(lines)


def _normalize_selection(raw: dict[str, Any], *, evidence_id: str) -> dict[str, Any]:
    if raw.get("should_inherit") is not True:
        return {}
    confidence = safe_float(raw.get("confidence"), default=0.6, minimum=0.0, maximum=1.0)
    context: dict[str, Any] = {
        "source": "llm_context_selection",
        "llm_should_inherit": True,
        "llm_reason": str(raw.get("reason") or "").strip()[:500],
        "llm_confidence": confidence,
        "quality_score": max(0.6, confidence),
    }
    for key in ("keywords", "semantic_anchors", "semantic_domains"):
        values = unique_text(raw.get(key) or [], limit=8) if isinstance(raw.get(key), list) else []
        if values:
            context[key] = values
    for key in ("game", "source_name", "category", "sort_field", "sort_order"):
        value = str(raw.get(key) or "").strip()
        if value:
            context[key] = value
    if isinstance(raw.get("adult_content"), bool):
        context["adult_content"] = raw["adult_content"]
    if evidence_id:
        context["evidence_id"] = evidence_id
    return context if has_query_context_signal(context) else {}
