import ast
import json
import re

from app.models.mod import Mod
from app.services.agent.history import compress_history
from app.services.agent.schemas import AgentHistoryItem, AgentModMatch
from app.services.llm_client import create_llm_client


def build_fallback_answer(matches: list[AgentModMatch]) -> str:
    return "找到以下相关 Mod：\n" + "\n".join([f"- {item.title} ({item.source})" for item in matches])


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
            f"用户问题：{_display_query(query)}",
            "候选结果：",
        ])
        for idx, item in enumerate(matches, start=1):
            prompt_lines.append(
                f"{idx}. title={item.title}; source={item.source}; game={item.game}; "
                f"game_domain={item.game_domain or 'unknown'}; category={item.category or 'unknown'}; "
                f"adult_content={item.adult_content}; downloads={item.downloads}; endorsements={item.endorsements}; "
                f"likes={item.likes}; author={item.author or 'unknown'}; version={item.version or 'unknown'}; url={item.url}"
            )
        prompt = "\n".join(prompt_lines)

        client = create_llm_client(provider=provider, api_key=api_key, base_url=base_url)
        return await client.chat(prompt, model=model, max_tokens=500)

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
            "4) 不要使用固定模板，不要编造候选列表中没有的 Mod",
            "",
            f"用户问题：{_display_query(query)}",
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


def _display_query(query: str) -> str:
    return (query or "").split("[scope]", 1)[0].strip()


def parse_next_steps(content: str) -> list[str]:
    raw = str(content or "").strip()
    if not raw:
        return []
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.IGNORECASE | re.DOTALL).strip()
    parsed: object
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        parsed = [_parse_next_step_line(line) for line in raw.splitlines() if line.strip()]
    if not isinstance(parsed, list):
        return []
    steps = []
    for item in parsed:
        value = _next_step_value(item)
        if value and value not in steps:
            steps.append(value[:160])
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
    if value.startswith("{") and value.endswith("}"):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            try:
                parsed = ast.literal_eval(value)
            except (SyntaxError, ValueError):
                return ""
            return parsed if isinstance(parsed, dict) else ""
    return value
