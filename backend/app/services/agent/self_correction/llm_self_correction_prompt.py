import json

from app.services.agent.self_correction.self_correction_evidence import SelfCorrectionEvidence


def build_llm_self_correction_review_prompt(
    *,
    evidence: SelfCorrectionEvidence,
    round_index: int,
    max_rounds: int,
    phase: str,
) -> str:
    payload = {
        "round_index": round_index,
        "max_rounds": max_rounds,
        "phase": phase,
        "evidence": evidence.model_dump(mode="python"),
    }
    return (
        "你是 Agent 自我修正审查器。你的任务是审查当前检索和候选分型是否足以回答本轮用户问题。\n"
        "必须只输出一个 JSON object，不要输出 Markdown，不要输出隐藏推理链。\n"
        "reason_summary 只能写可审计摘要，不得写逐步思维过程。\n"
        "original_query 是最高优先级；history_summary 只能辅助理解省略指代，不能覆盖本轮问题。\n"
        "不得放宽 hard_constraints，不得删除用户明确的 game/source/adult_content/excluded_keywords/exact_title。\n"
        "不得把 support_context 或 off_scope 候选升级为主目标，不得把它们的标题加入核心检索词。\n"
        "如果 direct_match 足够且无明显违约，action=continue_answer。\n"
        "如果 query_plan 有污染，action=repair_query_plan。\n"
        "如果 direct_match 不足且存在可检索 gap，action=refine_retrieval。\n"
        "如果需要重新分型，action=rejudge_candidates。\n"
        "如果无法安全修正，action=fallback_no_direct_match 或 ask_clarification。\n"
        "输出 JSON schema:\n"
        "{\n"
        '  "action": "continue_answer|repair_query_plan|refine_retrieval|rejudge_candidates|fallback_no_direct_match|ask_clarification",\n'
        '  "detected_errors": ["..."],\n'
        '  "reason_summary": "审计摘要",\n'
        '  "correction_plan": {},\n'
        '  "changed_fields": ["..."],\n'
        '  "preserved_constraints": ["..."],\n'
        '  "rejected_changes": ["..."],\n'
        '  "confidence": 0.0\n'
        "}\n\n"
        f"审查输入:\n{json.dumps(payload, ensure_ascii=False, indent=2)}"
    )


def build_llm_self_correction_review_repair_prompt(*, original_prompt: str, invalid_output: str) -> str:
    return (
        "上一次输出不是合法的自我修正审查 JSON。请重新输出一个 JSON object。\n"
        "不要输出 Markdown，不要解释，不要输出隐藏推理链。\n"
        "必须包含字段 action, detected_errors, reason_summary, correction_plan, changed_fields, "
        "preserved_constraints, rejected_changes, confidence。\n\n"
        f"原始任务:\n{original_prompt}\n\n"
        f"非法输出:\n{invalid_output[:2000]}"
    )
