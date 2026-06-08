import json
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

import app.models  # noqa: F401
from app.models.agent_message import AgentMessage
from app.services.agent import conversation_service
from app.services.agent.memory.evidence_service import (
    build_memory_evidence,
    build_memory_writeback_evidence,
    link_understanding_to_evidence,
)
from app.services.agent.memory.memory_service import AgentMemoryService
from app.services.agent.memory.preference_service import PREFERENCES_KEY, AgentPreferenceService
from app.services.agent.schemas import AgentChatResponse, AgentConversationMessage
from app.services.agent.tools.memory_context_tool import MemoryContextInput, MemoryContextTool
from app.services.agent.tools.memory_writeback_tool import MemoryWritebackInput, MemoryWritebackTool
from app.services.settings_service import SettingsService


def _session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def test_memory_service_merges_short_term_and_long_term_context():
    with _session() as session:
        AgentPreferenceService(session).save_preferences(
            {
                "last_query_context": {"game": "Stellar Blade", "source_name": "nexusmods"},
                "favorite_summary": {"top_games": ["Skyrim Special Edition"]},
                "conversation_summary": {"top_sources": ["loverslab"]},
            }
        )
        memory = AgentMemoryService(session).load_memory_context(
            short_term={
                "last_query_context": {"category": "outfit"},
                "active_constraints": {"adult_content": False},
            }
        )

    assert memory["short_term"]["active_constraints"]["adult_content"] is False
    assert memory["long_term"]["favorite_summary"]["top_games"] == ["Skyrim Special Edition"]
    assert memory["merged"]["last_query_context"]["game"] == "Stellar Blade"
    assert memory["merged"]["last_query_context"]["category"] == "outfit"
    assert memory["merged"]["conversation_summary"]["top_sources"] == ["loverslab"]


def test_memory_service_marks_stale_preference_memory():
    with _session() as session:
        old_updated_at = (datetime.now(UTC) - timedelta(days=180)).isoformat()
        pref_service = AgentPreferenceService(session)
        pref_service.save_preferences(
            {
                "favorite_summary": {"top_games": ["Skyrim Special Edition"]},
            }
        )
        current = pref_service.load_preferences()
        current["updated_at"] = old_updated_at
        pref_service.settings.set(PREFERENCES_KEY, json.dumps(current, ensure_ascii=False))
        memory = AgentMemoryService(session).load_memory_context(short_term={"last_query_context": {}})

    assert memory["merged"]["memory_meta"]["preference_stale"] is True
    assert isinstance(memory["merged"]["memory_meta"]["preferences_age_days"], int)
    assert memory["merged"]["memory_meta"]["preferences_age_days"] >= 179


def test_memory_service_merges_semantic_lists_from_long_and_short_context():
    with _session() as session:
        AgentPreferenceService(session).save_preferences(
            {
                "last_query_context": {
                    "keywords": ["bimbo", "怀孕"],
                    "semantic_anchors": ["bimbo", "roleplay", "pregnant"],
                    "semantic_domains": ["mechanics"],
                }
            }
        )
        memory = AgentMemoryService(session).load_memory_context(
            short_term={
                "last_query_context": {
                    "keywords": ["pregnancy", "体系"],
                    "semantic_anchors": ["pregnancy", "bimbo", "system"],
                    "semantic_domains": ["content_type"],
                }
            }
        )

    merged_query = memory["merged"]["last_query_context"]
    assert merged_query["keywords"] == ["bimbo", "pregnancy", "framework"]
    assert merged_query["semantic_anchors"] == ["bimbo", "roleplay", "pregnancy", "framework"]
    assert merged_query["semantic_domains"] == ["mechanics", "content_type"]


def test_memory_context_tool_matches_memory_service_contract():
    with _session() as session:
        AgentPreferenceService(session).save_preferences(
            {
                "last_query_context": {"game": "Stellar Blade", "source_name": "nexusmods"},
                "favorite_summary": {"top_games": ["Skyrim Special Edition"]},
            }
        )
        short_term = {"last_query_context": {"category": "outfit"}}
        direct = AgentMemoryService(session).load_memory_context(short_term=short_term)
        via_tool = MemoryContextTool(session).run(MemoryContextInput(short_term=short_term))

    assert via_tool == direct


def test_memory_context_tool_logs_evidence_id(caplog):
    caplog.set_level(logging.INFO)
    with _session() as session:
        MemoryContextTool(session).run(
            MemoryContextInput(
                short_term={"last_query_context": {"keywords": ["bimbo"]}},
                evidence_id="ev_memory_log",
            )
        )

    assert any(
        "agent.tool name=memory_context_loader status=succeeded" in record.message
        and "evidence_id=ev_memory_log" in record.message
        for record in caplog.records
    )


def test_memory_writeback_tool_persists_current_turn_context_and_logs_evidence(caplog):
    caplog.set_level(logging.INFO)
    with _session() as session:
        result = MemoryWritebackTool(session).run(
            MemoryWritebackInput(
                query="有什么在玩法上可以扮演bimbo的MOD",
                query_plan={
                    "keywords": ["bimbo", "roleplay"],
                    "games": ["Skyrim Special Edition"],
                    "sources": ["loverslab"],
                    "categories": ["Gameplay"],
                    "adult_content": True,
                    "sort_field": "relevance",
                    "evidence_id": "ev_memory_write",
                },
                understanding={
                    "confidence": 0.82,
                    "evidence": [
                        {"field": "semantic_anchors", "value": ["bimbo", "roleplay"]},
                        {"field": "semantic_domains", "value": ["mechanics"]},
                    ],
                },
                evidence_id="ev_memory_write",
            )
        )
        loaded = AgentPreferenceService(session).load_preferences()

    context = loaded["last_query_context"]
    assert result["status"] == "succeeded"
    assert context["source"] == "chat_turn"
    assert context["keywords"] == ["bimbo", "roleplay"]
    assert context["game"] == "Skyrim Special Edition"
    assert context["source_name"] == "loverslab"
    assert context["category"] == "Gameplay"
    assert context["semantic_anchors"] == ["bimbo", "roleplay"]
    assert context["semantic_domains"] == ["mechanics"]
    assert context["quality_score"] == 0.82
    assert any(
        "agent.tool name=memory_writeback status=succeeded" in record.message
        and "evidence_id=ev_memory_write" in record.message
        for record in caplog.records
    )


def test_memory_evidence_service_builds_short_long_and_writeback_fragments():
    memory_context = {
        "short_term": {
            "last_query_context": {"keywords": ["bimbo"], "semantic_anchors": ["roleplay"]},
            "active_constraints": {"adult_content": True},
        },
        "long_term": {
            "favorite_summary": {"top_games": ["Skyrim Special Edition"], "adult_content_allowed": True},
            "conversation_summary": {"top_sources": ["loverslab"]},
        },
        "merged": {
            "memory_meta": {
                "preference_stale": False,
                "preferences_age_days": 3,
                "preferences_updated_at": "2026-05-26T00:00:00+00:00",
            }
        },
    }
    writeback = {
        "status": "succeeded",
        "evidence_id": "ev_memory_fragments",
        "context": {"query": "ignored", "source": "chat_turn", "game": "Skyrim", "keywords": ["bimbo"]},
    }

    evidence = build_memory_evidence(memory_context, evidence_id="ev_memory_fragments")
    evidence.extend(build_memory_writeback_evidence(writeback))

    fragment_ids = {item["fragment_id"] for item in evidence}
    assert "m_short_last_query_keywords" in fragment_ids
    assert "m_short_last_query_semantic_anchors" in fragment_ids
    assert "m_short_constraints_adult_content" in fragment_ids
    assert "m_long_favorite_game" in fragment_ids
    assert "m_long_favorite_adult_content_allowed" in fragment_ids
    assert "m_long_conversation_source" in fragment_ids
    assert "m_long_meta_preferences_age_days" in fragment_ids
    assert "m_writeback_game" in fragment_ids
    assert "m_writeback_keywords" in fragment_ids
    assert all(item["evidence_id"] == "ev_memory_fragments" for item in evidence)


def test_memory_evidence_service_tolerates_invalid_preference_age():
    evidence = build_memory_evidence(
        {
            "merged": {
                "memory_meta": {
                    "preferences_age_days": "stale",
                }
            }
        },
        evidence_id="ev_bad_memory_age",
    )

    age = [item for item in evidence if item["field"] == "preferences_age_days"][0]
    assert age["value"] == 0
    assert age["evidence_id"] == "ev_bad_memory_age"


def test_memory_evidence_service_links_memory_retrieval_and_conflict_fragments():
    response = AgentChatResponse(
        answer="ok",
        used_llm=False,
        matches=[],
        response_cards=None,
        understanding={
            "slots": {"game": "Skyrim Special Edition"},
            "evidence": [
                {"fragment_id": "u_game", "source": "query_plan", "field": "game", "value": "Skyrim Special Edition"},
                {
                    "fragment_id": "u_anchor",
                    "source": "analysis",
                    "field": "semantic_anchors",
                    "value": ["bimbo"],
                },
            ],
        },
        memory_evidence=[
            {
                "fragment_id": "m_short_last_query_semantic_anchors",
                "source": "short_term_memory",
                "field": "semantic_anchors",
                "value": ["bimbo"],
                "evidence_id": "ev_link",
            },
            {
                "fragment_id": "m_long_favorite_game",
                "source": "long_term_favorite",
                "field": "game",
                "value": "Fallout 4",
                "evidence_id": "ev_link",
            },
        ],
        retrieval_evidence=[
            {
                "fragment_id": "r_game_filter",
                "fields": ["game", "games"],
                "evidence_id": "ev_link",
            }
        ],
    )

    link_understanding_to_evidence(response)

    game_evidence = next(item for item in response.understanding["evidence"] if item["field"] == "game")
    anchor_evidence = next(item for item in response.understanding["evidence"] if item["field"] == "semantic_anchors")
    assert "r_game_filter" in game_evidence["related_fragments"]
    assert any(fragment.startswith("m_conflict_hard_conflict_long_term_favorite_game") for fragment in game_evidence["related_fragments"])
    assert "m_short_last_query_semantic_anchors" in anchor_evidence["related_fragments"]
    assert any(item.get("source") == "memory_conflict" for item in response.memory_evidence)


def test_conversation_state_preserves_standard_response_card_keys():
    with _session() as session:
        session.add(
            AgentMessage(
                message_id="m1",
                role="assistant",
                text="ok",
                session_id="s1",
                created_at="2026-05-25T00:00:00+00:00",
                sort_index=0,
                response_cards_json=json.dumps(
                    {
                        "analysis": ["任务分析：识别 bimbo 风格查询。"],
                        "evidence": ["证据：继承上一轮 bimbo 语义锚点。"],
                        "conclusion": ["结论：继续查找相关风格 Mod。"],
                        "understanding": ["兼容旧卡片。"],
                        "empty": [],
                    },
                    ensure_ascii=False,
                ),
            )
        )
        session.commit()

        state = conversation_service.load_conversation_state(session, SettingsService(session))

    cards = state.messages[0].response_cards or {}
    assert list(cards.keys())[:3] == ["analysis", "evidence", "conclusion"]
    assert cards["analysis"] == ["任务分析：识别 bimbo 风格查询。"]
    assert cards["evidence"] == ["证据：继承上一轮 bimbo 语义锚点。"]
    assert cards["conclusion"] == ["结论：继续查找相关风格 Mod。"]
    assert cards["understanding"] == ["兼容旧卡片。"]
    assert "empty" not in cards


def test_conversation_state_skips_bad_matches_without_dropping_good_matches():
    with _session() as session:
        session.add(
            AgentMessage(
                message_id="m1",
                role="assistant",
                text="ok",
                session_id="s1",
                created_at="2026-05-25T00:00:00+00:00",
                sort_index=0,
                matches_json=json.dumps(
                    [
                        {"bad": "shape"},
                        {
                            "id": 1,
                            "title": "Good Match",
                            "source": "nexusmods",
                            "game": "Skyrim Special Edition",
                            "url": "https://example.com/good",
                            "author": None,
                            "version": None,
                            "updated_at_remote": None,
                            "score": 10,
                        },
                    ],
                    ensure_ascii=False,
                ),
            )
        )
        session.commit()

        state = conversation_service.load_conversation_state(session, SettingsService(session))

    assert state.messages[0].matches is not None
    assert [match.title for match in state.messages[0].matches] == ["Good Match"]


def test_conversation_state_round_trips_audit_evidence():
    audit = {
        "analysis": {"intent": "search", "evidence_id": "ev_saved"},
        "evidence": {
            "web_search": {
                "enabled": True,
                "queried": True,
                "tools": ["nexusmods_search"],
                "tool_statuses": {"nexusmods_search": "succeeded"},
                "tool_result_counts": {"nexusmods_search": 2},
            }
        },
        "conclusion": {"recommended_action": "expand_online_sources_and_narrow_scope"},
    }
    with _session() as session:
        settings = SettingsService(session)
        saved = conversation_service.save_conversation_state(
            body=conversation_service.AgentConversationStateSaveRequest(
                active_session_id="s1",
                messages=[
                    AgentConversationMessage(
                        id="m1",
                        role="assistant",
                        text="ok",
                        session_id="s1",
                        audit=audit,
                    )
                ],
            ),
            session=session,
            settings=settings,
        )
        reloaded = conversation_service.load_conversation_state(session, settings)

    assert saved.messages[0].audit is not None
    assert saved.messages[0].audit.evidence.web_search is not None
    assert saved.messages[0].audit.evidence.web_search.tool_statuses == {"nexusmods_search": "succeeded"}
    assert saved.messages[0].audit.evidence.web_search.tool_result_counts == {"nexusmods_search": 2}
    assert reloaded.messages[0].audit is not None
    assert reloaded.messages[0].audit.analysis.evidence_id == "ev_saved"
    assert reloaded.messages[0].audit.evidence.web_search is not None
    assert reloaded.messages[0].audit.evidence.web_search.tool_statuses == {"nexusmods_search": "succeeded"}
    assert reloaded.messages[0].audit.conclusion.recommended_action == "expand_online_sources_and_narrow_scope"


def test_conversation_state_save_rolls_back_when_settings_update_fails():
    class FailingSettings(SettingsService):
        def set(self, key: str, value: str, *, commit: bool = True) -> None:
            if key.startswith(conversation_service.AGENT_CHAT_LAST_UPDATE_PREFIX):
                raise RuntimeError("settings write failed")
            super().set(key, value, commit=commit)

    with _session() as session:
        settings = FailingSettings(session)
        try:
            conversation_service.save_conversation_state(
                body=conversation_service.AgentConversationStateSaveRequest(
                    active_session_id="s1",
                    messages=[
                        AgentConversationMessage(
                            id="m1",
                            role="assistant",
                            text="ok",
                            session_id="s1",
                        )
                    ],
                ),
                session=session,
                settings=settings,
            )
        except RuntimeError:
            pass
        else:
            raise AssertionError("expected settings failure")

        assert session.exec(select(AgentMessage)).all() == []
        assert SettingsService(session).get(conversation_service.AGENT_CHAT_ACTIVE_SESSION_KEY) is None
