import ast
import re

from app.models.mod import Mod
from app.services.agent.history import compress_history
from app.services.agent.response_builder import display_query
from app.services.agent.schemas import AgentHistoryItem, AgentModMatch
from app.services.llm_client import create_llm_client
from app.utils.json import json_array_from_text, json_object_from_text, strip_json_fence


def build_fallback_answer(matches: list[AgentModMatch]) -> str:
    return "找到以下相关 Mod：\n" + "\n".join([f"- {item.title} ({item.source})" for item in matches])


def build_recommendation_fallback(matches: list[AgentModMatch]) -> str:
    lines = ["优先推荐这些 Mod："]
    for item in matches[:5]:
        notes = []
        if item.downloads is not None:
            notes.append(f"下载量 {item.downloads}")
        if item.endorsements is not None:
            notes.append(f"背书 {item.endorsements}")
        if item.likes is not None:
            notes.append(f"喜欢数 {item.likes}")
        if item.category:
            notes.append(item.category)
        if not notes:
            notes.append("与本次需求相关")
        lines.append(f"- {item.title}：{'；'.join(notes)}。")
    return "\n".join(lines)


def build_alternative_fallback(matches: list[AgentModMatch]) -> str:
    lines = ["可以考虑这些替代 Mod："]
    for item in matches[:5]:
        notes = []
        if item.version:
            notes.append(f"版本 {item.version}")
        if item.adult_content is False:
            notes.append("SFW 记录")
        if item.rank_reason:
            notes.append(item.rank_reason)
        if not notes:
            notes.append("和当前需求相关，可作为候选替代")
        lines.append(f"- {item.title}：{'；'.join(notes)}。")
    return "\n".join(lines)


def build_comparison_fallback(matches: list[AgentModMatch]) -> str:
    if not matches:
        return "当前没有足够候选可以比较。"
    ranked = sorted(matches, key=_comparison_score, reverse=True)
    recommended = ranked[0]
    lines = [
        f"如果优先考虑新手友好和低风险，我更推荐：{recommended.title}。",
        "比较依据：",
    ]
    for item in ranked[:5]:
        notes = []
        if item.version:
            notes.append(f"有版本信息（{item.version}）")
        else:
            notes.append("版本信息缺失")
        if item.adult_content is False:
            notes.append("SFW 记录")
        elif item.adult_content is True:
            notes.append("包含成人内容")
        summary = " ".join([item.original_summary or "", item.translated_summary or ""]).lower()
        if any(marker in summary for marker in ["stable", "conservative", "safe", "compat", "稳定", "保守", "兼容"]):
            notes.append("摘要包含稳定/兼容信号")
        lines.append(f"- {item.title}：{'；'.join(notes)}。")
    return "\n".join(lines)


def build_install_risk_fallback(matches: list[AgentModMatch]) -> str:
    lines = ["基于当前已收录信息，安装风险初步判断如下："]
    for item in matches[:5]:
        risk_notes = []
        if item.adult_content is True:
            risk_notes.append("包含成人内容，安装前确认来源和本地内容设置")
        if not item.version:
            risk_notes.append("版本信息缺失，建议到源站确认支持的游戏版本")
        if not item.original_summary and not item.translated_summary:
            risk_notes.append("摘要信息不足，建议先查看源站说明和前置依赖")
        requirement_terms = _requirement_terms_from_match(item)
        if requirement_terms:
            risk_notes.append(f"摘要/源站信息提到前置或依赖：{', '.join(requirement_terms[:4])}")
        if not risk_notes:
            risk_notes.append("当前记录没有明显风险信号，仍建议检查前置依赖、加载顺序和评论区反馈")
        lines.append(f"- {item.title}：{'；'.join(risk_notes)}。")
    return "\n".join(lines)


def _comparison_score(item: AgentModMatch) -> int:
    score = 0
    if item.version:
        score += 3
    if item.adult_content is False:
        score += 2
    if item.adult_content is True:
        score -= 2
    summary = " ".join([item.original_summary or "", item.translated_summary or ""]).lower()
    for marker in ["stable", "conservative", "safe", "compat", "稳定", "保守", "兼容"]:
        if marker in summary:
            score += 2
    return score


def _requirement_terms_from_match(item: AgentModMatch) -> list[str]:
    text = " ".join([item.original_summary or "", item.translated_summary or ""])
    candidates = []
    for token in re.findall(r"\b[A-Z][A-Z0-9_+-]{2,}\b", text):
        if token.lower() not in {"mod", "mods"}:
            candidates.append(token)
    lowered = text.lower()
    for marker in ["skse", "cbbe", "bodyslide", "nemesis", "fnis", "3ba", "xpmsse"]:
        if marker in lowered:
            candidates.append(marker.upper())
    return list(dict.fromkeys(candidates))


def _compact_prompt_text(value: str | None, *, limit: int = 420) -> str:
    text = re.sub(r"\s+", " ", str(value or "").strip())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _format_match_for_prompt(idx: int, item: AgentModMatch) -> str:
    parts = [
        f"{idx}. title={item.title}",
        f"translated_title_zh={item.translated_title_zh or 'unknown'}",
        f"source={item.source}",
        f"game={item.game}",
        f"game_domain={item.game_domain or 'unknown'}",
        f"category={item.category or 'unknown'}",
        f"adult_content={item.adult_content}",
        f"downloads={item.downloads}",
        f"endorsements={item.endorsements}",
        f"likes={item.likes}",
        f"author={item.author or 'unknown'}",
        f"version={item.version or 'unknown'}",
        f"url={item.url}",
    ]
    if item.rank_reason:
        parts.append(f"rank_reason={_compact_prompt_text(item.rank_reason, limit=260)}")
    if item.translated_summary:
        parts.append(f"translated_summary={_compact_prompt_text(item.translated_summary)}")
    if item.original_summary:
        parts.append(f"original_summary={_compact_prompt_text(item.original_summary)}")
    return "; ".join(parts)


def build_detail_fallback(mod: Mod, match: AgentModMatch) -> str:
    return (
        f"Mod：{mod.title}\n"
        f"来源：{mod.source}\n"
        f"游戏：{mod.game}\n"
        f"作者：{mod.author or 'unknown'}\n"
        f"版本：{mod.version or 'unknown'}\n"
        f"链接：{mod.url}\n\n"
        f"译文摘要：{match.translated_summary or '暂无'}\n"
        f"原文摘要：{match.original_summary or '暂无'}"
    )


class AgentAnswerService:
    async def answer_matches(
        self,
        *,
        query: str,
        matches: list[AgentModMatch],
        provider: str,
        api_key: str,
        base_url: str,
        model: str,
        history: list[AgentHistoryItem],
    ) -> str:
        history_summary, recent_history = compress_history(history)

        prompt_lines = [
            "你是 Mod 查询助手。请基于给定候选结果回答用户问题。",
            "要求：",
            "1) 优先给出最相关的 3-5 条",
            "2) 回答使用中文",
            "3) 不要编造未提供的数据",
            "4) 若上下文有历史偏好，优先延续用户偏好",
            "5) 如果用户在问“扮演/RP/路线/玩法/怎么搭”，不要只列标题；按用途分层说明：核心玩法、外观/身体配套、对话或生态扩展、安装与兼容风险",
            "6) 具体 Mod 名必须来自候选结果或最近对话；没有证据的搭配方向可以写成“建议继续检索的方向”，但不要写成已确认推荐",
            "7) 对成人向、SexLab、LoversLab、诅咒/转化类内容，要明确前置依赖、MCM/配置复杂度、机制叠加风险和只启用一个同类核心机制的建议",
            "8) 对玩法/RP 查询，区分“核心玩法 Mod”和“预设/插件/重制/纹身等配套”。如果某候选摘要明确包含任务、NPC、诅咒、转化、玩家或随从影响，应优先作为核心推荐；不要把 preset/addon/overhaul/tats 类配套放在核心前面",
        ]
        if history_summary:
            prompt_lines.extend(["", history_summary])
        if recent_history:
            prompt_lines.append("")
            prompt_lines.append("最近对话：")
            for item in recent_history:
                prefix = "用户" if item.role == "user" else "助手"
                prompt_lines.append(f"{prefix}: {item.text[:280]}")
        prompt_lines.extend([
            "",
            f"用户问题：{display_query(query)}",
            "候选结果：",
        ])
        prompt_matches = _order_matches_for_answer(query, matches)
        for idx, item in enumerate(prompt_matches, start=1):
            prompt_lines.append(_format_match_for_prompt(idx, item))
        prompt = "\n".join(prompt_lines)

        client = create_llm_client(provider=provider, api_key=api_key, base_url=base_url)
        return await client.chat(prompt, model=model, max_tokens=900)

    async def suggest_next_steps(
        self,
        *,
        query: str,
        answer: str,
        matches: list[AgentModMatch],
        provider: str,
        api_key: str,
        base_url: str,
        model: str,
    ) -> list[str]:
        prompt_lines = [
            "你是 Mod 查询助手。请根据用户问题、已给出的回答和候选 Mod，生成后续可追问建议。",
            "要求：",
            "1) 只输出 JSON 字符串数组，不要输出 Markdown 或解释",
            "2) 生成 1-3 条，使用中文",
            "3) 每条建议必须贴合本次结果，例如围绕具体游戏、来源、排序、安装风险、兼容性或某个候选 Mod",
            "4) 每条必须像用户下一轮会直接输入的问题或请求；不要写“建议你/你可以/请补充/当前...”这类助手说明",
            "5) 不要使用固定模板，不要编造候选列表中没有的 Mod",
            "",
            f"用户问题：{display_query(query)}",
            f"当前回答：{answer[:1200]}",
            "候选结果：",
        ]
        for idx, item in enumerate(matches[:5], start=1):
            prompt_lines.append(
                f"{idx}. title={item.title}; source={item.source}; game={item.game}; "
                f"category={item.category or 'unknown'}; adult_content={item.adult_content}; "
                f"downloads={item.downloads}; endorsements={item.endorsements}; url={item.url}"
            )
        prompt = "\n".join(prompt_lines)

        client = create_llm_client(provider=provider, api_key=api_key, base_url=base_url)
        content = await client.chat(prompt, model=model, max_tokens=220)
        return parse_next_steps(content)

    async def answer_detail(
        self,
        *,
        mod: Mod,
        match: AgentModMatch,
        question: str,
        provider: str,
        api_key: str,
        base_url: str,
        model: str,
        history: list[AgentHistoryItem],
    ) -> str:
        history_summary, recent_history = compress_history(history)
        prompt_lines = [
            "你是 Mod 查询助手，请只基于给定单个 Mod 信息，输出更详细解析。",
            "要求：",
            "1) 用中文回答",
            "2) 不编造未提供信息；不确定时明确说明",
            "3) 输出结构：核心特点 / 兼容性与风险 / 适合人群 / 建议下一步",
        ]
        if history_summary:
            prompt_lines.extend(["", history_summary])
        if recent_history:
            prompt_lines.append("")
            prompt_lines.append("最近对话：")
            for item in recent_history:
                prefix = "用户" if item.role == "user" else "助手"
                prompt_lines.append(f"{prefix}: {item.text[:280]}")

        prompt_lines.extend([
            "",
            f"用户问题：{question}",
            "Mod 信息：",
            f"title={mod.title}",
            f"source={mod.source}",
            f"game={mod.game}",
            f"game_domain={mod.game_domain or ''}",
            f"category={mod.category or ''}",
            f"adult_content={mod.adult_content}",
            f"downloads={mod.downloads}",
            f"endorsements={mod.endorsements}",
            f"likes={mod.likes}",
            f"author={mod.author or 'unknown'}",
            f"version={mod.version or 'unknown'}",
            f"url={mod.url}",
            f"translated_summary={match.translated_summary or ''}",
            f"original_summary={match.original_summary or ''}",
        ])
        prompt = "\n".join(prompt_lines)
        client = create_llm_client(provider=provider, api_key=api_key, base_url=base_url)
        return await client.chat(prompt, model=model, max_tokens=800)


def _order_matches_for_answer(query: str, matches: list[AgentModMatch]) -> list[AgentModMatch]:
    if not _is_roleplay_or_gameplay_query(query):
        return matches
    return sorted(matches, key=_answer_priority_score, reverse=True)


def _is_roleplay_or_gameplay_query(query: str) -> bool:
    text = str(query or "").lower()
    return any(marker in text for marker in ["扮演", "角色扮演", "玩法", "路线", "roleplay", "play as", "rp", "gameplay"])


def _answer_priority_score(item: AgentModMatch) -> int:
    text = " ".join([item.title, item.category or "", item.original_summary or "", item.translated_summary or ""]).lower()
    score = int(item.score or 0)
    for marker in ["quest", "任务", "curse", "诅咒", "transform", "转化", "player", "玩家", "follower", "随从", "npc"]:
        if marker in text:
            score += 8
    for marker in ["preset", "预设", "addon", "plugin", "插件", "overhaul", "重制", "tats", "纹身", "lips", "嘴唇"]:
        if marker in text:
            score -= 10
    return score


def parse_next_steps(content: str) -> list[str]:
    raw = strip_json_fence(content)
    if not raw:
        return []
    json_array = json_array_from_text(raw)
    parsed: object = json_array if json_array is not None else [_parse_next_step_line(line) for line in raw.splitlines() if line.strip()]
    if not isinstance(parsed, list):
        return []
    steps = []
    for item in parsed:
        value = _next_step_value(item)
        if value and value not in steps:
            steps.append(_normalize_next_step_text(value)[:160])
    return steps[:3]


def _next_step_value(item: object) -> str:
    if isinstance(item, dict):
        for key in ("question", "text", "label", "title"):
            value = str(item.get(key) or "").strip()
            if value:
                return value
        return ""
    value = str(item or "").strip()
    dict_value = _parse_next_step_line(value)
    if isinstance(dict_value, dict):
        return _next_step_value(dict_value)
    return re.sub(r"^[\s\-*•\d.)、]+", "", value).strip()


def _parse_next_step_line(line: str) -> object:
    value = re.sub(r"^[\s\-*•\d.)、]+", "", line).strip().rstrip(",")
    if not value:
        return ""
    if value.startswith(("[", "{")) and not value.endswith(("]", "}")):
        return ""
    if value.startswith("{") and value.endswith("}"):
        parsed = json_object_from_text(value)
        if isinstance(parsed, dict):
            return parsed
        try:
            parsed = ast.literal_eval(value)
        except (SyntaxError, ValueError):
            return ""
        return parsed if isinstance(parsed, dict) else ""
    return value


def _normalize_next_step_text(value: str) -> str:
    text = re.sub(r"\s+", " ", str(value or "").strip())
    for prefix in (
        "你可以继续问：",
        "你可以继续指定：",
        "建议下一步：",
        "下一步：",
        "建议：",
    ):
        if text.startswith(prefix):
            text = text[len(prefix):].strip()
    return text
