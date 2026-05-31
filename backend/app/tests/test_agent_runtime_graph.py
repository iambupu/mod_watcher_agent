import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

import app.models  # noqa: F401
from app.models.mod import Mod
from app.services.agent import runtime as runtime_module
from app.services.agent.memory.preference_service import AgentPreferenceService
from app.services.agent.reflection.audit_service import (
    annotate_action_evidence_consistency,
    apply_consistency_guard,
    audit_contract_violations,
    build_standard_audit,
    classify_retrieval_reason_group,
    expected_reason_for_action,
)
from app.services.agent.runtime import (
    AgentRuntime,
)
from app.services.agent.schemas import (
    AgentAudit,
    AgentChatRequest,
    AgentChatResponse,
    AgentModDetailRequest,
)
from app.services.agent.tools.mod_detail_answer_tool import ModDetailAnswerTool
from app.services.agent.workflows.mod_search_graph import (
    _event_duration_ms,
    generate_detail_answer_step,
    run_agent_graph,
)


def _response(answer: str) -> AgentChatResponse:
    return AgentChatResponse(answer=answer, used_llm=False, matches=[], response_cards=None)


def test_standard_audit_keeps_string_tool_policy_fields_as_single_items():
    audit = build_standard_audit(
        AgentChatResponse(
            answer="ok",
            used_llm=False,
            matches=[],
            response_cards={"next_steps": []},
            understanding={"intent": "search", "evidence": []},
        ),
        {
            "tool_policy_evidence": {
                "score": 0.4,
                "strategy": "local_first",
                "expand_online_candidates": "loverslab_google",
                "online_tools": "nexusmods_search",
            }
        },
    )

    tool_policy = audit["evidence"]["tool_policy"]
    assert tool_policy["expand_online_candidates"] == ["loverslab_google"]
    assert tool_policy["online_tools"] == ["nexusmods_search"]


def test_graph_event_duration_tolerates_invalid_values():
    assert _event_duration_ms({"duration_ms": "bad"}) == 0
    assert _event_duration_ms({"duration_ms": -5}) == 0
    assert _event_duration_ms({"duration_ms": "12"}) == 12


def _trace_steps(trace: list[dict]) -> list[str]:
    return [event["step"] for event in trace]


def _assert_succeeded_trace(trace: list[dict], *, compat: bool = False) -> None:
    expected_steps = [
        "load_state",
        "summarize_context",
    ]
    if compat:
        expected_steps.extend(["generate_detail_answer", "persist_result"])
    else:
        expected_steps.extend(
            [
                "diagnose_query",
                "plan_tools",
                "staged_retrieval",
                "rank_results",
                "generate_answer",
                "reflect",
                "persist_result",
            ]
        )
    assert _trace_steps(trace) == expected_steps
    for event in trace:
        assert event["status"] == "succeeded"
        assert isinstance(event["duration_ms"], int)
        assert event["duration_ms"] >= 0
        assert str(event.get("evidence_id") or "").startswith("ev_")
    assert len({event["evidence_id"] for event in trace}) == 1


def _session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    return Session(engine)


@pytest.mark.asyncio
async def test_agent_runtime_chat_returns_graph_response(monkeypatch):
    expected = _response("chat response")
    seen = {}

    async def fake_run_agent_graph(session, state):
        seen["session"] = session
        seen["state"] = state
        return {"response": expected, "trace": [{"step": "load_state", "status": "succeeded", "duration_ms": 0, "evidence_id": "ev_test"}]}

    monkeypatch.setattr(runtime_module, "run_agent_graph", fake_run_agent_graph)
    request = object()
    body = AgentChatRequest(message="recent mods")
    runtime = AgentRuntime(session="session")

    response = await runtime.chat(body, request)

    assert response is expected
    assert seen["session"] == "session"
    assert seen["state"]["chat_request"] == body
    assert seen["state"]["fastapi_request"] == request
    assert isinstance(response.audit, AgentAudit)
    assert set(response.audit.keys()) == {"analysis", "evidence", "conclusion"}
    assert runtime.last_trace == [{"step": "load_state", "status": "succeeded", "duration_ms": 0, "evidence_id": "ev_test"}]


@pytest.mark.asyncio
async def test_agent_runtime_delegates_chat_response_finalization(monkeypatch):
    expected = _response("chat response")
    seen = {}

    async def fake_run_agent_graph(session, state):
        return {
            "response": expected,
            "trace": [],
            "query_plan": {"evidence_id": "ev_finalize"},
            "query_diagnosis": {"intent": "search"},
            "memory_context": {"short_term": {}, "long_term": {}, "merged": {}},
        }

    def fake_finalize(session, *, request, response, graph_state, fallback_evidence_id):
        seen["session"] = session
        seen["request"] = request
        seen["response"] = response
        seen["graph_state"] = graph_state
        seen["fallback_evidence_id"] = fallback_evidence_id
        response.evidence_id = "ev_finalized"
        return response

    monkeypatch.setattr(runtime_module, "run_agent_graph", fake_run_agent_graph)
    monkeypatch.setattr(runtime_module, "finalize_chat_response", fake_finalize)
    body = AgentChatRequest(message="recent mods")

    response = await AgentRuntime(session="session").chat(body, object())

    assert response is expected
    assert response.evidence_id == "ev_finalized"
    assert seen["session"] == "session"
    assert seen["request"] == body
    assert seen["response"] is expected
    assert seen["graph_state"]["query_plan"]["evidence_id"] == "ev_finalize"
    assert str(seen["fallback_evidence_id"]).startswith("ev_")


@pytest.mark.asyncio
async def test_agent_runtime_chat_writes_current_turn_memory(monkeypatch):
    async def fake_run_agent_graph(session, state):
        return {
            "response": AgentChatResponse(answer="ok", used_llm=False, matches=[], response_cards=None),
            "trace": [],
            "query_plan": {
                "evidence_id": "ev_runtime_memory",
                "keywords": ["pregnancy"],
                "games": ["Skyrim Special Edition"],
                "categories": ["Gameplay"],
            },
            "query_diagnosis": {
                "intent": "search",
                "understanding": {
                    "intent": "search",
                    "slots": {"keywords": ["pregnancy"]},
                    "confidence": 0.79,
                    "followup": False,
                    "evidence": [
                        {
                            "fragment_id": "u_analysis_semantic_anchors",
                            "field": "semantic_anchors",
                            "source": "analysis",
                            "value": ["pregnancy"],
                            "evidence_id": "ev_runtime_memory",
                        },
                        {
                            "fragment_id": "u_analysis_semantic_domains",
                            "field": "semantic_domains",
                            "source": "analysis",
                            "value": ["mechanics"],
                            "evidence_id": "ev_runtime_memory",
                        },
                    ],
                },
            },
            "memory_context": {"short_term": {}, "long_term": {}, "merged": {}},
        }

    monkeypatch.setattr(runtime_module, "run_agent_graph", fake_run_agent_graph)
    with _session() as session:
        response = await AgentRuntime(session).chat(AgentChatRequest(message="有什么mod支持怀孕玩法"), object())
        preferences = AgentPreferenceService(session).load_preferences()

    context = preferences["last_query_context"]
    assert context["keywords"] == ["pregnancy"]
    assert context["game"] == "Skyrim Special Edition"
    assert context["category"] == "Gameplay"
    assert context["semantic_anchors"] == ["pregnancy"]
    assert context["semantic_domains"] == ["mechanics"]
    assert any(item.get("source") == "memory_writeback" for item in response.memory_evidence or [])
    assert all(item.get("evidence_id") == "ev_runtime_memory" for item in response.memory_evidence or [])


@pytest.mark.asyncio
async def test_agent_runtime_mod_detail_returns_detail_tool_response(monkeypatch):
    expected = _response("detail response")
    seen = {}

    async def fake_detail(self, tool_input):
        seen["session"] = self.session
        seen["tool_input"] = tool_input
        return expected

    monkeypatch.setattr(ModDetailAnswerTool, "run", fake_detail)
    request = object()
    body = AgentModDetailRequest(mod_id=42, question="risk?")
    runtime = AgentRuntime(session="session")

    response = await runtime.ask_mod_detail(body, request)

    assert response is expected
    assert seen["session"] == "session"
    assert seen["tool_input"].mod_id == body.mod_id
    assert seen["tool_input"].question == body.question
    assert seen["tool_input"].request is request
    _assert_succeeded_trace(runtime.last_trace, compat=True)


@pytest.mark.asyncio
async def test_agent_runtime_chat_detail_phrase_routes_to_mod_detail_by_title(monkeypatch):
    expected = _response("detail response")
    seen = {}

    async def fake_detail(self, tool_input):
        seen["tool_input"] = tool_input
        return expected

    monkeypatch.setattr(ModDetailAnswerTool, "run", fake_detail)
    with _session() as session:
        mod = Mod(
            source="loverslab",
            external_id="bimbolips-131",
            game="skyrimspecialedition",
            game_domain="skyrimspecialedition",
            title="Bimbos of Skyrim - BimboLips 1.3.1",
            url="https://example.com/bimbolips",
            original_summary="Adds BimboLips progression changes.",
            first_seen_at="2026-05-28T00:00:00+00:00",
            last_seen_at="2026-05-28T00:00:00+00:00",
        )
        session.add(mod)
        session.commit()
        session.refresh(mod)

        response = await AgentRuntime(session).chat(
            AgentChatRequest(message="请详细解析这个 Mod：Bimbos of Skyrim - BimboLips 1.3.1"),
            object(),
        )

    assert response is expected
    assert seen["tool_input"].mod_id == mod.id
    assert seen["tool_input"].question == "请详细解析这个 Mod：Bimbos of Skyrim - BimboLips 1.3.1"


@pytest.mark.asyncio
async def test_agent_graph_trace_records_minimum_steps(monkeypatch):
    with _session() as session:
        state = await run_agent_graph(
            session,
            {
                "request_kind": "chat",
                "chat_request": AgentChatRequest(message="recent mods"),
                "detail_request": None,
                "fastapi_request": object(),
                "response": None,
                "trace": [],
                "errors": [],
            },
        )

    assert state["response"].answer
    assert state["running_summary"] == "上下文摘要:\n本轮用户: recent mods"
    assert state["active_constraints"]["sort_field"] == "updated_at_remote"
    assert "query_diagnosis" in state
    assert "tool_plan" in state
    _assert_succeeded_trace(state["trace"])


@pytest.mark.asyncio
async def test_agent_graph_uses_long_term_writeback_when_short_context_is_weak(monkeypatch):
    with _session() as session:
        session.add(
            Mod(
                source="nexusmods",
                external_id="skyrim-context-seed",
                game="Skyrim Special Edition",
                game_domain="skyrimspecialedition",
                title="Context Seed",
                url="https://example.com/context-seed",
                first_seen_at="2026-05-25T00:00:00+00:00",
                last_seen_at="2026-05-25T00:00:00+00:00",
            )
        )
        session.commit()
        AgentPreferenceService(session).save_last_query_context(
            {
                "source": "chat_turn",
                "query": "有什么bimbo化的mod",
                "keywords": ["bimbo"],
                "semantic_anchors": ["bimbo", "roleplay"],
                "semantic_domains": ["mechanics"],
                "game": "Skyrim Special Edition",
                "quality_score": 0.82,
            }
        )
        state = await run_agent_graph(
            session,
            {
                "request_kind": "chat",
                "chat_request": AgentChatRequest(message="有什么相关风格的mod"),
                "detail_request": None,
                "fastapi_request": object(),
                "response": None,
                "trace": [],
                "errors": [],
            },
        )

    assert "bimbo" in (state["query_plan"].get("keywords") or [])
    assert state["query_plan"]["games"] == ["Skyrim Special Edition"]
    evidence = state["query_diagnosis"]["understanding"]["evidence"]
    assert any(
        item.get("field") == "context_source" and item.get("value") == "long_term_writeback"
        for item in evidence
    )
    assert any(
        item.get("field") == "context_semantic_anchors" and "bimbo" in (item.get("value") or [])
        for item in evidence
    )


@pytest.mark.asyncio
async def test_agent_graph_records_failed_detail_answer_trace(monkeypatch):
    async def fake_detail(self, tool_input):
        raise RuntimeError("boom")

    monkeypatch.setattr(ModDetailAnswerTool, "run", fake_detail)

    result = await generate_detail_answer_step(
        "session",
        {
            "request_kind": "mod_detail",
            "chat_request": None,
            "detail_request": AgentModDetailRequest(mod_id=1),
            "fastapi_request": object(),
            "response": None,
            "trace": [],
            "errors": [],
        },
    )

    assert "response" not in result
    assert result["errors"] == ["RuntimeError"]
    assert result["trace"][0]["step"] == "generate_detail_answer"
    assert result["trace"][0]["status"] == "failed"
    assert result["trace"][0]["error_type"] == "RuntimeError"
    assert "boom" not in str(result["trace"][0])


@pytest.mark.asyncio
async def test_trace_event_does_not_include_sensitive_request_data(monkeypatch):
    async def fake_run_agent_graph(session, state):
        return {
            "response": _response("safe"),
            "trace": [{"step": "load_state", "status": "succeeded", "duration_ms": 0, "evidence_id": "ev_safe"}],
        }

    monkeypatch.setattr(runtime_module, "run_agent_graph", fake_run_agent_graph)
    body = AgentChatRequest(
        message="private user query",
        provider_override="secret-provider",
        model_override="secret-model",
    )

    runtime = AgentRuntime(session="session")
    await runtime.chat(body, object())

    serialized_trace = str(runtime.last_trace)
    assert "private user query" not in serialized_trace
    assert "secret-provider" not in serialized_trace
    assert "secret-model" not in serialized_trace


@pytest.mark.asyncio
async def test_runtime_adds_memory_conflict_evidence_and_links_related_fragments(monkeypatch):
    async def fake_run_agent_graph(session, state):
        return {
            "response": AgentChatResponse(answer="ok", used_llm=False, matches=[], response_cards=None),
            "trace": [],
            "query_plan": {"evidence_id": "ev_test"},
            "query_diagnosis": {
                "intent": "search",
                "understanding": {
                    "intent": "search",
                    "slots": {"game": "Skyrim"},
                    "confidence": 0.8,
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
                    "merged": {
                        "memory_meta": {
                            "preference_stale": True,
                            "preferences_updated_at": "2025-01-01T00:00:00+00:00",
                            "preferences_age_days": 120,
                        }
                    },
                },
            "tool_plan": {
                "tool_policy_evidence": {
                    "score": 0.71,
                    "strategy": "local_first_with_online",
                    "known_slot_count": 1,
                    "should_clarify": False,
                    "local_tools": ["structured_sql", "sqlite_fts"],
                    "online_tools": ["nexusmods_search"],
                    "degraded_reasons": [],
                }
            },
        }

    monkeypatch.setattr(runtime_module, "run_agent_graph", fake_run_agent_graph)
    runtime = AgentRuntime(session="session")

    response = await runtime.chat(AgentChatRequest(message="test"), object())

    assert response.evidence_id == "ev_test"
    assert all(item.get("evidence_id") == "ev_test" for item in (response.memory_evidence or []))
    assert any(item.get("source") == "memory_conflict" for item in (response.memory_evidence or []))
    assert any(item.get("severity") == "hard_conflict" for item in (response.memory_evidence or []))
    assert any(item.get("field") == "preference_stale" and item.get("value") is True for item in (response.memory_evidence or []))
    assert any(item.get("field") == "preferences_age_days" for item in (response.memory_evidence or []))
    game_evidence = response.understanding["evidence"][0]
    assert any(fragment.startswith("m_conflict_") for fragment in game_evidence.get("related_fragments", []))
    assert response.audit["analysis"]["intent"] == "search"
    assert response.audit["conclusion"]["match_count"] == 0
    assert response.audit["conclusion"]["consistency_risk"] == "high"
    assert response.audit["conclusion"]["evidence_sufficiency"] in {"partial", "sufficient", "insufficient"}
    assert response.audit["conclusion"]["contract_status"] in {"ok", "violated"}
    assert response.audit["conclusion"]["contract_violations_count"] == len(
        response.audit["evidence"]["audit_contract_violations"]
    )
    if response.audit["conclusion"]["contract_status"] == "ok":
        assert response.audit["conclusion"]["contract_violations_count"] == 0
    else:
        assert response.audit["conclusion"]["contract_violations_count"] > 0
    assert response.audit["conclusion"]["recommended_action_reason"] == "high_consistency_risk_memory_conflict"
    assert response.audit["evidence"]["action_evidence_consistent"] is True
    assert response.audit["evidence"]["audit_contract_passed"] is True
    assert response.audit["evidence"]["audit_contract_violations"] == []
    assert response.audit["conclusion"]["requires_clarification"] is True
    assert response.audit["conclusion"]["recommended_action"] == "clarify_memory_conflict"
    assert response.audit["conclusion"]["action_payload"]["requires_user_confirmation"] is True
    assert "game" in response.audit["conclusion"]["action_payload"]["conflict_fields"]
    assert "上下文存在冲突" in (response.clarifying_question or "")
    assert response.audit["evidence"]["conflict_count"] >= 1
    assert "game" in response.audit["evidence"]["conflict_fields"]
    assert response.audit["evidence"]["hard_conflict_count"] >= 1
    assert response.audit["evidence"]["tool_policy"]["strategy"] == "local_first_with_online"
    assert response.audit["evidence"]["tool_policy"]["score"] == 0.71
    coverage = response.audit["evidence"]["analysis_evidence_coverage"]
    assert coverage["coverage_ratio"] <= 1.0
    assert "slots" in coverage["required_fields"]
    assert isinstance(coverage["field_fragments"]["slots"], list)


@pytest.mark.asyncio
async def test_runtime_sets_narrow_scope_action_when_tool_policy_confidence_is_low(monkeypatch):
    async def fake_run_agent_graph(session, state):
        return {
            "response": AgentChatResponse(
                answer="ok",
                used_llm=False,
                matches=[],
                response_cards={"next_steps": ["继续筛选"]},
            ),
            "trace": [],
            "query_plan": {"evidence_id": "ev_plan_low"},
            "query_diagnosis": {
                "intent": "search",
                "understanding": {
                    "intent": "search",
                    "slots": {},
                    "confidence": 0.4,
                    "followup": False,
                    "evidence": [{"fragment_id": "u_query_plan_intent", "field": "intent", "source": "query_plan", "value": "search"}],
                },
            },
            "memory_context": {"short_term": {}, "long_term": {}, "merged": {}},
            "tool_plan": {
                "tool_policy_evidence": {
                    "score": 0.33,
                    "strategy": "local_first_with_online",
                    "known_slot_count": 0,
                    "should_clarify": False,
                    "local_tools": ["structured_sql", "sqlite_fts"],
                    "online_tools": ["nexusmods_search"],
                    "degraded_reasons": [],
                }
            },
        }

    monkeypatch.setattr(runtime_module, "run_agent_graph", fake_run_agent_graph)
    runtime = AgentRuntime(session="session")
    response = await runtime.chat(AgentChatRequest(message="test"), object())

    assert response.audit["conclusion"]["consistency_risk"] == "low"
    assert response.audit["conclusion"]["tool_policy_confidence"] == "low"
    assert response.audit["conclusion"]["evidence_sufficiency"] in {"partial", "sufficient", "insufficient"}
    assert response.audit["evidence"]["action_evidence_consistent"] is True
    assert response.audit["conclusion"]["recommended_action"] == "narrow_query_scope"
    assert response.audit["conclusion"]["recommended_action_reason"] == "low_tool_policy_confidence"
    assert response.audit["conclusion"]["action_payload"]["narrow_scope_fields"] == ["game", "source", "keywords"]
    assert response.audit["conclusion"]["requires_clarification"] is False
    assert response.response_cards["next_steps"][0] == "我想补充游戏、来源和关键词后再查一次"


@pytest.mark.asyncio
async def test_runtime_sets_expand_sources_action_when_online_adaptation_signal_exists(monkeypatch):
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
            "query_plan": {"evidence_id": "ev_plan_low_adapt"},
            "query_diagnosis": {
                "intent": "search",
                "understanding": {
                    "intent": "search",
                    "slots": {},
                    "confidence": 0.35,
                    "followup": False,
                    "evidence": [{"fragment_id": "u_query_plan_intent", "field": "intent", "source": "query_plan", "value": "search"}],
                },
            },
            "memory_context": {"short_term": {}, "long_term": {}, "merged": {}},
            "tool_plan": {
                "tool_policy_evidence": {
                    "score": 0.32,
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
    runtime = AgentRuntime(session="session")
    response = await runtime.chat(AgentChatRequest(message="test"), object())

    assert response.audit["conclusion"]["tool_policy_confidence"] == "low"
    assert response.audit["conclusion"]["recommended_action"] == "expand_online_sources_and_narrow_scope"
    assert response.audit["conclusion"]["recommended_action_reason"] == "narrow_online_zero_result_expand_sources"
    assert response.audit["conclusion"]["expand_online_candidates"] == ["loverslab_google"]
    assert response.audit["conclusion"]["expand_online_candidates_detail"] == [
        {"id": "loverslab_google", "label": "LoversLab"}
    ]
    assert response.audit["conclusion"]["action_payload"]["expand_online_candidates"] == [
        {"id": "loverslab_google", "label": "LoversLab"}
    ]
    assert response.audit["conclusion"]["action_payload"]["narrow_scope_fields"] == ["game", "source", "keywords"]
    assert response.audit["evidence"]["web_search"]["enabled"] is True
    assert response.audit["evidence"]["web_search"]["adaptation_triggered"] is True
    assert response.audit["evidence"]["web_search"]["tools"] == []
    assert response.audit["evidence"]["web_search"]["tool_statuses"] == {"online_gate": "skipped"}
    assert response.audit["evidence"]["web_search"]["tool_result_counts"] == {"online_gate": 0}
    assert response.audit["evidence"]["web_search"]["queried"] is False
    assert "narrow_online_zero_result_expand_sources" in response.audit["evidence"]["web_search"]["trigger_reasons"]
    assert response.audit["evidence"]["retrieval_decision"]["mode"] == "web_adaptation_only"
    assert "narrow_online_zero_result_expand_sources" in response.audit["evidence"]["retrieval_decision"]["reasons"]
    assert "narrow_online_zero_result_expand_sources" in response.audit["evidence"]["retrieval_decision"]["reason_groups"]["web"]
    assert response.response_cards["next_steps"][0] == "继续查 LoversLab 来源，并放宽关键词再试"


@pytest.mark.asyncio
async def test_runtime_records_web_search_query_evidence_when_online_tools_run(monkeypatch):
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
            "query_plan": {"evidence_id": "ev_web_query"},
            "query_diagnosis": {
                "intent": "search",
                "understanding": {
                    "intent": "search",
                    "slots": {},
                    "confidence": 0.72,
                    "followup": False,
                    "evidence": [{"fragment_id": "u_query_plan_intent", "field": "intent", "source": "query_plan", "value": "search"}],
                },
            },
            "memory_context": {"short_term": {}, "long_term": {}, "merged": {}},
            "tool_plan": {"tool_policy_evidence": {"score": 0.76, "strategy": "local_first_with_online"}},
        }

    monkeypatch.setattr(runtime_module, "run_agent_graph", fake_run_agent_graph)
    runtime = AgentRuntime(session="session")
    response = await runtime.chat(AgentChatRequest(message="test"), object())

    web = response.audit["evidence"]["web_search"]
    assert web["enabled"] is True
    assert web["queried"] is True
    assert web["tools"] == ["nexusmods_search"]
    assert web["tool_statuses"] == {"nexusmods_search": "succeeded"}
    assert web["tool_result_counts"] == {"nexusmods_search": 2}
    assert int(web["online_result_count"]) == 2
    decision = response.audit["evidence"]["retrieval_decision"]
    assert decision["mode"] == "local_plus_web"
    assert decision["web_enabled"] is True
    assert decision["web_queried"] is True
    assert decision["reason_groups"]["web"] == []


@pytest.mark.asyncio
async def test_runtime_web_search_evidence_does_not_count_bool_as_result_count(monkeypatch):
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
                        "count": True,
                    }
                ],
            ),
            "trace": [],
            "query_plan": {"evidence_id": "ev_web_bool_count"},
            "query_diagnosis": {
                "intent": "search",
                "understanding": {
                    "intent": "search",
                    "slots": {},
                    "confidence": 0.72,
                    "followup": False,
                    "evidence": [{"fragment_id": "u_query_plan_intent", "field": "intent", "source": "query_plan", "value": "search"}],
                },
            },
            "memory_context": {"short_term": {}, "long_term": {}, "merged": {}},
            "tool_plan": {"tool_policy_evidence": {"score": 0.76, "strategy": "local_first_with_online"}},
        }

    monkeypatch.setattr(runtime_module, "run_agent_graph", fake_run_agent_graph)
    runtime = AgentRuntime(session="session")
    response = await runtime.chat(AgentChatRequest(message="test"), object())

    web = response.audit["evidence"]["web_search"]
    assert web["tool_result_counts"] == {"nexusmods_search": 0}
    assert web["online_result_count"] == 0


@pytest.mark.asyncio
async def test_runtime_web_search_evidence_keeps_per_tool_statuses(monkeypatch):
    async def fake_run_agent_graph(session, state):
        return {
            "response": AgentChatResponse(
                answer="ok",
                used_llm=False,
                matches=[],
                response_cards={"next_steps": ["继续筛选"]},
                retrieval_evidence=[
                    {
                        "fragment_id": "r_nexus",
                        "stage": "online_retrieval",
                        "tool": "nexusmods_search",
                        "status": "succeeded",
                        "count": 2,
                    },
                    {
                        "fragment_id": "r_google",
                        "stage": "online_retrieval",
                        "tool": "loverslab_google",
                        "status": "degraded",
                        "count": 0,
                        "reason": "timeout",
                    },
                    {
                        "fragment_id": "r_scrape",
                        "stage": "online_retrieval",
                        "tool": "loverslab_scrape",
                        "status": "skipped",
                        "count": 0,
                        "reason": "source_filter",
                    },
                ],
            ),
            "trace": [],
            "query_plan": {"evidence_id": "ev_web_statuses"},
            "query_diagnosis": {
                "intent": "search",
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
            "tool_plan": {"tool_policy_evidence": {"score": 0.76, "strategy": "local_first_with_online"}},
        }

    monkeypatch.setattr(runtime_module, "run_agent_graph", fake_run_agent_graph)
    runtime = AgentRuntime(session="session")
    response = await runtime.chat(AgentChatRequest(message="test"), object())

    web = response.audit["evidence"]["web_search"]
    assert web["tools"] == ["loverslab_google", "loverslab_scrape", "nexusmods_search"]
    assert web["tool_statuses"] == {
        "loverslab_google": "degraded",
        "loverslab_scrape": "skipped",
        "nexusmods_search": "succeeded",
    }
    assert web["tool_result_counts"] == {
        "loverslab_google": 0,
        "loverslab_scrape": 0,
        "nexusmods_search": 2,
    }
    assert web["trigger_reasons"] == ["source_filter", "timeout"]


@pytest.mark.asyncio
async def test_runtime_retrieval_decision_includes_semantic_anchor_evidence(monkeypatch):
    async def fake_run_agent_graph(session, state):
        return {
            "response": AgentChatResponse(
                answer="ok",
                used_llm=False,
                matches=[],
                response_cards={"next_steps": ["继续筛选"]},
            ),
            "trace": [],
            "query_plan": {"evidence_id": "ev_semantic"},
            "query_diagnosis": {
                "intent": "search",
                "understanding": {
                    "intent": "search",
                    "slots": {},
                    "confidence": 0.7,
                    "followup": False,
                    "evidence": [
                        {"fragment_id": "u_query_plan_intent", "field": "intent", "source": "query_plan", "value": "search"},
                        {"fragment_id": "u_analysis_semantic_anchors", "field": "semantic_anchors", "source": "analysis", "value": ["pregnancy", "gameplay"]},
                        {"fragment_id": "u_analysis_semantic_domains", "field": "semantic_domains", "source": "analysis", "value": ["mechanics", "content_type"]},
                    ],
                },
            },
            "memory_context": {"short_term": {}, "long_term": {}, "merged": {}},
            "tool_plan": {"tool_policy_evidence": {"score": 0.76, "strategy": "local_first_with_online"}},
        }

    monkeypatch.setattr(runtime_module, "run_agent_graph", fake_run_agent_graph)
    runtime = AgentRuntime(session="session")
    response = await runtime.chat(AgentChatRequest(message="test"), object())

    decision = response.audit["evidence"]["retrieval_decision"]
    analysis = response.audit["analysis"]
    coverage = response.audit["evidence"]["analysis_evidence_coverage"]
    semantic_trace = response.audit["evidence"]["semantic_trace"]
    assert analysis["semantic_anchors"] == ["pregnancy", "gameplay"]
    assert analysis["semantic_domains"] == ["mechanics", "content_type"]
    assert "semantic_anchors" in coverage["required_fields"]
    assert "semantic_domains" in coverage["required_fields"]
    assert coverage["field_fragments"]["semantic_anchors"]
    assert coverage["field_fragments"]["semantic_domains"]
    assert decision["semantic_anchors"] == ["pregnancy", "gameplay"]
    assert decision["semantic_domains"] == ["mechanics", "content_type"]
    assert "semantic_anchors_detected" in decision["reasons"]
    assert "semantic_anchors_detected" in decision["reason_groups"]["semantic"]
    assert "semantic_domain_mechanics" in decision["reason_groups"]["semantic"]
    assert "semantic_domain_content_type" in decision["reason_groups"]["semantic"]
    assert semantic_trace["anchors"] == ["pregnancy", "gameplay"]
    assert semantic_trace["context_anchors"] == []
    assert semantic_trace["domains"] == ["mechanics", "content_type"]
    assert semantic_trace["inherited_anchor_overlap"] == 0
    assert isinstance(semantic_trace["memory_fragment_count"], int)


@pytest.mark.asyncio
async def test_runtime_normalizes_semantic_memory_field_aliases(monkeypatch):
    async def fake_run_agent_graph(session, state):
        return {
            "response": AgentChatResponse(answer="ok", used_llm=False, matches=[], response_cards=None),
            "trace": [],
            "query_plan": {"evidence_id": "ev_semantic_memory_alias"},
            "query_diagnosis": {
                "intent": "search",
                "understanding": {
                    "intent": "search",
                    "slots": {},
                    "confidence": 0.8,
                    "followup": False,
                    "evidence": [{"fragment_id": "u_query_plan_intent", "field": "intent", "source": "query_plan", "value": "search"}],
                },
            },
            "memory_context": {
                "short_term": {
                    "last_query_context": {
                        "semantic_anchor": ["pregnancy"],
                        "semantic_domain": ["mechanics"],
                    }
                },
                "long_term": {},
                "merged": {},
            },
        }

    monkeypatch.setattr(runtime_module, "run_agent_graph", fake_run_agent_graph)
    runtime = AgentRuntime(session="session")
    response = await runtime.chat(AgentChatRequest(message="test"), object())

    fields = {item.get("field") for item in (response.memory_evidence or []) if isinstance(item, dict)}
    assert "semantic_anchors" in fields
    assert "semantic_domains" in fields


@pytest.mark.asyncio
async def test_runtime_links_semantic_understanding_to_memory_fragments(monkeypatch):
    async def fake_run_agent_graph(session, state):
        return {
            "response": AgentChatResponse(answer="ok", used_llm=False, matches=[], response_cards=None),
            "trace": [],
            "query_plan": {"evidence_id": "ev_semantic_link"},
            "query_diagnosis": {
                "intent": "search",
                "understanding": {
                    "intent": "search",
                    "slots": {},
                    "confidence": 0.8,
                    "followup": False,
                    "evidence": [
                        {"fragment_id": "u_query_plan_intent", "field": "intent", "source": "query_plan", "value": "search"},
                        {"fragment_id": "u_analysis_semantic_anchors", "field": "semantic_anchors", "source": "analysis", "value": ["bimbo"]},
                        {"fragment_id": "u_analysis_semantic_domains", "field": "semantic_domains", "source": "analysis", "value": ["mechanics"]},
                    ],
                },
            },
            "memory_context": {
                "short_term": {
                    "last_query_context": {
                        "semantic_anchors": ["bimbo"],
                        "semantic_domains": ["mechanics"],
                    }
                },
                "long_term": {},
                "merged": {},
            },
        }

    monkeypatch.setattr(runtime_module, "run_agent_graph", fake_run_agent_graph)
    runtime = AgentRuntime(session="session")
    response = await runtime.chat(AgentChatRequest(message="test"), object())

    evidence = response.understanding["evidence"]
    anchor_items = [item for item in evidence if item.get("field") == "semantic_anchors"]
    domain_items = [item for item in evidence if item.get("field") == "semantic_domains"]
    assert anchor_items and any(str(frag).startswith("m_short_last_query_semantic_anchors") for frag in anchor_items[0].get("related_fragments", []))
    assert domain_items and any(str(frag).startswith("m_short_last_query_semantic_domains") for frag in domain_items[0].get("related_fragments", []))


@pytest.mark.asyncio
async def test_runtime_sets_review_memory_action_payload_for_medium_risk(monkeypatch):
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
    runtime = AgentRuntime(session="session")
    response = await runtime.chat(AgentChatRequest(message="test"), object())

    assert response.audit["conclusion"]["consistency_risk"] == "medium"
    assert response.audit["conclusion"]["recommended_action"] == "review_memory_signals"
    assert response.audit["conclusion"]["recommended_action_reason"] == "memory_signal_conflicts_detected"
    assert response.audit["conclusion"]["action_payload"]["review_targets"] == ["memory_signals", "context_slots"]


@pytest.mark.asyncio
async def test_runtime_upgrades_to_medium_risk_for_low_quality_inherited_context(monkeypatch):
    async def fake_run_agent_graph(session, state):
        return {
            "response": AgentChatResponse(
                answer="ok",
                used_llm=False,
                matches=[],
                response_cards={"next_steps": ["继续筛选"]},
            ),
            "trace": [],
            "query_plan": {"evidence_id": "ev_ctx_quality"},
            "query_diagnosis": {
                "intent": "search",
                "understanding": {
                    "intent": "search",
                    "slots": {},
                    "confidence": 0.62,
                    "followup": True,
                    "evidence": [
                        {
                            "fragment_id": "u_short_term_memory_context_source",
                            "field": "context_source",
                            "source": "short_term_memory",
                            "value": "recent_user",
                        },
                        {
                            "fragment_id": "u_short_term_memory_context_quality_score",
                            "field": "context_quality_score",
                            "source": "short_term_memory",
                            "value": 0.18,
                        },
                        {
                            "fragment_id": "u_short_term_memory_context_inherit_score",
                            "field": "context_inherit_score",
                            "source": "short_term_memory",
                            "value": 0.72,
                        },
                        {
                            "fragment_id": "u_diagnosis_context_inherited",
                            "field": "context_inherited",
                            "source": "diagnosis",
                            "value": True,
                        },
                        {
                            "fragment_id": "u_diagnosis_topic_shift_detected",
                            "field": "topic_shift_detected",
                            "source": "diagnosis",
                            "value": False,
                        },
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
    runtime = AgentRuntime(session="session")
    response = await runtime.chat(AgentChatRequest(message="test"), object())

    assert response.audit["conclusion"]["consistency_risk"] == "medium"
    assert response.audit["conclusion"]["recommended_action"] == "review_memory_signals"
    assert response.audit["conclusion"]["recommended_action_reason"] == "memory_signal_conflicts_detected"
    assert response.audit["evidence"]["context_signal"]["source"] == "recent_user"
    assert float(response.audit["evidence"]["context_signal"]["quality_score"]) == 0.18
    assert float(response.audit["evidence"]["context_signal"]["inherit_score"]) == 0.72
    assert response.audit["evidence"]["context_signal"]["inherited"] is True
    assert response.audit["evidence"]["context_signal"]["policy_reasons"] == []
    assert response.audit["evidence"]["memory_context_alignment"]["decision"] == "review_memory_and_context"
    assert float(response.audit["evidence"]["memory_context_alignment"]["score"]) <= 0.55


@pytest.mark.asyncio
async def test_runtime_uses_review_memory_action_for_high_risk_without_explicit_conflicts(monkeypatch):
    async def fake_run_agent_graph(session, state):
        return {
            "response": AgentChatResponse(
                answer="ok",
                used_llm=False,
                matches=[],
                response_cards={"next_steps": ["继续筛选"]},
            ),
            "trace": [],
            "query_plan": {"evidence_id": "ev_alignment_high"},
            "query_diagnosis": {
                "intent": "search",
                "understanding": {
                    "intent": "search",
                    "slots": {},
                    "confidence": 0.58,
                    "followup": True,
                    "evidence": [
                        {
                            "fragment_id": "u_short_term_memory_context_source",
                            "field": "context_source",
                            "source": "short_term_memory",
                            "value": "recent_user",
                        },
                        {
                            "fragment_id": "u_short_term_memory_context_quality_score",
                            "field": "context_quality_score",
                            "source": "short_term_memory",
                            "value": 0.05,
                        },
                        {
                            "fragment_id": "u_short_term_memory_context_inherit_score",
                            "field": "context_inherit_score",
                            "source": "short_term_memory",
                            "value": 0.91,
                        },
                        {
                            "fragment_id": "u_diagnosis_context_inherited",
                            "field": "context_inherited",
                            "source": "diagnosis",
                            "value": True,
                        },
                        {
                            "fragment_id": "u_diagnosis_topic_shift_detected",
                            "field": "topic_shift_detected",
                            "source": "diagnosis",
                            "value": True,
                        },
                    ],
                },
            },
            "memory_context": {"short_term": {}, "long_term": {}, "merged": {}},
            "tool_plan": {
                "tool_policy_evidence": {
                    "score": 0.74,
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
    runtime = AgentRuntime(session="session")
    response = await runtime.chat(AgentChatRequest(message="test"), object())

    assert response.audit["conclusion"]["consistency_risk"] == "high"
    assert response.audit["conclusion"]["recommended_action"] == "review_memory_signals"
    assert response.audit["conclusion"]["recommended_action_reason"] == "memory_signal_conflicts_detected"
    assert response.audit["conclusion"]["requires_clarification"] is False
    assert response.audit["conclusion"]["action_payload"]["review_targets"] == [
        "memory_signals",
        "context_slots",
        "alignment_score",
    ]
    assert response.clarifying_question in (None, "")


@pytest.mark.asyncio
async def test_runtime_collects_more_evidence_when_analysis_coverage_is_low(monkeypatch):
    async def fake_run_agent_graph(session, state):
        return {
            "response": AgentChatResponse(
                answer="ok",
                used_llm=False,
                matches=[],
                response_cards={"next_steps": ["继续筛选"]},
            ),
            "trace": [],
            "query_plan": {"evidence_id": "ev_low_coverage"},
            "query_diagnosis": {
                "intent": "search",
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
                    "score": 0.8,
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
    runtime = AgentRuntime(session="session")
    response = await runtime.chat(AgentChatRequest(message="test"), object())

    coverage = response.audit["evidence"]["analysis_evidence_coverage"]
    assert float(coverage["coverage_ratio"]) < 0.67
    assert "intent" in coverage["missing_fields"]
    assert "confidence" in coverage["missing_fields"]
    assert response.audit["conclusion"]["evidence_sufficiency"] == "insufficient"
    assert response.audit["conclusion"]["contract_status"] == "ok"
    assert response.audit["conclusion"]["contract_violations_count"] == 0
    assert response.audit["conclusion"]["recommended_action"] == "collect_more_evidence"
    assert response.audit["conclusion"]["recommended_action_reason"] == "insufficient_analysis_evidence"
    assert response.audit["evidence"]["action_evidence_consistent"] is True
    assert response.audit["evidence"]["audit_contract_passed"] is True
    assert response.audit["evidence"]["audit_contract_violations"] == []
    assert "analysis_evidence" in response.audit["conclusion"]["action_payload"]["review_targets"]
    assert response.response_cards["next_steps"][0] == "我想补充目标游戏和关键词后再查一次"


def test_audit_contract_violations_flags_collect_more_evidence_mismatch():
    violations = audit_contract_violations(
        conclusion={
            "recommended_action": "collect_more_evidence",
            "evidence_sufficiency": "sufficient",
            "consistency_risk": "low",
        },
        evidence={"analysis_evidence_coverage": {"coverage_ratio": 1.0}},
    )

    assert "collect_more_evidence_requires_insufficient_evidence" in violations


def test_audit_contract_violations_flags_collect_more_evidence_reason_mismatch():
    violations = audit_contract_violations(
        conclusion={
            "recommended_action": "collect_more_evidence",
            "recommended_action_reason": "wrong_reason",
            "evidence_sufficiency": "insufficient",
            "consistency_risk": "low",
        },
        evidence={"analysis_evidence_coverage": {"coverage_ratio": 0.4}},
    )

    assert "recommended_action_reason_mismatch:collect_more_evidence" in violations


def test_audit_contract_violations_flags_clarify_memory_conflict_reason_mismatch():
    violations = audit_contract_violations(
        conclusion={
            "recommended_action": "clarify_memory_conflict",
            "recommended_action_reason": "wrong_reason",
            "evidence_sufficiency": "sufficient",
            "consistency_risk": "high",
        },
        evidence={"analysis_evidence_coverage": {"coverage_ratio": 0.9}},
    )

    assert "recommended_action_reason_mismatch:clarify_memory_conflict" in violations


def test_audit_contract_violations_flags_missing_reason_when_action_exists():
    violations = audit_contract_violations(
        conclusion={
            "recommended_action": "narrow_query_scope",
            "recommended_action_reason": "",
            "evidence_sufficiency": "partial",
            "consistency_risk": "low",
        },
        evidence={"analysis_evidence_coverage": {"coverage_ratio": 0.9}},
    )

    assert "recommended_action_requires_non_empty_reason" in violations


def test_recommended_action_reason_mapping_is_complete_for_known_actions():
    known_actions = {
        "collect_more_evidence",
        "review_memory_signals",
        "clarify_memory_conflict",
        "expand_online_sources_and_narrow_scope",
        "narrow_query_scope_and_review_memory",
        "narrow_query_scope",
    }
    for action in known_actions:
        reason = expected_reason_for_action(action)
        assert isinstance(reason, str) and reason


def test_annotate_action_evidence_consistency_sets_violation_count():
    response = AgentChatResponse(
        answer="ok",
        used_llm=False,
        matches=[],
        response_cards=None,
        audit={
            "analysis": {"intent": "search", "confidence": 0.8, "slots": {}, "evidence_id": "ev_1"},
            "evidence": {"analysis_evidence_coverage": {"coverage_ratio": 1.0}},
            "conclusion": {
                "recommended_action": "collect_more_evidence",
                "recommended_action_reason": "wrong_reason",
                "evidence_sufficiency": "sufficient",
                "consistency_risk": "low",
            },
        },
    )

    annotate_action_evidence_consistency(response)

    violations = response.audit["evidence"]["audit_contract_violations"]
    assert response.audit["conclusion"]["contract_status"] == "violated"
    assert response.audit["conclusion"]["contract_violations_count"] == len(violations)
    assert response.audit["conclusion"]["contract_violations_count"] > 0
    assert isinstance(response.audit, AgentAudit)


def test_consistency_guard_handles_agent_audit_model_without_dropping_evidence():
    response = AgentChatResponse(
        answer="ok",
        used_llm=False,
        matches=[],
        response_cards={"next_steps": ["继续筛选"]},
        audit=AgentAudit.model_validate(
            {
                "analysis": {"intent": "search", "confidence": 0.8, "slots": {}, "evidence_id": "ev_model"},
                "evidence": {
                    "conflict_count": 0,
                    "analysis_evidence_coverage": {"coverage_ratio": 0.5, "missing_fields": ["slots"]},
                    "tool_policy": {"score": 0.8, "strategy": "local_first_with_online"},
                },
                "conclusion": {
                    "consistency_risk": "low",
                    "evidence_sufficiency": "insufficient",
                    "tool_policy_confidence": "high",
                },
            }
        ),
    )

    apply_consistency_guard(response)

    assert isinstance(response.audit, AgentAudit)
    annotate_action_evidence_consistency(response)

    assert isinstance(response.audit, AgentAudit)
    assert response.audit["analysis"]["evidence_id"] == "ev_model"
    assert response.audit["evidence"]["analysis_evidence_coverage"]["coverage_ratio"] == 0.5
    assert response.audit["conclusion"]["recommended_action"] == "collect_more_evidence"
    assert response.audit["conclusion"]["recommended_action_reason"] == "insufficient_analysis_evidence"
    assert response.audit["evidence"]["audit_contract_passed"] is True
    assert response.response_cards["next_steps"][0] == "我想补充目标游戏和关键词后再查一次"


def test_consistency_guard_tolerates_invalid_count_evidence():
    response = AgentChatResponse(
        answer="ok",
        used_llm=False,
        matches=[],
        response_cards={"next_steps": []},
    )
    response.audit = {
        "analysis": {"intent": "search", "confidence": 0.8, "slots": {}, "evidence_id": "ev_bad_counts"},
        "evidence": {
            "conflict_count": "bad",
            "analysis_evidence_coverage": {"coverage_ratio": 0.5, "missing_fields": ["slots"]},
            "tool_policy": {"score": 0.8, "strategy": "local_first_with_online"},
        },
        "conclusion": {
            "consistency_risk": "low",
            "evidence_sufficiency": "insufficient",
            "tool_policy_confidence": "high",
        },
    }

    apply_consistency_guard(response)

    assert response.audit["conclusion"]["recommended_action"] == "collect_more_evidence"


def test_audit_contract_violations_flags_missing_semantic_trace_when_semantic_anchors_exist():
    violations = audit_contract_violations(
        conclusion={
            "recommended_action": "narrow_query_scope",
            "recommended_action_reason": "low_tool_policy_confidence",
            "evidence_sufficiency": "partial",
            "consistency_risk": "low",
        },
        evidence={
            "analysis_evidence_coverage": {"coverage_ratio": 1.0},
            "retrieval_decision": {"semantic_anchors": ["bimbo"]},
        },
    )

    assert "semantic_trace_missing_for_semantic_query" in violations


def test_audit_contract_violations_rejects_bool_semantic_trace_counts():
    violations = audit_contract_violations(
        conclusion={
            "recommended_action": "narrow_query_scope",
            "recommended_action_reason": "low_tool_policy_confidence",
            "evidence_sufficiency": "partial",
            "consistency_risk": "low",
        },
        evidence={
            "analysis_evidence_coverage": {"coverage_ratio": 1.0},
            "retrieval_decision": {"semantic_anchors": ["bimbo"]},
            "semantic_trace": {
                "anchors": ["bimbo"],
                "domains": ["content_type"],
                "memory_fragment_count": True,
            },
        },
    )

    assert "semantic_trace_memory_fragment_count_invalid" in violations


def test_classify_retrieval_reason_group_routes_context_memory_and_web():
    assert classify_retrieval_reason_group("memory_context_alignment_low") == "memory"
    assert classify_retrieval_reason_group("low_quality_context_with_high_inherit") == "context"
    assert classify_retrieval_reason_group("narrow_online_zero_result_expand_sources") == "web"
    assert classify_retrieval_reason_group("semantic_anchors_detected") == "semantic"
