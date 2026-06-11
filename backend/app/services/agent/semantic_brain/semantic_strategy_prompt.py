from typing import Any

from app.services.agent.history import compress_history
from app.services.agent.schemas import AgentHistoryItem
from app.utils.json import json_text


def build_semantic_strategy_prompt(
    *,
    query: str,
    history: list[AgentHistoryItem],
    active_constraints: dict[str, Any],
    last_query_context: dict[str, Any],
    memory_context: dict[str, Any],
    shown_mod_titles: list[str],
) -> str:
    """构造语义策略提示词：让 LLM 判断任务策略，而不是填数据库查询槽位。"""
    history_summary, recent_history = compress_history(history, max_items=10, max_chars=1800)
    long_term = memory_context.get("long_term") if isinstance(memory_context, dict) else {}
    short_term = memory_context.get("short_term") if isinstance(memory_context, dict) else {}
    lines = [
        "你是 Mod 查询 Agent 的 Semantic Brain。你的任务是理解用户真正想完成什么，并输出轻量语义策略 JSON。",
        "",
        "重要边界：",
        "1) 只输出 JSON 对象，不要 Markdown，不要解释。",
        "2) 你不能生成 SQL、URL、工具调用或绕过工具权限。",
        "3) hard_filters 只能放用户本轮明确说死的条件，例如游戏、来源、标题、URL、ID、不要/排除。",
        "4) history、memory、收藏偏好默认只能作为 soft_signals 或语境提示，不能覆盖本轮明确输入。",
        "5) 开放发现问题不要擅自把分类、标签、依赖、兼容词变成 hard filter。",
        "6) core_terms / soft_signals 只能来自本轮问题可归因的语义线索，不允许添加用户没有提到且与 query 无关的宽泛词（例如 subtitle、翻译、补丁等未提及项）。",
        "",
        "JSON 结构：",
        "{",
        '  "task_type": "exact_lookup|open_discovery|comparative|advisory|preference|unknown",',
        '  "user_goal": "用户目标的自然语言摘要",',
        '  "strategy": "exact_then_explain|broad_then_judge|compare_known_and_fetch_missing|evidence_then_advice|memory_summary|clarify_first",',
        '  "hard_filters": {',
        '    "game": string|null,',
        '    "source": string|null,',
        '    "adult_content": true|false|null,',
        '    "exact_title": string|null,',
        '    "external_id": string|null,',
        '    "source_url": string|null,',
        '    "excluded_keywords": [string],',
        '    "excluded_sources": [string]',
        "  },",
        '  "core_terms": [string],',
        '  "soft_signals": [string],',
        '  "direct_match_definition": [string],',
        '  "support_context_definition": [string],',
        '  "reject_as_primary": [string],',
        '  "answer_policy": {',
        '    "main_results": "only_direct_match|ranked_by_fit_type",',
        '    "support_context": "separate_section|merge_with_explanation",',
        '    "uncertain_items": "mark_uncertain|hide",',
        '    "insufficient_direct_matches": "state_insufficient_before_support_items|normal_answer"',
        "  },",
        '  "ranking_goal": "如何判断候选更相关",',
        '  "answer_shape": "direct_lookup|grouped_recommendation|comparison_table|risk_advice|memory_summary|clarify_first",',
        '  "confidence": 0.0,',
        '  "reason": "为什么选择该策略"',
        "}",
        "",
        "策略选择：",
        "- exact_lookup：用户给出明确标题、URL、ID 或指定详情目标。",
        "- open_discovery：用户问有什么、有哪些、推荐、怎么搭、扮演、RP、路线。",
        "- comparative：用户问对比、替代、哪个更适合、第二个怎么样。",
        "- advisory：用户问安装风险、兼容、依赖、搭配建议。",
        "- preference：用户问自己的收藏偏好、用户画像、历史偏好。",
        "- unknown：缺少关键信息，需要先澄清。",
        "",
        "问题契约规则：",
        "- direct_match_definition 描述候选本体怎样才算直接满足用户主目标。",
        "- support_context_definition 描述哪些候选只能作为依赖、兼容、背景或搭配上下文。",
        "- reject_as_primary 描述不能进入主结果的类型或违例原因。",
        "- answer_policy 约束最终回答。用户说“只看/不要/排除”时，主结果必须更严格。",
        "- core_terms/soft_signals 可以帮助宽召回，但不能反向改变 primary goal；扩展词命中的辅助项不能自动成为主结果。",
        "",
        f"本轮用户输入：{query}",
        "",
        "active_constraints：",
        json_text(active_constraints),
        "",
        "last_query_context：",
        json_text(last_query_context),
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


def build_semantic_strategy_repair_prompt(*, original_prompt: str, invalid_output: str) -> str:
    return "\n".join(
        [
            "上一次输出不是合法 JSON 对象，或不符合 SemanticStrategy schema。请修正。",
            "严格要求：",
            "1) 只输出一个 JSON 对象，不要 Markdown，不要解释。",
            "2) 保持原任务的字段结构和枚举值。",
            "3) 不要新增用户没有明确表达的 hard_filters。",
            "",
            "原任务：",
            original_prompt,
            "",
            "无效输出：",
            str(invalid_output or "")[:4000],
        ]
    )
