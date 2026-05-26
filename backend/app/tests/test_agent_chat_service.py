import pytest

from app.services.agent.chat_service import AgentService
from app.services.agent.planning.context_plan_merge import merge_context_query_plan, merge_llm_context_query_plan
from app.services.agent.planning.tool_plan_merge import apply_tool_plan_to_query_plan
from app.services.agent.runtime import AgentRuntime
from app.services.agent.schemas import AgentChatRequest, AgentModDetailRequest


class _SessionWithoutMods:
    def get(self, model, key):  # noqa: ARG002
        return None


def test_agent_service_keeps_session_dependency():
    service = AgentService(session=None)

    assert service.session is None
    assert hasattr(service, "chat")
    assert hasattr(service, "ask_mod_detail")


def test_agent_runtime_keeps_session_dependency():
    runtime = AgentRuntime(session=None)

    assert runtime.session is None
    assert runtime.last_trace == []
    assert hasattr(runtime, "chat")
    assert hasattr(runtime, "ask_mod_detail")


@pytest.mark.asyncio
async def test_agent_service_empty_query_uses_standard_response_cards():
    response = await AgentService(session=None).chat(AgentChatRequest(message="   "), request=object())

    assert response.answer == "请输入要查询的内容。"
    assert response.matches == []
    assert isinstance(response.evidence_id, str)
    assert response.evidence_id.startswith("ev_")
    assert list((response.response_cards or {}).keys())[:3] == ["analysis", "evidence", "conclusion"]
    assert response.response_cards["conclusion"][0] == "结论：需要先提供查询内容。"


@pytest.mark.asyncio
async def test_agent_service_missing_mod_detail_uses_standard_response_cards():
    response = await AgentService(session=_SessionWithoutMods()).ask_mod_detail(
        AgentModDetailRequest(mod_id=404),
        request=object(),
    )

    assert response.answer == "未找到该 Mod。"
    assert response.matches == []
    assert list((response.response_cards or {}).keys())[:3] == ["analysis", "evidence", "conclusion"]
    assert response.response_cards["evidence"] == ["证据：本地数据库未找到对应 Mod。"]


def test_context_query_plan_fills_only_missing_slots():
    merged = merge_context_query_plan(
        {
            "keywords": ["outfit"],
            "games": ["Skyrim"],
            "adult_content": None,
        },
        {
            "games": ["Stellar Blade"],
            "sources": ["nexusmods"],
            "adult_content": True,
            "sort_field": "updated_at_remote",
            "sort_order": "desc",
        },
    )

    assert merged["games"] == ["Skyrim"]
    assert merged["sources"] == ["nexusmods"]
    assert merged["adult_content"] is True
    assert merged["sort_field"] == "updated_at_remote"


def test_context_query_plan_replaces_weak_followup_keywords():
    merged = merge_context_query_plan(
        {"keywords": ["风格的"], "adult_content": None},
        {"keywords": ["bimbo"], "adult_content": False},
    )

    assert merged["keywords"] == ["bimbo"]
    assert merged["adult_content"] is False


def test_context_query_plan_keeps_current_strong_keywords():
    merged = merge_context_query_plan(
        {"keywords": ["cbbe"], "adult_content": None},
        {"keywords": ["bimbo"], "adult_content": False},
    )

    assert merged["keywords"] == ["cbbe"]


def test_context_query_plan_does_not_replace_new_topic_keywords():
    merged = merge_context_query_plan(
        {"keywords": ["cyberpunk", "vehicle"], "adult_content": None},
        {"keywords": ["bimbo"], "adult_content": False},
    )

    assert merged["keywords"] == ["cyberpunk", "vehicle"]


def test_context_query_plan_keeps_internal_agent_hints():
    merged = merge_context_query_plan(
        {"keywords": ["bimbo"]},
        {"_agent_conservative_mode": True},
    )

    assert merged["_agent_conservative_mode"] is True


def test_llm_context_query_plan_does_not_backfill_current_turn_fallback_slots():
    merged = merge_llm_context_query_plan(
        {"keywords": ["framework"]},
        {"sources": ["loverslab"], "keywords": ["bimbo"], "_agent_context_signal": {"inherited": False}},
    )

    assert merged["keywords"] == ["framework"]
    assert "sources" not in merged
    assert merged["_agent_context_signal"]["inherited"] is False


def test_llm_context_query_plan_can_fill_explicitly_inherited_scope():
    merged = merge_llm_context_query_plan(
        {"keywords": ["related"]},
        {
            "games": ["Skyrim Special Edition"],
            "sources": ["loverslab"],
            "_agent_context_signal": {"inherited": True, "topic_shift": False},
        },
    )

    assert merged["keywords"] == ["related"]
    assert merged["games"] == ["Skyrim Special Edition"]
    assert merged["sources"] == ["loverslab"]


def test_llm_context_query_plan_preserves_result_reference_exact_title():
    merged = merge_llm_context_query_plan(
        {"intent": "install_risk", "keywords": ["risk"]},
        {
            "keywords": ["Stable Bimbo Preset"],
            "exact_title": "Stable Bimbo Preset",
            "_agent_result_reference_signal": {
                "applied": True,
                "fields": ["keywords", "exact_title"],
            },
        },
    )

    assert merged["exact_title"] == "Stable Bimbo Preset"
    assert merged["keywords"] == ["Stable Bimbo Preset"]


def test_llm_context_query_plan_preserves_result_reference_exclusions_without_context_inherit():
    merged = merge_llm_context_query_plan(
        {"intent": "search", "keywords": ["similar"]},
        {
            "exclude_titles": ["Bimbo Body Morph"],
            "_agent_result_reference_signal": {
                "applied": True,
                "fields": ["exclude_titles"],
                "has_explicit_reference": False,
            },
            "_agent_context_signal": {"inherited": False},
        },
    )

    assert merged["keywords"] == ["similar"]
    assert merged["exclude_titles"] == ["Bimbo Body Morph"]


def test_llm_context_query_plan_preserves_referenced_similarity_keywords():
    merged = merge_llm_context_query_plan(
        {"intent": "search", "keywords": ["similar"]},
        {
            "keywords": ["doll", "face", "preset"],
            "keyword_match_mode": "all",
            "_agent_result_reference_signal": {
                "applied": True,
                "fields": ["keywords", "keyword_match_mode"],
            },
        },
    )

    assert merged["keywords"] == ["doll", "face", "preset"]
    assert merged["keyword_match_mode"] == "all"


def test_tool_plan_merge_applies_conservative_execution_hint():
    merged = apply_tool_plan_to_query_plan(
        {"keywords": ["ambiguous"]},
        {"planning_evidence": {"conservative_mode": True}},
    )

    assert merged["_agent_conservative_mode"] is True
