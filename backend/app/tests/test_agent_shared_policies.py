import importlib
import importlib.util


def test_specific_mod_question_marker_has_one_shared_policy():
    module_name = "app.services.agent.routing.question_policy"
    assert importlib.util.find_spec(module_name) is not None
    policy = importlib.import_module(module_name)

    assert policy.has_specific_mod_question_marker("这个 Mod 怎么安装？") is True
    assert policy.has_specific_mod_question_marker("给我推荐一些服装") is False


def test_tool_plan_policy_normalizes_tools_and_online_recall_mode():
    module_name = "app.services.agent.planning.tool_plan_policy"
    assert importlib.util.find_spec(module_name) is not None
    policy = importlib.import_module(module_name)
    tool_plan = {
        "parallel_groups": [{"tools": ["sqlite_fts", "web_search", ""]}],
        "online_steps": [{"tool": "loverslab_google"}],
        "tool_policy_evidence": {"online_recall_mode": "narrow"},
    }

    assert policy.planned_tools(tool_plan) == {
        "sqlite_fts",
        "web_search",
        "loverslab_google",
    }
    assert policy.online_recall_mode(tool_plan) == "narrow"
    assert policy.online_recall_mode({}) == "broad"
    assert policy.allowed_online_tools(policy.planned_tools(tool_plan)) == {
        "nexusmods_search",
        "loverslab_google",
        "loverslab_scrape",
    }


def test_retrieval_policy_reserves_current_only_results_consistently():
    module_name = "app.services.agent.planning.retrieval_policy"
    assert importlib.util.find_spec(module_name) is not None
    policy = importlib.import_module(module_name)

    assert policy.current_only_reserved(limit=10, current_only_count=0) == 0
    assert policy.current_only_reserved(limit=1, current_only_count=4) == 1
    assert policy.current_only_reserved(limit=4, current_only_count=5) == 2
    assert policy.current_only_reserved(limit=20, current_only_count=5) == 3


def test_query_plan_contract_reads_only_mapping_semantic_strategy():
    contract = importlib.import_module("app.services.agent.planning.query_plan_contract")
    strategy = {"task_type": "open_discovery"}

    assert contract.semantic_strategy({"_agent_semantic_strategy": strategy}) is strategy
    assert contract.semantic_strategy({"_agent_semantic_strategy": "invalid"}) == {}
    assert contract.semantic_strategy(None) == {}
