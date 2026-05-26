from typing import Any


def critique_answer(*, matches: list[dict[str, Any]], answer: str) -> dict[str, Any]:
    missing_reason = bool(matches) and not any(item.get("rank_reason") for item in matches)
    if missing_reason:
        return {
            "stage": "answer_critic",
            "confidence": 0.6,
            "issues": ["回答缺少排序依据"],
            "actions": [{"type": "answer_with_limitations", "target": "answer", "reason": "补充推荐依据"}],
            "public_summary": "回答需要补充推荐依据和限制说明。",
        }
    return {
        "stage": "answer_critic",
        "confidence": 0.9 if answer.strip() else 0.2,
        "issues": [] if answer.strip() else ["回答为空"],
        "actions": [] if answer.strip() else [{"type": "answer_with_limitations", "target": "answer"}],
        "public_summary": "回答已通过基础依据检查。",
    }
