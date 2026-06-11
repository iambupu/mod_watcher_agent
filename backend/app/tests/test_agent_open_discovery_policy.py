# 中文注释：说明 backend/app/tests/test_agent_open_discovery_policy.py 的模块职责，便于后续维护定位。

from app.services.agent.planning.open_discovery_policy import (
    JUDGE_CANDIDATE_LIMIT,
    OPEN_DISCOVERY_DISPLAY_LIMIT,
    OPEN_DISCOVERY_POOL_LIMIT,
    apply_open_discovery_executor_policy,
    is_open_discovery_plan,
    judge_candidate_pool_limit,
    open_discovery_result_limit,
)


def test_open_discovery_policy_tolerates_invalid_limits():
    plan = {"limit": "many", "candidate_pool_limit": "-5"}

    apply_open_discovery_executor_policy(plan)

    assert plan["limit"] == OPEN_DISCOVERY_DISPLAY_LIMIT
    assert plan["candidate_pool_limit"] == OPEN_DISCOVERY_POOL_LIMIT
    assert open_discovery_result_limit(plan, default_limit=8) == OPEN_DISCOVERY_POOL_LIMIT


def test_open_discovery_limits_are_positive_for_bad_non_open_plan():
    assert open_discovery_result_limit({"limit": "-5"}, default_limit=8) == 1
    assert judge_candidate_pool_limit({}, display_limit=12) == min(12 * 4, JUDGE_CANDIDATE_LIMIT)


def test_open_discovery_policy_treats_string_false_as_disabled():
    plan = {"open_discovery": "false", "retrieval_mode": "fuzzy", "limit": 8, "candidate_pool_limit": 60}

    assert is_open_discovery_plan(plan) is False
    assert open_discovery_result_limit(plan, default_limit=8) == 8
