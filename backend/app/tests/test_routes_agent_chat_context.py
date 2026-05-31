import json
import logging
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.db import get_session
from app.main import app as fastapi_app
from app.models.mod import Mod
from app.models.settings import Setting
from app.models.summary import ModSummary
from app.services import llm_provider_config
from app.services.agent import llm_config_service
from app.services.agent import runtime as runtime_module
from app.services.agent.answer_service import AgentAnswerService
from app.services.agent.schemas import AgentChatResponse
from app.services.agent.search_types import SearchResult
from app.services.agent.tools.llm_candidate_validator_tool import (
    LlmCandidateValidatorOutput,
    LlmCandidateValidatorTool,
)
from app.services.agent.tools.nexusmods_search_tool import NexusModsSearchTool


@pytest.fixture(name="engine")
def engine_fixture():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    yield engine


@pytest.fixture(name="client")
def client_fixture(engine):
    def override_get_session():
        with Session(engine) as session:
            yield session

    fastapi_app.dependency_overrides[get_session] = override_get_session
    yield TestClient(fastapi_app)
    fastapi_app.dependency_overrides.clear()


def _seed_mods(engine) -> None:
    with Session(engine) as session:
        session.add_all(
            [
                Mod(
                    source="nexusmods",
                    external_id="bimbo-1",
                    game="Skyrim Special Edition",
                    game_domain="skyrimspecialedition",
                    title="Bimbo Body Morph",
                    url="https://example.com/bimbo",
                    category="Body",
                    original_summary="A bimbo transformation style preset.",
                    first_seen_at="2026-05-20T00:00:00+00:00",
                    last_seen_at="2026-05-20T00:00:00+00:00",
                    adult_content=False,
                ),
                Mod(
                    source="nexusmods",
                    external_id="armor-1",
                    game="Skyrim Special Edition",
                    game_domain="skyrimspecialedition",
                    title="Realistic Armor Overhaul",
                    url="https://example.com/armor",
                    category="Armor",
                    original_summary="A lore friendly armor replacement.",
                    first_seen_at="2026-05-19T00:00:00+00:00",
                    last_seen_at="2026-05-19T00:00:00+00:00",
                    adult_content=False,
                ),
            ]
        )
        session.commit()


def _seed_skyrim_bimbo_open_discovery_mods(engine) -> None:
    with Session(engine) as session:
        session.add_all(
            [
                Mod(
                    source="loverslab",
                    external_id="skyrimspecialedition:24435",
                    game="skyrimspecialedition",
                    title="Bimbos Of Skyrim LE SE",
                    url="https://example.com/bimbos-of-skyrim",
                    category="Bimbos Of Skyrim",
                    original_summary="BIMBOS OF SKYRIM adds bimbofied NPCs, quests, and player progression.",
                    first_seen_at="2026-05-20T00:00:00+00:00",
                    last_seen_at="2026-05-20T00:00:00+00:00",
                    adult_content=True,
                ),
                Mod(
                    source="loverslab",
                    external_id="skyrimspecialedition:47968",
                    game="skyrimspecialedition",
                    title="Bimbos of Skyrim - BimboLips",
                    url="https://example.com/bimbolips",
                    category="Bimbos of Skyrim",
                    original_summary="A Bimbos of Skyrim plugin adding bimbo lip changes based on progression.",
                    first_seen_at="2026-05-19T00:00:00+00:00",
                    last_seen_at="2026-05-19T00:00:00+00:00",
                    adult_content=True,
                ),
                Mod(
                    source="nexusmods",
                    external_id="skyrimspecialedition:156753",
                    game="Skyrim Special Edition",
                    game_domain="skyrimspecialedition",
                    title="Bimbos of Skyrim - Charismatic HPH Overhaul",
                    url="https://example.com/charismatic-hph",
                    category="Overhauls",
                    original_summary="Overhaul of Bimbos of Skyrim female NPCs.",
                    first_seen_at="2026-05-18T00:00:00+00:00",
                    last_seen_at="2026-05-18T00:00:00+00:00",
                    adult_content=True,
                ),
                Mod(
                    source="nexusmods",
                    external_id="skyrimspecialedition:armor",
                    game="Skyrim Special Edition",
                    game_domain="skyrimspecialedition",
                    title="Realistic Armor Overhaul",
                    url="https://example.com/armor",
                    category="Armor",
                    original_summary="A lore friendly armor replacement.",
                    first_seen_at="2026-05-17T00:00:00+00:00",
                    last_seen_at="2026-05-17T00:00:00+00:00",
                    adult_content=False,
                ),
            ]
        )
        session.commit()


def _log_messages(caplog) -> list[str]:
    return [record.getMessage() for record in caplog.records]


def _assert_graph_stage_logs(messages: list[str]) -> None:
    assert any("agent.api path=/api/agent/chat status=started" in message for message in messages)
    assert any("agent.api path=/api/agent/chat status=succeeded" in message for message in messages)
    assert any("agent.runtime request_kind=chat status=started" in message for message in messages)
    assert any("agent.runtime request_kind=chat status=succeeded" in message for message in messages)
    assert any("agent.workflow graph=mod_search request_kind=chat status=started" in message for message in messages)
    assert any("agent.workflow graph=mod_search request_kind=chat status=succeeded" in message for message in messages)
    for step in [
        "load_state",
        "summarize_context",
        "diagnose_query",
        "plan_tools",
        "staged_retrieval",
        "rank_results",
        "generate_answer",
        "reflect",
        "persist_result",
    ]:
        assert any(f"agent.stage step={step} status=succeeded" in message for message in messages)


def test_chat_endpoint_inherits_context_keywords_and_logs_agent_stages(client, engine, caplog):
    _seed_mods(engine)
    caplog.set_level(logging.INFO)

    response = client.post(
        "/api/agent/chat",
        json={
            "message": "有什么相关风格的mod",
            "history": [
                {"role": "user", "text": "有什么bimbo化的mod"},
                {"role": "assistant", "text": "我会优先查找 bimbo 相关风格。"},
            ],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert [match["title"] for match in body["matches"]][:1] == ["Bimbo Body Morph"]
    assert any(item.get("field") == "context_continuity_score" for item in body.get("understanding", {}).get("evidence", []))
    assert any(
        item.get("field") == "context_semantic_anchors"
        for item in body.get("understanding", {}).get("evidence", [])
    )

    messages = _log_messages(caplog)
    _assert_graph_stage_logs(messages)
    assert any("agent.memory loaded=" in message for message in messages)
    assert any("agent.chat.plan" in message and "bimbo" in message for message in messages)
    assert any("agent.retrieval.fts status=succeeded" in message and "bimbo" in message for message in messages)
    assert any("agent.search.local count=" in message and "bimbo" in message for message in messages)
    assert any(
        "agent.context_inherit" in message and "followup_score=" in message and "continuity_score=" in message
        for message in messages
    )
    assert any(
        "agent.context_inherit" in message and "inherit_score=" in message and "topic_shift=" in message
        for message in messages
    )
    assert any(
        "agent.context_inherit" in message and "context_semantic_anchors=" in message
        for message in messages
    )
    assert any("agent.fusion status=succeeded" in message for message in messages)
    assert any("agent.ranking status=succeeded" in message for message in messages)
    assert any("agent.answer status=fallback reason=llm_unavailable" in message for message in messages)
    assert any("agent.tool name=response_card_builder status=succeeded" in message for message in messages)
    assert any("agent.search.final count=" in message for message in messages)
    assert any("agent.diagnosis" in message and "context_continuity_score=" in message for message in messages)
    assert any("agent.diagnosis" in message and "semantic_anchors=" in message and "semantic_domains=" in message for message in messages)


def test_chat_endpoint_open_discovery_fuzzy_retrieval_returns_multiple_bimbo_matches(client, engine, caplog):
    _seed_skyrim_bimbo_open_discovery_mods(engine)
    caplog.set_level(logging.INFO)

    response = client.post("/api/agent/chat", json={"message": "天际有什么扮演bimbo的MOD"})

    assert response.status_code == 200
    body = response.json()
    titles = [match["title"] for match in body["matches"]]
    assert len(titles) >= 3
    assert "Bimbos Of Skyrim LE SE" in titles
    assert "Bimbos of Skyrim - BimboLips" in titles
    assert "Bimbos of Skyrim - Charismatic HPH Overhaul" in titles
    slots = ((body.get("understanding") or {}).get("slots") or {})
    assert slots.get("open_discovery") is True
    assert slots.get("retrieval_mode") == "fuzzy"
    messages = _log_messages(caplog)
    assert any("agent.retrieval" in message and "keywords=['bimbo', 'bimbos', 'bimbofication', 'bimbofied']" in message for message in messages)
    assert any("agent.search.local count=" in message and "open_discovery=True" in message and "retrieval_mode=fuzzy" in message for message in messages)


def test_chat_endpoint_semantic_followup_inherits_bimbo_intent(client, engine):
    _seed_mods(engine)

    response = client.post(
        "/api/agent/chat",
        json={
            "message": "有什么相关风格的mod",
            "history": [
                {"role": "user", "text": "有什么bimbo化的mod"},
                {"role": "assistant", "text": "我会优先查找 bimbo 相关风格。"},
            ],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert [match["title"] for match in body["matches"]][:1] == ["Bimbo Body Morph"]

    understanding_evidence = ((body.get("understanding") or {}).get("evidence") or [])
    inherit_score_items = [item for item in understanding_evidence if item.get("field") == "context_inherit_score"]
    semantic_context_items = [item for item in understanding_evidence if item.get("field") == "context_semantic_anchors"]
    semantic_anchor_items = [item for item in understanding_evidence if item.get("field") == "semantic_anchors"]
    assert inherit_score_items and float(inherit_score_items[0].get("value") or 0.0) >= 0.35
    assert semantic_context_items and "bimbo" in (semantic_context_items[0].get("value") or [])
    assert semantic_anchor_items and "bimbo" in (semantic_anchor_items[0].get("value") or [])

    retrieval_decision = (((body.get("audit") or {}).get("evidence") or {}).get("retrieval_decision") or {})
    semantic_trace = (((body.get("audit") or {}).get("evidence") or {}).get("semantic_trace") or {})
    assert "bimbo" in (retrieval_decision.get("semantic_anchors") or [])
    assert "semantic_anchors_detected" in ((retrieval_decision.get("reason_groups") or {}).get("semantic") or [])
    assert "bimbo" in (semantic_trace.get("anchors") or [])
    assert "bimbo" in (semantic_trace.get("context_anchors") or [])
    assert int(semantic_trace.get("inherited_anchor_overlap") or 0) >= 1


def test_chat_endpoint_uses_memory_writeback_across_requests_without_history(client, engine, caplog):
    _seed_mods(engine)
    caplog.set_level(logging.INFO)

    first = client.post(
        "/api/agent/chat",
        json={"message": "Skyrim Special Edition 有什么bimbo化的mod", "history": []},
    )
    assert first.status_code == 200
    assert [match["title"] for match in first.json()["matches"]][:1] == ["Bimbo Body Morph"]

    second = client.post(
        "/api/agent/chat",
        json={"message": "有什么相关风格的mod", "history": []},
    )

    assert second.status_code == 200
    body = second.json()
    assert [match["title"] for match in body["matches"]][:1] == ["Bimbo Body Morph"]
    slots = ((body.get("understanding") or {}).get("slots") or {})
    assert slots["game"] == "Skyrim Special Edition"
    assert "bimbo" in (slots.get("keywords") or [])

    evidence = ((body.get("understanding") or {}).get("evidence") or [])
    assert any(
        item.get("field") == "context_source" and item.get("value") == "long_term_writeback"
        for item in evidence
    )
    assert any(
        item.get("field") == "context_semantic_anchors" and "bimbo" in (item.get("value") or [])
        for item in evidence
    )
    messages = _log_messages(caplog)
    assert any("agent.tool name=memory_writeback status=succeeded" in message for message in messages)
    assert any("agent.context_inherit" in message and "source=long_term_writeback" in message for message in messages)


def test_chat_endpoint_semantic_followup_stays_on_topic_with_weak_phrase(client, engine):
    _seed_mods(engine)

    response = client.post(
        "/api/agent/chat",
        json={
            "message": "这种风格继续找",
            "history": [
                {"role": "user", "text": "我想找 bimbo 化的 mod"},
                {"role": "assistant", "text": "我会优先查找 bimbo 相关风格。"},
            ],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert [match["title"] for match in body["matches"]][:1] == ["Bimbo Body Morph"]

    understanding_evidence = ((body.get("understanding") or {}).get("evidence") or [])
    semantic_context_items = [item for item in understanding_evidence if item.get("field") == "context_semantic_anchors"]
    semantic_anchor_items = [item for item in understanding_evidence if item.get("field") == "semantic_anchors"]
    followup_items = [item for item in understanding_evidence if item.get("field") == "followup"]
    inherit_score_items = [item for item in understanding_evidence if item.get("field") == "context_inherit_score"]

    assert followup_items and followup_items[0].get("value") is True
    assert semantic_context_items and "bimbo" in (semantic_context_items[0].get("value") or [])
    assert semantic_anchor_items and "bimbo" in (semantic_anchor_items[0].get("value") or [])
    assert inherit_score_items and float(inherit_score_items[0].get("value") or 0.0) >= 0.3

def test_chat_endpoint_merges_context_and_current_keywords_in_followup(client, engine, caplog):
    _seed_mods(engine)
    caplog.set_level(logging.INFO)

    response = client.post(
        "/api/agent/chat",
        json={
            "message": "find similar ones, add curvy body, non adult",
            "history": [
                {"role": "user", "text": "any bimbo style mods"},
                {"role": "assistant", "text": "I will prioritize bimbo style results."},
            ],
        },
    )

    assert response.status_code == 200
    messages = _log_messages(caplog)
    _assert_graph_stage_logs(messages)
    # Follow-up inheritance should keep current-turn constraints visible.
    assert any("agent.context_inherit" in message and "inherit_keywords=" in message for message in messages)
    assert any("agent.chat.plan" in message and "curvy" in message and "body" in message for message in messages)
    assert any("agent.chat.plan" in message and "adult_content=False" in message for message in messages)


def test_chat_endpoint_detects_topic_shift_and_does_not_stick_to_previous_context(client, engine, caplog):
    _seed_mods(engine)
    with Session(engine) as session:
        session.add(
            Mod(
                source="nexusmods",
                external_id="cp2077-vehicle-1",
                game="Cyberpunk 2077",
                game_domain="cyberpunk2077",
                title="Cyber Vehicle Handling Overhaul",
                url="https://example.com/cp2077-vehicle",
                category="Vehicles",
                original_summary="Improves vehicle steering and drift control in Cyberpunk 2077.",
                first_seen_at="2026-05-23T00:00:00+00:00",
                last_seen_at="2026-05-23T00:00:00+00:00",
                adult_content=False,
            )
        )
        session.commit()
    caplog.set_level(logging.INFO)

    response = client.post(
        "/api/agent/chat",
        json={
            "message": "有什么 cyberpunk 2077 的载具改装 mod",
            "history": [
                {"role": "user", "text": "有什么bimbo化的mod"},
                {"role": "assistant", "text": "我会优先查找 bimbo 相关风格。"},
            ],
        },
    )

    assert response.status_code == 200
    body = response.json()
    titles = [match["title"] for match in body["matches"]]
    assert titles[:1] == ["Cyber Vehicle Handling Overhaul"]
    assert "Bimbo Body Morph" not in titles
    game_items = [item for item in body.get("understanding", {}).get("evidence", []) if item.get("field") == "game"]
    assert game_items
    assert game_items[0].get("value") == "Cyberpunk 2077"

    messages = _log_messages(caplog)
    _assert_graph_stage_logs(messages)
    assert any("agent.chat.plan" in message and "cyberpunk" in message.lower() for message in messages)


def test_chat_endpoint_handles_natural_language_style_intent(client, engine, caplog):
    _seed_mods(engine)
    caplog.set_level(logging.INFO)

    response = client.post(
        "/api/agent/chat",
        json={"message": "我想让角色变成那种夸张的 bimbo 化审美，有没有相关 mod"},
    )

    assert response.status_code == 200
    body = response.json()
    assert [match["title"] for match in body["matches"]][:1] == ["Bimbo Body Morph"]
    messages = _log_messages(caplog)
    _assert_graph_stage_logs(messages)
    assert any("agent.chat.plan" in message and "bimbo" in message for message in messages)
    assert not any("agent.chat.plan" in message and "角色" in message for message in messages)
    assert any("agent.search.final count=" in message for message in messages)


def test_chat_endpoint_treats_recommendation_as_preference_summary_not_comparison(client, engine, caplog):
    _seed_mods(engine)
    caplog.set_level(logging.INFO)

    response = client.post(
        "/api/agent/chat",
        json={"message": "recommend Skyrim Special Edition body mods"},
    )

    assert response.status_code == 200
    body = response.json()
    assert [match["title"] for match in body["matches"]][:1] == ["Bimbo Body Morph"]
    assert body["answer"].startswith("优先推荐这些 Mod：")
    assert "如果优先考虑新手友好和低风险" not in body["answer"]
    messages = _log_messages(caplog)
    _assert_graph_stage_logs(messages)
    assert any("agent.chat.plan intent=preference_summary" in message for message in messages)
    assert not any("agent.chat.plan intent=comparison" in message for message in messages)
    assert any("agent.answer status=fallback reason=llm_unavailable" in message for message in messages)
    assert any("agent.search.final count=" in message for message in messages)


def test_chat_endpoint_treats_safer_recommendation_as_preference_not_alternative(client, engine, caplog):
    _seed_mods(engine)
    caplog.set_level(logging.INFO)

    response = client.post(
        "/api/agent/chat",
        json={"message": "推荐更安全的 Skyrim Special Edition body mod"},
    )

    assert response.status_code == 200
    body = response.json()
    assert [match["title"] for match in body["matches"]][:1] == ["Bimbo Body Morph"]
    assert body["answer"].startswith("优先推荐这些 Mod：")
    assert "可以考虑这些替代 Mod" not in body["answer"]
    messages = _log_messages(caplog)
    _assert_graph_stage_logs(messages)
    assert any("agent.chat.plan intent=preference_summary" in message for message in messages)
    assert not any("agent.chat.plan intent=alternative" in message for message in messages)
    assert any("agent.search.local count=" in message and "body" in message for message in messages)
    assert any("agent.answer status=fallback reason=llm_unavailable" in message for message in messages)


def test_chat_endpoint_handles_chinese_game_alias_adult_outfit_intent(client, engine, caplog):
    _seed_mods(engine)
    with Session(engine) as session:
        session.add_all(
            [
                Mod(
                    source="nexusmods",
                    external_id="stellar-adult-outfit-new",
                    game="Stellar Blade",
                    game_domain="stellarblade",
                    title="Stellar Lace Combat Suit",
                    url="https://example.com/stellar-lace",
                    category="Outfits",
                    original_summary="An adult outfit mod for Stellar Blade with a combat suit style.",
                    downloads=9000,
                    updated_at_remote="2026-05-23T00:00:00+00:00",
                    first_seen_at="2026-05-23T00:00:00+00:00",
                    last_seen_at="2026-05-23T00:00:00+00:00",
                    adult_content=True,
                ),
                Mod(
                    source="nexusmods",
                    external_id="stellar-adult-outfit-old",
                    game="Stellar Blade",
                    game_domain="stellarblade",
                    title="Stellar Classic Dress",
                    url="https://example.com/stellar-dress",
                    category="Outfits",
                    original_summary="An older adult outfit mod for Stellar Blade.",
                    downloads=12000,
                    updated_at_remote="2026-05-20T00:00:00+00:00",
                    first_seen_at="2026-05-20T00:00:00+00:00",
                    last_seen_at="2026-05-20T00:00:00+00:00",
                    adult_content=True,
                ),
                Mod(
                    source="nexusmods",
                    external_id="stellar-safe-outfit",
                    game="Stellar Blade",
                    game_domain="stellarblade",
                    title="Stellar Safe Jacket",
                    url="https://example.com/stellar-safe",
                    category="Outfits",
                    original_summary="A safe outfit mod for Stellar Blade.",
                    downloads=15000,
                    updated_at_remote="2026-05-24T00:00:00+00:00",
                    first_seen_at="2026-05-24T00:00:00+00:00",
                    last_seen_at="2026-05-24T00:00:00+00:00",
                    adult_content=False,
                ),
                Mod(
                    source="nexusmods",
                    external_id="skyrim-adult-outfit",
                    game="Skyrim Special Edition",
                    game_domain="skyrimspecialedition",
                    title="Skyrim Lace Dress",
                    url="https://example.com/skyrim-lace",
                    category="Outfits",
                    original_summary="An adult outfit mod for Skyrim.",
                    downloads=20000,
                    updated_at_remote="2026-05-24T00:00:00+00:00",
                    first_seen_at="2026-05-24T00:00:00+00:00",
                    last_seen_at="2026-05-24T00:00:00+00:00",
                    adult_content=True,
                ),
            ]
        )
        session.commit()
    caplog.set_level(logging.INFO)

    response = client.post(
        "/api/agent/chat",
        json={"message": "帮我找最近比较火的剑星成人服装 Mod"},
    )

    assert response.status_code == 200
    body = response.json()
    titles = [match["title"] for match in body["matches"]]
    assert titles[:2] == ["Stellar Lace Combat Suit", "Stellar Classic Dress"]
    assert "Stellar Safe Jacket" not in titles
    assert "Skyrim Lace Dress" not in titles
    messages = _log_messages(caplog)
    _assert_graph_stage_logs(messages)
    assert any("agent.chat.plan intent=recent" in message for message in messages)
    assert any("agent.chat.plan" in message and "games=['Stellar Blade']" in message for message in messages)
    assert any("agent.chat.plan" in message and "categories=['Outfits']" in message for message in messages)
    assert any("agent.chat.plan" in message and "adult_content=True" in message for message in messages)
    assert any("agent.chat.plan" in message and "sort=updated_at_remote/desc" in message for message in messages)
    assert any("agent.search.local count=" in message and "games=['Stellar Blade']" in message for message in messages)
    assert any("agent.search.local count=" in message and "categories=['Outfits']" in message for message in messages)
    assert any("agent.retrieval." in message and "adult_content=True" in message for message in messages)
    assert any("agent.search.final count=2" in message for message in messages)


def test_chat_endpoint_inherits_context_keywords_and_applies_sfw_constraint(client, engine, caplog):
    _seed_mods(engine)
    with Session(engine) as session:
        session.add(
            Mod(
                source="nexusmods",
                external_id="bimbo-adult",
                game="Skyrim Special Edition",
                game_domain="skyrimspecialedition",
                title="Adult Bimbo Morph",
                url="https://example.com/adult-bimbo",
                category="Body",
                original_summary="An adult bimbo transformation preset.",
                first_seen_at="2026-05-22T00:00:00+00:00",
                last_seen_at="2026-05-22T00:00:00+00:00",
                adult_content=True,
            )
        )
        session.commit()
    caplog.set_level(logging.INFO)

    response = client.post(
        "/api/agent/chat",
        json={
            "message": "不要成人内容但保持同类效果",
            "history": [
                {"role": "user", "text": "有什么 Skyrim bimbo mod"},
                {"role": "assistant", "text": "我会优先查找 bimbo 相关风格。"},
            ],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert [match["title"] for match in body["matches"]][:1] == ["Bimbo Body Morph"]
    assert all(match["adult_content"] is False for match in body["matches"])
    messages = _log_messages(caplog)
    _assert_graph_stage_logs(messages)
    assert any("agent.chat.plan" in message and "bimbo" in message for message in messages)
    assert any("agent.chat.plan" in message and "adult_content=False" in message for message in messages)
    assert any("agent.retrieval.fts status=succeeded" in message and "bimbo" in message for message in messages)
    assert any("agent.search.final count=" in message for message in messages)


def test_chat_endpoint_treats_no_nsfw_as_adult_filter_without_excluding_search_terms(client, engine, caplog):
    _seed_mods(engine)
    with Session(engine) as session:
        session.add_all(
            [
                Mod(
                    source="nexusmods",
                    external_id="sfw-cbbe-body",
                    game="Skyrim Special Edition",
                    game_domain="skyrimspecialedition",
                    title="SFW CBBE Body Preset",
                    url="https://example.com/sfw-cbbe-body",
                    category="Body",
                    original_summary="A CBBE body preset suitable for safe-for-work setups.",
                    first_seen_at="2026-05-24T00:00:00+00:00",
                    last_seen_at="2026-05-24T00:00:00+00:00",
                    adult_content=False,
                ),
                Mod(
                    source="nexusmods",
                    external_id="nsfw-cbbe-body",
                    game="Skyrim Special Edition",
                    game_domain="skyrimspecialedition",
                    title="NSFW CBBE Body Preset",
                    url="https://example.com/nsfw-cbbe-body",
                    category="Body",
                    original_summary="An adult CBBE body preset.",
                    first_seen_at="2026-05-23T00:00:00+00:00",
                    last_seen_at="2026-05-23T00:00:00+00:00",
                    adult_content=True,
                ),
            ]
        )
        session.commit()
    caplog.set_level(logging.INFO)

    response = client.post(
        "/api/agent/chat",
        json={"message": "Skyrim Special Edition no NSFW CBBE body preset"},
    )

    assert response.status_code == 200
    body = response.json()
    titles = [match["title"] for match in body["matches"]]
    assert titles[:1] == ["SFW CBBE Body Preset"]
    assert "NSFW CBBE Body Preset" not in titles
    messages = _log_messages(caplog)
    _assert_graph_stage_logs(messages)
    assert any("agent.chat.plan" in message and "adult_content=False" in message for message in messages)
    assert any("agent.chat.plan" in message and "excluded_keywords=[]" in message for message in messages)
    assert any("agent.search.local count=" in message and "adult_content=False" in message for message in messages)
    assert any("agent.search.local count=" in message and "excluded_keywords=[]" in message for message in messages)
    assert any("agent.retrieval." in message and "adult_content=False" in message for message in messages)
    assert any("agent.search.final count=1" in message for message in messages)


def test_chat_endpoint_inherits_context_keywords_for_filter_only_followup(client, engine, caplog):
    _seed_mods(engine)
    with Session(engine) as session:
        session.add_all(
            [
                Mod(
                    source="nexusmods",
                    external_id="bimbo-thumb",
                    game="Skyrim Special Edition",
                    game_domain="skyrimspecialedition",
                    title="Bimbo Visual Preset",
                    url="https://example.com/bimbo-visual",
                    category="Body",
                    thumbnail_url="https://example.com/bimbo-visual.jpg",
                    original_summary="A bimbo transformation preset with preview images.",
                    first_seen_at="2026-05-22T00:00:00+00:00",
                    last_seen_at="2026-05-22T00:00:00+00:00",
                    adult_content=False,
                ),
                Mod(
                    source="nexusmods",
                    external_id="armor-thumb",
                    game="Skyrim Special Edition",
                    game_domain="skyrimspecialedition",
                    title="Armor Visual Preview",
                    url="https://example.com/armor-visual",
                    category="Armor",
                    thumbnail_url="https://example.com/armor-visual.jpg",
                    original_summary="An armor overhaul with preview images.",
                    first_seen_at="2026-05-23T00:00:00+00:00",
                    last_seen_at="2026-05-23T00:00:00+00:00",
                    adult_content=False,
                ),
            ]
        )
        session.commit()
    caplog.set_level(logging.INFO)

    response = client.post(
        "/api/agent/chat",
        json={
            "message": "only show bimbo mods with preview images",
            "history": [
                {"role": "user", "text": "show me bimbo style mods"},
                {"role": "assistant", "text": "I will prioritize bimbo style results."},
            ],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert isinstance(body.get("audit"), dict)
    messages = _log_messages(caplog)
    _assert_graph_stage_logs(messages)
    assert any("agent.chat.plan" in message and "bimbo" in message and "has_thumbnail=True" in message for message in messages)
    assert any("agent.search.local count=" in message and "bimbo" in message and "has_thumbnail=True" in message for message in messages)
    assert any("agent.retrieval." in message and "bimbo" in message and "has_thumbnail=True" in message for message in messages)


def test_chat_endpoint_applies_natural_language_source_exclusion(client, engine, caplog):
    _seed_mods(engine)
    with Session(engine) as session:
        session.add(
            Mod(
                source="loverslab",
                external_id="ll-bimbo",
                game="Skyrim Special Edition",
                game_domain=None,
                title="LoversLab Bimbo Morph",
                url="https://example.com/ll-bimbo",
                category="Body",
                original_summary="A bimbo transformation preset.",
                first_seen_at="2026-05-22T00:00:00+00:00",
                last_seen_at="2026-05-22T00:00:00+00:00",
                adult_content=False,
            )
        )
        session.commit()
    caplog.set_level(logging.INFO)

    response = client.post(
        "/api/agent/chat",
        json={"message": "排除 LoversLab，只看 Nexus bimbo mod"},
    )

    assert response.status_code == 200
    body = response.json()
    assert [match["title"] for match in body["matches"]][:1] == ["Bimbo Body Morph"]
    assert all(match["source"] == "nexusmods" for match in body["matches"])
    assert "LoversLab Bimbo Morph" not in [match["title"] for match in body["matches"]]
    messages = _log_messages(caplog)
    _assert_graph_stage_logs(messages)
    assert any("agent.chat.plan" in message and "sources=['nexusmods']" in message for message in messages)
    assert any("agent.chat.plan" in message and "bimbo" in message for message in messages)
    assert any("agent.search.local count=" in message and "sources=['nexusmods']" in message for message in messages)
    assert any("agent.search.final count=" in message for message in messages)


def test_chat_endpoint_understands_except_source_exclusion(client, engine, caplog):
    _seed_mods(engine)
    with Session(engine) as session:
        session.add(
            Mod(
                source="loverslab",
                external_id="ll-bimbo-except",
                game="Skyrim Special Edition",
                game_domain=None,
                title="LoversLab Bimbo Morph",
                url="https://example.com/ll-bimbo-except",
                category="Body",
                original_summary="A bimbo transformation preset.",
                first_seen_at="2026-05-23T00:00:00+00:00",
                last_seen_at="2026-05-23T00:00:00+00:00",
                adult_content=False,
            )
        )
        session.commit()
    caplog.set_level(logging.INFO)

    response = client.post(
        "/api/agent/chat",
        json={"message": "除了 LoversLab 的 Skyrim bimbo mod"},
    )

    assert response.status_code == 200
    body = response.json()
    assert [match["title"] for match in body["matches"]][:1] == ["Bimbo Body Morph"]
    assert all(match["source"] != "loverslab" for match in body["matches"])
    assert "LoversLab Bimbo Morph" not in [match["title"] for match in body["matches"]]
    messages = _log_messages(caplog)
    _assert_graph_stage_logs(messages)
    assert any("agent.chat.plan" in message and "excluded_sources=['loverslab']" in message for message in messages)
    assert any("agent.chat.plan" in message and "sources=['nexusmods']" in message for message in messages)
    assert any("agent.search.local count=" in message and "excluded_sources=['loverslab']" in message for message in messages)
    assert any("agent.search.local count=" in message and "sources=['nexusmods']" in message for message in messages)
    assert any("agent.retrieval.online tool=loverslab_google status=skipped" in message for message in messages)
    assert any("agent.search.final count=" in message for message in messages)


def test_chat_endpoint_understands_not_from_source_exclusion(client, engine, caplog):
    _seed_mods(engine)
    with Session(engine) as session:
        session.add(
            Mod(
                source="loverslab",
                external_id="ll-bimbo-not-from",
                game="Skyrim Special Edition",
                game_domain=None,
                title="LoversLab Bimbo Morph",
                url="https://example.com/ll-bimbo-not-from",
                category="Body",
                original_summary="A bimbo transformation preset.",
                first_seen_at="2026-05-23T00:00:00+00:00",
                last_seen_at="2026-05-23T00:00:00+00:00",
                adult_content=False,
            )
        )
        session.commit()
    caplog.set_level(logging.INFO)

    response = client.post(
        "/api/agent/chat",
        json={"message": "Skyrim bimbo mod not from LoversLab"},
    )

    assert response.status_code == 200
    body = response.json()
    assert [match["title"] for match in body["matches"]][:1] == ["Bimbo Body Morph"]
    assert all(match["source"] != "loverslab" for match in body["matches"])
    assert "LoversLab Bimbo Morph" not in [match["title"] for match in body["matches"]]
    messages = _log_messages(caplog)
    _assert_graph_stage_logs(messages)
    assert any("agent.chat.plan" in message and "excluded_sources=['loverslab']" in message for message in messages)
    assert any("agent.chat.plan" in message and "sources=['nexusmods']" in message for message in messages)
    assert any("agent.search.local count=" in message and "excluded_sources=['loverslab']" in message for message in messages)
    assert any("agent.search.local count=" in message and "sources=['nexusmods']" in message for message in messages)
    assert any("agent.retrieval.online tool=loverslab_google status=skipped" in message for message in messages)
    assert any("agent.search.final count=" in message for message in messages)


def test_chat_endpoint_understands_loverslab_short_alias_and_logs_constraints(client, engine, caplog):
    _seed_mods(engine)
    with Session(engine) as session:
        session.add(
            Mod(
                source="loverslab",
                external_id="ll-cbbe-short-alias",
                game="Skyrim Special Edition",
                game_domain=None,
                title="LoversLab CBBE Preset",
                url="https://example.com/ll-cbbe-short-alias",
                category="Body",
                original_summary="A CBBE body preset hosted on LoversLab.",
                first_seen_at="2026-05-23T00:00:00+00:00",
                last_seen_at="2026-05-23T00:00:00+00:00",
                adult_content=False,
            )
        )
        session.commit()
    caplog.set_level(logging.INFO)

    response = client.post(
        "/api/agent/chat",
        json={"message": "LL Skyrim Special Edition CBBE preset"},
    )

    assert response.status_code == 200
    body = response.json()
    assert [match["title"] for match in body["matches"]][:1] == ["LoversLab CBBE Preset"]
    assert all(match["source"] == "loverslab" for match in body["matches"])
    assert "Bimbo Body Morph" not in [match["title"] for match in body["matches"]]
    messages = _log_messages(caplog)
    _assert_graph_stage_logs(messages)
    assert any("agent.chat.plan" in message and "sources=['loverslab']" in message for message in messages)
    assert any("agent.chat.plan" in message and "CBBE".lower() in message.lower() for message in messages)
    assert any("agent.search.local count=" in message and "sources=['loverslab']" in message for message in messages)
    assert any("agent.retrieval." in message and "sources=['loverslab']" in message for message in messages)
    assert any("agent.search.final count=1" in message for message in messages)


def test_chat_endpoint_understands_skyrim_le_game_alias_and_logs_constraints(client, engine, caplog):
    with Session(engine) as session:
        session.add_all(
            [
                Mod(
                    source="nexusmods",
                    external_id="sse-cbbe-preset",
                    game="Skyrim Special Edition",
                    game_domain="skyrimspecialedition",
                    title="SSE CBBE Preset",
                    url="https://example.com/sse-cbbe-preset",
                    category="Body",
                    original_summary="A CBBE body preset for Skyrim Special Edition.",
                    first_seen_at="2026-05-23T00:00:00+00:00",
                    last_seen_at="2026-05-23T00:00:00+00:00",
                    adult_content=False,
                ),
                Mod(
                    source="nexusmods",
                    external_id="le-cbbe-preset",
                    game="Skyrim Legendary Edition",
                    game_domain="skyrim",
                    title="Oldrim CBBE Preset",
                    url="https://example.com/le-cbbe-preset",
                    category="Body",
                    original_summary="A CBBE body preset for Skyrim Legendary Edition and Oldrim.",
                    first_seen_at="2026-05-24T00:00:00+00:00",
                    last_seen_at="2026-05-24T00:00:00+00:00",
                    adult_content=False,
                ),
            ]
        )
        session.commit()
    caplog.set_level(logging.INFO)

    response = client.post(
        "/api/agent/chat",
        json={"message": "Skyrim LE CBBE body preset"},
    )

    assert response.status_code == 200
    body = response.json()
    assert [match["title"] for match in body["matches"]][:1] == ["Oldrim CBBE Preset"]
    assert all(match["game"] == "Skyrim Legendary Edition" for match in body["matches"])
    assert "SSE CBBE Preset" not in [match["title"] for match in body["matches"]]
    messages = _log_messages(caplog)
    _assert_graph_stage_logs(messages)
    assert any("agent.chat.plan" in message and "games=['Skyrim Legendary Edition']" in message for message in messages)
    assert any("agent.search.local count=" in message and "games=['Skyrim Legendary Edition']" in message for message in messages)
    assert any("agent.retrieval." in message and "games=['Skyrim Legendary Edition']" in message for message in messages)
    assert any("agent.search.final count=1" in message for message in messages)


def test_chat_endpoint_sorts_natural_language_download_request(client, engine, caplog):
    _seed_mods(engine)
    with Session(engine) as session:
        session.add(
            Mod(
                source="nexusmods",
                external_id="popular-bimbo",
                game="Skyrim Special Edition",
                game_domain="skyrimspecialedition",
                title="Popular Bimbo Preset",
                url="https://example.com/popular-bimbo",
                category="Body",
                original_summary="A bimbo transformation preset.",
                downloads=5000,
                first_seen_at="2026-05-22T00:00:00+00:00",
                last_seen_at="2026-05-22T00:00:00+00:00",
                adult_content=False,
            )
        )
        session.commit()
    caplog.set_level(logging.INFO)

    response = client.post(
        "/api/agent/chat",
        json={"message": "下载最多的 Skyrim bimbo mod"},
    )

    assert response.status_code == 200
    body = response.json()
    assert [match["title"] for match in body["matches"]][:1] == ["Popular Bimbo Preset"]
    messages = _log_messages(caplog)
    _assert_graph_stage_logs(messages)
    assert any("agent.chat.plan" in message and "sort=downloads/desc" in message for message in messages)
    assert any("agent.retrieval.fts status=skipped" in message and "bimbo" in message for message in messages)
    assert any("agent.retrieval.sql status=succeeded" in message and "sort=downloads/desc" in message for message in messages)
    assert any("agent.search.final count=" in message for message in messages)


def test_chat_endpoint_applies_natural_language_author_filter(client, engine, caplog):
    _seed_mods(engine)
    with Session(engine) as session:
        session.add_all(
            [
                Mod(
                    source="nexusmods",
                    external_id="ousnius-body",
                    game="Skyrim Special Edition",
                    game_domain="skyrimspecialedition",
                    title="Ousnius Body Preset",
                    author="Ousnius",
                    url="https://example.com/ousnius-body",
                    category="Body",
                    original_summary="A body preset for Skyrim.",
                    first_seen_at="2026-05-22T00:00:00+00:00",
                    last_seen_at="2026-05-22T00:00:00+00:00",
                    adult_content=False,
                ),
                Mod(
                    source="nexusmods",
                    external_id="other-body",
                    game="Skyrim Special Edition",
                    game_domain="skyrimspecialedition",
                    title="Other Body Preset",
                    author="OtherAuthor",
                    url="https://example.com/other-body",
                    category="Body",
                    original_summary="A body preset for Skyrim.",
                    first_seen_at="2026-05-21T00:00:00+00:00",
                    last_seen_at="2026-05-21T00:00:00+00:00",
                    adult_content=False,
                ),
            ]
        )
        session.commit()
    caplog.set_level(logging.INFO)

    response = client.post(
        "/api/agent/chat",
        json={"message": "作者 Ousnius 的 Skyrim Special Edition body mod"},
    )

    assert response.status_code == 200
    body = response.json()
    assert [match["title"] for match in body["matches"]][:1] == ["Ousnius Body Preset"]
    assert all(match["author"] == "Ousnius" for match in body["matches"])
    messages = _log_messages(caplog)
    _assert_graph_stage_logs(messages)
    assert any("agent.chat.plan" in message and "author=Ousnius" in message for message in messages)
    assert any("agent.chat.plan" in message and "Ousnius" in message and "keywords=['body']" in message for message in messages)
    assert any("agent.search.local count=" in message and "author=Ousnius" in message for message in messages)
    assert any("agent.search.final count=" in message for message in messages)


def test_chat_endpoint_keeps_author_separate_from_following_tag_constraint(client, engine, caplog):
    _seed_mods(engine)
    with Session(engine) as session:
        session.add_all(
            [
                Mod(
                    source="nexusmods",
                    external_id="ousnius-bodyslide-body",
                    game="Skyrim Special Edition",
                    game_domain="skyrimspecialedition",
                    title="Ousnius BodySlide Preset",
                    author="Ousnius",
                    url="https://example.com/ousnius-bodyslide-body",
                    category="Body",
                    tags_json=json.dumps(["BodySlide"]),
                    original_summary="A BodySlide body preset by Ousnius.",
                    first_seen_at="2026-05-23T00:00:00+00:00",
                    last_seen_at="2026-05-23T00:00:00+00:00",
                    adult_content=False,
                ),
                Mod(
                    source="nexusmods",
                    external_id="ousnius-manual-body",
                    game="Skyrim Special Edition",
                    game_domain="skyrimspecialedition",
                    title="Ousnius Manual Preset",
                    author="Ousnius",
                    url="https://example.com/ousnius-manual-body",
                    category="Body",
                    tags_json=json.dumps(["Manual"]),
                    original_summary="A manual body preset by Ousnius.",
                    first_seen_at="2026-05-22T00:00:00+00:00",
                    last_seen_at="2026-05-22T00:00:00+00:00",
                    adult_content=False,
                ),
                Mod(
                    source="nexusmods",
                    external_id="other-bodyslide-body",
                    game="Skyrim Special Edition",
                    game_domain="skyrimspecialedition",
                    title="Other BodySlide Preset",
                    author="OtherAuthor",
                    url="https://example.com/other-bodyslide-body",
                    category="Body",
                    tags_json=json.dumps(["BodySlide"]),
                    original_summary="A BodySlide body preset by another author.",
                    first_seen_at="2026-05-21T00:00:00+00:00",
                    last_seen_at="2026-05-21T00:00:00+00:00",
                    adult_content=False,
                ),
            ]
        )
        session.commit()
    caplog.set_level(logging.INFO)

    response = client.post(
        "/api/agent/chat",
        json={"message": "Skyrim Special Edition body preset by Ousnius with BodySlide tag"},
    )

    assert response.status_code == 200
    body = response.json()
    titles = [match["title"] for match in body["matches"]]
    assert titles[:1] == ["Ousnius BodySlide Preset"]
    assert "Ousnius Manual Preset" not in titles
    assert "Other BodySlide Preset" not in titles
    messages = _log_messages(caplog)
    _assert_graph_stage_logs(messages)
    assert any("agent.chat.plan" in message and "author=Ousnius" in message for message in messages)
    assert any("agent.chat.plan" in message and "tags=['BodySlide']" in message for message in messages)
    assert any("agent.search.local count=" in message and "author=Ousnius" in message for message in messages)
    assert any("agent.search.local count=" in message and "tags=['BodySlide']" in message for message in messages)
    assert any("agent.retrieval." in message and "tags=['BodySlide']" in message for message in messages)
    assert any("agent.search.final count=1" in message for message in messages)


def test_chat_endpoint_applies_natural_language_excluded_keyword_filter(client, engine, caplog):
    _seed_mods(engine)
    with Session(engine) as session:
        session.add(
            Mod(
                source="nexusmods",
                external_id="body-armor",
                game="Skyrim Special Edition",
                game_domain="skyrimspecialedition",
                title="Body Armor Kit",
                author="ArmorAuthor",
                url="https://example.com/body-armor",
                category="Armor",
                original_summary="A body armor kit for Skyrim.",
                first_seen_at="2026-05-22T00:00:00+00:00",
                last_seen_at="2026-05-22T00:00:00+00:00",
                adult_content=False,
            )
        )
        session.commit()
    caplog.set_level(logging.INFO)

    response = client.post(
        "/api/agent/chat",
        json={"message": "Skyrim Special Edition body mod 不要 armor"},
    )

    assert response.status_code == 200
    body = response.json()
    titles = [match["title"] for match in body["matches"]]
    assert "Bimbo Body Morph" in titles
    assert "Body Armor Kit" not in titles
    assert all("armor" not in " ".join([match["title"], match.get("category") or ""]).lower() for match in body["matches"])
    messages = _log_messages(caplog)
    _assert_graph_stage_logs(messages)
    assert any("agent.chat.plan" in message and "excluded_keywords=" in message and "armor" in message for message in messages)
    assert any("agent.search.local count=" in message and "excluded_keywords=" in message and "armor" in message for message in messages)
    assert any("agent.search.final count=" in message for message in messages)


def test_chat_endpoint_understands_not_phrase_as_excluded_keyword(client, engine, caplog):
    _seed_mods(engine)
    with Session(engine) as session:
        session.add(
            Mod(
                source="nexusmods",
                external_id="body-replacer",
                game="Skyrim Special Edition",
                game_domain="skyrimspecialedition",
                title="Body Replacer Kit",
                author="PresetAuthor",
                url="https://example.com/body-replacer",
                category="Body",
                original_summary="A body replacer for Skyrim.",
                first_seen_at="2026-05-22T00:00:00+00:00",
                last_seen_at="2026-05-22T00:00:00+00:00",
                adult_content=False,
            )
        )
        session.commit()
    caplog.set_level(logging.INFO)

    response = client.post(
        "/api/agent/chat",
        json={"message": "Skyrim Special Edition body mod 不是 replacer"},
    )

    assert response.status_code == 200
    body = response.json()
    titles = [match["title"] for match in body["matches"]]
    assert "Bimbo Body Morph" in titles
    assert "Body Replacer Kit" not in titles
    assert all("replacer" not in " ".join([match["title"], match.get("original_summary") or ""]).lower() for match in body["matches"])
    messages = _log_messages(caplog)
    _assert_graph_stage_logs(messages)
    assert any("agent.chat.plan" in message and "excluded_keywords=" in message and "replacer" in message for message in messages)
    assert any("agent.search.local count=" in message and "excluded_keywords=" in message and "replacer" in message for message in messages)
    assert any("agent.retrieval." in message and "excluded_keywords=" in message and "replacer" in message for message in messages)
    assert any("agent.search.final count=" in message for message in messages)


def test_chat_endpoint_filters_metric_thresholds_and_logs_constraints(client, engine, caplog):
    _seed_mods(engine)
    with Session(engine) as session:
        session.add_all(
            [
                Mod(
                    source="nexusmods",
                    external_id="bimbo-low-downloads",
                    game="Skyrim Special Edition",
                    game_domain="skyrimspecialedition",
                    title="Small Bimbo Preset",
                    author="PresetAuthor",
                    url="https://example.com/bimbo-low-downloads",
                    category="Body",
                    original_summary="A bimbo preset with a small audience.",
                    downloads=50,
                    endorsements=2,
                    first_seen_at="2026-05-21T00:00:00+00:00",
                    last_seen_at="2026-05-21T00:00:00+00:00",
                    adult_content=False,
                ),
                Mod(
                    source="nexusmods",
                    external_id="bimbo-popular",
                    game="Skyrim Special Edition",
                    game_domain="skyrimspecialedition",
                    title="Popular Bimbo Preset",
                    author="PresetAuthor",
                    url="https://example.com/bimbo-popular",
                    category="Body",
                    original_summary="A bimbo preset with broad usage.",
                    downloads=5000,
                    endorsements=120,
                    first_seen_at="2026-05-22T00:00:00+00:00",
                    last_seen_at="2026-05-22T00:00:00+00:00",
                    adult_content=False,
                ),
            ]
        )
        session.commit()
    caplog.set_level(logging.INFO)

    response = client.post(
        "/api/agent/chat",
        json={"message": "Skyrim Special Edition bimbo mod 下载至少 1000"},
    )

    assert response.status_code == 200
    body = response.json()
    titles = [match["title"] for match in body["matches"]]
    assert "Popular Bimbo Preset" in titles
    assert "Small Bimbo Preset" not in titles
    assert "Bimbo Body Morph" not in titles
    messages = _log_messages(caplog)
    _assert_graph_stage_logs(messages)
    assert any("agent.chat.plan" in message and "min_downloads=1000" in message for message in messages)
    assert any("agent.search.local count=" in message and "min_downloads=1000" in message for message in messages)
    assert any("agent.retrieval.fts status=" in message for message in messages)
    assert any("agent.search.final count=" in message for message in messages)


def test_chat_endpoint_sorts_most_endorsed_without_download_bias(client, engine, caplog):
    _seed_mods(engine)
    with Session(engine) as session:
        session.add_all(
            [
                Mod(
                    source="nexusmods",
                    external_id="endorsed-body",
                    game="Skyrim Special Edition",
                    game_domain="skyrimspecialedition",
                    title="Endorsed Body Preset",
                    author="PresetAuthor",
                    url="https://example.com/endorsed-body",
                    category="Body",
                    original_summary="A body preset with strong community endorsements.",
                    downloads=100,
                    endorsements=300,
                    first_seen_at="2026-05-22T00:00:00+00:00",
                    last_seen_at="2026-05-22T00:00:00+00:00",
                    adult_content=False,
                ),
                Mod(
                    source="nexusmods",
                    external_id="downloaded-body",
                    game="Skyrim Special Edition",
                    game_domain="skyrimspecialedition",
                    title="Downloaded Body Preset",
                    author="PresetAuthor",
                    url="https://example.com/downloaded-body",
                    category="Body",
                    original_summary="A body preset with many downloads but fewer endorsements.",
                    downloads=5000,
                    endorsements=10,
                    first_seen_at="2026-05-23T00:00:00+00:00",
                    last_seen_at="2026-05-23T00:00:00+00:00",
                    adult_content=False,
                ),
            ]
        )
        session.commit()
    caplog.set_level(logging.INFO)

    response = client.post(
        "/api/agent/chat",
        json={"message": "Skyrim Special Edition most endorsed body preset"},
    )

    assert response.status_code == 200
    body = response.json()
    titles = [match["title"] for match in body["matches"]]
    assert titles[:1] == ["Endorsed Body Preset"]
    messages = _log_messages(caplog)
    _assert_graph_stage_logs(messages)
    assert any("agent.chat.plan" in message and "sort=endorsements/desc" in message for message in messages)
    assert any("agent.search.local count=" in message and "sort=endorsements/desc" in message for message in messages)
    assert any("agent.retrieval.sql status=succeeded" in message and "sort=endorsements/desc" in message for message in messages)
    assert any("agent.search.final count=" in message for message in messages)


def test_chat_endpoint_filters_views_and_likes_thresholds_and_logs_constraints(client, engine, caplog):
    _seed_mods(engine)
    with Session(engine) as session:
        session.add_all(
            [
                Mod(
                    source="nexusmods",
                    external_id="body-low-views",
                    game="Skyrim Special Edition",
                    game_domain="skyrimspecialedition",
                    title="Quiet Body Preset",
                    author="PresetAuthor",
                    url="https://example.com/body-low-views",
                    category="Body",
                    original_summary="A body preset with limited attention.",
                    views=200,
                    likes=5,
                    first_seen_at="2026-05-21T00:00:00+00:00",
                    last_seen_at="2026-05-21T00:00:00+00:00",
                    adult_content=False,
                ),
                Mod(
                    source="nexusmods",
                    external_id="body-high-views",
                    game="Skyrim Special Edition",
                    game_domain="skyrimspecialedition",
                    title="Watched Body Preset",
                    author="PresetAuthor",
                    url="https://example.com/body-high-views",
                    category="Body",
                    original_summary="A body preset with many views and likes.",
                    views=2500,
                    likes=35,
                    first_seen_at="2026-05-22T00:00:00+00:00",
                    last_seen_at="2026-05-22T00:00:00+00:00",
                    adult_content=False,
                ),
            ]
        )
        session.commit()
    caplog.set_level(logging.INFO)

    response = client.post(
        "/api/agent/chat",
        json={
            "message": "\u6d4f\u89c8\u91cf\u81f3\u5c11 1000\u3001\u559c\u6b22\u6570\u81f3\u5c11 20 \u7684 Skyrim Special Edition body mod"
        },
    )

    assert response.status_code == 200
    body = response.json()
    titles = [match["title"] for match in body["matches"]]
    assert titles[:1] == ["Watched Body Preset"]
    assert "Quiet Body Preset" not in titles
    assert "Bimbo Body Morph" not in titles
    messages = _log_messages(caplog)
    _assert_graph_stage_logs(messages)
    assert any("agent.chat.plan" in message and "min_views=1000" in message for message in messages)
    assert any("agent.chat.plan" in message and "min_likes=20" in message for message in messages)
    assert any("agent.search.local count=" in message and "min_views=1000" in message for message in messages)
    assert any("agent.search.local count=" in message and "min_likes=20" in message for message in messages)
    assert any("agent.retrieval." in message and "min_views=1000" in message for message in messages)
    assert any("agent.retrieval." in message and "min_likes=20" in message for message in messages)
    assert any("agent.search.final count=1" in message for message in messages)


def test_chat_endpoint_filters_explicit_time_window_and_logs_constraints(client, engine, caplog):
    _seed_mods(engine)
    now = datetime.now(UTC)
    with Session(engine) as session:
        session.add_all(
            [
                Mod(
                    source="nexusmods",
                    external_id="bimbo-old-update",
                    game="Skyrim Special Edition",
                    game_domain="skyrimspecialedition",
                    title="Old Bimbo Preset",
                    author="PresetAuthor",
                    url="https://example.com/bimbo-old-update",
                    category="Body",
                    original_summary="A bimbo preset from an older update.",
                    updated_at_remote=(now - timedelta(days=30)).isoformat(),
                    first_seen_at=(now - timedelta(days=30)).isoformat(),
                    last_seen_at=(now - timedelta(days=30)).isoformat(),
                    adult_content=False,
                ),
                Mod(
                    source="nexusmods",
                    external_id="bimbo-recent-update",
                    game="Skyrim Special Edition",
                    game_domain="skyrimspecialedition",
                    title="Recent Bimbo Preset",
                    author="PresetAuthor",
                    url="https://example.com/bimbo-recent-update",
                    category="Body",
                    original_summary="A bimbo preset updated this week.",
                    updated_at_remote=(now - timedelta(days=2)).isoformat(),
                    first_seen_at=(now - timedelta(days=2)).isoformat(),
                    last_seen_at=(now - timedelta(days=2)).isoformat(),
                    adult_content=False,
                ),
            ]
        )
        session.commit()
    caplog.set_level(logging.INFO)

    response = client.post(
        "/api/agent/chat",
        json={"message": "最近7天的 Skyrim Special Edition bimbo mod"},
    )

    assert response.status_code == 200
    body = response.json()
    titles = [match["title"] for match in body["matches"]]
    assert "Recent Bimbo Preset" in titles
    assert "Old Bimbo Preset" not in titles
    assert "Bimbo Body Morph" not in titles
    messages = _log_messages(caplog)
    _assert_graph_stage_logs(messages)
    assert any("agent.chat.plan" in message and "updated_since_days=7" in message for message in messages)
    assert any("agent.search.local count=" in message and "updated_since_days=7" in message for message in messages)
    assert any("agent.retrieval.fts status=" in message for message in messages)
    assert any("agent.search.final count=" in message for message in messages)


def test_chat_endpoint_sorts_latest_preset_without_mod_word_and_keeps_thumbnail(client, engine, caplog):
    _seed_mods(engine)
    with Session(engine) as session:
        session.add_all(
            [
                Mod(
                    source="nexusmods",
                    external_id="old-cbbe-preview",
                    game="Skyrim Special Edition",
                    game_domain="skyrimspecialedition",
                    title="Old CBBE Preview Preset",
                    author="PresetAuthor",
                    url="https://example.com/old-cbbe-preview",
                    category="Body",
                    original_summary="A CBBE body preset with preview media.",
                    thumbnail_url="https://example.com/old-cbbe.jpg",
                    updated_at_remote="2026-05-01T00:00:00+00:00",
                    first_seen_at="2026-05-01T00:00:00+00:00",
                    last_seen_at="2026-05-01T00:00:00+00:00",
                    adult_content=False,
                ),
                Mod(
                    source="nexusmods",
                    external_id="new-cbbe-preview",
                    game="Skyrim Special Edition",
                    game_domain="skyrimspecialedition",
                    title="New CBBE Preview Preset",
                    author="PresetAuthor",
                    url="https://example.com/new-cbbe-preview",
                    category="Body",
                    original_summary="A newer CBBE body preset with preview media.",
                    thumbnail_url="https://example.com/new-cbbe.jpg",
                    updated_at_remote="2026-05-24T00:00:00+00:00",
                    first_seen_at="2026-05-24T00:00:00+00:00",
                    last_seen_at="2026-05-24T00:00:00+00:00",
                    adult_content=False,
                ),
                Mod(
                    source="nexusmods",
                    external_id="new-cbbe-no-preview",
                    game="Skyrim Special Edition",
                    game_domain="skyrimspecialedition",
                    title="New CBBE Text Preset",
                    author="PresetAuthor",
                    url="https://example.com/new-cbbe-text",
                    category="Body",
                    original_summary="A newer CBBE body preset without preview media.",
                    thumbnail_url="",
                    updated_at_remote="2026-05-25T00:00:00+00:00",
                    first_seen_at="2026-05-25T00:00:00+00:00",
                    last_seen_at="2026-05-25T00:00:00+00:00",
                    adult_content=False,
                ),
            ]
        )
        session.commit()
    caplog.set_level(logging.INFO)

    response = client.post(
        "/api/agent/chat",
        json={"message": "Skyrim Special Edition latest CBBE preset with preview image"},
    )

    assert response.status_code == 200
    body = response.json()
    titles = [match["title"] for match in body["matches"]]
    assert titles[:1] == ["New CBBE Preview Preset"]
    assert "New CBBE Text Preset" not in titles
    messages = _log_messages(caplog)
    _assert_graph_stage_logs(messages)
    assert any("agent.chat.plan" in message and "sort=updated_at_remote/desc" in message for message in messages)
    assert any("agent.chat.plan" in message and "has_thumbnail=True" in message for message in messages)
    assert any("agent.search.local count=" in message and "sort=updated_at_remote/desc" in message for message in messages)
    assert any("agent.search.local count=" in message and "has_thumbnail=True" in message for message in messages)
    assert any("agent.retrieval." in message and "has_thumbnail=True" in message for message in messages)
    assert any("agent.search.final count=" in message for message in messages)


def test_chat_endpoint_filters_absolute_updated_after_and_logs_constraints(client, engine, caplog):
    _seed_mods(engine)
    with Session(engine) as session:
        session.add_all(
            [
                Mod(
                    source="nexusmods",
                    external_id="body-2023-update",
                    game="Skyrim Special Edition",
                    game_domain="skyrimspecialedition",
                    title="Legacy Body Preset",
                    author="PresetAuthor",
                    url="https://example.com/body-2023-update",
                    category="Body",
                    original_summary="A body preset updated before the requested year.",
                    updated_at_remote="2023-12-31T23:59:59+00:00",
                    first_seen_at="2023-12-31T23:59:59+00:00",
                    last_seen_at="2023-12-31T23:59:59+00:00",
                    adult_content=False,
                ),
                Mod(
                    source="nexusmods",
                    external_id="body-2024-update",
                    game="Skyrim Special Edition",
                    game_domain="skyrimspecialedition",
                    title="Modern Body Preset",
                    author="PresetAuthor",
                    url="https://example.com/body-2024-update",
                    category="Body",
                    original_summary="A body preset updated after the requested year.",
                    updated_at_remote="2024-02-01T00:00:00+00:00",
                    first_seen_at="2024-02-01T00:00:00+00:00",
                    last_seen_at="2024-02-01T00:00:00+00:00",
                    adult_content=False,
                ),
            ]
        )
        session.commit()
    caplog.set_level(logging.INFO)

    response = client.post(
        "/api/agent/chat",
        json={"message": "2024年以后更新的 Skyrim Special Edition body mod"},
    )

    assert response.status_code == 200
    body = response.json()
    titles = [match["title"] for match in body["matches"]]
    assert "Modern Body Preset" in titles
    assert "Legacy Body Preset" not in titles
    assert "Bimbo Body Morph" not in titles
    messages = _log_messages(caplog)
    _assert_graph_stage_logs(messages)
    assert any("agent.chat.plan" in message and "updated_after=2024-01-01T00:00:00+00:00" in message for message in messages)
    assert any("agent.search.local count=" in message and "updated_after=2024-01-01T00:00:00+00:00" in message for message in messages)
    assert any("agent.retrieval." in message and "updated_after=2024-01-01T00:00:00+00:00" in message for message in messages)
    assert any("agent.search.final count=" in message for message in messages)


def test_chat_endpoint_filters_published_year_range_and_logs_constraints(client, engine, caplog):
    _seed_mods(engine)
    with Session(engine) as session:
        session.add_all(
            [
                Mod(
                    source="nexusmods",
                    external_id="body-2023-published",
                    game="Skyrim Special Edition",
                    game_domain="skyrimspecialedition",
                    title="Older Published Body Preset",
                    author="PresetAuthor",
                    url="https://example.com/body-2023-published",
                    category="Body",
                    original_summary="A body preset published before the requested year.",
                    published_at_remote="2023-12-31T23:59:59+00:00",
                    first_seen_at="2023-12-31T23:59:59+00:00",
                    last_seen_at="2023-12-31T23:59:59+00:00",
                    adult_content=False,
                ),
                Mod(
                    source="nexusmods",
                    external_id="body-2024-published",
                    game="Skyrim Special Edition",
                    game_domain="skyrimspecialedition",
                    title="Published Body Preset 2024",
                    author="PresetAuthor",
                    url="https://example.com/body-2024-published",
                    category="Body",
                    original_summary="A body preset published during the requested year.",
                    published_at_remote="2024-06-01T00:00:00+00:00",
                    first_seen_at="2024-06-01T00:00:00+00:00",
                    last_seen_at="2024-06-01T00:00:00+00:00",
                    adult_content=False,
                ),
                Mod(
                    source="nexusmods",
                    external_id="body-2025-published",
                    game="Skyrim Special Edition",
                    game_domain="skyrimspecialedition",
                    title="Future Published Body Preset",
                    author="PresetAuthor",
                    url="https://example.com/body-2025-published",
                    category="Body",
                    original_summary="A body preset published after the requested year.",
                    published_at_remote="2025-01-01T00:00:00+00:00",
                    first_seen_at="2025-01-01T00:00:00+00:00",
                    last_seen_at="2025-01-01T00:00:00+00:00",
                    adult_content=False,
                ),
            ]
        )
        session.commit()
    caplog.set_level(logging.INFO)

    response = client.post(
        "/api/agent/chat",
        json={"message": "2024\u5e74\u53d1\u5e03\u7684 Skyrim Special Edition body mod"},
    )

    assert response.status_code == 200
    body = response.json()
    titles = [match["title"] for match in body["matches"]]
    assert titles[:1] == ["Published Body Preset 2024"]
    assert "Older Published Body Preset" not in titles
    assert "Future Published Body Preset" not in titles
    assert "Bimbo Body Morph" not in titles
    messages = _log_messages(caplog)
    _assert_graph_stage_logs(messages)
    assert any("agent.chat.plan" in message and "published_after=2024-01-01T00:00:00+00:00" in message for message in messages)
    assert any("agent.chat.plan" in message and "published_before=2024-12-31T23:59:59+00:00" in message for message in messages)
    assert any("agent.search.local count=" in message and "published_after=2024-01-01T00:00:00+00:00" in message for message in messages)
    assert any("agent.search.local count=" in message and "published_before=2024-12-31T23:59:59+00:00" in message for message in messages)
    assert any("agent.retrieval." in message and "published_after=2024-01-01T00:00:00+00:00" in message for message in messages)
    assert any("agent.retrieval." in message and "published_before=2024-12-31T23:59:59+00:00" in message for message in messages)
    assert any("agent.search.final count=1" in message for message in messages)


def test_chat_endpoint_filters_explicit_tags_and_logs_constraints(client, engine, caplog):
    _seed_mods(engine)
    with Session(engine) as session:
        session.add_all(
            [
                Mod(
                    source="nexusmods",
                    external_id="cbbe-body",
                    game="Skyrim Special Edition",
                    game_domain="skyrimspecialedition",
                    title="CBBE Body Preset",
                    author="PresetAuthor",
                    url="https://example.com/cbbe-body",
                    category="Body",
                    tags_json=json.dumps(["CBBE", "BodySlide"]),
                    original_summary="A body preset tagged for CBBE.",
                    first_seen_at="2026-05-22T00:00:00+00:00",
                    last_seen_at="2026-05-22T00:00:00+00:00",
                    adult_content=False,
                ),
                Mod(
                    source="nexusmods",
                    external_id="bhunp-body",
                    game="Skyrim Special Edition",
                    game_domain="skyrimspecialedition",
                    title="BHUNP Body Preset",
                    author="PresetAuthor",
                    url="https://example.com/bhunp-body",
                    category="Body",
                    tags_json=json.dumps(["BHUNP", "BodySlide"]),
                    original_summary="A body preset tagged for BHUNP.",
                    first_seen_at="2026-05-21T00:00:00+00:00",
                    last_seen_at="2026-05-21T00:00:00+00:00",
                    adult_content=False,
                ),
            ]
        )
        session.commit()
    caplog.set_level(logging.INFO)

    response = client.post(
        "/api/agent/chat",
        json={"message": "Skyrim Special Edition body mod with CBBE tag"},
    )

    assert response.status_code == 200
    body = response.json()
    titles = [match["title"] for match in body["matches"]]
    assert "CBBE Body Preset" in titles
    assert "BHUNP Body Preset" not in titles
    assert "Bimbo Body Morph" not in titles
    messages = _log_messages(caplog)
    _assert_graph_stage_logs(messages)
    assert any("agent.chat.plan" in message and "tags=['CBBE']" in message for message in messages)
    assert any("agent.search.local count=" in message and "tags=['CBBE']" in message for message in messages)
    assert any("agent.retrieval.fts status=" in message for message in messages)
    assert any("agent.search.final count=" in message for message in messages)


def test_chat_endpoint_excludes_negative_tag_phrase_from_hidden_tags(client, engine, caplog):
    _seed_mods(engine)
    with Session(engine) as session:
        session.add_all(
            [
                Mod(
                    source="nexusmods",
                    external_id="hidden-cbbe-body",
                    game="Skyrim Special Edition",
                    game_domain="skyrimspecialedition",
                    title="Classic Body Preset",
                    author="PresetAuthor",
                    url="https://example.com/hidden-cbbe-body",
                    category="Body",
                    tags_json=json.dumps(["CBBE", "BodySlide"]),
                    original_summary="A body preset for Skyrim.",
                    first_seen_at="2026-05-23T00:00:00+00:00",
                    last_seen_at="2026-05-23T00:00:00+00:00",
                    adult_content=False,
                ),
                Mod(
                    source="nexusmods",
                    external_id="hidden-bhunp-body",
                    game="Skyrim Special Edition",
                    game_domain="skyrimspecialedition",
                    title="Neutral Body Preset",
                    author="PresetAuthor",
                    url="https://example.com/hidden-bhunp-body",
                    category="Body",
                    tags_json=json.dumps(["BHUNP", "BodySlide"]),
                    original_summary="A body preset for Skyrim.",
                    first_seen_at="2026-05-22T00:00:00+00:00",
                    last_seen_at="2026-05-22T00:00:00+00:00",
                    adult_content=False,
                ),
            ]
        )
        session.commit()
    caplog.set_level(logging.INFO)

    response = client.post(
        "/api/agent/chat",
        json={"message": "Skyrim Special Edition body mod 不带 CBBE 标签"},
    )

    assert response.status_code == 200
    body = response.json()
    titles = [match["title"] for match in body["matches"]]
    assert "Neutral Body Preset" in titles
    assert "Classic Body Preset" not in titles
    messages = _log_messages(caplog)
    _assert_graph_stage_logs(messages)
    assert any("agent.chat.plan" in message and "excluded_keywords=" in message and "cbbe" in message for message in messages)
    assert any("agent.chat.plan" in message and "tags=[]" in message for message in messages)
    assert any("agent.search.local count=" in message and "excluded_keywords=" in message and "cbbe" in message for message in messages)
    assert any("agent.search.local count=" in message and "tags=[]" in message for message in messages)
    assert any("agent.retrieval." in message and "excluded_keywords=" in message and "cbbe" in message for message in messages)
    assert any("agent.search.final count=2" in message for message in messages)


def test_chat_endpoint_splits_positive_and_negative_tag_constraints(client, engine, caplog):
    _seed_mods(engine)
    with Session(engine) as session:
        session.add_all(
            [
                Mod(
                    source="nexusmods",
                    external_id="mixed-cbbe-bodyslide",
                    game="Skyrim Special Edition",
                    game_domain="skyrimspecialedition",
                    title="CBBE BodySlide Preset",
                    author="PresetAuthor",
                    url="https://example.com/mixed-cbbe-bodyslide",
                    category="Body",
                    tags_json=json.dumps(["CBBE", "BodySlide"]),
                    original_summary="A BodySlide preset tagged for CBBE.",
                    first_seen_at="2026-05-23T00:00:00+00:00",
                    last_seen_at="2026-05-23T00:00:00+00:00",
                    adult_content=False,
                ),
                Mod(
                    source="nexusmods",
                    external_id="mixed-bhunp-bodyslide",
                    game="Skyrim Special Edition",
                    game_domain="skyrimspecialedition",
                    title="BHUNP BodySlide Preset",
                    author="PresetAuthor",
                    url="https://example.com/mixed-bhunp-bodyslide",
                    category="Body",
                    tags_json=json.dumps(["BHUNP", "BodySlide"]),
                    original_summary="A BodySlide preset tagged for BHUNP.",
                    first_seen_at="2026-05-22T00:00:00+00:00",
                    last_seen_at="2026-05-22T00:00:00+00:00",
                    adult_content=False,
                ),
                Mod(
                    source="nexusmods",
                    external_id="mixed-bhunp-no-bodyslide",
                    game="Skyrim Special Edition",
                    game_domain="skyrimspecialedition",
                    title="BHUNP Manual Preset",
                    author="PresetAuthor",
                    url="https://example.com/mixed-bhunp-manual",
                    category="Body",
                    tags_json=json.dumps(["BHUNP"]),
                    original_summary="A BHUNP preset without BodySlide files.",
                    first_seen_at="2026-05-21T00:00:00+00:00",
                    last_seen_at="2026-05-21T00:00:00+00:00",
                    adult_content=False,
                ),
            ]
        )
        session.commit()
    caplog.set_level(logging.INFO)

    response = client.post(
        "/api/agent/chat",
        json={"message": "Skyrim Special Edition body mod with BodySlide but not CBBE tag"},
    )

    assert response.status_code == 200
    body = response.json()
    titles = [match["title"] for match in body["matches"]]
    assert titles[:1] == ["BHUNP BodySlide Preset"]
    assert "CBBE BodySlide Preset" not in titles
    assert "BHUNP Manual Preset" not in titles
    messages = _log_messages(caplog)
    _assert_graph_stage_logs(messages)
    assert any("agent.chat.plan" in message and "tags=['BodySlide']" in message for message in messages)
    assert any("agent.chat.plan" in message and "excluded_keywords=" in message and "cbbe" in message for message in messages)
    assert any("agent.search.local count=" in message and "tags=['BodySlide']" in message for message in messages)
    assert any("agent.search.local count=" in message and "excluded_keywords=" in message and "cbbe" in message for message in messages)
    assert any("agent.retrieval." in message and "tags=['BodySlide']" in message for message in messages)
    assert any("agent.search.final count=1" in message for message in messages)


def test_chat_endpoint_infers_weapon_category_and_logs_constraints(client, engine, caplog):
    _seed_mods(engine)
    with Session(engine) as session:
        session.add_all(
            [
                Mod(
                    source="nexusmods",
                    external_id="dragon-sword",
                    game="Skyrim Special Edition",
                    game_domain="skyrimspecialedition",
                    title="Dragonsteel Blade",
                    author="WeaponAuthor",
                    url="https://example.com/dragonsteel-blade",
                    category="Weapons",
                    original_summary="A lore friendly sword pack.",
                    first_seen_at="2026-05-24T00:00:00+00:00",
                    last_seen_at="2026-05-24T00:00:00+00:00",
                    adult_content=False,
                ),
                Mod(
                    source="nexusmods",
                    external_id="dragon-armor",
                    game="Skyrim Special Edition",
                    game_domain="skyrimspecialedition",
                    title="Dragonsteel Armor",
                    author="ArmorAuthor",
                    url="https://example.com/dragonsteel-armor",
                    category="Armor",
                    original_summary="A matching armor pack.",
                    first_seen_at="2026-05-23T00:00:00+00:00",
                    last_seen_at="2026-05-23T00:00:00+00:00",
                    adult_content=False,
                ),
            ]
        )
        session.commit()
    caplog.set_level(logging.INFO)

    response = client.post(
        "/api/agent/chat",
        json={"message": "Skyrim Special Edition \u6b66\u5668\u7c7b mod"},
    )

    assert response.status_code == 200
    body = response.json()
    titles = [match["title"] for match in body["matches"]]
    assert titles[:1] == ["Dragonsteel Blade"]
    assert "Dragonsteel Armor" not in titles
    messages = _log_messages(caplog)
    _assert_graph_stage_logs(messages)
    assert any("agent.chat.plan" in message and "categories=['Weapons']" in message for message in messages)
    assert any("agent.search.local count=" in message and "categories=['Weapons']" in message for message in messages)
    assert any("agent.retrieval." in message and "keywords=" in message for message in messages)
    assert any("agent.search.final count=1" in message for message in messages)


def test_chat_endpoint_filters_exact_title_and_logs_constraints(client, engine, caplog):
    _seed_mods(engine)
    with Session(engine) as session:
        session.add(
            Mod(
                source="nexusmods",
                external_id="bimbo-morph-pack",
                game="Skyrim Special Edition",
                game_domain="skyrimspecialedition",
                title="Bimbo Morph Pack",
                author="PresetAuthor",
                url="https://example.com/bimbo-morph-pack",
                category="Body",
                original_summary="A similarly named bimbo morph collection.",
                first_seen_at="2026-05-22T00:00:00+00:00",
                last_seen_at="2026-05-22T00:00:00+00:00",
                adult_content=False,
            )
        )
        session.commit()
    caplog.set_level(logging.INFO)

    response = client.post(
        "/api/agent/chat",
        json={"message": 'Skyrim Special Edition mod named "Bimbo Body Morph"'},
    )

    assert response.status_code == 200
    body = response.json()
    titles = [match["title"] for match in body["matches"]]
    assert titles[:1] == ["Bimbo Body Morph"]
    assert "Bimbo Morph Pack" not in titles
    messages = _log_messages(caplog)
    _assert_graph_stage_logs(messages)
    assert any("agent.chat.plan" in message and "exact_title=Bimbo Body Morph" in message for message in messages)
    assert any("agent.search.local count=" in message and "exact_title=Bimbo Body Morph" in message for message in messages)
    assert any("agent.retrieval.fts status=" in message for message in messages)
    assert any("agent.search.final count=" in message for message in messages)


def test_chat_endpoint_keeps_unquoted_title_separate_from_following_constraints(client, engine, caplog):
    _seed_mods(engine)
    with Session(engine) as session:
        session.add_all(
            [
                Mod(
                    source="nexusmods",
                    external_id="visual-preset-named",
                    game="Skyrim Special Edition",
                    game_domain="skyrimspecialedition",
                    title="Visual Body Preset",
                    author="PresetAuthor",
                    url="https://example.com/visual-preset-named",
                    category="Body",
                    thumbnail_url="https://example.com/visual-preset-named.jpg",
                    original_summary="A body preset with preview media.",
                    first_seen_at="2026-05-23T00:00:00+00:00",
                    last_seen_at="2026-05-23T00:00:00+00:00",
                    adult_content=False,
                ),
                Mod(
                    source="nexusmods",
                    external_id="visual-preset-named-extended",
                    game="Skyrim Special Edition",
                    game_domain="skyrimspecialedition",
                    title="Visual Body Preset Extended",
                    author="PresetAuthor",
                    url="https://example.com/visual-preset-named-extended",
                    category="Body",
                    thumbnail_url="https://example.com/visual-preset-named-extended.jpg",
                    original_summary="A similarly named body preset.",
                    first_seen_at="2026-05-22T00:00:00+00:00",
                    last_seen_at="2026-05-22T00:00:00+00:00",
                    adult_content=False,
                ),
            ]
        )
        session.commit()
    caplog.set_level(logging.INFO)

    response = client.post(
        "/api/agent/chat",
        json={"message": "Skyrim Special Edition mod named Visual Body Preset with preview image"},
    )

    assert response.status_code == 200
    body = response.json()
    titles = [match["title"] for match in body["matches"]]
    assert titles[:1] == ["Visual Body Preset"]
    assert "Visual Body Preset Extended" not in titles
    messages = _log_messages(caplog)
    _assert_graph_stage_logs(messages)
    assert any("agent.chat.plan" in message and "exact_title=Visual Body Preset" in message for message in messages)
    assert any("agent.chat.plan" in message and "has_thumbnail=True" in message for message in messages)
    assert any("agent.search.local count=" in message and "exact_title=Visual Body Preset" in message for message in messages)
    assert any("agent.search.local count=" in message and "has_thumbnail=True" in message for message in messages)
    assert any(
        "agent.filter.exact_title status=succeeded exact_title=Visual Body Preset input=1 output=1" in message
        for message in messages
    )
    assert any("agent.search.final count=1" in message for message in messages)


def test_chat_endpoint_filters_explicit_version_and_logs_constraints(client, engine, caplog):
    _seed_mods(engine)
    with Session(engine) as session:
        session.add_all(
            [
                Mod(
                    source="nexusmods",
                    external_id="stable-bimbo-120",
                    game="Skyrim Special Edition",
                    game_domain="skyrimspecialedition",
                    title="Stable Bimbo Preset",
                    author="PresetAuthor",
                    url="https://example.com/stable-bimbo-120",
                    category="Body",
                    original_summary="A stable bimbo preset release.",
                    version="1.2.0",
                    first_seen_at="2026-05-22T00:00:00+00:00",
                    last_seen_at="2026-05-22T00:00:00+00:00",
                    adult_content=False,
                ),
                Mod(
                    source="nexusmods",
                    external_id="stable-bimbo-130",
                    game="Skyrim Special Edition",
                    game_domain="skyrimspecialedition",
                    title="Stable Bimbo Preset",
                    author="PresetAuthor",
                    url="https://example.com/stable-bimbo-130",
                    category="Body",
                    original_summary="A newer bimbo preset release.",
                    version="1.3.0",
                    first_seen_at="2026-05-23T00:00:00+00:00",
                    last_seen_at="2026-05-23T00:00:00+00:00",
                    adult_content=False,
                ),
            ]
        )
        session.commit()
    caplog.set_level(logging.INFO)

    response = client.post(
        "/api/agent/chat",
        json={"message": "Skyrim Special Edition stable bimbo preset version 1.2.0"},
    )

    assert response.status_code == 200
    body = response.json()
    matches = body["matches"]
    assert [match["title"] for match in matches][:1] == ["Stable Bimbo Preset"]
    assert matches[0]["version"] == "1.2.0"
    assert all(match["version"] == "1.2.0" for match in matches)
    messages = _log_messages(caplog)
    _assert_graph_stage_logs(messages)
    assert any("agent.chat.plan" in message and "version=1.2.0" in message for message in messages)
    assert any("agent.search.local count=" in message and "version=1.2.0" in message for message in messages)
    assert any("agent.retrieval.fts status=" in message for message in messages)
    assert any("agent.search.final count=" in message for message in messages)


def test_chat_endpoint_filters_source_url_identity_and_logs_constraints(client, engine, caplog):
    _seed_mods(engine)
    with Session(engine) as session:
        session.add_all(
            [
                Mod(
                    source="nexusmods",
                    external_id="1001",
                    game="Skyrim Special Edition",
                    game_domain="skyrimspecialedition",
                    title="Identity Locked Body Preset",
                    author="PresetAuthor",
                    url="https://www.nexusmods.com/skyrimspecialedition/mods/1001",
                    category="Body",
                    original_summary="A specific source page result.",
                    first_seen_at="2026-05-22T00:00:00+00:00",
                    last_seen_at="2026-05-22T00:00:00+00:00",
                    adult_content=False,
                ),
                Mod(
                    source="nexusmods",
                    external_id="1002",
                    game="Skyrim Special Edition",
                    game_domain="skyrimspecialedition",
                    title="Similar Identity Body Preset",
                    author="PresetAuthor",
                    url="https://www.nexusmods.com/skyrimspecialedition/mods/1002",
                    category="Body",
                    original_summary="A similar source page result that should not match.",
                    first_seen_at="2026-05-23T00:00:00+00:00",
                    last_seen_at="2026-05-23T00:00:00+00:00",
                    adult_content=False,
                ),
            ]
        )
        session.commit()
    caplog.set_level(logging.INFO)

    url = "https://www.nexusmods.com/skyrimspecialedition/mods/1001?tab=files"
    response = client.post("/api/agent/chat", json={"message": f"看看这个 mod {url}"})

    assert response.status_code == 200
    body = response.json()
    titles = [match["title"] for match in body["matches"]]
    assert titles[:1] == ["Identity Locked Body Preset"]
    assert "Similar Identity Body Preset" not in titles
    messages = _log_messages(caplog)
    _assert_graph_stage_logs(messages)
    assert any("agent.chat.plan" in message and "external_id=skyrimspecialedition:1001" in message for message in messages)
    assert any("agent.chat.plan" in message and f"source_url={url}" in message for message in messages)
    assert any("agent.search.local count=" in message and "external_id=skyrimspecialedition:1001" in message for message in messages)
    assert any("agent.search.local count=" in message and f"source_url={url}" in message for message in messages)
    assert any("agent.retrieval.fts status=" in message for message in messages)
    assert any("agent.search.final count=1" in message for message in messages)


def test_chat_endpoint_canonicalizes_nexus_numeric_id_with_game_and_logs_constraints(client, engine, caplog):
    _seed_mods(engine)
    with Session(engine) as session:
        session.add_all(
            [
                Mod(
                    source="nexusmods",
                    external_id="skyrimspecialedition:1001",
                    game="Skyrim Special Edition",
                    game_domain="skyrimspecialedition",
                    title="Canonical Nexus Body Preset",
                    author="PresetAuthor",
                    url="https://www.nexusmods.com/skyrimspecialedition/mods/1001",
                    category="Body",
                    original_summary="A canonical Nexus source id result.",
                    first_seen_at="2026-05-22T00:00:00+00:00",
                    last_seen_at="2026-05-22T00:00:00+00:00",
                    adult_content=False,
                ),
                Mod(
                    source="nexusmods",
                    external_id="stellarblade:1001",
                    game="Stellar Blade",
                    game_domain="stellarblade",
                    title="Wrong Game Nexus Preset",
                    author="PresetAuthor",
                    url="https://www.nexusmods.com/stellarblade/mods/1001",
                    category="Body",
                    original_summary="A same numeric id from another game.",
                    first_seen_at="2026-05-23T00:00:00+00:00",
                    last_seen_at="2026-05-23T00:00:00+00:00",
                    adult_content=False,
                ),
            ]
        )
        session.commit()
    caplog.set_level(logging.INFO)

    response = client.post(
        "/api/agent/chat",
        json={"message": "Nexus Skyrim Special Edition mod id 1001"},
    )

    assert response.status_code == 200
    body = response.json()
    titles = [match["title"] for match in body["matches"]]
    assert titles[:1] == ["Canonical Nexus Body Preset"]
    assert "Wrong Game Nexus Preset" not in titles
    messages = _log_messages(caplog)
    _assert_graph_stage_logs(messages)
    assert any("agent.chat.plan" in message and "external_id=skyrimspecialedition:1001" in message for message in messages)
    assert any("agent.search.local count=" in message and "external_id=skyrimspecialedition:1001" in message for message in messages)
    assert any("agent.retrieval." in message and "external_id=skyrimspecialedition:1001" in message for message in messages)
    assert any("agent.search.final count=1" in message for message in messages)


def test_chat_endpoint_uses_result_history_to_avoid_repeating_followup_results(client, engine):
    _seed_mods(engine)
    with Session(engine) as session:
        session.add(
            Mod(
                source="nexusmods",
                external_id="bimbo-2",
                game="Skyrim Special Edition",
                game_domain="skyrimspecialedition",
                title="Bimbo Body Preset",
                url="https://example.com/bimbo-preset",
                category="Body",
                original_summary="Another bimbo transformation preset.",
                first_seen_at="2026-05-21T00:00:00+00:00",
                last_seen_at="2026-05-21T00:00:00+00:00",
                adult_content=False,
            )
        )
        session.commit()

    response = client.post(
        "/api/agent/chat",
        json={
            "message": "还有其他类似的mod",
            "history": [
                {"role": "user", "text": "有什么 Skyrim bimbo mod"},
                {
                    "role": "assistant",
                    "text": "找到以下相关 Mod：\n\n[shown_mods]\n"
                    "1. title=Bimbo Body Morph; source=nexusmods; game=Skyrim Special Edition; category=Body",
                },
            ],
        },
    )

    assert response.status_code == 200
    titles = [match["title"] for match in response.json()["matches"]]
    assert "Bimbo Body Preset" in titles
    assert "Bimbo Body Morph" not in titles


def test_chat_endpoint_uses_ordinal_reference_for_similar_followup(client, engine, caplog):
    _seed_mods(engine)
    with Session(engine) as session:
        session.add_all(
            [
                Mod(
                    source="nexusmods",
                    external_id="doll-face-shown",
                    game="Skyrim Special Edition",
                    game_domain="skyrimspecialedition",
                    title="Doll Face Preset",
                    url="https://example.com/doll-face",
                    category="Body",
                    original_summary="A porcelain doll face preset.",
                    first_seen_at="2026-05-21T00:00:00+00:00",
                    last_seen_at="2026-05-21T00:00:00+00:00",
                    adult_content=False,
                ),
                Mod(
                    source="nexusmods",
                    external_id="doll-face-pack",
                    game="Skyrim Special Edition",
                    game_domain="skyrimspecialedition",
                    title="Doll Face Pack",
                    url="https://example.com/doll-face-pack",
                    category="Body",
                    original_summary="A similar porcelain doll face preset pack.",
                    first_seen_at="2026-05-22T00:00:00+00:00",
                    last_seen_at="2026-05-22T00:00:00+00:00",
                    adult_content=False,
                ),
                Mod(
                    source="nexusmods",
                    external_id="bimbo-body-preset",
                    game="Skyrim Special Edition",
                    game_domain="skyrimspecialedition",
                    title="Bimbo Body Preset",
                    url="https://example.com/bimbo-body-preset",
                    category="Body",
                    original_summary="Another bimbo body transformation preset.",
                    first_seen_at="2026-05-22T00:00:00+00:00",
                    last_seen_at="2026-05-22T00:00:00+00:00",
                    adult_content=False,
                ),
            ]
        )
        session.commit()
    caplog.set_level(logging.INFO)

    response = client.post(
        "/api/agent/chat",
        json={
            "message": "第二个还有类似的吗？",
            "history": [
                {"role": "user", "text": "有什么 Skyrim bimbo mod"},
                {
                    "role": "assistant",
                    "text": "找到以下相关 Mod：\n\n[shown_mods]\n"
                    "1. title=Bimbo Body Morph; source=nexusmods; game=Skyrim Special Edition; category=Body\n"
                    "2. title=Doll Face Preset; source=nexusmods; game=Skyrim Special Edition; category=Body",
                },
            ],
        },
    )

    assert response.status_code == 200
    body = response.json()
    titles = [match["title"] for match in body["matches"]]
    assert titles[:1] == ["Doll Face Pack"]
    assert "Bimbo Body Morph" not in titles
    assert "Doll Face Preset" not in titles
    messages = _log_messages(caplog)
    _assert_graph_stage_logs(messages)
    assert any("agent.chat.plan" in message and "doll" in message.lower() and "face" in message.lower() for message in messages)
    assert any("agent.chat.plan" in message and "keyword_match_mode=all" in message for message in messages)
    assert any("agent.chat.plan" in message and "exclude_titles=" in message and "Doll Face Preset" in message for message in messages)
    assert any("agent.search.local count=" in message and "keyword_match_mode=all" in message for message in messages)
    assert any("agent.search.local count=" in message and "exclude_titles=" in message and "Doll Face Preset" in message for message in messages)
    assert any("agent.search.final count=1" in message for message in messages)


def test_chat_endpoint_understands_alternative_followup_and_excludes_seen_result(client, engine, caplog):
    _seed_mods(engine)
    with Session(engine) as session:
        session.add(
            Mod(
                source="nexusmods",
                external_id="bimbo-stable",
                game="Skyrim Special Edition",
                game_domain="skyrimspecialedition",
                title="Stable Bimbo Preset",
                url="https://example.com/stable-bimbo",
                category="Body",
                original_summary="A stable bimbo transformation preset with narrow defaults.",
                version="1.2.0",
                first_seen_at="2026-05-22T00:00:00+00:00",
                last_seen_at="2026-05-22T00:00:00+00:00",
                adult_content=False,
            )
        )
        session.commit()
    caplog.set_level(logging.INFO)

    response = client.post(
        "/api/agent/chat",
        json={
            "message": "有没有更稳的替代品？",
            "history": [
                {"role": "user", "text": "有什么 Skyrim bimbo mod"},
                {
                    "role": "assistant",
                    "text": "找到以下相关 Mod：\n\n[shown_mods]\n"
                    "1. title=Bimbo Body Morph; source=nexusmods; game=Skyrim Special Edition; category=Body",
                },
            ],
        },
    )

    assert response.status_code == 200
    body = response.json()
    titles = [match["title"] for match in body["matches"]]
    assert titles[:1] == ["Stable Bimbo Preset"]
    assert "Bimbo Body Morph" not in titles
    assert "替代" in body["answer"]
    messages = _log_messages(caplog)
    _assert_graph_stage_logs(messages)
    assert any("agent.chat.plan" in message and "alternative" in message for message in messages)
    assert any("agent.chat.plan" in message and "bimbo" in message for message in messages)
    assert any("agent.search.final count=" in message for message in messages)


def test_chat_endpoint_uses_ordinal_reference_for_alternative_followup(client, engine, caplog):
    _seed_mods(engine)
    with Session(engine) as session:
        session.add(
            Mod(
                source="nexusmods",
                external_id="stable-safe-bimbo",
                game="Skyrim Special Edition",
                game_domain="skyrimspecialedition",
                title="Stable Safe Bimbo Preset",
                url="https://example.com/stable-safe-bimbo",
                category="Body",
                original_summary="A safer stable bimbo preset with narrow dependency choices.",
                version="1.2.0",
                first_seen_at="2026-05-23T00:00:00+00:00",
                last_seen_at="2026-05-23T00:00:00+00:00",
                adult_content=False,
            )
        )
        session.commit()
    caplog.set_level(logging.INFO)

    response = client.post(
        "/api/agent/chat",
        json={
            "message": "第二个有没有更安全的替代品？",
            "history": [
                {"role": "user", "text": "有什么 Skyrim bimbo mod"},
                {
                    "role": "assistant",
                    "text": "找到以下相关 Mod：\n\n[shown_mods]\n"
                    "1. title=Bimbo Body Morph; source=nexusmods; game=Skyrim Special Edition; category=Body\n"
                    "2. title=Stable Bimbo Preset; source=nexusmods; game=Skyrim Special Edition; category=Body",
                },
            ],
        },
    )

    assert response.status_code == 200
    body = response.json()
    titles = [match["title"] for match in body["matches"]]
    assert titles[:1] == ["Stable Safe Bimbo Preset"]
    assert "Bimbo Body Morph" not in titles
    assert "Stable Bimbo Preset" not in titles
    assert "替代" in body["answer"]
    messages = _log_messages(caplog)
    _assert_graph_stage_logs(messages)
    assert any("agent.chat.plan intent=alternative" in message for message in messages)
    assert any("agent.chat.plan" in message and "stable" in message.lower() and "bimbo" in message.lower() for message in messages)
    assert any("agent.chat.plan" in message and "exclude_titles=" in message and "Stable Bimbo Preset" in message for message in messages)
    assert any("agent.search.local count=" in message and "exclude_titles=" in message and "Stable Bimbo Preset" in message for message in messages)
    assert any("agent.search.final count=1" in message for message in messages)


def test_chat_endpoint_compares_shown_mods_for_beginner_safety(client, engine, caplog):
    _seed_mods(engine)
    with Session(engine) as session:
        session.add(
            Mod(
                source="nexusmods",
                external_id="bimbo-stable",
                game="Skyrim Special Edition",
                game_domain="skyrimspecialedition",
                title="Stable Bimbo Preset",
                url="https://example.com/stable-bimbo",
                category="Body",
                original_summary="A stable narrow bimbo transformation preset with compatibility notes.",
                version="1.2.0",
                first_seen_at="2026-05-22T00:00:00+00:00",
                last_seen_at="2026-05-22T00:00:00+00:00",
                adult_content=False,
            )
        )
        session.commit()
    caplog.set_level(logging.INFO)

    response = client.post(
        "/api/agent/chat",
        json={
            "message": "这两个哪个更适合新手，风险更低？",
            "history": [
                {"role": "user", "text": "有什么 Skyrim bimbo mod"},
                {
                    "role": "assistant",
                    "text": "找到以下相关 Mod：\n\n[shown_mods]\n"
                    "1. title=Bimbo Body Morph; source=nexusmods; game=Skyrim Special Edition; category=Body\n"
                    "2. title=Stable Bimbo Preset; source=nexusmods; game=Skyrim Special Edition; category=Body",
                },
            ],
        },
    )

    assert response.status_code == 200
    body = response.json()
    titles = [match["title"] for match in body["matches"]]
    assert {"Bimbo Body Morph", "Stable Bimbo Preset"}.issubset(set(titles))
    assert "更推荐：Stable Bimbo Preset" in body["answer"]
    messages = _log_messages(caplog)
    _assert_graph_stage_logs(messages)
    assert any("agent.chat.plan" in message and "comparison" in message for message in messages)
    assert any("agent.chat.plan" in message and "stable bimbo preset" in message for message in messages)
    assert any("agent.answer status=fallback reason=llm_unavailable" in message for message in messages)


def test_chat_endpoint_uses_shown_mod_context_for_install_risk_followup(client, engine, caplog):
    _seed_mods(engine)
    caplog.set_level(logging.INFO)

    response = client.post(
        "/api/agent/chat",
        json={
            "message": "这个安装风险高吗，会不会有前置依赖冲突？",
            "history": [
                {"role": "user", "text": "有什么 Skyrim bimbo mod"},
                {
                    "role": "assistant",
                    "text": "找到以下相关 Mod：\n\n[shown_mods]\n"
                    "1. title=Bimbo Body Morph; source=nexusmods; game=Skyrim Special Edition; category=Body",
                },
            ],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert [match["title"] for match in body["matches"]][:1] == ["Bimbo Body Morph"]
    assert "安装风险" in body["answer"]
    messages = _log_messages(caplog)
    _assert_graph_stage_logs(messages)
    assert any("agent.chat.plan" in message and "bimbo body morph" in message for message in messages)
    assert any("agent.chat.plan" in message and "install_risk" in message for message in messages)
    assert any("agent.answer status=fallback reason=llm_unavailable" in message for message in messages)


def test_chat_endpoint_uses_ordinal_shown_mod_reference_for_install_risk(client, engine, caplog):
    _seed_mods(engine)
    with Session(engine) as session:
        session.add(
            Mod(
                source="nexusmods",
                external_id="bimbo-stable",
                game="Skyrim Special Edition",
                game_domain="skyrimspecialedition",
                title="Stable Bimbo Preset",
                url="https://example.com/stable-bimbo",
                category="Body",
                original_summary="A stable bimbo transformation preset with dependency notes.",
                version="1.2.0",
                first_seen_at="2026-05-22T00:00:00+00:00",
                last_seen_at="2026-05-22T00:00:00+00:00",
                adult_content=False,
            )
        )
        session.commit()
    caplog.set_level(logging.INFO)

    response = client.post(
        "/api/agent/chat",
        json={
            "message": "第二个安装风险高吗，会不会有前置依赖冲突？",
            "history": [
                {"role": "user", "text": "有什么 Skyrim bimbo mod"},
                {
                    "role": "assistant",
                    "text": "找到以下相关 Mod：\n\n[shown_mods]\n"
                    "1. title=Bimbo Body Morph; source=nexusmods; game=Skyrim Special Edition; category=Body\n"
                    "2. title=Stable Bimbo Preset; source=nexusmods; game=Skyrim Special Edition; category=Body",
                },
            ],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert [match["title"] for match in body["matches"]][:1] == ["Stable Bimbo Preset"]
    assert "Bimbo Body Morph" not in [match["title"] for match in body["matches"]]
    assert "安装风险" in body["answer"]
    messages = _log_messages(caplog)
    _assert_graph_stage_logs(messages)
    assert any("agent.chat.plan" in message and "install_risk" in message for message in messages)
    assert any("agent.chat.plan" in message and "exact_title=Stable Bimbo Preset" in message for message in messages)
    assert any("agent.search.local count=" in message and "exact_title=Stable Bimbo Preset" in message for message in messages)
    assert any("agent.search.final count=1" in message for message in messages)
    assert any("agent.answer status=fallback reason=llm_unavailable" in message for message in messages)


def test_chat_endpoint_filters_requirement_terms_and_logs_constraints(client, engine, caplog):
    _seed_mods(engine)
    with Session(engine) as session:
        session.add_all(
            [
                Mod(
                    source="nexusmods",
                    external_id="skse-required",
                    game="Skyrim Special Edition",
                    game_domain="skyrimspecialedition",
                    title="SKSE Utility Patch",
                    url="https://example.com/skse-required",
                    category="Utilities",
                    original_summary="Requires SKSE and Address Library before installation.",
                    raw_json='{"requirements": ["SKSE", "Address Library"]}',
                    version="1.0.0",
                    first_seen_at="2026-05-22T00:00:00+00:00",
                    last_seen_at="2026-05-22T00:00:00+00:00",
                    adult_content=False,
                ),
                Mod(
                    source="nexusmods",
                    external_id="simple-utility",
                    game="Skyrim Special Edition",
                    game_domain="skyrimspecialedition",
                    title="Simple Utility Patch",
                    url="https://example.com/simple-utility",
                    category="Utilities",
                    original_summary="A lightweight utility patch with no script extender requirement.",
                    version="1.0.0",
                    first_seen_at="2026-05-23T00:00:00+00:00",
                    last_seen_at="2026-05-23T00:00:00+00:00",
                    adult_content=False,
                ),
            ]
        )
        session.commit()
    caplog.set_level(logging.INFO)

    response = client.post(
        "/api/agent/chat",
        json={"message": "需要 SKSE 前置的 Skyrim Special Edition utility mod 安装风险怎么样？"},
    )

    assert response.status_code == 200
    body = response.json()
    titles = [match["title"] for match in body["matches"]]
    assert titles[:1] == ["SKSE Utility Patch"]
    assert "Simple Utility Patch" not in titles
    assert "SKSE" in body["answer"]
    messages = _log_messages(caplog)
    _assert_graph_stage_logs(messages)
    assert any("agent.chat.plan intent=install_risk" in message for message in messages)
    assert any("agent.chat.plan" in message and "requirement_terms=['SKSE']" in message for message in messages)
    assert any("agent.search.local count=" in message and "requirement_terms=['SKSE']" in message for message in messages)
    assert any("agent.retrieval." in message and "requirement_terms=['SKSE']" in message for message in messages)
    assert any("agent.search.final count=1" in message for message in messages)
    assert any("agent.answer status=fallback reason=llm_unavailable" in message for message in messages)


def test_chat_endpoint_understands_script_extender_requirement_alias(client, engine, caplog):
    with Session(engine) as session:
        session.add_all(
            [
                Mod(
                    source="nexusmods",
                    external_id="skse-utility-alias",
                    game="Skyrim Special Edition",
                    game_domain="skyrimspecialedition",
                    title="Script Extender Utility Patch",
                    url="https://example.com/skse-utility-alias",
                    category="Utilities",
                    original_summary="Requires SKSE and Address Library before installation.",
                    raw_json='{"requirements": ["SKSE", "Address Library"]}',
                    version="1.0.0",
                    first_seen_at="2026-05-24T00:00:00+00:00",
                    last_seen_at="2026-05-24T00:00:00+00:00",
                    adult_content=False,
                ),
                Mod(
                    source="nexusmods",
                    external_id="plain-utility-alias",
                    game="Skyrim Special Edition",
                    game_domain="skyrimspecialedition",
                    title="No Extender Utility Patch",
                    url="https://example.com/plain-utility-alias",
                    category="Utilities",
                    original_summary="A lightweight utility patch with no script extender requirement.",
                    raw_json='{"requirements": []}',
                    version="1.0.0",
                    first_seen_at="2026-05-23T00:00:00+00:00",
                    last_seen_at="2026-05-23T00:00:00+00:00",
                    adult_content=False,
                ),
            ]
        )
        session.commit()
    caplog.set_level(logging.INFO)

    response = client.post(
        "/api/agent/chat",
        json={"message": "Skyrim Special Edition utility mod requiring script extender"},
    )

    assert response.status_code == 200
    body = response.json()
    titles = [match["title"] for match in body["matches"]]
    assert titles[:1] == ["Script Extender Utility Patch"]
    assert "No Extender Utility Patch" not in titles
    messages = _log_messages(caplog)
    _assert_graph_stage_logs(messages)
    assert any("agent.chat.plan" in message and "requirement_terms=['SKSE']" in message for message in messages)
    assert any("agent.search.local count=" in message and "requirement_terms=['SKSE']" in message for message in messages)
    assert any("agent.retrieval." in message and "requirement_terms=['SKSE']" in message for message in messages)
    assert any("agent.search.final count=1" in message for message in messages)


def test_chat_endpoint_treats_negative_requirement_as_exclusion(client, engine, caplog):
    _seed_mods(engine)
    with Session(engine) as session:
        session.add_all(
            [
                Mod(
                    source="nexusmods",
                    external_id="skse-required",
                    game="Skyrim Special Edition",
                    game_domain="skyrimspecialedition",
                    title="SKSE Utility Patch",
                    url="https://example.com/skse-required",
                    category="Utilities",
                    original_summary="Requires SKSE and Address Library before installation.",
                    raw_json='{"requirements": ["SKSE", "Address Library"]}',
                    version="1.0.0",
                    first_seen_at="2026-05-22T00:00:00+00:00",
                    last_seen_at="2026-05-22T00:00:00+00:00",
                    adult_content=False,
                ),
                Mod(
                    source="nexusmods",
                    external_id="simple-utility",
                    game="Skyrim Special Edition",
                    game_domain="skyrimspecialedition",
                    title="Simple Utility Patch",
                    url="https://example.com/simple-utility",
                    category="Utilities",
                    original_summary="A lightweight utility patch with no script extender requirement.",
                    version="1.0.0",
                    first_seen_at="2026-05-23T00:00:00+00:00",
                    last_seen_at="2026-05-23T00:00:00+00:00",
                    adult_content=False,
                ),
            ]
        )
        session.commit()
    caplog.set_level(logging.INFO)

    response = client.post(
        "/api/agent/chat",
        json={"message": "不需要 SKSE 前置的 Skyrim Special Edition utility mod"},
    )

    assert response.status_code == 200
    body = response.json()
    titles = [match["title"] for match in body["matches"]]
    assert titles[:1] == ["Simple Utility Patch"]
    assert "SKSE Utility Patch" not in titles
    messages = _log_messages(caplog)
    _assert_graph_stage_logs(messages)
    assert any("agent.chat.plan" in message and "intent=search" in message for message in messages)
    assert not any("agent.chat.plan" in message and "requirement_terms=['SKSE']" in message for message in messages)
    assert any("agent.chat.plan" in message and "excluded_keywords=" in message and "skse" in message.lower() for message in messages)
    assert any("agent.search.local count=" in message and "excluded_keywords=" in message and "skse" in message.lower() for message in messages)
    assert any("agent.retrieval." in message and "excluded_keywords=" in message and "skse" in message.lower() for message in messages)
    assert any("agent.search.final count=1" in message for message in messages)


def test_chat_endpoint_filters_compatibility_terms_and_logs_constraints(client, engine, caplog):
    _seed_mods(engine)
    with Session(engine) as session:
        session.add_all(
            [
                Mod(
                    source="nexusmods",
                    external_id="ae-body",
                    game="Skyrim Special Edition",
                    game_domain="skyrimspecialedition",
                    title="AE Body Preset",
                    url="https://example.com/ae-body",
                    category="Body",
                    original_summary="A body preset compatible with AE and runtime 1.6.640.",
                    raw_json='{"compatibility": ["AE", "1.6.640"]}',
                    version="1.0.0",
                    first_seen_at="2026-05-22T00:00:00+00:00",
                    last_seen_at="2026-05-22T00:00:00+00:00",
                    adult_content=False,
                ),
                Mod(
                    source="nexusmods",
                    external_id="se-body",
                    game="Skyrim Special Edition",
                    game_domain="skyrimspecialedition",
                    title="SE Body Preset",
                    url="https://example.com/se-body",
                    category="Body",
                    original_summary="A body preset for classic Special Edition runtime.",
                    raw_json='{"compatibility": ["SE"]}',
                    version="1.0.0",
                    first_seen_at="2026-05-23T00:00:00+00:00",
                    last_seen_at="2026-05-23T00:00:00+00:00",
                    adult_content=False,
                ),
            ]
        )
        session.commit()
    caplog.set_level(logging.INFO)

    response = client.post(
        "/api/agent/chat",
        json={"message": "支持 AE 的 Skyrim Special Edition body mod"},
    )

    assert response.status_code == 200
    body = response.json()
    titles = [match["title"] for match in body["matches"]]
    assert titles[:1] == ["AE Body Preset"]
    assert "SE Body Preset" not in titles
    messages = _log_messages(caplog)
    _assert_graph_stage_logs(messages)
    assert any("agent.chat.plan intent=search" in message for message in messages)
    assert not any("agent.chat.plan intent=install_risk" in message for message in messages)
    assert any("agent.chat.plan" in message and "compatibility_terms=['AE']" in message for message in messages)
    assert any("agent.search.local count=" in message and "compatibility_terms=['AE']" in message for message in messages)
    assert any("agent.retrieval." in message and "compatibility_terms=['AE']" in message for message in messages)
    assert any("agent.search.final count=1" in message for message in messages)


def test_chat_endpoint_filters_runtime_compatibility_terms_and_logs_constraints(client, engine, caplog):
    with Session(engine) as session:
        session.add_all(
            [
                Mod(
                    source="nexusmods",
                    external_id="ae-runtime-1640",
                    game="Skyrim Special Edition",
                    game_domain="skyrimspecialedition",
                    title="AE 1.6.640 Body Preset",
                    url="https://example.com/ae-runtime-1640",
                    category="Body",
                    original_summary="Supports Anniversary Edition builds. Runtime target 1.6.640.",
                    raw_json='{"compatibility": ["AE", "1.6.640"]}',
                    version="1.0.0",
                    first_seen_at="2026-05-24T00:00:00+00:00",
                    last_seen_at="2026-05-24T00:00:00+00:00",
                    adult_content=False,
                ),
                Mod(
                    source="nexusmods",
                    external_id="ae-runtime-1170",
                    game="Skyrim Special Edition",
                    game_domain="skyrimspecialedition",
                    title="AE 1.6.1170 Body Preset",
                    url="https://example.com/ae-runtime-1170",
                    category="Body",
                    original_summary="Supports Anniversary Edition builds. Runtime target 1.6.1170.",
                    raw_json='{"compatibility": ["AE", "1.6.1170"]}',
                    version="1.0.0",
                    first_seen_at="2026-05-23T00:00:00+00:00",
                    last_seen_at="2026-05-23T00:00:00+00:00",
                    adult_content=False,
                ),
                Mod(
                    source="nexusmods",
                    external_id="se-runtime-1640",
                    game="Skyrim Special Edition",
                    game_domain="skyrimspecialedition",
                    title="SE 1.6.640 Body Preset",
                    url="https://example.com/se-runtime-1640",
                    category="Body",
                    original_summary="Supports Special Edition builds. Runtime target 1.6.640.",
                    raw_json='{"compatibility": ["SE", "1.6.640"]}',
                    version="1.0.0",
                    first_seen_at="2026-05-22T00:00:00+00:00",
                    last_seen_at="2026-05-22T00:00:00+00:00",
                    adult_content=False,
                ),
            ]
        )
        session.commit()
    caplog.set_level(logging.INFO)

    response = client.post(
        "/api/agent/chat",
        json={"message": "Skyrim Special Edition body mod for AE 1.6.640"},
    )

    assert response.status_code == 200
    body = response.json()
    titles = [match["title"] for match in body["matches"]]
    assert titles[:1] == ["AE 1.6.640 Body Preset"]
    assert "AE 1.6.1170 Body Preset" not in titles
    assert "SE 1.6.640 Body Preset" not in titles
    messages = _log_messages(caplog)
    _assert_graph_stage_logs(messages)
    assert any("agent.chat.plan" in message and "compatibility_terms=['AE', '1.6.640']" in message for message in messages)
    assert not any("agent.chat.plan" in message and "version=1.6.640" in message for message in messages)
    assert any("agent.search.local count=" in message and "compatibility_terms=['AE', '1.6.640']" in message for message in messages)
    assert any("agent.retrieval." in message and "compatibility_terms=['AE', '1.6.640']" in message for message in messages)
    assert any("agent.search.final count=1" in message for message in messages)


def test_chat_endpoint_applies_generic_negative_keyword_after_compatibility(client, engine, caplog):
    _seed_mods(engine)
    with Session(engine) as session:
        session.add_all(
            [
                Mod(
                    source="nexusmods",
                    external_id="3ba-clean-body",
                    game="Skyrim Special Edition",
                    game_domain="skyrimspecialedition",
                    title="3BA Clean Body Preset",
                    url="https://example.com/3ba-clean-body",
                    category="Body",
                    original_summary="A 3BA body preset for physics body setups.",
                    raw_json='{"compatibility": ["3BA"], "requirements": ["BodySlide"]}',
                    first_seen_at="2026-05-22T00:00:00+00:00",
                    last_seen_at="2026-05-22T00:00:00+00:00",
                    adult_content=False,
                ),
                Mod(
                    source="nexusmods",
                    external_id="3ba-bhunp-body",
                    game="Skyrim Special Edition",
                    game_domain="skyrimspecialedition",
                    title="3BA BHUNP Hybrid Body Preset",
                    url="https://example.com/3ba-bhunp-body",
                    category="Body",
                    original_summary="A 3BA and BHUNP hybrid body preset.",
                    raw_json='{"compatibility": ["3BA", "BHUNP"], "requirements": ["BodySlide"]}',
                    first_seen_at="2026-05-24T00:00:00+00:00",
                    last_seen_at="2026-05-24T00:00:00+00:00",
                    adult_content=False,
                ),
                Mod(
                    source="nexusmods",
                    external_id="bhunp-only-body",
                    game="Skyrim Special Edition",
                    game_domain="skyrimspecialedition",
                    title="BHUNP Body Preset",
                    url="https://example.com/bhunp-only-body",
                    category="Body",
                    original_summary="A BHUNP body preset without 3BA compatibility.",
                    raw_json='{"compatibility": ["BHUNP"], "requirements": ["BodySlide"]}',
                    first_seen_at="2026-05-23T00:00:00+00:00",
                    last_seen_at="2026-05-23T00:00:00+00:00",
                    adult_content=False,
                ),
            ]
        )
        session.commit()
    caplog.set_level(logging.INFO)

    response = client.post(
        "/api/agent/chat",
        json={"message": "Skyrim Special Edition body preset for 3BA but not BHUNP"},
    )

    assert response.status_code == 200
    body = response.json()
    titles = [match["title"] for match in body["matches"]]
    assert titles[:1] == ["3BA Clean Body Preset"]
    assert "3BA BHUNP Hybrid Body Preset" not in titles
    assert "BHUNP Body Preset" not in titles
    messages = _log_messages(caplog)
    _assert_graph_stage_logs(messages)
    assert any("agent.chat.plan" in message and "compatibility_terms=['3BA']" in message for message in messages)
    assert any("agent.chat.plan" in message and "excluded_keywords=['bhunp']" in message for message in messages)
    assert any("agent.search.local count=" in message and "compatibility_terms=['3BA']" in message for message in messages)
    assert any("agent.search.local count=" in message and "excluded_keywords=['bhunp']" in message for message in messages)
    assert any("agent.retrieval." in message and "excluded_keywords=['bhunp']" in message for message in messages)
    assert any("agent.search.final count=1" in message for message in messages)


def test_chat_endpoint_splits_compatibility_and_negative_requirement(client, engine, caplog):
    _seed_mods(engine)
    with Session(engine) as session:
        session.add_all(
            [
                Mod(
                    source="nexusmods",
                    external_id="ae-lightweight-body",
                    game="Skyrim Special Edition",
                    game_domain="skyrimspecialedition",
                    title="AE Lightweight Body Preset",
                    url="https://example.com/ae-lightweight-body",
                    category="Body",
                    original_summary="A body preset compatible with AE and no script extender requirement.",
                    raw_json='{"compatibility": ["AE"], "requirements": []}',
                    first_seen_at="2026-05-23T00:00:00+00:00",
                    last_seen_at="2026-05-23T00:00:00+00:00",
                    adult_content=False,
                ),
                Mod(
                    source="nexusmods",
                    external_id="ae-skse-body",
                    game="Skyrim Special Edition",
                    game_domain="skyrimspecialedition",
                    title="AE SKSE Body Preset",
                    url="https://example.com/ae-skse-body",
                    category="Body",
                    original_summary="A body preset compatible with AE but requires SKSE.",
                    raw_json='{"compatibility": ["AE"], "requirements": ["SKSE"]}',
                    first_seen_at="2026-05-22T00:00:00+00:00",
                    last_seen_at="2026-05-22T00:00:00+00:00",
                    adult_content=False,
                ),
                Mod(
                    source="nexusmods",
                    external_id="se-no-skse-body",
                    game="Skyrim Special Edition",
                    game_domain="skyrimspecialedition",
                    title="SE No SKSE Body Preset",
                    url="https://example.com/se-no-skse-body",
                    category="Body",
                    original_summary="A body preset for classic Special Edition with no script extender requirement.",
                    raw_json='{"compatibility": ["SE"], "requirements": []}',
                    first_seen_at="2026-05-21T00:00:00+00:00",
                    last_seen_at="2026-05-21T00:00:00+00:00",
                    adult_content=False,
                ),
            ]
        )
        session.commit()
    caplog.set_level(logging.INFO)

    response = client.post(
        "/api/agent/chat",
        json={"message": "Skyrim Special Edition body mod compatible with AE but without SKSE requirement"},
    )

    assert response.status_code == 200
    body = response.json()
    titles = [match["title"] for match in body["matches"]]
    assert titles[:1] == ["AE Lightweight Body Preset"]
    assert "AE SKSE Body Preset" not in titles
    assert "SE No SKSE Body Preset" not in titles
    messages = _log_messages(caplog)
    _assert_graph_stage_logs(messages)
    assert any("agent.chat.plan intent=search" in message for message in messages)
    assert not any("agent.chat.plan intent=install_risk" in message for message in messages)
    assert any("agent.chat.plan" in message and "compatibility_terms=['AE']" in message for message in messages)
    assert not any("agent.chat.plan" in message and "requirement_terms=['SKSE']" in message for message in messages)
    assert any("agent.chat.plan" in message and "excluded_keywords=" in message and "skse" in message.lower() for message in messages)
    assert any("agent.search.local count=" in message and "compatibility_terms=['AE']" in message for message in messages)
    assert any("agent.search.local count=" in message and "excluded_keywords=" in message and "skse" in message.lower() for message in messages)
    assert any("agent.retrieval." in message and "compatibility_terms=['AE']" in message for message in messages)
    assert any("agent.search.final count=1" in message for message in messages)


def test_chat_endpoint_splits_negative_compatibility_and_positive_requirement(client, engine, caplog):
    _seed_mods(engine)
    with Session(engine) as session:
        session.add_all(
            [
                Mod(
                    source="nexusmods",
                    external_id="skse-se-body",
                    game="Skyrim Special Edition",
                    game_domain="skyrimspecialedition",
                    title="SKSE Classic Body Preset",
                    url="https://example.com/skse-se-body",
                    category="Body",
                    original_summary="A body preset for classic Special Edition that requires SKSE.",
                    raw_json='{"compatibility": ["SE"], "requirements": ["SKSE"]}',
                    first_seen_at="2026-05-24T00:00:00+00:00",
                    last_seen_at="2026-05-24T00:00:00+00:00",
                    adult_content=False,
                ),
                Mod(
                    source="nexusmods",
                    external_id="skse-ae-body",
                    game="Skyrim Special Edition",
                    game_domain="skyrimspecialedition",
                    title="SKSE AE Body Preset",
                    url="https://example.com/skse-ae-body",
                    category="Body",
                    original_summary="A body preset compatible with AE that requires SKSE.",
                    raw_json='{"compatibility": ["AE"], "requirements": ["SKSE"]}',
                    first_seen_at="2026-05-23T00:00:00+00:00",
                    last_seen_at="2026-05-23T00:00:00+00:00",
                    adult_content=False,
                ),
                Mod(
                    source="nexusmods",
                    external_id="se-no-skse-body-2",
                    game="Skyrim Special Edition",
                    game_domain="skyrimspecialedition",
                    title="Classic No Requirement Body Preset",
                    url="https://example.com/se-no-skse-body-2",
                    category="Body",
                    original_summary="A classic Special Edition body preset with no script extender requirement.",
                    raw_json='{"compatibility": ["SE"], "requirements": []}',
                    first_seen_at="2026-05-22T00:00:00+00:00",
                    last_seen_at="2026-05-22T00:00:00+00:00",
                    adult_content=False,
                ),
            ]
        )
        session.commit()
    caplog.set_level(logging.INFO)

    response = client.post(
        "/api/agent/chat",
        json={"message": "Skyrim Special Edition body mod not compatible with AE but requires SKSE"},
    )

    assert response.status_code == 200
    body = response.json()
    titles = [match["title"] for match in body["matches"]]
    assert titles[:1] == ["SKSE Classic Body Preset"]
    assert "SKSE AE Body Preset" not in titles
    assert "Classic No Requirement Body Preset" not in titles
    messages = _log_messages(caplog)
    _assert_graph_stage_logs(messages)
    assert any("agent.chat.plan" in message and "requirement_terms=['SKSE']" in message for message in messages)
    assert any("agent.chat.plan" in message and "excluded_keywords=['ae']" in message for message in messages)
    assert not any("agent.chat.plan" in message and "excluded_keywords=['ae', 'requires', 'skse']" in message for message in messages)
    assert not any("agent.search.local count=" in message and "keywords=['body', 'requires']" in message for message in messages)
    assert any("agent.search.local count=" in message and "requirement_terms=['SKSE']" in message for message in messages)
    assert any("agent.search.local count=" in message and "excluded_keywords=['ae']" in message for message in messages)
    assert any("agent.retrieval." in message and "requirement_terms=['SKSE']" in message for message in messages)
    assert any("agent.search.final count=1" in message for message in messages)


def test_chat_endpoint_filters_summary_language_and_logs_constraints(client, engine, caplog):
    _seed_mods(engine)
    with Session(engine) as session:
        zh_mod = Mod(
            source="nexusmods",
            external_id="zh-summary-body",
            game="Skyrim Special Edition",
            game_domain="skyrimspecialedition",
            title="Chinese Summary Body Preset",
            url="https://example.com/zh-summary-body",
            category="Body",
            original_summary="A body preset with translated notes.",
            first_seen_at="2026-05-22T00:00:00+00:00",
            last_seen_at="2026-05-22T00:00:00+00:00",
            adult_content=False,
        )
        en_mod = Mod(
            source="nexusmods",
            external_id="en-summary-body",
            game="Skyrim Special Edition",
            game_domain="skyrimspecialedition",
            title="English Summary Body Preset",
            url="https://example.com/en-summary-body",
            category="Body",
            original_summary="A body preset with English notes.",
            first_seen_at="2026-05-23T00:00:00+00:00",
            last_seen_at="2026-05-23T00:00:00+00:00",
            adult_content=False,
        )
        session.add_all([zh_mod, en_mod])
        session.flush()
        session.add_all(
            [
                ModSummary(
                    mod_id=zh_mod.id or 0,
                    language="zh-CN",
                    summary_type="brief",
                    content="中文摘要：身体预设，适合想看中文说明的用户。",
                    generated_at="2026-05-22T00:00:00+00:00",
                ),
                ModSummary(
                    mod_id=en_mod.id or 0,
                    language="en",
                    summary_type="brief",
                    content="English summary for a body preset.",
                    generated_at="2026-05-23T00:00:00+00:00",
                ),
            ]
        )
        session.commit()
    caplog.set_level(logging.INFO)

    response = client.post(
        "/api/agent/chat",
        json={"message": "有中文摘要的 Skyrim Special Edition body mod"},
    )

    assert response.status_code == 200
    body = response.json()
    titles = [match["title"] for match in body["matches"]]
    assert titles[:1] == ["Chinese Summary Body Preset"]
    assert "English Summary Body Preset" not in titles
    assert body["matches"][0]["translated_summary"] == "中文摘要：身体预设，适合想看中文说明的用户。"
    messages = _log_messages(caplog)
    _assert_graph_stage_logs(messages)
    assert any("agent.chat.plan" in message and "summary_languages=['zh-CN']" in message for message in messages)
    assert any("agent.search.local count=" in message and "summary_languages=['zh-CN']" in message for message in messages)
    assert any("agent.retrieval." in message and "summary_languages=['zh-CN']" in message for message in messages)
    assert any("agent.search.final count=1" in message for message in messages)


def test_chat_endpoint_keeps_tag_separate_from_following_summary_language(client, engine, caplog):
    _seed_mods(engine)
    with Session(engine) as session:
        target = Mod(
            source="nexusmods",
            external_id="zh-bodyslide-body",
            game="Skyrim Special Edition",
            game_domain="skyrimspecialedition",
            title="Chinese BodySlide Body Preset",
            url="https://example.com/zh-bodyslide-body",
            category="Body",
            tags_json=json.dumps(["BodySlide"]),
            original_summary="A BodySlide body preset with translated notes.",
            first_seen_at="2026-05-24T00:00:00+00:00",
            last_seen_at="2026-05-24T00:00:00+00:00",
            adult_content=False,
        )
        no_summary = Mod(
            source="nexusmods",
            external_id="plain-bodyslide-body",
            game="Skyrim Special Edition",
            game_domain="skyrimspecialedition",
            title="Plain BodySlide Body Preset",
            url="https://example.com/plain-bodyslide-body",
            category="Body",
            tags_json=json.dumps(["BodySlide"]),
            original_summary="A BodySlide body preset without translated notes.",
            first_seen_at="2026-05-23T00:00:00+00:00",
            last_seen_at="2026-05-23T00:00:00+00:00",
            adult_content=False,
        )
        wrong_tag = Mod(
            source="nexusmods",
            external_id="zh-manual-body",
            game="Skyrim Special Edition",
            game_domain="skyrimspecialedition",
            title="Chinese Manual Body Preset",
            url="https://example.com/zh-manual-body",
            category="Body",
            tags_json=json.dumps(["Manual"]),
            original_summary="A manual body preset with translated notes.",
            first_seen_at="2026-05-22T00:00:00+00:00",
            last_seen_at="2026-05-22T00:00:00+00:00",
            adult_content=False,
        )
        session.add_all([target, no_summary, wrong_tag])
        session.flush()
        session.add_all(
            [
                ModSummary(
                    mod_id=target.id or 0,
                    language="zh-CN",
                    summary_type="brief",
                    content="中文摘要：BodySlide 身体预设。",
                    generated_at="2026-05-24T00:00:00+00:00",
                ),
                ModSummary(
                    mod_id=wrong_tag.id or 0,
                    language="zh-CN",
                    summary_type="brief",
                    content="中文摘要：手动身体预设。",
                    generated_at="2026-05-22T00:00:00+00:00",
                ),
            ]
        )
        session.commit()
    caplog.set_level(logging.INFO)

    response = client.post(
        "/api/agent/chat",
        json={"message": "Skyrim Special Edition body mod with BodySlide tag and Chinese summary"},
    )

    assert response.status_code == 200
    body = response.json()
    titles = [match["title"] for match in body["matches"]]
    assert titles[:1] == ["Chinese BodySlide Body Preset"]
    assert "Plain BodySlide Body Preset" not in titles
    assert "Chinese Manual Body Preset" not in titles
    messages = _log_messages(caplog)
    _assert_graph_stage_logs(messages)
    assert any("agent.chat.plan" in message and "tags=['BodySlide']" in message for message in messages)
    assert any("agent.chat.plan" in message and "summary_languages=['zh-CN']" in message for message in messages)
    assert any("agent.search.local count=" in message and "tags=['BodySlide']" in message for message in messages)
    assert any("agent.search.local count=" in message and "summary_languages=['zh-CN']" in message for message in messages)
    assert any("agent.retrieval." in message and "tags=['BodySlide']" in message for message in messages)
    assert any("agent.retrieval." in message and "summary_languages=['zh-CN']" in message for message in messages)
    assert any("agent.search.final count=1" in message for message in messages)


def test_chat_endpoint_filters_negative_summary_language_with_thumbnail(client, engine, caplog):
    _seed_mods(engine)
    with Session(engine) as session:
        target = Mod(
            source="nexusmods",
            external_id="preview-no-zh-body",
            game="Skyrim Special Edition",
            game_domain="skyrimspecialedition",
            title="Preview Only Body Preset",
            url="https://example.com/preview-no-zh-body",
            category="Body",
            original_summary="A body preset with preview media and English-only notes.",
            thumbnail_url="https://example.com/preview-no-zh.jpg",
            first_seen_at="2026-05-24T00:00:00+00:00",
            last_seen_at="2026-05-24T00:00:00+00:00",
            adult_content=False,
        )
        zh_summary = Mod(
            source="nexusmods",
            external_id="preview-zh-body",
            game="Skyrim Special Edition",
            game_domain="skyrimspecialedition",
            title="Preview Chinese Body Preset",
            url="https://example.com/preview-zh-body",
            category="Body",
            original_summary="A body preset with preview media and translated notes.",
            thumbnail_url="https://example.com/preview-zh.jpg",
            first_seen_at="2026-05-23T00:00:00+00:00",
            last_seen_at="2026-05-23T00:00:00+00:00",
            adult_content=False,
        )
        text_only = Mod(
            source="nexusmods",
            external_id="text-no-preview-body",
            game="Skyrim Special Edition",
            game_domain="skyrimspecialedition",
            title="Text Only Body Preset",
            url="https://example.com/text-no-preview-body",
            category="Body",
            original_summary="A body preset without preview media.",
            thumbnail_url="",
            first_seen_at="2026-05-22T00:00:00+00:00",
            last_seen_at="2026-05-22T00:00:00+00:00",
            adult_content=False,
        )
        session.add_all([target, zh_summary, text_only])
        session.flush()
        session.add(
            ModSummary(
                mod_id=zh_summary.id or 0,
                language="zh-CN",
                summary_type="brief",
                content="中文摘要：带预览图的身体预设。",
                generated_at="2026-05-23T00:00:00+00:00",
            )
        )
        session.commit()
    caplog.set_level(logging.INFO)

    response = client.post(
        "/api/agent/chat",
        json={"message": "Skyrim Special Edition body mod with preview image but no Chinese summary"},
    )

    assert response.status_code == 200
    body = response.json()
    titles = [match["title"] for match in body["matches"]]
    assert titles[:1] == ["Preview Only Body Preset"]
    assert "Preview Chinese Body Preset" not in titles
    assert "Text Only Body Preset" not in titles
    messages = _log_messages(caplog)
    _assert_graph_stage_logs(messages)
    assert any("agent.chat.plan" in message and "has_thumbnail=True" in message for message in messages)
    assert any("agent.chat.plan" in message and "excluded_summary_languages=['zh-CN']" in message for message in messages)
    assert any("agent.search.local count=" in message and "has_thumbnail=True" in message for message in messages)
    assert any(
        "agent.search.local count=" in message and "excluded_summary_languages=['zh-CN']" in message
        for message in messages
    )
    assert any("agent.retrieval." in message and "excluded_summary_languages=['zh-CN']" in message for message in messages)
    assert any("agent.search.final count=1" in message for message in messages)


def test_chat_endpoint_filters_thumbnail_requirement_and_logs_constraints(client, engine, caplog):
    _seed_mods(engine)
    with Session(engine) as session:
        session.add_all(
            [
                Mod(
                    source="nexusmods",
                    external_id="visual-body",
                    game="Skyrim Special Edition",
                    game_domain="skyrimspecialedition",
                    title="Visual Body Preset",
                    url="https://example.com/visual-body",
                    category="Body",
                    original_summary="A body preset with preview images.",
                    thumbnail_url="https://example.com/thumb.jpg",
                    first_seen_at="2026-05-24T00:00:00+00:00",
                    last_seen_at="2026-05-24T00:00:00+00:00",
                    adult_content=False,
                ),
                Mod(
                    source="nexusmods",
                    external_id="text-only-body",
                    game="Skyrim Special Edition",
                    game_domain="skyrimspecialedition",
                    title="Text Only Body Preset",
                    url="https://example.com/text-only-body",
                    category="Body",
                    original_summary="A body preset without preview media.",
                    thumbnail_url="",
                    first_seen_at="2026-05-23T00:00:00+00:00",
                    last_seen_at="2026-05-23T00:00:00+00:00",
                    adult_content=False,
                ),
            ]
        )
        session.commit()
    caplog.set_level(logging.INFO)

    response = client.post(
        "/api/agent/chat",
        json={"message": "\u6709\u9884\u89c8\u56fe\u7684 Skyrim Special Edition body mod"},
    )

    assert response.status_code == 200
    body = response.json()
    titles = [match["title"] for match in body["matches"]]
    assert titles[:1] == ["Visual Body Preset"]
    assert "Text Only Body Preset" not in titles
    assert "Bimbo Body Morph" not in titles
    messages = _log_messages(caplog)
    _assert_graph_stage_logs(messages)
    assert any("agent.chat.plan" in message and "has_thumbnail=True" in message for message in messages)
    assert any("agent.search.local count=" in message and "has_thumbnail=True" in message for message in messages)
    assert any("agent.retrieval." in message and "has_thumbnail=True" in message for message in messages)
    assert any("agent.search.final count=1" in message for message in messages)


def test_chat_endpoint_logs_sql_branch_for_recent_query(client, engine, caplog):
    _seed_mods(engine)
    caplog.set_level(logging.INFO)

    response = client.post("/api/agent/chat", json={"message": "最近更新的mod"})

    assert response.status_code == 200
    assert response.json()["matches"]
    messages = _log_messages(caplog)
    _assert_graph_stage_logs(messages)
    assert any("agent.retrieval.fts status=skipped" in message for message in messages)
    assert any("agent.retrieval.sql status=succeeded" in message for message in messages)
    assert any("agent.search.final count=" in message for message in messages)
    assert any("agent.tool name=response_card_builder status=succeeded" in message for message in messages)


def test_chat_endpoint_logs_online_branch_from_real_entry(client, caplog, monkeypatch):
    caplog.set_level(logging.INFO)
    online_mod = Mod(
        source="nexusmods",
        external_id="online-1",
        game="Skyrim Special Edition",
        game_domain="skyrimspecialedition",
        title="Online Bimbo Style",
        url="https://example.com/online-bimbo",
        category="Body",
        original_summary="Online bimbo style result.",
        first_seen_at="2026-05-21T00:00:00+00:00",
        last_seen_at="2026-05-21T00:00:00+00:00",
        adult_content=False,
    )

    async def fake_nexus_run(self, tool_input):
        return [SearchResult(score=9, mod=online_mod, tool_name=self.name)]

    monkeypatch.setattr(NexusModsSearchTool, "run", fake_nexus_run)

    response = client.post(
        "/api/agent/chat",
        json={"message": "bimbo\n\n[scope]\nsource=nexusmods"},
    )

    assert response.status_code == 200
    assert [match["title"] for match in response.json()["matches"]][:1] == ["Online Bimbo Style"]
    messages = _log_messages(caplog)
    _assert_graph_stage_logs(messages)
    assert any("agent.retrieval.online tool=nexusmods_search status=succeeded count=1" in message for message in messages)
    assert any("agent.tool name=web_search status=succeeded results=1" in message for message in messages)
    assert any("agent.fusion status=succeeded" in message for message in messages)
    assert any("agent.ranking status=succeeded" in message for message in messages)


def test_chat_endpoint_logs_memory_preferences_in_tool_plan(client, engine, caplog):
    _seed_mods(engine)
    with Session(engine) as session:
        session.add(
            Setting(
                key="agent_preferences_json",
                value=json.dumps({"favorite_summary": {"top_sources": ["nexusmods"]}}),
                updated_at="2026-05-23T00:00:00+00:00",
            )
        )
        session.commit()
    caplog.set_level(logging.INFO)

    response = client.post("/api/agent/chat", json={"message": "Skyrim bimbo"})

    assert response.status_code == 200
    messages = _log_messages(caplog)
    _assert_graph_stage_logs(messages)
    assert any("agent.memory loaded=True favorite_summary=True" in message for message in messages)
    assert any("agent.tool name=tool_planner" in message and "nexusmods_search" in message for message in messages)
    assert any(
        "agent.tool name=tool_planner" in message
        and "tool_policy_score=" in message
        and "tool_policy_strategy=" in message
        and "online_recall_mode=" in message
        for message in messages
    )


def test_chat_endpoint_marks_stale_preference_memory_and_does_not_apply_long_term_slots(client, engine, caplog):
    _seed_mods(engine)
    stale_updated_at = (datetime.now(UTC) - timedelta(days=180)).isoformat()
    with Session(engine) as session:
        session.add(
            Setting(
                key="agent_preferences_json",
                value=json.dumps(
                    {
                        "favorite_summary": {
                            "top_games": ["Stellar Blade"],
                            "top_sources": ["nexusmods"],
                            "adult_content_allowed": True,
                        },
                        "updated_at": stale_updated_at,
                    }
                ),
                updated_at="2026-05-23T00:00:00+00:00",
            )
        )
        session.commit()
    caplog.set_level(logging.INFO)

    response = client.post("/api/agent/chat", json={"message": "找最近更新的服装 Mod"})

    assert response.status_code == 200
    body = response.json()
    evidence = body.get("understanding", {}).get("evidence", [])
    assert any(item.get("field") == "preference_memory_stale" and item.get("value") is True for item in evidence)
    assert any(
        item.get("field") == "preference_memory_reason" and item.get("value") == "stale_preference_memory"
        for item in evidence
    )
    assert not any(item.get("source") == "long_term_favorite" and item.get("field") in {"game", "source"} for item in evidence)
    assert any(item.get("field") == "preference_stale" and item.get("value") is True for item in (body.get("memory_evidence") or []))
    assert any(item.get("field") == "preferences_age_days" for item in (body.get("memory_evidence") or []))


def test_chat_endpoint_logs_llm_answer_branch(client, engine, caplog, monkeypatch):
    _seed_mods(engine)
    caplog.set_level(logging.INFO)

    monkeypatch.setattr(
        llm_config_service,
        "get_llm_config",
        lambda settings, provider_override=None, model_override=None: ("test", "key", "", "model"),
    )
    monkeypatch.setattr(llm_provider_config, "provider_has_credentials", lambda provider, api_key: True)

    async def fake_answer_matches(self, **kwargs):
        return "LLM 推荐 Bimbo Body Morph。"

    async def fake_next_steps(self, **kwargs):
        return ["继续看安装风险"]

    monkeypatch.setattr(AgentAnswerService, "answer_matches", fake_answer_matches)
    monkeypatch.setattr(AgentAnswerService, "suggest_next_steps", fake_next_steps)

    async def fake_validate_matches(self, tool_input):
        return LlmCandidateValidatorOutput(matches=tool_input.matches, status="succeeded")

    monkeypatch.setattr(LlmCandidateValidatorTool, "run", fake_validate_matches)

    response = client.post("/api/agent/chat", json={"message": "bimbo"})

    assert response.status_code == 200
    body = response.json()
    assert body["used_llm"] is True
    assert body["answer"] == "LLM 推荐 Bimbo Body Morph。"
    assert "继续看安装风险" in body["response_cards"]["next_steps"]
    messages = _log_messages(caplog)
    _assert_graph_stage_logs(messages)
    assert any("agent.answer status=llm" in message for message in messages)
    assert any("agent.tool name=response_card_builder status=succeeded" in message for message in messages)


def test_chat_endpoint_returns_standard_understanding_and_evidence_id(client, engine, caplog):
    _seed_mods(engine)
    caplog.set_level(logging.INFO)

    response = client.post("/api/agent/chat", json={"message": "Skyrim bimbo"})

    assert response.status_code == 200
    body = response.json()
    assert isinstance(body.get("understanding"), dict)
    assert body["understanding"]["intent"] == "search"
    assert isinstance(body["understanding"].get("slots"), dict)
    assert isinstance(body["understanding"].get("evidence"), list)
    assert all(item.get("evidence_id") == body.get("evidence_id") for item in body["understanding"]["evidence"])
    assert any(item.get("field") == "game" for item in body["understanding"]["evidence"])
    assert any(item.get("field") == "preference_memory_applied" for item in body["understanding"]["evidence"])
    assert any(item.get("field") == "preference_memory_stale" for item in body["understanding"]["evidence"])
    assert any(item.get("field") == "preference_memory_reason" for item in body["understanding"]["evidence"])
    assert any("related_fragments" in item for item in body["understanding"]["evidence"] if item.get("field") == "game")
    assert isinstance(body.get("memory_evidence"), list)
    assert all(item.get("evidence_id") == body.get("evidence_id") for item in body["memory_evidence"])
    assert any(str(item.get("fragment_id", "")).startswith("m_") for item in body["memory_evidence"])
    assert any(item.get("field") == "game" for item in body["memory_evidence"])
    assert any(item.get("field") == "preference_stale" for item in body["memory_evidence"])
    assert isinstance(body.get("retrieval_evidence"), list)
    assert all(item.get("evidence_id") == body.get("evidence_id") for item in body["retrieval_evidence"])
    assert all(str(item.get("fragment_id", "")).startswith("r_") for item in body["retrieval_evidence"])
    assert any(isinstance(item.get("fields"), list) for item in body["retrieval_evidence"])
    assert any(item.get("stage") == "local_retrieval" for item in body["retrieval_evidence"])
    assert all(item.get("stage") in {"local_retrieval", "vector_retrieval", "online_retrieval", "final_ranking", "online_adaptation"} for item in body["retrieval_evidence"])
    assert isinstance(body.get("audit"), dict)
    assert set(body["audit"].keys()) == {"analysis", "evidence", "conclusion"}
    assert body["audit"]["analysis"]["intent"] == "search"
    assert body["audit"]["conclusion"]["match_count"] >= 1
    assert body["audit"]["conclusion"]["consistency_risk"] in {"low", "medium", "high"}
    assert body["audit"]["conclusion"]["tool_policy_confidence"] in {"low", "medium", "high", "unknown"}
    assert body["audit"]["conclusion"]["evidence_sufficiency"] in {"insufficient", "partial", "sufficient"}
    assert body["audit"]["conclusion"]["contract_status"] in {"ok", "violated"}
    assert isinstance(body["audit"]["conclusion"]["contract_violations_count"], int)
    assert isinstance(body["audit"]["conclusion"]["requires_clarification"], bool)
    assert isinstance(body["audit"]["conclusion"].get("recommended_action_reason"), str)
    assert isinstance(body["audit"]["conclusion"].get("action_payload"), dict)
    assert "conflict_count" in body["audit"]["evidence"]
    assert "conflict_fields" in body["audit"]["evidence"]
    assert "hard_conflict_count" in body["audit"]["evidence"]
    assert "soft_conflict_count" in body["audit"]["evidence"]
    assert isinstance(body["audit"]["evidence"].get("action_evidence_consistent"), bool)
    assert isinstance(body["audit"]["evidence"].get("action_evidence_consistency_reason"), str)
    assert isinstance(body["audit"]["evidence"].get("audit_contract_passed"), bool)
    assert isinstance(body["audit"]["evidence"].get("audit_contract_violations"), list)
    assert body["audit"]["conclusion"]["contract_violations_count"] == len(
        body["audit"]["evidence"]["audit_contract_violations"]
    )
    if body["audit"]["conclusion"]["contract_status"] == "ok":
        assert body["audit"]["conclusion"]["contract_violations_count"] == 0
    else:
        assert body["audit"]["conclusion"]["contract_violations_count"] > 0
    assert isinstance(body["audit"]["evidence"].get("analysis_evidence_coverage"), dict)
    assert isinstance(body["audit"]["evidence"]["analysis_evidence_coverage"].get("coverage_ratio"), float)
    assert isinstance(body["audit"]["evidence"]["analysis_evidence_coverage"].get("missing_fields"), list)
    assert isinstance(body["audit"]["evidence"].get("tool_policy"), dict)
    assert body["audit"]["evidence"]["tool_policy"].get("strategy") in {
        "local_only",
        "local_first_with_online",
        "local_first",
    }
    assert body["audit"]["evidence"]["tool_policy"].get("online_recall_mode") in {"narrow", "broad"}
    assert isinstance(body["audit"]["evidence"]["tool_policy"].get("expand_online_candidates"), list)
    assert isinstance(body["audit"]["evidence"]["tool_policy"].get("score"), float)
    assert "clarifying_question" in body
    assert isinstance(body.get("evidence_id"), str)
    assert body["evidence_id"].startswith("ev_")
    messages = _log_messages(caplog)
    assert any("agent.chat.plan evidence_id=" in message for message in messages)
    assert any("agent.search.final count=" in message and "evidence_id=" in message for message in messages)


def test_chat_endpoint_conflict_risk_requires_clarification(client, monkeypatch):
    async def fake_run_agent_graph(session, state):
        return {
            "response": AgentChatResponse(
                answer="ok",
                used_llm=False,
                matches=[],
                response_cards={"next_steps": ["继续筛选"]},
            ),
            "trace": [],
            "query_plan": {"evidence_id": "ev_conflict"},
            "query_diagnosis": {
                "intent": "search",
                "clarifying_question": None,
                "understanding": {
                    "intent": "search",
                    "slots": {"game": "Skyrim"},
                    "confidence": 0.7,
                    "followup": False,
                    "evidence": [
                        {
                            "fragment_id": "u_short_term_memory_game",
                            "field": "game",
                            "source": "short_term_memory",
                            "value": "Skyrim",
                        }
                    ],
                },
            },
            "memory_context": {
                "short_term": {"last_query_context": {"game": "Stellar Blade"}},
                "long_term": {},
                "merged": {},
            },
        }

    monkeypatch.setattr(runtime_module, "run_agent_graph", fake_run_agent_graph)

    response = client.post("/api/agent/chat", json={"message": "test"})
    assert response.status_code == 200
    body = response.json()
    assert body["audit"]["conclusion"]["consistency_risk"] == "high"
    assert body["audit"]["conclusion"]["requires_clarification"] is True
    assert body["audit"]["conclusion"]["recommended_action"] == "clarify_memory_conflict"
    assert body["audit"]["conclusion"]["recommended_action_reason"] == "high_consistency_risk_memory_conflict"
    assert body["audit"]["conclusion"]["action_payload"]["requires_user_confirmation"] is True
    assert "上下文存在冲突" in (body.get("clarifying_question") or "")


def test_chat_endpoint_recommends_expand_sources_when_online_adaptation_signal_present(client, monkeypatch):
    async def fake_run_agent_graph(session, state):
        return {
            "response": AgentChatResponse(
                answer="ok",
                used_llm=False,
                matches=[],
                response_cards={"next_steps": ["继续筛选"]},
                retrieval_evidence=[
                    {
                        "fragment_id": "r_1",
                        "stage": "online_adaptation",
                        "tool": "online_strategy",
                        "status": "suggested",
                        "count": 0,
                        "reason": "narrow_online_zero_result_expand_sources",
                    }
                ],
            ),
            "trace": [],
            "query_plan": {"evidence_id": "ev_adapt"},
            "query_diagnosis": {
                "intent": "search",
                "clarifying_question": None,
                "understanding": {
                    "intent": "search",
                    "slots": {},
                    "confidence": 0.35,
                    "followup": False,
                    "evidence": [
                        {
                            "fragment_id": "u_query_plan_intent",
                            "field": "intent",
                            "source": "query_plan",
                            "value": "search",
                        }
                    ],
                },
            },
            "memory_context": {"short_term": {}, "long_term": {}, "merged": {}},
            "tool_plan": {
                "tool_policy_evidence": {
                    "score": 0.31,
                    "strategy": "local_first_with_online",
                    "known_slot_count": 0,
                    "should_clarify": False,
                    "online_recall_mode": "narrow",
                    "local_tools": ["structured_sql", "sqlite_fts"],
                    "online_tools": ["nexusmods_search"],
                    "degraded_reasons": [],
                }
            },
        }

    monkeypatch.setattr(runtime_module, "run_agent_graph", fake_run_agent_graph)
    response = client.post("/api/agent/chat", json={"message": "test"})
    assert response.status_code == 200
    body = response.json()
    assert body["audit"]["conclusion"]["tool_policy_confidence"] == "low"
    assert body["audit"]["conclusion"]["recommended_action"] == "expand_online_sources_and_narrow_scope"
    assert body["audit"]["conclusion"]["expand_online_candidates"] == ["loverslab_google"]
    assert body["audit"]["conclusion"]["expand_online_candidates_detail"] == [
        {"id": "loverslab_google", "label": "LoversLab"}
    ]
    assert body["audit"]["conclusion"]["action_payload"]["expand_online_candidates"] == [
        {"id": "loverslab_google", "label": "LoversLab"}
    ]
    assert body["audit"]["evidence"]["web_search"]["enabled"] is True
    assert body["audit"]["evidence"]["web_search"]["adaptation_triggered"] is True
    assert body["audit"]["evidence"]["web_search"]["queried"] is False
    assert body["audit"]["evidence"]["web_search"]["tool_statuses"] == {
        "online_gate": "skipped",
    }
    assert body["audit"]["evidence"]["web_search"]["tool_result_counts"] == {
        "online_gate": 0,
    }
    assert "narrow_online_zero_result_expand_sources" in body["audit"]["evidence"]["web_search"]["trigger_reasons"]
    assert body["audit"]["evidence"]["retrieval_decision"]["mode"] == "web_adaptation_only"
    assert "narrow_online_zero_result_expand_sources" in body["audit"]["evidence"]["retrieval_decision"]["reason_groups"]["web"]
    assert body["response_cards"]["next_steps"][0] == "继续查 LoversLab 来源，并放宽关键词再试"


def test_chat_endpoint_exposes_web_query_decision_evidence(client, monkeypatch):
    async def fake_run_agent_graph(session, state):
        return {
            "response": AgentChatResponse(
                answer="ok",
                used_llm=False,
                matches=[],
                response_cards={"next_steps": ["继续筛选"]},
                retrieval_evidence=[
                    {
                        "fragment_id": "r_1",
                        "stage": "online_retrieval",
                        "tool": "nexusmods_search",
                        "status": "succeeded",
                        "count": 2,
                    }
                ],
            ),
            "trace": [],
            "query_plan": {"evidence_id": "ev_web_query_api"},
            "query_diagnosis": {
                "intent": "search",
                "clarifying_question": None,
                "understanding": {
                    "intent": "search",
                    "slots": {},
                    "confidence": 0.72,
                    "followup": False,
                    "evidence": [
                        {
                            "fragment_id": "u_query_plan_intent",
                            "field": "intent",
                            "source": "query_plan",
                            "value": "search",
                        }
                    ],
                },
            },
            "memory_context": {"short_term": {}, "long_term": {}, "merged": {}},
            "tool_plan": {
                "tool_policy_evidence": {
                    "score": 0.76,
                    "strategy": "local_first_with_online",
                    "known_slot_count": 0,
                    "should_clarify": False,
                    "online_recall_mode": "broad",
                    "local_tools": ["structured_sql", "sqlite_fts"],
                    "online_tools": ["nexusmods_search"],
                    "degraded_reasons": [],
                }
            },
        }

    monkeypatch.setattr(runtime_module, "run_agent_graph", fake_run_agent_graph)
    response = client.post("/api/agent/chat", json={"message": "test"})
    assert response.status_code == 200
    body = response.json()
    assert body["audit"]["evidence"]["web_search"]["enabled"] is True
    assert body["audit"]["evidence"]["web_search"]["queried"] is True
    assert body["audit"]["evidence"]["web_search"]["tools"] == ["nexusmods_search"]
    assert body["audit"]["evidence"]["web_search"]["tool_statuses"] == {"nexusmods_search": "succeeded"}
    assert body["audit"]["evidence"]["web_search"]["tool_result_counts"] == {"nexusmods_search": 2}
    assert body["audit"]["evidence"]["web_search"]["online_result_count"] == 2
    assert body["audit"]["evidence"]["retrieval_decision"]["mode"] == "local_plus_web"
    assert body["audit"]["evidence"]["retrieval_decision"]["reason_groups"]["web"] == []


def test_chat_endpoint_recommends_review_memory_signals_for_medium_risk(client, monkeypatch):
    async def fake_run_agent_graph(session, state):
        return {
            "response": AgentChatResponse(
                answer="ok",
                used_llm=False,
                matches=[],
                response_cards={"next_steps": ["继续筛选"]},
            ),
            "trace": [],
            "query_plan": {"evidence_id": "ev_medium"},
            "query_diagnosis": {
                "intent": "search",
                "clarifying_question": None,
                "understanding": {
                    "intent": "search",
                    "slots": {"sort_field": "downloads", "sort_order": "asc"},
                    "confidence": 0.6,
                    "followup": False,
                    "evidence": [
                        {
                            "fragment_id": "u_short_term_memory_sort_field",
                            "field": "sort_field",
                            "source": "short_term_memory",
                            "value": "downloads",
                        },
                        {
                            "fragment_id": "u_short_term_memory_sort_order",
                            "field": "sort_order",
                            "source": "short_term_memory",
                            "value": "asc",
                        },
                    ],
                },
            },
            "memory_context": {
                "short_term": {"active_constraints": {"sort_field": "updated_at_remote", "sort_order": "desc"}},
                "long_term": {},
                "merged": {},
            },
            "tool_plan": {
                "tool_policy_evidence": {
                    "score": 0.66,
                    "strategy": "local_first_with_online",
                    "known_slot_count": 1,
                    "should_clarify": False,
                    "online_recall_mode": "broad",
                    "local_tools": ["structured_sql", "sqlite_fts"],
                    "online_tools": ["nexusmods_search"],
                    "degraded_reasons": [],
                }
            },
        }

    monkeypatch.setattr(runtime_module, "run_agent_graph", fake_run_agent_graph)
    response = client.post("/api/agent/chat", json={"message": "test"})
    assert response.status_code == 200
    body = response.json()
    assert body["audit"]["conclusion"]["consistency_risk"] == "medium"
    assert body["audit"]["conclusion"]["recommended_action"] == "review_memory_signals"
    assert body["audit"]["conclusion"]["recommended_action_reason"] == "memory_signal_conflicts_detected"
    assert body["audit"]["conclusion"]["action_payload"]["review_targets"] == ["memory_signals", "context_slots"]


def test_chat_endpoint_collects_more_evidence_when_analysis_coverage_is_low(client, monkeypatch):
    async def fake_run_agent_graph(session, state):
        return {
            "response": AgentChatResponse(
                answer="ok",
                used_llm=False,
                matches=[],
                response_cards={"next_steps": ["继续筛选"]},
            ),
            "trace": [],
            "query_plan": {"evidence_id": "ev_low_coverage_api"},
            "query_diagnosis": {
                "intent": "search",
                "clarifying_question": None,
                "understanding": {
                    "intent": "search",
                    "slots": {},
                    "confidence": 0.55,
                    "followup": False,
                    "evidence": [],
                },
            },
            "memory_context": {"short_term": {}, "long_term": {}, "merged": {}},
            "tool_plan": {
                "tool_policy_evidence": {
                    "score": 0.81,
                    "strategy": "local_first_with_online",
                    "known_slot_count": 0,
                    "should_clarify": False,
                    "online_recall_mode": "broad",
                    "local_tools": ["structured_sql", "sqlite_fts"],
                    "online_tools": ["nexusmods_search"],
                    "degraded_reasons": [],
                }
            },
        }

    monkeypatch.setattr(runtime_module, "run_agent_graph", fake_run_agent_graph)
    response = client.post("/api/agent/chat", json={"message": "test"})
    assert response.status_code == 200
    body = response.json()
    assert body["audit"]["conclusion"]["evidence_sufficiency"] == "insufficient"
    assert body["audit"]["conclusion"]["recommended_action"] == "collect_more_evidence"
    assert body["audit"]["conclusion"]["recommended_action_reason"] == "insufficient_analysis_evidence"
    assert "analysis_evidence" in body["audit"]["conclusion"]["action_payload"]["review_targets"]
    assert body["response_cards"]["next_steps"][0] == "我想补充目标游戏和关键词后再查一次"


def test_chat_endpoint_normalizes_semantic_memory_field_aliases(client, monkeypatch):
    async def fake_run_agent_graph(session, state):
        return {
            "response": AgentChatResponse(answer="ok", used_llm=False, matches=[], response_cards={"next_steps": ["继续筛选"]}),
            "trace": [],
            "query_plan": {"evidence_id": "ev_semantic_memory_alias_api"},
            "query_diagnosis": {
                "intent": "search",
                "clarifying_question": None,
                "understanding": {
                    "intent": "search",
                    "slots": {},
                    "confidence": 0.7,
                    "followup": False,
                    "evidence": [{"fragment_id": "u_query_plan_intent", "field": "intent", "source": "query_plan", "value": "search"}],
                },
            },
            "memory_context": {
                "short_term": {"last_query_context": {"semantic_anchor": ["pregnancy"], "semantic_domain": ["mechanics"]}},
                "long_term": {},
                "merged": {},
            },
        }

    monkeypatch.setattr(runtime_module, "run_agent_graph", fake_run_agent_graph)
    response = client.post("/api/agent/chat", json={"message": "test"})
    assert response.status_code == 200
    body = response.json()
    fields = {item.get("field") for item in (body.get("memory_evidence") or []) if isinstance(item, dict)}
    assert "semantic_anchors" in fields
    assert "semantic_domains" in fields


def test_agent_chat_openapi_includes_standardized_action_payload_schema(client):
    response = client.get("/openapi.json")
    assert response.status_code == 200
    body = response.json()
    schemas = ((body.get("components") or {}).get("schemas") or {})
    response_schema = schemas.get("AgentChatResponse") or {}
    response_props = response_schema.get("properties") or {}
    assert response_props.get("audit") == {"$ref": "#/components/schemas/AgentAudit"}
    audit_schema = schemas.get("AgentAudit") or {}
    audit_props = audit_schema.get("properties") or {}
    assert audit_props.get("analysis") == {"$ref": "#/components/schemas/AgentAuditAnalysis"}
    assert audit_props.get("evidence") == {"$ref": "#/components/schemas/AgentAuditEvidence"}
    assert audit_props.get("conclusion") == {"$ref": "#/components/schemas/AgentAuditConclusion"}

    conclusion_schema = schemas.get("AgentAuditConclusion") or {}
    conclusion_props = conclusion_schema.get("properties") or {}
    assert "action_payload" in conclusion_props
    assert "expand_online_candidates_detail" in conclusion_props
    assert "evidence_sufficiency" in conclusion_props
    assert "contract_status" in conclusion_props
    assert "contract_violations_count" in conclusion_props
    assert "recommended_action_reason" in conclusion_props

    payload_schema = schemas.get("AgentActionPayload") or {}
    payload_props = payload_schema.get("properties") or {}
    assert "expand_online_candidates" in payload_props
    assert "narrow_scope_fields" in payload_props
    assert "review_targets" in payload_props
    assert "conflict_fields" in payload_props
    assert "requires_user_confirmation" in payload_props
    evidence_schema = schemas.get("AgentAuditEvidence") or {}
    evidence_props = evidence_schema.get("properties") or {}
    assert "web_search" in evidence_props
    assert "retrieval_decision" in evidence_props
    assert "semantic_trace" in evidence_props
    assert "context_signal" in evidence_props
    assert "memory_context_alignment" in evidence_props
    assert "analysis_evidence_coverage" in evidence_props
    assert "tool_policy" in evidence_props
    assert "fragments" in evidence_props
    assert "memory_count" in evidence_props
    assert "retrieval_count" in evidence_props
    assert "conflict_count" in evidence_props
    assert "conflict_fields" in evidence_props
    assert "hard_conflict_count" in evidence_props
    assert "soft_conflict_count" in evidence_props
    assert "action_evidence_consistent" in evidence_props
    assert "action_evidence_consistency_reason" in evidence_props
    assert "audit_contract_passed" in evidence_props
    assert "audit_contract_violations" in evidence_props

    analysis_schema = schemas.get("AgentAuditAnalysis") or {}
    analysis_props = analysis_schema.get("properties") or {}
    assert "intent" in analysis_props
    assert "confidence" in analysis_props
    assert "slots" in analysis_props
    assert "semantic_anchors" in analysis_props
    assert "semantic_domains" in analysis_props
    assert "evidence_id" in analysis_props

    web_search_schema = schemas.get("AgentWebSearchEvidence") or {}
    web_props = web_search_schema.get("properties") or {}
    assert "enabled" in web_props
    assert "queried" in web_props
    assert "tools" in web_props
    assert "tool_statuses" in web_props
    assert "tool_result_counts" in web_props
    assert "trigger_reasons" in web_props

    retrieval_schema = schemas.get("AgentRetrievalDecisionEvidence") or {}
    retrieval_props = retrieval_schema.get("properties") or {}
    assert "mode" in retrieval_props
    assert "reasons" in retrieval_props
    assert "reason_groups" in retrieval_props
    assert "semantic_anchors" in retrieval_props
    assert "semantic_domains" in retrieval_props
    semantic_trace_schema = schemas.get("AgentSemanticTraceEvidence") or {}
    semantic_trace_props = semantic_trace_schema.get("properties") or {}
    assert "anchors" in semantic_trace_props
    assert "context_anchors" in semantic_trace_props
    assert "domains" in semantic_trace_props
    assert "inherited_anchor_overlap" in semantic_trace_props
    assert "memory_fragment_count" in semantic_trace_props

    context_signal_schema = schemas.get("AgentContextSignalEvidence") or {}
    context_signal_props = context_signal_schema.get("properties") or {}
    assert "source" in context_signal_props
    assert "quality_score" in context_signal_props
    assert "inherit_score" in context_signal_props
    assert "inherit_threshold" in context_signal_props
    assert "followup_score" in context_signal_props
    assert "inherited" in context_signal_props
    assert "topic_shift_detected" in context_signal_props
    assert "policy_reasons" in context_signal_props


@pytest.mark.parametrize(
    ("message", "expected_title", "expected_anchor", "expected_domain", "expected_keyword"),
    [
        ("有什么在玩法上可以扮演bimbo的MOD", "Bimbo Roleplay Framework", "roleplay", "mechanics", "bimbo"),
        ("有什么妓女风格的服装MOD", "Street Courtesan Outfit", "sexworker_style", "content_type", "prostitute"),
        ("有什么mod支持怀孕玩法", "Pregnancy Gameplay Overhaul", "pregnancy", "mechanics", "pregnancy"),
        ("爱的实验室有什么体系mod", "LoversLab System Framework", "framework", "source_scope", "framework"),
    ],
)
def test_chat_endpoint_business_examples_include_retrieval_decision_evidence(
    client,
    engine,
    message,
    expected_title,
    expected_anchor,
    expected_domain,
    expected_keyword,
):
    _seed_mods(engine)
    with Session(engine) as session:
        session.add_all(
            [
                Mod(
                    source="nexusmods",
                    external_id="bimbo-roleplay-1",
                    game="Skyrim Special Edition",
                    game_domain="skyrimspecialedition",
                    title="Bimbo Roleplay Framework",
                    url="https://example.com/bimbo-roleplay",
                    category="Gameplay",
                    original_summary="Roleplay framework for bimbo-style character progression.",
                    first_seen_at="2026-05-22T00:00:00+00:00",
                    last_seen_at="2026-05-22T00:00:00+00:00",
                    adult_content=False,
                ),
                Mod(
                    source="nexusmods",
                    external_id="courtesan-outfit-1",
                    game="Skyrim Special Edition",
                    game_domain="skyrimspecialedition",
                    title="Street Courtesan Outfit",
                    url="https://example.com/courtesan-outfit",
                    category="Outfit",
                    original_summary="Provocative prostitute-style outfit set.",
                    first_seen_at="2026-05-22T00:00:00+00:00",
                    last_seen_at="2026-05-22T00:00:00+00:00",
                    adult_content=True,
                ),
                Mod(
                    source="nexusmods",
                    external_id="pregnancy-gameplay-1",
                    game="Skyrim Special Edition",
                    game_domain="skyrimspecialedition",
                    title="Pregnancy Gameplay Overhaul",
                    url="https://example.com/pregnancy-gameplay",
                    category="Gameplay",
                    original_summary="Adds pregnancy systems and related gameplay loops.",
                    first_seen_at="2026-05-22T00:00:00+00:00",
                    last_seen_at="2026-05-22T00:00:00+00:00",
                    adult_content=True,
                ),
                Mod(
                    source="loverslab",
                    external_id="ll-framework-1",
                    game="Skyrim Special Edition",
                    game_domain="skyrimspecialedition",
                    title="LoversLab System Framework",
                    url="https://example.com/ll-framework",
                    category="Framework",
                    original_summary="Core system framework published on LoversLab.",
                    first_seen_at="2026-05-22T00:00:00+00:00",
                    last_seen_at="2026-05-22T00:00:00+00:00",
                    adult_content=True,
                ),
            ]
        )
        session.commit()

    response = client.post("/api/agent/chat", json={"message": message})
    assert response.status_code == 200
    body = response.json()
    titles = [match.get("title") for match in body.get("matches", [])]
    assert expected_title in titles

    evidence = ((body.get("audit") or {}).get("evidence") or {})
    retrieval_decision = evidence.get("retrieval_decision") or {}
    semantic_trace = evidence.get("semantic_trace") or {}
    assert retrieval_decision.get("mode") in {"local_only", "web_adaptation_only", "local_plus_web"}
    assert isinstance(retrieval_decision.get("reasons"), list)
    assert "web_enabled" in retrieval_decision
    assert "web_queried" in retrieval_decision
    assert isinstance(retrieval_decision.get("semantic_anchors"), list)
    assert isinstance(retrieval_decision.get("semantic_domains"), list)
    assert "semantic" in (retrieval_decision.get("reason_groups") or {})
    assert isinstance((retrieval_decision.get("reason_groups") or {}).get("semantic"), list)
    assert "semantic_anchors_detected" in (retrieval_decision.get("reason_groups") or {}).get("semantic", [])
    assert isinstance(semantic_trace.get("anchors"), list)
    assert isinstance(semantic_trace.get("domains"), list)
    assert isinstance(semantic_trace.get("memory_fragment_count"), int)
    assert ((body.get("audit") or {}).get("conclusion") or {}).get("contract_status") == "ok"
    assert ((body.get("audit") or {}).get("conclusion") or {}).get("contract_violations_count") == 0
    assert (evidence.get("audit_contract_violations") or []) == []

    understanding_evidence = ((body.get("understanding") or {}).get("evidence") or [])
    semantic_anchor_items = [item for item in understanding_evidence if item.get("field") == "semantic_anchors"]
    semantic_domain_items = [item for item in understanding_evidence if item.get("field") == "semantic_domains"]
    keyword_items = [item for item in understanding_evidence if item.get("field") == "keywords"]
    assert semantic_anchor_items
    assert semantic_domain_items
    assert keyword_items
    understanding_slots = (body.get("understanding") or {}).get("slots") or {}
    audit_analysis = (body.get("audit") or {}).get("analysis") or {}
    assert expected_keyword in (understanding_slots.get("keywords") or [])
    assert expected_keyword in ((audit_analysis.get("slots") or {}).get("keywords") or [])
    assert expected_keyword in (keyword_items[0].get("value") or [])
    assert expected_anchor in (semantic_anchor_items[0].get("value") or [])
    assert expected_domain in (semantic_domain_items[0].get("value") or [])

    tool_policy = evidence.get("tool_policy") or {}
    assert isinstance(tool_policy.get("semantic_anchors"), list)
    assert isinstance(tool_policy.get("semantic_domains"), list)
    assert expected_anchor in (tool_policy.get("semantic_anchors") or [])
    assert expected_domain in (tool_policy.get("semantic_domains") or [])
    assert expected_anchor in (retrieval_decision.get("semantic_anchors") or [])
    assert expected_domain in (retrieval_decision.get("semantic_domains") or [])
    assert f"semantic_domain_{expected_domain}" in ((retrieval_decision.get("reason_groups") or {}).get("semantic") or [])
