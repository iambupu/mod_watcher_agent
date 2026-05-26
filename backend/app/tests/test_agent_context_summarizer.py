from app.services.agent.context.context_summarizer import summarize_agent_context
from app.services.agent.schemas import AgentChatRequest, AgentHistoryItem
from app.services.agent.tools.context_summary_tool import ContextSummaryTool


def _item(role: str, text: str) -> AgentHistoryItem:
    return AgentHistoryItem(role=role, text=text)


def test_context_summary_keeps_recent_messages_and_summarizes_older_context():
    history = [
        _item("user", "我想找 Stellar Blade 成人服装 Mod"),
        _item("assistant", "我会按 Stellar Blade 和成人内容查找。"),
        _item("user", "优先 NexusMods，按最近更新排序"),
        _item("assistant", "已记录 NexusMods 和最近更新。"),
        _item("user", "继续找类似的"),
        _item("assistant", "可以继续。"),
    ]
    request = AgentChatRequest(message="再找一些", history=history)

    context = summarize_agent_context(request, recent_message_count=3)

    assert [item.text for item in context["recent_messages"]] == [
        "已记录 NexusMods 和最近更新。",
        "继续找类似的",
        "可以继续。",
    ]
    assert "Stellar Blade" in context["running_summary"]
    assert "成人服装" in context["running_summary"]
    assert context["active_constraints"]["game"] == "Stellar Blade"
    assert context["active_constraints"]["source"] == "nexusmods"
    assert context["active_constraints"]["sort_field"] == "updated_at_remote"
    assert context["active_constraints"]["adult_content"] is True


def test_context_summary_preserves_current_explicit_adult_content_override():
    history = [
        _item("user", "找 Stellar Blade R18 服装"),
        _item("assistant", "已按成人内容筛选。"),
    ]
    request = AgentChatRequest(message="这次只看非成人内容", history=history)

    context = summarize_agent_context(request)

    assert context["active_constraints"]["adult_content"] is False
    assert "非成人" in context["running_summary"]


def test_context_summary_prefers_current_game_over_history():
    history = [
        _item("user", "找 Stellar Blade 服装"),
        _item("assistant", "已按 Stellar Blade 查询。"),
    ]
    request = AgentChatRequest(message="现在换成 Skyrim 最近更新", history=history)

    context = summarize_agent_context(request)

    assert context["active_constraints"]["game"] == "Skyrim"


def test_context_summary_does_not_inherit_history_constraints_for_new_strong_topic():
    history = [
        _item("user", "Skyrim Special Edition 有什么 bimbo 化成人 mod，优先 LoversLab 最近更新"),
        _item("assistant", "已按 Skyrim、LoversLab、成人内容和最近更新查询。"),
    ]
    request = AgentChatRequest(message="cyberpunk vehicle handling overhaul mod", history=history)

    context = summarize_agent_context(request)

    assert "game" not in context["active_constraints"]
    assert "source" not in context["active_constraints"]
    assert "adult_content" not in context["active_constraints"]
    assert "sort_field" not in context["active_constraints"]
    assert context["last_query_context"]["source"] == "current"
    assert "cyberpunk" in context["last_query_context"]["keywords"]


def test_context_summary_keeps_previous_keywords_for_contextual_followup():
    history = [
        _item("user", "有什么 Skyrim 最近更新的 bimbo 化 mod"),
        _item("assistant", "我会查找 bimbo 相关风格。"),
    ]
    request = AgentChatRequest(message="有什么相关风格的mod", history=history)

    context = summarize_agent_context(request)

    assert "bimbo" in context["last_query_context"]["keywords"]
    assert context["last_query_context"]["game"] == "Skyrim"
    assert context["last_query_context"]["sort_field"] == "updated_at_remote"
    assert float(context["last_query_context"]["quality_score"]) >= 0.4


def test_context_summary_uses_history_for_relational_refinement_with_strong_keywords():
    history = [
        _item("user", "Skyrim bimbo mod"),
        _item("assistant", "I will search Skyrim bimbo mods first."),
    ]
    request = AgentChatRequest(message="find similar bimbo mods, non adult content", history=history)

    context = summarize_agent_context(request)

    assert context["last_query_context"]["source"] == "recent_user"
    assert context["last_query_context"]["game"] == "Skyrim"
    assert "bimbo" in context["last_query_context"]["keywords"]
    assert context["active_constraints"]["adult_content"] is False
    assert "game" not in context["active_constraints"]


def test_context_summary_extracts_shown_mod_titles_from_assistant_history():
    history = [
        _item("user", "有什么 Skyrim bimbo mod"),
        _item(
            "assistant",
            "找到以下相关 Mod：\n\n[shown_mods]\n"
            "1. title=Bimbo Body Morph; source=nexusmods; game=Skyrim Special Edition; category=Body\n"
            "2. title=Realistic Armor Overhaul; source=nexusmods; game=Skyrim Special Edition; category=Armor",
        ),
    ]
    request = AgentChatRequest(message="还有其他类似的吗", history=history)

    context = summarize_agent_context(request)

    assert context["shown_mod_titles"] == ["Bimbo Body Morph", "Realistic Armor Overhaul"]


def test_context_summary_drops_noisy_mojibake_keywords_from_last_query_context():
    history = [
        _item("user", "����Ҫ SKSE ǰ�õ� Skyrim Special Edition utility mod"),
        _item("assistant", "已记录你的需求。"),
    ]
    request = AgentChatRequest(message="继续找类似的", history=history)

    context = summarize_agent_context(request)

    keywords = context["last_query_context"].get("keywords") or []
    assert all("�" not in str(token) for token in keywords)
    assert "skse" in keywords


def test_context_summary_keeps_normal_ascii_keywords():
    history = [
        _item("user", "Skyrim Special Edition utility mod requiring script extender"),
        _item("assistant", "已记录你的需求。"),
    ]
    request = AgentChatRequest(message="继续找类似的", history=history)

    context = summarize_agent_context(request)

    keywords = context["last_query_context"].get("keywords") or []
    assert "skyrim" in keywords
    assert "utility" in keywords
    assert float(context["last_query_context"].get("quality_score") or 0.0) > 0


def test_context_summary_persists_semantic_anchors_in_last_query_context():
    history = [
        _item("user", "有什么mod支持怀孕玩法"),
        _item("assistant", "我会优先检索 pregnancy gameplay 相关结果。"),
    ]
    request = AgentChatRequest(message="继续找相关的", history=history)

    context = summarize_agent_context(request)

    last_context = context["last_query_context"]
    assert "semantic_anchors" in last_context
    assert "pregnancy" in (last_context.get("semantic_anchors") or [])
    assert "semantic_domains" in last_context
    assert "mechanics" in (last_context.get("semantic_domains") or [])


def test_context_summary_tool_matches_summarizer_contract():
    history = [
        _item("user", "有什么 Skyrim 最近更新的 bimbo 化 mod"),
        _item("assistant", "我会查找 bimbo 相关风格。"),
    ]
    request = AgentChatRequest(message="有什么相关风格的mod", history=history)

    direct = summarize_agent_context(request)
    via_tool = ContextSummaryTool().run(request)

    assert via_tool["active_constraints"] == direct["active_constraints"]
    assert via_tool["last_query_context"] == direct["last_query_context"]
    assert via_tool["shown_mod_titles"] == direct["shown_mod_titles"]


def test_context_summary_tool_logs_evidence_id(caplog):
    request = AgentChatRequest(message="有什么相关风格的mod", history=[])

    with caplog.at_level("INFO"):
        ContextSummaryTool().run(request, evidence_id="ev_context_summary")

    assert any(
        "agent.tool name=context_summary status=succeeded" in item.message
        and "evidence_id=ev_context_summary" in item.message
        for item in caplog.records
    )
