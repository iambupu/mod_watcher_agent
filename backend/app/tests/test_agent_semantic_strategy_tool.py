import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.models.mod import Mod
from app.services.agent.planning.open_discovery_policy import build_open_discovery_retrieval_plan
from app.services.agent.reflection.audit_service import build_standard_audit
from app.services.agent.schemas import AgentChatResponse, AgentHistoryItem
from app.services.agent.semantic_brain import semantic_strategy_tool as strategy_tool_module
from app.services.agent.semantic_brain.semantic_strategy_adapter import (
    attach_semantic_strategy_to_query_plan,
)
from app.services.agent.semantic_brain.semantic_strategy_schema import SemanticStrategy
from app.services.agent.semantic_brain.semantic_strategy_tool import (
    SemanticStrategyInput,
    SemanticStrategyTool,
)
from app.services.agent.tools.task_understanding_tool import (
    TaskUnderstandingInput,
    TaskUnderstandingTool,
)


@pytest.fixture(name="session")
def session_fixture():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _mod(**kwargs) -> Mod:
    defaults = {
        "source": "nexusmods",
        "external_id": "1",
        "game": "Skyrim Special Edition",
        "game_domain": "skyrimspecialedition",
        "title": "Bimbo Roleplay",
        "url": "https://example.com",
        "first_seen_at": "2025-01-01T00:00:00",
        "last_seen_at": "2025-01-01T00:00:00",
        "adult_content": True,
    }
    defaults.update(kwargs)
    return Mod(**defaults)


def test_semantic_strategy_schema_normalizes_terms_and_filters():
    strategy = SemanticStrategy.model_validate(
        {
            "task_type": "open_discovery",
            "user_goal": " 找 Skyrim bimbo 玩法 ",
            "strategy": "broad_then_judge",
            "hard_filters": {
                "game": " skyrimspecialedition ",
                "source": "",
                "excluded_keywords": ["SKSE", "skse", ""],
            },
            "core_terms": ["bimbo", "bimbo", "roleplay"],
            "soft_signals": ["Bimbos of Skyrim", "", "Bimbos of Skyrim"],
            "ranking_goal": "按玩法相关性排序",
            "answer_shape": "grouped_recommendation",
            "confidence": 2,
        }
    )

    assert strategy.user_goal == "找 Skyrim bimbo 玩法"
    assert strategy.hard_filters.game == "skyrimspecialedition"
    assert strategy.hard_filters.source is None
    assert strategy.hard_filters.excluded_keywords == ["SKSE"]
    assert strategy.core_terms == ["bimbo", "roleplay"]
    assert strategy.soft_signals == ["Bimbos of Skyrim"]
    assert strategy.confidence == 1.0


def test_semantic_strategy_schema_normalizes_source_aliases():
    strategy = SemanticStrategy.model_validate(
        {
            "hard_filters": {
                "source": "Nexus Mods",
                "excluded_sources": ["LL", "lovers lab"],
            },
        }
    )

    assert strategy.hard_filters.source == "nexusmods"
    assert strategy.hard_filters.excluded_sources == ["loverslab"]


@pytest.mark.asyncio
async def test_semantic_strategy_tool_uses_llm_and_repairs_invalid_json(monkeypatch):
    calls = []

    class FakeClient:
        async def chat(self, prompt, model, max_tokens=1024, request_timeout=None):  # noqa: ARG002
            calls.append(prompt)
            if len(calls) == 1:
                return "不是 JSON"
            assert "上一次输出不是合法 JSON 对象" in prompt
            return """
            {
              "task_type": "open_discovery",
              "user_goal": "找到 Skyrim 中适合 bimbo roleplay 的 MOD",
              "strategy": "broad_then_judge",
              "hard_filters": {"game": "skyrimspecialedition"},
              "core_terms": ["bimbo", "roleplay"],
              "soft_signals": ["Bimbos of Skyrim", "bimbofication"],
              "ranking_goal": "优先玩法与角色扮演相关候选",
              "answer_shape": "grouped_recommendation",
              "confidence": 0.91,
              "reason": "开放发现问题"
            }
            """

    monkeypatch.setattr(strategy_tool_module, "create_llm_client", lambda **kwargs: FakeClient())  # noqa: ARG005

    result = await SemanticStrategyTool().run(
        SemanticStrategyInput(
            query="天际有什么扮演bimbo的MOD",
            llm_available=True,
            provider="test",
            api_key="key",
            model="model",
            evidence_id="ev_semantic",
        )
    )

    assert len(calls) == 2
    assert result.used_llm is True
    assert result.source == "llm"
    assert result.strategy.task_type == "open_discovery"
    assert result.strategy.strategy == "broad_then_judge"
    assert result.strategy.hard_filters.game == "skyrimspecialedition"
    assert result.evidence[0]["field"] == "semantic_strategy"
    assert result.evidence[0]["evidence_id"] == "ev_semantic"


@pytest.mark.asyncio
async def test_semantic_strategy_fallback_keeps_memory_as_soft_hint():
    result = await SemanticStrategyTool().run(
        SemanticStrategyInput(
            query="天际有什么扮演bimbo的MOD",
            active_constraints={"game": "skyrimspecialedition"},
            last_query_context={
                "game": "Stellar Blade",
                "keywords": ["outfit"],
                "semantic_anchors": ["roleplay"],
            },
            memory_context={
                "long_term": {
                    "last_query_context": {
                        "game": "Stellar Blade",
                        "keywords": ["outfit"],
                    }
                }
            },
            llm_available=False,
            evidence_id="ev_fallback",
        )
    )

    assert result.source == "fallback"
    assert result.strategy.task_type == "open_discovery"
    assert result.strategy.hard_filters.game == "skyrimspecialedition"
    assert "roleplay" in result.strategy.soft_signals
    assert result.strategy.hard_filters.game != "Stellar Blade"


def test_semantic_strategy_adapter_applies_primary_executor_query_plan():
    strategy = SemanticStrategy(
        task_type="open_discovery",
        user_goal="找 bimbo MOD",
        strategy="broad_then_judge",
        core_terms=["bimbo"],
        answer_shape="grouped_recommendation",
    )
    result = strategy_tool_module.SemanticStrategyResult(strategy=strategy, source="fallback", status="fallback")

    plan = attach_semantic_strategy_to_query_plan({"keywords": ["bimbo"], "limit": 8}, result)

    assert plan["keywords"] == ["bimbo"]
    assert plan["limit"] == 8
    assert plan["_agent_query_plan_role"] == "executor_query"
    assert plan["_agent_semantic_strategy_primary"] is True
    assert plan["_agent_semantic_strategy"]["task_type"] == "open_discovery"
    assert plan["_agent_semantic_strategy_source"] == "fallback"


def test_semantic_strategy_adapter_softens_open_discovery_slots():
    strategy = SemanticStrategy(
        task_type="open_discovery",
        user_goal="找 bimbo roleplay",
        strategy="broad_then_judge",
        core_terms=["bimbo", "roleplay"],
        soft_signals=["curse"],
        answer_shape="grouped_recommendation",
    )
    result = strategy_tool_module.SemanticStrategyResult(
        strategy=strategy,
        source="llm",
        status="succeeded",
        used_llm=True,
    )

    plan = attach_semantic_strategy_to_query_plan(
        {
            "categories": ["Gameplay"],
            "tags": ["3BA"],
            "requirement_terms": ["SKSE"],
            "compatibility_terms": ["AE"],
        },
        result,
    )

    assert plan["categories"] == []
    assert plan["tags"] == []
    assert plan["requirement_terms"] == []
    assert plan["compatibility_terms"] == []
    assert plan["category_hints"] == ["Gameplay", "3BA", "SKSE", "AE", "curse"]


def test_semantic_strategy_adapter_llm_open_discovery_updates_executor_mode():
    strategy = SemanticStrategy(
        task_type="open_discovery",
        user_goal="找 bimbo MOD",
        strategy="broad_then_judge",
        core_terms=["bimbo"],
        answer_shape="grouped_recommendation",
    )
    result = strategy_tool_module.SemanticStrategyResult(
        strategy=strategy,
        source="llm",
        status="succeeded",
        used_llm=True,
    )

    plan = attach_semantic_strategy_to_query_plan({"keywords": ["old"], "limit": 8}, result)

    assert plan["keywords"] == ["bimbo"]
    assert plan["limit"] == 12
    assert plan["candidate_pool_limit"] == 60
    assert plan["open_discovery"] is True
    assert plan["retrieval_mode"] == "fuzzy"


def test_open_discovery_retrieval_uses_normalized_plan_source_for_semantic_filter():
    plan = build_open_discovery_retrieval_plan(
        {
            "keywords": ["bimbo"],
            "open_discovery": True,
            "retrieval_mode": "fuzzy",
            "sources": ["nexusmods"],
            "_agent_semantic_strategy": {
                "task_type": "open_discovery",
                "hard_filters": {"source": "Nexus Mods"},
            },
        },
        "有什么 bimbo MOD",
    )

    assert plan["sources"] == ["nexusmods"]


def test_semantic_strategy_adapter_preserves_alternative_intent_for_comparative_task():
    strategy = SemanticStrategy(
        task_type="comparative",
        user_goal="找一个替代",
        strategy="compare_known_and_fetch_missing",
        core_terms=["bimbo"],
        answer_shape="comparison_table",
    )
    result = strategy_tool_module.SemanticStrategyResult(
        strategy=strategy,
        source="fallback",
        status="fallback",
    )

    plan = attach_semantic_strategy_to_query_plan({"intent": "alternative", "keywords": ["bimbo"]}, result)

    assert plan["intent"] == "alternative"


@pytest.mark.asyncio
async def test_task_understanding_exposes_semantic_strategy_in_diagnosis():
    output = await TaskUnderstandingTool(session=None).run(
        TaskUnderstandingInput(
            query="有什么bimbo玩法mod",
            active_constraints={"game": "skyrimspecialedition"},
            history=[AgentHistoryItem(role="user", text="之前找过 Skyrim 的玩法 Mod")],
            evidence_id="ev_task",
        )
    )

    strategy = output.query_plan["_agent_semantic_strategy"]
    evidence = output.query_diagnosis["understanding"]["evidence"]

    assert strategy["task_type"] == "open_discovery"
    assert strategy["hard_filters"]["game"] == "skyrimspecialedition"
    assert any(item["field"] == "semantic_strategy" for item in evidence)
    assert output.semantic_strategy["task_type"] == "open_discovery"


@pytest.mark.asyncio
async def test_task_understanding_normalizes_semantic_strategy_hard_filter_aliases(monkeypatch, session):
    session.add(_mod())
    session.commit()

    async def fake_strategy_run(self, tool_input):  # noqa: ARG001
        strategy = SemanticStrategy(
            task_type="open_discovery",
            user_goal="找 Skyrim SE 的 bimbo MOD",
            strategy="broad_then_judge",
            hard_filters={"game": "Skyrim SE"},
            core_terms=["bimbo"],
            answer_shape="grouped_recommendation",
        )
        return strategy_tool_module.SemanticStrategyResult(
            strategy=strategy,
            source="llm",
            status="succeeded",
            used_llm=True,
        )

    monkeypatch.setattr(SemanticStrategyTool, "run", fake_strategy_run)

    output = await TaskUnderstandingTool(session=session).run(
        TaskUnderstandingInput(
            query="找 Skyrim SE 的 bimbo MOD",
            evidence_id="ev_task_alias",
        )
    )

    assert output.query_plan["games"] == ["Skyrim Special Edition"]
    assert output.query_plan["_agent_semantic_strategy"]["hard_filters"]["game"] == "Skyrim SE"


def test_standard_audit_exposes_semantic_strategy_observation():
    strategy = {
        "task_type": "open_discovery",
        "user_goal": "找 bimbo MOD",
        "strategy": "broad_then_judge",
        "hard_filters": {"game": "skyrimspecialedition"},
        "core_terms": ["bimbo"],
        "soft_signals": ["roleplay"],
        "ranking_goal": "按角色扮演相关性排序",
        "answer_shape": "grouped_recommendation",
        "confidence": 0.8,
        "reason": "开放发现",
    }
    response = AgentChatResponse(
        answer="ok",
        used_llm=False,
        matches=[],
        understanding={
            "intent": "search",
            "confidence": 0.8,
            "slots": {},
            "evidence": [
                {
                    "fragment_id": "u_semantic_strategy",
                    "field": "semantic_strategy",
                    "source": "fallback",
                    "value": strategy,
                }
            ],
        },
        evidence_id="ev_audit",
    )

    audit = build_standard_audit(response)

    assert audit.analysis.model_dump(mode="python")["semantic_strategy"]["task_type"] == "open_discovery"
    assert audit.evidence.model_dump(mode="python")["semantic_strategy"]["strategy"] == "broad_then_judge"
