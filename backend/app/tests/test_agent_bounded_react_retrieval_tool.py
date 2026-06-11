import pytest

from app.models.mod import Mod
from app.services.agent.search_types import SearchResult
from app.services.agent.tools import bounded_react_retrieval_tool as react_tool
from app.services.agent.tools.bounded_react_retrieval_tool import (
    BoundedReactRetrievalInput,
    BoundedReactRetrievalTool,
    ReactRetrievalAction,
    assess_retrieval_quality,
    guard_react_action,
)
from app.services.agent.tools.web_search_tool import WebSearchOutput


def _mod(
    *,
    title: str,
    source: str = "nexusmods",
    external_id: str = "mod-1",
    game: str = "Skyrim",
    game_domain: str = "skyrimspecialedition",
    url: str = "https://example.test/mod-1",
    summary: str | None = "A useful mod.",
    adult_content: bool | None = None,
) -> Mod:
    return Mod(
        source=source,
        external_id=external_id,
        game=game,
        game_domain=game_domain,
        title=title,
        url=url,
        original_summary=summary,
        adult_content=adult_content,
        first_seen_at="2026-01-01T00:00:00Z",
        last_seen_at="2026-01-01T00:00:00Z",
    )


def _result(mod: Mod, *, score: int = 90, tool_name: str = "local_db_search") -> SearchResult:
    return SearchResult(score=score, mod=mod, tool_name=tool_name)


@pytest.mark.asyncio
async def test_bounded_react_does_not_trigger_on_single_exact_match():
    tool = BoundedReactRetrievalTool("session")
    staged = [
        _result(
            _mod(
                title="Known Pregnancy Framework",
                source="nexusmods",
                external_id="skyrimspecialedition:123",
                game="Skyrim",
                url="https://www.nexusmods.com/skyrimspecialedition/mods/123",
            )
        )
    ]

    output = await tool.run(
        BoundedReactRetrievalInput(
            query="Known Pregnancy Framework",
            query_plan={
                "exact_title": "Known Pregnancy Framework",
                "sources": ["nexusmods"],
                "games": ["Skyrim"],
            },
            tool_plan={"parallel_groups": [{"name": "online", "tools": ["web_search"]}]},
            staged_results=staged,
            evidence_id="ev_react",
        )
    )

    assert output.react_summary["triggered"] is False
    assert output.react_summary["quality_triggered"] is False
    assert output.react_trace[0]["weak_signals"] == ["low_result_count"]
    assert output.react_trace[0]["action"] == "stop"
    assert output.staged_results == staged


@pytest.mark.asyncio
async def test_bounded_react_expands_online_for_complex_insufficient_evidence(monkeypatch):
    seen = {}

    async def fake_web_run(self, *, query, query_plan, evidence_id="", online_recall_mode="broad", allowed_tools=None):
        seen["query"] = query
        seen["query_plan"] = query_plan
        seen["allowed_tools"] = allowed_tools
        seen["online_recall_mode"] = online_recall_mode
        return WebSearchOutput(
            results=[
                _result(
                    _mod(
                        title="Pregnancy Framework Patch",
                        source="loverslab",
                        external_id="ll:1",
                        game="Skyrim",
                        url="https://www.loverslab.com/files/file/1",
                        summary="SexLab framework compatibility patch.",
                    ),
                    tool_name="loverslab_google",
                )
            ],
            evidence=[
                {
                    "fragment_id": "r_web_1",
                    "stage": "online_retrieval",
                    "tool": "loverslab_google",
                    "status": "succeeded",
                    "count": 1,
                }
            ],
        )

    monkeypatch.setattr(react_tool.WebSearchTool, "run", fake_web_run)

    output = await BoundedReactRetrievalTool("session").run(
        BoundedReactRetrievalInput(
            query="有没有兼容 sexlab 的 pregnancy framework",
            query_plan={
                "keywords": ["pregnancy"],
                "sources": ["loverslab"],
                "games": ["Skyrim"],
                "requirement_terms": ["framework"],
                "compatibility_terms": ["sexlab"],
                "_agent_semantic_strategy": {
                    "task_type": "compatibility",
                    "hard_filters": {"sources": ["loverslab"], "games": ["Skyrim"]},
                },
            },
            tool_plan={
                "parallel_groups": [{"name": "online", "tools": ["loverslab_google"]}],
                "tool_policy_evidence": {"online_recall_mode": "narrow"},
            },
            staged_results=[
                _result(
                    _mod(
                        title="Pregnancy Old Entry",
                        source="loverslab",
                        external_id="ll:old",
                        game="Skyrim",
                        summary=None,
                    )
                )
            ],
            retrieval_evidence=[
                {
                    "fragment_id": "r_web_1",
                    "stage": "online_retrieval",
                    "tool": "online_gate",
                    "status": "skipped",
                    "reason": "local_matches_sufficient",
                    "count": 0,
                }
            ],
            evidence_id="ev_online",
        )
    )

    assert output.react_summary["triggered"] is True
    assert "expand_online_search" in output.react_summary["executed_actions"]
    assert output.online_results[0].mod.title == "Pregnancy Framework Patch"
    assert seen["query_plan"]["sources"] == ["loverslab"]
    assert seen["query_plan"]["games"] == ["Skyrim"]
    assert seen["allowed_tools"] == {"loverslab_google", "loverslab_scrape"}
    assert any(item.get("stage") == "bounded_react_retrieval" for item in output.retrieval_evidence)
    fragment_ids = [str(item.get("fragment_id") or "") for item in output.retrieval_evidence if item.get("fragment_id")]
    assert "r_react_web_1" in fragment_ids
    assert len(fragment_ids) == len(set(fragment_ids))


@pytest.mark.asyncio
async def test_bounded_react_refines_local_when_online_not_allowed(monkeypatch):
    seen = {}

    async def fake_local_run(self, tool_input):
        seen["query"] = tool_input.query
        seen["plan"] = tool_input.plan.to_query_plan()
        return [
            _result(
                _mod(
                    title="Local Compatibility Result",
                    source="nexusmods",
                    external_id="local-1",
                    summary="Framework requirement and compatibility notes.",
                )
            )
        ]

    monkeypatch.setattr(react_tool.LocalDbSearchTool, "run", fake_local_run)

    output = await BoundedReactRetrievalTool("session").run(
        BoundedReactRetrievalInput(
            query="pregnancy framework 兼容",
            query_plan={
                "keywords": ["pregnancy"],
                "requirement_terms": ["framework"],
                "compatibility_terms": ["compatibility"],
            },
            tool_plan={"parallel_groups": [{"name": "local", "tools": ["local_db_search"]}]},
            staged_results=[],
            evidence_id="ev_local",
        )
    )

    assert output.react_summary["triggered"] is True
    assert "refine_local_query" in output.react_summary["executed_actions"]
    assert output.staged_results[0].mod.title == "Local Compatibility Result"
    assert "pregnancy" in seen["query"]
    assert seen["plan"]["candidate_pool_limit"] == 30


@pytest.mark.asyncio
async def test_bounded_react_does_not_repeat_unavailable_online_tools(monkeypatch):
    seen = {}

    async def fail_web_run(self, **kwargs):
        raise AssertionError("online search should not be repeated after terminal skip evidence")

    async def fake_local_run(self, tool_input):
        seen["query"] = tool_input.query
        return [
            _result(
                _mod(
                    title="Local Fallback Result",
                    source="nexusmods",
                    external_id="fallback-1",
                    summary="Framework compatibility fallback.",
                )
            )
        ]

    monkeypatch.setattr(react_tool.WebSearchTool, "run", fail_web_run)
    monkeypatch.setattr(react_tool.LocalDbSearchTool, "run", fake_local_run)

    output = await BoundedReactRetrievalTool("session").run(
        BoundedReactRetrievalInput(
            query="pregnancy framework 兼容",
            query_plan={
                "keywords": ["pregnancy"],
                "requirement_terms": ["framework"],
                "compatibility_terms": ["compatibility"],
            },
            tool_plan={"parallel_groups": [{"name": "mixed", "tools": ["local_db_search", "nexusmods_search"]}]},
            staged_results=[],
            retrieval_evidence=[
                {
                    "stage": "online_retrieval",
                    "tool": "nexusmods_search",
                    "status": "skipped",
                    "reason": "missing_credentials",
                    "count": 0,
                }
            ],
            evidence_id="ev_prior_online",
        )
    )

    assert output.react_summary["triggered"] is True
    assert "refine_local_query" in output.react_summary["executed_actions"]
    assert output.react_trace[0]["action_reason"] == "online_unavailable_refine_local_query"
    assert seen["query"]


def test_guard_blocks_hard_constraint_changes():
    decision = guard_react_action(
        {"sources": ["nexusmods"], "games": ["Skyrim"]},
        ReactRetrievalAction(
            "expand_online_search",
            "unsafe_source_change",
            query_plan_patch={"sources": ["loverslab"]},
        ),
    )

    assert decision.allowed is False
    assert decision.reason == "hard_constraint_change_blocked"
    assert decision.blocked_fields == ["sources"]


def test_source_url_identity_does_not_match_empty_candidate_url():
    assessment = assess_retrieval_quality(
        query="https://example.test/mods/123",
        query_plan={"source_url": "https://example.test/mods/123"},
        staged_results=[
            _result(
                _mod(
                    title="Wrong URL Candidate",
                    external_id="empty-url",
                    url="",
                )
            )
        ],
        online_results=[],
    )

    assert assessment.direct_match_confidence == "missing"
    assert assessment.hard_constraints_satisfied is False
    assert "direct_match_missing_for_specific_query" in assessment.reasons
    assert "hard_constraint_violation" in assessment.reasons
