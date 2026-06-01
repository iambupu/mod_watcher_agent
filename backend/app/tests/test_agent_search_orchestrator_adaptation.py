import logging

import pytest

from app.services.agent.tools.web_search_tool import WebSearchTool


@pytest.mark.asyncio
async def test_web_search_tool_adds_adaptation_evidence_for_narrow_zero_result(monkeypatch, caplog):
    caplog.set_level(logging.INFO)

    async def _noop_run(self, tool_input):
        self.last_status = "succeeded"
        self.last_reason = None
        return []

    monkeypatch.setattr("app.services.agent.tools.web_search_tool.NexusModsSearchTool.run", _noop_run)
    monkeypatch.setattr("app.services.agent.tools.web_search_tool.LoversLabGoogleSearchTool.run", _noop_run)
    monkeypatch.setattr("app.services.agent.tools.web_search_tool.LoversLabSearchScrapeTool.run", _noop_run)

    output = await WebSearchTool(session="session").run(
        query="test",
        query_plan={},
        evidence_id="ev_test",
        online_recall_mode="narrow",
    )
    adaptation = [item for item in output.evidence if item.get("stage") == "online_adaptation"]
    assert len(adaptation) == 1
    assert adaptation[0]["reason"] == "narrow_online_zero_result_expand_sources"
    assert all(item.get("evidence_id") == "ev_test" for item in output.evidence)
    assert any(
        "agent.tool name=web_search status=succeeded results=0" in item.message
        and "adaptation=True" in item.message
        and "evidence_id=ev_test" in item.message
        for item in caplog.records
    )


@pytest.mark.asyncio
async def test_web_search_tool_skips_adaptation_evidence_when_recall_is_broad(monkeypatch):
    async def _noop_run(self, tool_input):
        return []

    monkeypatch.setattr("app.services.agent.tools.web_search_tool.NexusModsSearchTool.run", _noop_run)
    monkeypatch.setattr("app.services.agent.tools.web_search_tool.LoversLabGoogleSearchTool.run", _noop_run)
    monkeypatch.setattr("app.services.agent.tools.web_search_tool.LoversLabSearchScrapeTool.run", _noop_run)

    output = await WebSearchTool(session="session").run(
        query="test",
        query_plan={},
        evidence_id="ev_test",
        online_recall_mode="broad",
    )
    adaptation = [item for item in output.evidence if item.get("stage") == "online_adaptation"]
    assert adaptation == []


@pytest.mark.asyncio
async def test_web_search_tool_tolerates_invalid_online_count_evidence(monkeypatch):
    async def _noop_run(self, tool_input):  # noqa: ARG001
        self.last_status = "succeeded"
        return []

    def _append_bad_count(evidence, **kwargs):
        if kwargs.get("status") == "succeeded":
            kwargs["count"] = "bad"
        evidence.append(kwargs)

    monkeypatch.setattr("app.services.agent.tools.web_search_tool.NexusModsSearchTool.run", _noop_run)
    monkeypatch.setattr("app.services.agent.tools.web_search_tool.LoversLabGoogleSearchTool.run", _noop_run)
    monkeypatch.setattr("app.services.agent.tools.web_search_tool.LoversLabSearchScrapeTool.run", _noop_run)
    monkeypatch.setattr("app.services.agent.tools.web_search_tool.append_retrieval_evidence", _append_bad_count)

    output = await WebSearchTool(session="session").run(
        query="test",
        query_plan={},
        online_recall_mode="broad",
    )

    assert output.results == []
    assert any(item.get("count") == "bad" for item in output.evidence)


@pytest.mark.asyncio
async def test_web_search_tool_logs_missing_credentials_as_skipped(monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    monkeypatch.setattr("app.services.agent.tools.nexusmods_search_tool.SettingsService.get", lambda self, key: "")

    output = await WebSearchTool(session="session").run(
        query="bimbo",
        query_plan={"sources": ["nexusmods"]},
        evidence_id="ev_missing_credentials",
        online_recall_mode="broad",
    )

    nexus_evidence = [item for item in output.evidence if item.get("tool") == "nexusmods_search"]
    assert nexus_evidence[0]["status"] == "skipped"
    assert nexus_evidence[0]["reason"] == "missing_credentials"
    assert nexus_evidence[0]["evidence_id"] == "ev_missing_credentials"
    assert any(
        "agent.retrieval.online tool=nexusmods_search status=skipped count=0 reason=missing_credentials"
        in item.message
        and "evidence_id=ev_missing_credentials" in item.message
        for item in caplog.records
    )


@pytest.mark.asyncio
async def test_web_search_tool_does_not_adapt_when_narrow_result_is_only_skipped(monkeypatch):
    monkeypatch.setattr("app.services.agent.tools.nexusmods_search_tool.SettingsService.get", lambda self, key: "")

    output = await WebSearchTool(session="session").run(
        query="bimbo",
        query_plan={"sources": ["nexusmods"]},
        evidence_id="ev_missing_credentials",
        online_recall_mode="narrow",
    )

    assert [item for item in output.evidence if item.get("stage") == "online_adaptation"] == []
    assert any(item.get("reason") == "missing_credentials" for item in output.evidence)


@pytest.mark.asyncio
async def test_web_search_tool_respects_empty_allowed_tools(monkeypatch):
    async def _fail_run(self, tool_input):  # noqa: ARG001
        raise AssertionError("unplanned online leaf tools must not run")

    monkeypatch.setattr("app.services.agent.tools.web_search_tool.NexusModsSearchTool.run", _fail_run)
    monkeypatch.setattr("app.services.agent.tools.web_search_tool.LoversLabGoogleSearchTool.run", _fail_run)
    monkeypatch.setattr("app.services.agent.tools.web_search_tool.LoversLabSearchScrapeTool.run", _fail_run)

    output = await WebSearchTool(session="session").run(
        query="bimbo",
        query_plan={"sources": ["nexusmods", "loverslab"]},
        evidence_id="ev_no_online_tools",
        allowed_tools=set(),
    )

    assert output.results == []
    assert {item.get("tool") for item in output.evidence} >= {"nexusmods_search", "loverslab_google"}
    assert all(item.get("status") == "skipped" for item in output.evidence)
    assert all(item.get("reason") == "not_planned" for item in output.evidence)
