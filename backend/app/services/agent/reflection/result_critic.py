def critique_results(*, result_count: int, local_results_below_threshold: bool) -> dict:
    actions = []
    issues = []
    if result_count < 3:
        issues.append("结果数量不足 3 条")
    if local_results_below_threshold:
        actions.append(
            {
                "type": "run_tool_group",
                "target": "online_retrieval",
                "reason": "本地结果不足，补查在线来源",
            }
        )
    return {
        "stage": "result_critic",
        "confidence": 0.65 if issues else 0.9,
        "issues": issues,
        "actions": actions,
        "public_summary": "本地结果较少，建议补查在线来源。" if actions else "召回结果数量满足当前阈值。",
    }
