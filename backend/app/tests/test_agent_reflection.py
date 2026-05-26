from app.services.agent.reflection.answer_critic import critique_answer
from app.services.agent.reflection.plan_critic import critique_plan
from app.services.agent.reflection.reflection_service import run_reflection
from app.services.agent.reflection.result_critic import critique_results


def test_plan_critic_blocks_unknown_tools():
    result = critique_plan({"steps": [{"tool": "unsafe_url_fetch"}]})

    assert result["stage"] == "plan_critic"
    assert result["actions"][0]["type"] == "answer_with_limitations"
    assert "工具白名单" in result["public_summary"]


def test_result_critic_requests_online_when_results_are_sparse():
    result = critique_results(result_count=1, local_results_below_threshold=True)

    assert {"type": "run_tool_group", "target": "online_retrieval"} in [
        {"type": item["type"], "target": item["target"]} for item in result["actions"]
    ]


def test_answer_critic_reports_missing_rank_reason():
    result = critique_answer(matches=[{"title": "A"}], answer="推荐 A")

    assert result["actions"][0]["type"] == "answer_with_limitations"
    assert "依据" in result["public_summary"]


def test_reflection_service_never_exposes_raw_reasoning():
    result = run_reflection(
        stage="plan",
        payload={"steps": [{"tool": "unsafe_url_fetch"}], "chain_of_thought": "hidden"},
    )

    assert "chain_of_thought" not in str(result)
    assert result["stage"] == "plan_critic"
