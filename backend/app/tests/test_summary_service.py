import ast
import inspect
import json

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.models.mod import Mod
from app.models.summary import ModSummary
from app.services.settings_service import SettingsService
from app.services.summary_service import (
    SummaryService,
    _parse_brief_translation_response,
    load_summary_map,
)


def _make_engine():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    return engine


def _make_mod(**kwargs) -> Mod:
    defaults = {
        "source": "nexusmods",
        "external_id": "skyrimspecialedition:12345",
        "game": "skyrim",
        "title": "Bug Catching Net Updated HDT-SMP",
        "url": "https://example.com/mods/12345",
        "first_seen_at": "2026-06-30T00:00:00",
        "last_seen_at": "2026-06-30T00:00:00",
    }
    defaults.update(kwargs)
    return Mod(**defaults)


def test_generate_summary_is_a_small_lifecycle_orchestrator():
    source = inspect.getsource(SummaryService.generate_summary)
    tree = ast.parse(inspect.cleandoc(source))
    decisions = sum(
        isinstance(node, (ast.If, ast.For, ast.While, ast.Try, ast.Match, ast.BoolOp))
        for node in ast.walk(tree)
    )

    assert len(source.splitlines()) <= 55
    assert decisions <= 6
    assert hasattr(SummaryService, "_build_summary_request")
    assert hasattr(SummaryService, "_generate_from_provider_chain")
    assert hasattr(SummaryService, "_persist_generated_summary")


def test_parse_brief_translation_response_accepts_translated_summary_zh_key():
    title, summary = _parse_brief_translation_response(
        '{"translated_title_zh":"捕虫网更新版 HDT-SMP","translated_summary_zh":"精美捕虫网模组的更新"}'
    )

    assert title == "捕虫网更新版 HDT-SMP"
    assert summary == "精美捕虫网模组的更新"


def test_parse_brief_translation_response_extracts_curly_quoted_summary_payload():
    title, summary = _parse_brief_translation_response(
        '{"translated_title_zh":"Skyrim 重生白河郡领地 - 北方海盗 SSE 补丁","translated_summary":“阻止两个模组之间的穿插”}'
    )

    assert title == "Skyrim 重生白河郡领地 - 北方海盗 SSE 补丁"
    assert summary == "阻止两个模组之间的穿插"


def test_load_summary_map_normalizes_legacy_brief_translation_json():
    engine = _make_engine()
    with Session(engine) as session:
        mod = _make_mod()
        session.add(mod)
        session.commit()
        session.refresh(mod)
        session.add(
            ModSummary(
                mod_id=mod.id,
                language="zh-CN",
                summary_type="brief",
                content='{"translated_title_zh":"捕虫网更新版 HDT-SMP","translated_summary_zh":"精美捕虫网模组的更新"}',
                model="test",
                generated_at="2026-06-30T00:00:00",
            )
        )
        session.commit()

        assert load_summary_map(session, [mod.id], "zh-CN", "brief") == {
            mod.id: "精美捕虫网模组的更新"
        }


def test_summary_refresh_candidates_include_legacy_json_payloads():
    engine = _make_engine()
    with Session(engine) as session:
        mod = _make_mod(updated_at_remote="2026-06-29T00:00:00")
        session.add(mod)
        session.commit()
        session.refresh(mod)
        session.add(
            ModSummary(
                mod_id=mod.id,
                language="zh-CN",
                summary_type="brief",
                content='{"translated_title_zh":"捕虫网更新版 HDT-SMP","translated_summary_zh":"精美捕虫网模组的更新"}',
                model="old-run",
                generated_at="2026-06-30T00:00:00",
            )
        )
        session.commit()

        assert SummaryService(session)._summary_refresh_candidate_ids(
            language="zh-CN",
            mod_ids=[mod.id],
            max_items=None,
        ) == [mod.id]


@pytest.mark.asyncio
async def test_generate_summary_releases_transaction_before_llm_call(monkeypatch):
    engine = _make_engine()
    observed: dict[str, bool] = {}

    class FakeClient:
        async def chat(self, prompt: str, model: str, **kwargs) -> str:  # noqa: ARG002
            observed["in_transaction"] = session.in_transaction()
            return '{"translated_title_zh":"猫咪家具","translated_summary":"添加可爱的猫咪主题家具。"}'

    monkeypatch.setattr(
        "app.services.summary_service.create_llm_client",
        lambda *args: FakeClient(),
    )

    with Session(engine) as session:
        SettingsService(session).set(
            "llm_providers_json",
            json.dumps(
                [
                    {
                        "provider": "ollama",
                        "enabled": True,
                        "priority": 1,
                        "model": "qwen3:8b",
                        "api_key": "",
                        "base_url": "http://localhost:11434/v1",
                    }
                ]
            ),
        )
        mod = _make_mod(
            title="Cat Furniture",
            original_summary="Adds cute cat themed furniture.",
        )
        session.add(mod)
        session.commit()
        session.refresh(mod)

        result = await SummaryService(session).generate_summary(
            mod.id,
            language="zh-CN",
            summary_type="brief",
        )

        assert observed == {"in_transaction": False}
        assert result["content"] == "添加可爱的猫咪主题家具。"
