from typing import Any

from app.services.agent.reflection.answer_critic import critique_answer
from app.services.agent.reflection.plan_critic import critique_plan
from app.services.agent.reflection.result_critic import critique_results


def run_reflection(*, stage: str, payload: dict[str, Any]) -> dict[str, Any]:
    sanitized = {key: value for key, value in payload.items() if key != "chain_of_thought"}
    if stage == "plan":
        return critique_plan(sanitized)
    if stage == "result":
        return critique_results(
            result_count=int(sanitized.get("result_count") or 0),
            local_results_below_threshold=bool(sanitized.get("local_results_below_threshold")),
        )
    if stage == "answer":
        return critique_answer(
            matches=list(sanitized.get("matches") or []),
            answer=str(sanitized.get("answer") or ""),
        )
    return {
        "stage": "reflection",
        "confidence": 0.5,
        "issues": ["未知自检阶段"],
        "actions": [{"type": "answer_with_limitations", "target": stage}],
        "public_summary": "无法识别自检阶段，已保守降级。",
    }
