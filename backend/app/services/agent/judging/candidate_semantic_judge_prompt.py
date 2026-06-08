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
            "10) 必须判断 category_semantic_compatibility：compatible、ambiguous、incompatible、not_applicable。",
            "11) category 是来源站点的粗标签，不等于用户语义目标；不要机械地因为 category 不同就判 off_scope。",
            "12) 当用户目标是服装、穿搭、outfit、clothing、女性服装、外观穿戴时，候选 category=Armour/Armor 但 title/summary 明确包含 bikini、lingerie、dress、outfit、robe、clothing、straps、heels、stockings、UNP、CBBE、BHUNP、3BA 等穿戴/身体服装证据，可判 category_semantic_compatibility=compatible。",
            "13) category 语义兼容只解决分类标签不一致问题；仍需检查游戏、内容分级、性别/身体体系、用户排除条件等硬约束。",
            "14) 如果 category 冲突且 title/summary 没有语义证据，设为 ambiguous 或 incompatible，并解释原因。",
            "15) 不要要求候选标题或摘要逐字包含用户问题原句；要用字段语义判断。",
            "16) 用户说“天际/Skyrim”时，优先用 candidate.game 或 game_domain 判断，不要求 title/summary 写“天际”。",
            "17) 用户说“R18/NSFW/adult”时，优先用 adult_content=true 判断，不要求 title/summary 写“R18”。",
            "18) 用户说“女性服装”时，可用 title/summary/category 中的 bikini、lingerie、dress、minidress、babydoll、bunny suit、outfit、clothes、CBBE、UNP、BHUNP、3BA 等证据判断；不要只因为没有“女性服装”四个字就降为 support_context。",
            "19) 若 game 符合、adult_content=true、且有明确穿戴/女性身体体系/服装证据，应优先判 direct_match；只有身体模型、补丁、翻译、随从、非穿戴项才降为 support_context 或 off_scope。",
            "",
            "JSON 结构：",
            "{",
            '  "judgements": [',
            '    {"candidate_id": 1, "relevance": "high|medium|low|reject", "fit_type": "direct_match|support_context|off_scope|uncertain", "group": "core_gameplay|visual_support|follower_or_npc|requirement_or_patch|related_addon|other_related|off_topic", "category_semantic_compatibility": "compatible|ambiguous|incompatible|not_applicable", "category_compatibility_reason": "分类语义兼容判断", "reason": "简短理由", "evidence": [string], "violations": [string]}',
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
            "2) relevance、fit_type、group、category_semantic_compatibility 必须使用允许的枚举值。",
            "3) category_semantic_compatibility 只能是 compatible、ambiguous、incompatible、not_applicable。",
            "4) candidate_id 必须来自原始 candidates。",
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
