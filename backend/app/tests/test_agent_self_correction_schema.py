import pytest
from pydantic import ValidationError

from app.services.agent.self_correction.self_correction_schema import (
    SelfCorrectionConfig,
    SelfCorrectionRound,
    SelfCorrectionTrace,
    default_self_correction_config,
    with_default_self_correction_config,
)


def test_default_self_correction_config_requires_llm_review():
    config = SelfCorrectionConfig()

    assert config.enabled is True
    assert config.llm_review_required is True
    assert config.max_rounds == 2
    assert config.allow_rule_only_review is False
    assert default_self_correction_config()["llm_review_required"] is True


def test_self_correction_config_rejects_invalid_max_rounds():
    with pytest.raises(ValidationError):
        SelfCorrectionConfig(max_rounds=0)

    with pytest.raises(ValidationError):
        SelfCorrectionConfig(max_rounds=4)


def test_self_correction_round_normalizes_audit_lists():
    round_item = SelfCorrectionRound(
        round_index=1,
        phase="round_review",
        llm_review_status="passed",
        action="refine_retrieval",
        detected_errors=["direct_match不足", "direct_match不足", ""],
        reason_summary="x" * 700,
        changed_fields=["keywords", "keywords"],
        preserved_constraints=["game=skyrim"],
        candidate_counts_before={"direct_match": 0},
    )

    assert round_item.detected_errors == ["direct_match不足"]
    assert round_item.changed_fields == ["keywords"]
    assert len(round_item.reason_summary) == 500


def test_self_correction_trace_rejects_invalid_phase():
    with pytest.raises(ValidationError):
        SelfCorrectionTrace(
            rounds=[
                {
                    "round_index": 1,
                    "phase": "free_thinking",
                    "llm_review_status": "passed",
                    "action": "continue_answer",
                }
            ]
        )


def test_query_plan_attaches_default_self_correction_config():
    plan = with_default_self_correction_config({"game": "skyrimspecialedition"})

    assert plan["game"] == "skyrimspecialedition"
    assert plan["_agent_self_correction_config"] == default_self_correction_config()


def test_query_plan_invalid_self_correction_config_falls_back_to_default():
    plan = with_default_self_correction_config({"_agent_self_correction_config": {"max_rounds": 99}})

    assert plan["_agent_self_correction_config"] == default_self_correction_config()
