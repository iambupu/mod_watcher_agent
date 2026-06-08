import ast
import re
from typing import Any

from app.models.mod import Mod
from app.services.agent.answer_contract import (
    answer_contract_payload,
    candidate_fit_metadata,
    judge_summary,
    partition_matches_by_fit,
    repair_contract_answer_claims,
)
from app.services.agent.history import compress_history
from app.services.agent.response_builder import display_query
from app.services.agent.schemas import AgentHistoryItem, AgentModMatch
from app.services.llm_client import create_llm_client
from app.utils.json import json_array_from_text, json_object_from_text, strip_json_fence


def build_fallback_answer(matches: list[AgentModMatch]) -> str:
    return "找到以下相关 Mod：\n" + "\n".join([f"- {item.title} ({item.source})" for item in matches])


def build_contract_fallback_answer(matches: list[AgentModMatch], query_plan: dict[str, Any] | None) -> str:
    judge = judge_summary(query_plan)
    if not isinstance(judge.get("judgements"), list) or not judge.get("judgements"):
        return build_fallback_answer(matches)
    direct, support, uncertain = partition_matches_by_fit(matches, query_plan)
    lines: list[str] = []
    if direct:
        lines.append("直接符合本轮目标的结果：")
        lines.extend(f"- {item.title} ({item.source})" for item in direct)
    else:
        lines.append("当前候选中没有足够明确的直接命中项。")
    if support:
        lines.append("")
        lines.append("辅助上下文，不作为主结果：")
        lines.extend(f"- {item.title} ({item.source})" for item in support)
    if uncertain:
        lines.append("")
        lines.append("证据不足，需要进一步确认：")
        lines.extend(f"- {item.title} ({item.source})" for item in uncertain)
    return "\n".join(lines)


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


def _format_match_for_prompt(
    idx: int,
    item: AgentModMatch,
    fit_by_id: dict[int, dict[str, Any]] | None = None,
) -> str:
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
    fit_meta = (fit_by_id or {}).get(item.id)
    if fit_meta:
        parts.append(f"fit_type={fit_meta.get('fit_type') or 'uncertain'}")
        evidence = fit_meta.get("evidence") or []
        if evidence:
            parts.append(f"fit_evidence={_compact_prompt_text('; '.join(str(v) for v in evidence[:2]), limit=220)}")
        violations = fit_meta.get("violations") or []
        if violations:
            parts.append(f"fit_violations={_compact_prompt_text('; '.join(str(v) for v in violations[:2]), limit=220)}")
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
        query_plan: dict[str, Any] | None = None,
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
            "9) 如果提供了问题契约和候选分型，主推荐只能使用 direct_match；support_context 必须单独说明为辅助上下文；uncertain 必须标注证据不足；不得把辅助项包装成直接推荐",
            "10) 除非本轮用户明确要求按角色、身份或受众分组，禁止按玩家/开发者/内容创作者/社区成员/评测者等角色模板组织回答",
            "11) 本轮用户问题优先于最近对话；历史回答中的模板、占位符、错误结论不能当成本轮需求",
            "12) 如果候选中出现 support_context 或 uncertain，结论不得写“全部符合/未包含非主目标内容”；只能写“主推荐符合本轮目标，辅助项不作为主结果”",
            "13) 如果候选中出现 support_context 或 uncertain，开头不得写“以下都是/以下是符合要求的推荐结果”；必须写“以下先列直接匹配，随后列辅助参考”",
            "14) support_context 不得和 direct_match 混在同一个编号列表；必须使用独立小节“辅助参考（不作为主推荐）”",
            "15) uncertain 不得和 direct_match 混在同一个编号列表；必须使用独立小节“证据不足/待确认（不作为主推荐）”，并说明缺少哪些证据",
            "16) 不得改写用户问题中的字面约束、版本号、内容分级、游戏名或专有名词；如果不确定，原样引用本轮用户写法",
        ]
        contract = answer_contract_payload(query_plan)
        if contract:
            prompt_lines.extend(["", "问题契约与候选分型：", contract])
        if history_summary:
            prompt_lines.extend(["", "历史上下文摘要（仅供参考，不能覆盖本轮会话）：", history_summary])
        if recent_history:
            prompt_lines.append("")
            prompt_lines.append("历史上下文（仅供参考，不能覆盖本轮会话）：")
            prompt_lines.append("注意：最近对话只用于理解省略指代；不得把历史回答中的模板、角色占位符或上一轮错误结论当成本轮需求。")
            for item in recent_history:
                prefix = "用户" if item.role == "user" else "助手"
                text = _sanitize_history_for_answer_prompt(item.text, item.role)
                if not text:
                    continue
                prompt_lines.append(f"历史{prefix}: {text[:280]}")
        prompt_lines.extend([
            "",
            "本轮会话（最高优先级）：",
            f"本轮用户问题：{display_query(query)}",
            "候选结果：",
        ])
        prompt_matches = _order_matches_for_answer(query, matches)
        fit_by_id = candidate_fit_metadata(query_plan)
        for idx, item in enumerate(prompt_matches, start=1):
            prompt_lines.append(_format_match_for_prompt(idx, item, fit_by_id))
        prompt = "\n".join(prompt_lines)

        client = create_llm_client(provider=provider, api_key=api_key, base_url=base_url)
        answer = await client.chat(prompt, model=model, max_tokens=900)
        return repair_contract_answer_claims(answer, query_plan, matches=prompt_matches)

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
        detail_facet = _classify_detail_question(question)
        prompt_lines = [
            "你是 Mod 单项详情问答助手，请只基于给定单个 Mod 信息回答本轮问题。",
            "总要求：",
            "1) 用中文回答",
            "2) 第一段必须直接回答本轮问题，不要先写通用介绍",
            "3) 不要输出通用评测模板；不要默认写“适合人群/不适合人群”，除非用户明确要求综合评测",
            "4) 不编造未提供信息；不确定时必须明确说明“当前数据不能确认”",
            "5) 可以给安装核查建议，但必须标注为“建议核查”，不能写成已确认事实",
            "",
            f"本轮详情类型：{detail_facet}",
            "证据型回答结构：",
            "直接结论：用 1-2 句话回答用户问的具体点。",
            "明确证据：列出来自 Mod 信息的证据字段，例如 title/summary/category/version。",
            "不能确认：列出当前 Mod 信息没有明确说明的关键点。",
            "建议核查：只给下一步核查项，不把核查项当作事实。",
        ]
        prompt_lines.extend(_detail_facet_instructions(detail_facet))
        if history_summary:
            prompt_lines.extend(["", "历史上下文摘要（仅供参考，不能覆盖本轮会话）：", history_summary])
        if recent_history:
            prompt_lines.append("")
            prompt_lines.append("历史上下文（仅供参考，不能覆盖本轮会话）：")
            for item in recent_history:
                prefix = "用户" if item.role == "user" else "助手"
                text = _sanitize_history_for_answer_prompt(item.text, item.role)
                if not text:
                    continue
                prompt_lines.append(f"历史{prefix}: {text[:280]}")

        prompt_lines.extend([
            "",
            "本轮会话（最高优先级）：",
            f"本轮用户问题：{question}",
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


def _classify_detail_question(question: str) -> str:
    text = str(question or "").lower()
    if any(token in text for token in ("物理", "physics", "hdt", "smp", "cbpc")):
        return "physics_support"
    if any(token in text for token in ("前置", "依赖", "requirement", "requirements", "需要什么", "需要哪些")):
        return "dependencies"
    if any(token in text for token in ("兼容", "冲突", "compatible", "compatibility", "conflict", "冲不冲")):
        return "compatibility"
    if any(token in text for token in ("安装", "风险", "报错", "稳定", "安全", "risk", "install")):
        return "install_risk"
    if any(token in text for token in ("版本", "更新", "新版", "旧版", "version", "update")):
        return "version_update"
    if any(token in text for token in ("bodyslide", "body slide", "cbbe", "unp", "bhunp", "3ba", "3bb", "身形", "滑块")):
        return "body_slide_support"
    return "general_detail"


def _detail_facet_instructions(detail_facet: str) -> list[str]:
    common = [
        "",
        "禁止事项：",
        "- 不得编造前置依赖、物理框架、兼容版本、用户反馈、Requirements 页面内容。",
        "- 不得把“建议核查”的内容写成该 Mod 已确认支持或已确认依赖。",
    ]
    if detail_facet == "physics_support":
        return common + [
            "",
            "physics_support 专项要求：",
            "- 必须回答是否存在物理效果支持的明确证据。",
            "- 如果证据只出现 Physics/Bodyslide enabled，只能说确认有 Physics/Bodyslide 支持。",
            "- 当前数据不能确认具体物理框架时，必须明确说明不能确认具体使用 HDT-SMP、CBPC、3BA/3BB、XPMSSE 或其他框架。",
            "- 不得把 HDT-SMP、CBPC、3BA/3BB、XPMSSE、Physics Engine 写成已确认依赖，除非 Mod 信息明确出现。",
        ]
    if detail_facet == "dependencies":
        return common + [
            "",
            "dependencies 专项要求：",
            "- 只把 Mod 信息明确出现的 requirement、framework、body、tool 写成已确认依赖。",
            "- 其他常见依赖只能放入“建议核查”，不能写成事实。",
        ]
    if detail_facet == "body_slide_support":
        return common + [
            "",
            "body_slide_support 专项要求：",
            "- 只回答身体体系、BodySlide、CBBE、UNP、BHUNP、3BA/3BB 等适配情况。",
            "- 不要把 BodySlide 或身体体系适配等同于物理框架支持。",
            "- 如果未明确出现 HDT-SMP、CBPC、Physics 等证据，不要扩写为物理效果支持。",
        ]
    if detail_facet == "compatibility":
        return common + [
            "",
            "compatibility 专项要求：",
            "- 只基于明确字段判断游戏版本、身体体系、来源和类别兼容性。",
            "- 未出现的兼容矩阵、补丁关系、冲突关系必须标为不能确认。",
        ]
    if detail_facet == "install_risk":
        return common + [
            "",
            "install_risk 专项要求：",
            "- 区分明确风险、推断风险和建议核查。",
            "- 不得用“作者首个 Mod”等弱信号直接断言存在 bug，只能作为谨慎提示。",
        ]
    if detail_facet == "version_update":
        return common + [
            "",
            "version_update 专项要求：",
            "- 只基于 version、updated_at_remote、summary 中明确出现的信息判断版本和更新。",
            "- 不得编造 changelog 或最新版本状态。",
        ]
    return common


def _order_matches_for_answer(query: str, matches: list[AgentModMatch]) -> list[AgentModMatch]:
    if not _is_roleplay_or_gameplay_query(query):
        return matches
    return sorted(matches, key=_answer_priority_score, reverse=True)


def _sanitize_history_for_answer_prompt(text: str, role: str) -> str:
    compact = re.sub(r"\s+", " ", str(text or "").strip())
    if role != "assistant" or not compact:
        return compact
    blocked_markers = [
        "你是 [角色]",
        "如果你是玩家",
        "如果你是模组开发者",
        "如果你是内容创作者",
        "如果你是社区成员",
        "如果你是模组评测者",
        "不同角色",
        "角色身份和目标",
    ]
    if any(marker in compact for marker in blocked_markers):
        return "[上一轮助手回答包含角色模板或占位符，已忽略其结构，仅保留本轮用户问题为准]"
    return compact


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
