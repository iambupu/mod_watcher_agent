from typing import Any

from app.services.agent.schemas import AgentModMatch
from app.utils.json import json_text


def build_candidate_semantic_judge_prompt(
    *,
    query: str,
    semantic_strategy: dict[str, Any],
    candidates: list[AgentModMatch],
    retrieval_evidence: list[dict[str, object]],
) -> str:
    """构造候选语义裁判提示词：让 LLM 判断候选相关性，不让它发明新候选。"""
    return "\n".join(
        [
            "你是 Mod 查询 Agent 的 Candidate Semantic Judge。你的任务是基于用户问题和候选列表判断相关性、分组和缺口。",
            "",
            "重要边界：",
            "1) 只输出 JSON 对象，不要 Markdown，不要解释。",
            "2) 只能评价 candidates 中已经给出的候选，不能编造新的 MOD、链接、版本或作者。",
            "3) relevance 只能是 high、medium、low、reject。",
            "4) fit_type 只能是 direct_match、support_context、off_scope、uncertain。",
            "5) reject/off_scope 表示候选不应进入最终推荐；support_context 只能作为辅助上下文；direct_match 才能作为主结果。",
            "6) low 表示可作为弱相关补充但不能放在前面。",
            "7) group 只能从 core_gameplay、visual_support、follower_or_npc、requirement_or_patch、related_addon、other_related、off_topic 中选择。",
            "8) gaps 用来描述当前候选集缺少什么证据或类型，不是让你直接生成检索结果。",
            "9) 根据 semantic_strategy 中的问题契约判断直接命中和辅助上下文；扩展词命中的候选不能自动升级为主结果。",
            "",
            "JSON 结构：",
            "{",
            '  "judgements": [',
            '    {"candidate_id": 1, "relevance": "high|medium|low|reject", "fit_type": "direct_match|support_context|off_scope|uncertain", "group": "core_gameplay|visual_support|follower_or_npc|requirement_or_patch|related_addon|other_related|off_topic", "reason": "简短理由", "evidence": [string], "violations": [string]}',
            "  ],",
            '  "groups": [{"name": "core_gameplay", "label": "核心玩法", "candidate_ids": [1], "reason": "为什么这样分组"}],',
            '  "gaps": [string],',
            '  "rejected": [{"candidate_id": 2, "reason": "为什么剔除"}]',
            "}",
            "",
            f"用户问题：{query}",
            "",
            "semantic_strategy：",
            json_text(semantic_strategy),
            "",
            "retrieval_evidence 摘要：",
            json_text(_compact_evidence(retrieval_evidence)),
            "",
            "candidates：",
            json_text([_candidate_payload(item) for item in candidates[:60]]),
        ]
    )


def build_candidate_semantic_judge_repair_prompt(*, original_prompt: str, invalid_output: str) -> str:
    return "\n".join(
        [
            "上一次输出不是合法 JSON，或不符合 CandidateSemanticJudge schema。请修正。",
            "严格要求：",
            "1) 只输出一个 JSON 对象，不要 Markdown，不要解释。",
            "2) relevance 和 group 必须使用允许的枚举值。",
            "3) candidate_id 必须来自原始 candidates。",
            "",
            "原任务：",
            original_prompt,
            "",
            "无效输出：",
            str(invalid_output or "")[:4000],
        ]
    )


def _candidate_payload(item: AgentModMatch) -> dict[str, object]:
    return {
        "candidate_id": item.id,
        "title": item.title,
        "source": item.source,
        "game": item.game,
        "category": item.category,
        "adult_content": item.adult_content,
        "rank_reason": item.rank_reason,
        "summary": (item.translated_summary or item.original_summary or "")[:700],
    }


def _compact_evidence(evidence: list[dict[str, object]]) -> list[dict[str, object]]:
    compacted: list[dict[str, object]] = []
    for item in evidence[-8:]:
        compacted.append(
            {
                "stage": item.get("stage"),
                "tool": item.get("tool"),
                "count": item.get("count") or item.get("result_count") or item.get("returned_count"),
                "reason": item.get("reason"),
            }
        )
    return compacted
