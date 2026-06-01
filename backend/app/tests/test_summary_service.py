import asyncio

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.jobs.generate_summaries import (
    generate_single_summary_payload,
    generate_single_summary_payload_locked,
)
from app.models.mod import Mod
from app.models.summary import ModSummary
from app.services.summary_service import (
    SUMMARY_BRIEF_LLM_TIMEOUT_SECONDS,
    SUMMARY_BRIEF_MAX_TOKENS,
    SUMMARY_BRIEF_REASONING_RETRY_MAX_TOKENS,
    SUMMARY_GENERATION_LOCK,
    SummaryService,
    _parse_brief_translation_response,
    load_summary_map,
)


def _make_engine():
    return create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


def _make_mod(external_id: str) -> Mod:
    return Mod(
        source="nexusmods",
        external_id=external_id,
        game="Skyrim Special Edition",
        title=f"Mod {external_id}",
        original_summary="Original summary",
        url=f"https://example.com/{external_id}",
        first_seen_at="2026-05-24T00:00:00+00:00",
        last_seen_at="2026-05-24T00:00:00+00:00",
    )


def _provider_chain(provider: str = "deepseek", model: str = "deepseek-chat") -> list[dict]:
    return [{"provider": provider, "api_key": "test-key", "model": model, "base_url": ""}]


def test_parse_brief_translation_response_extracts_json_from_deepseek_style_text():
    content = (
        "下面是翻译结果：\n"
        '```json\n{"translated_title_zh":"身体预设","translated_summary":"增加一个身体预设。"}\n```\n'
        "希望对你有帮助。"
    )

    title, summary = _parse_brief_translation_response(content)

    assert title == "身体预设"
    assert summary == "增加一个身体预设。"


def test_load_summary_map_handles_large_mod_id_sets():
    engine = _make_engine()
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        mods = [_make_mod(str(index)) for index in range(1205)]
        session.add_all(mods)
        session.commit()
        for mod in mods:
            session.refresh(mod)
        session.add_all(
            [
                ModSummary(
                    mod_id=mods[0].id,
                    language="zh-CN",
                    summary_type="brief",
                    content="第一条摘要",
                    model="test",
                    generated_at="2026-05-30T00:00:00",
                ),
                ModSummary(
                    mod_id=mods[-1].id,
                    language="zh-CN",
                    summary_type="brief",
                    content="最后一条摘要",
                    model="test",
                    generated_at="2026-05-30T00:00:00",
                ),
            ]
        )
        session.commit()

        result = load_summary_map(
            session,
            [mod.id for mod in mods if mod.id is not None],
            "zh-CN",
            "brief",
        )

    assert result == {mods[0].id: "第一条摘要", mods[-1].id: "最后一条摘要"}


@pytest.mark.asyncio
async def test_generate_missing_summaries_respects_max_items(monkeypatch):
    engine = _make_engine()
    SQLModel.metadata.create_all(engine)

    generated_ids: list[int] = []

    async def fake_generate_summary(self, mod_id: int, **kwargs):  # noqa: ARG001
        generated_ids.append(mod_id)
        return {"content": "ok", "model": "test"}

    monkeypatch.setattr(SummaryService, "generate_summary", fake_generate_summary)

    with Session(engine) as session:
        session.add_all([_make_mod("1"), _make_mod("2"), _make_mod("3")])
        session.commit()

        count = await SummaryService(session).generate_missing_summaries(
            language="zh-CN",
            max_items=2,
        )

    assert count == 2
    assert generated_ids == [1, 2]


@pytest.mark.asyncio
async def test_generate_missing_summaries_report_stops_when_requested(monkeypatch):
    engine = _make_engine()
    SQLModel.metadata.create_all(engine)

    generated_ids: list[int] = []

    async def fake_generate_summary(self, mod_id: int, **kwargs):  # noqa: ARG001
        generated_ids.append(mod_id)
        return {"content": "ok", "model": "test"}

    monkeypatch.setattr(SummaryService, "generate_summary", fake_generate_summary)

    with Session(engine) as session:
        session.add_all([_make_mod("1"), _make_mod("2"), _make_mod("3")])
        session.commit()

        report = await SummaryService(session).generate_missing_summaries_report(
            language="zh-CN",
            max_items=3,
            should_stop=lambda: bool(generated_ids),
        )

    assert report["generated"] == 1
    assert generated_ids == [1]


@pytest.mark.asyncio
async def test_generate_missing_summaries_report_retries_invalid_existing_translation(monkeypatch):
    engine = _make_engine()
    SQLModel.metadata.create_all(engine)
    generated_ids: list[int] = []

    async def fake_generate_summary(self, mod_id: int, **kwargs):  # noqa: ARG001
        generated_ids.append(mod_id)
        return {"content": "中文修复", "model": "test", "provider": "test"}

    monkeypatch.setattr(SummaryService, "generate_summary", fake_generate_summary)

    with Session(engine) as session:
        mod = _make_mod("invalid-existing")
        session.add(mod)
        session.commit()
        session.refresh(mod)
        session.add(
            ModSummary(
                mod_id=mod.id,
                language="zh-CN",
                summary_type="brief",
                content="This English content was stored under zh-CN.",
                model="old-bad-run",
                generated_at="2025-01-01T00:00:00",
            )
        )
        session.commit()

        report = await SummaryService(session).generate_missing_summaries_report(language="zh-CN")

    assert report["scanned"] == 1
    assert report["generated"] == 1
    assert report["failed"] == 0
    assert generated_ids == [1]


@pytest.mark.asyncio
async def test_generate_missing_summaries_report_returns_failure_details(monkeypatch):
    engine = _make_engine()
    SQLModel.metadata.create_all(engine)

    async def fake_generate_summary(self, mod_id: int, **kwargs):  # noqa: ARG001
        return {
            "content": "",
            "model": "none",
            "provider": "deepseek",
            "error": "target_language_missing",
            "provider_attempts": [{"provider": "deepseek", "success": False}],
        }

    monkeypatch.setattr(SummaryService, "generate_summary", fake_generate_summary)

    with Session(engine) as session:
        session.add(_make_mod("failed-detail"))
        session.commit()

        report = await SummaryService(session).generate_missing_summaries_report(language="zh-CN")

    assert report["scanned"] == 1
    assert report["generated"] == 0
    assert report["failed"] == 1
    assert report["failures"] == [
        {
            "mod_id": 1,
            "provider": "deepseek",
            "model": "none",
            "error": "target_language_missing",
            "provider_attempts": [{"provider": "deepseek", "success": False}],
        }
    ]


@pytest.mark.asyncio
async def test_generate_chinese_brief_summary_persists_translated_title(monkeypatch):
    engine = _make_engine()
    SQLModel.metadata.create_all(engine)

    class FakeClient:
        async def chat(
            self,
            prompt: str,
            model: str,  # noqa: ARG002
            max_tokens: int = 1024,  # noqa: ARG002
            request_timeout: float | None = None,  # noqa: ARG002
        ):
            assert "translated_title_zh" in prompt
            assert "Translate this mod title and summary into Simplified Chinese" in prompt
            return '{"translated_title_zh":"天际服装包","translated_summary":"增加一套适合天际的服装。"}'

    monkeypatch.setattr(
        SummaryService,
        "_get_provider_chain",
        lambda self: _provider_chain("openai", "test-model"),
    )
    monkeypatch.setattr("app.services.summary_service.create_llm_client", lambda *args: FakeClient())

    with Session(engine) as session:
        mod = _make_mod("title-translation")
        mod.title = "Skyrim Outfit Pack"
        mod.original_summary = "Adds an outfit for Skyrim."
        session.add(mod)
        session.commit()

        result = await SummaryService(session).generate_summary(
            mod.id or 0,
            language="zh-CN",
            summary_type="brief",
        )

        updated = session.get(Mod, mod.id)
        summary = session.exec(select(ModSummary).where(ModSummary.mod_id == mod.id)).first()

    assert result["content"] == "增加一套适合天际的服装。"
    assert result["translated_title_zh"] == "天际服装包"
    assert updated is not None
    assert updated.translated_title_zh == "天际服装包"
    assert summary is not None
    assert summary.content == "增加一套适合天际的服装。"


@pytest.mark.asyncio
async def test_generate_chinese_brief_summary_uses_short_fast_llm_request(monkeypatch):
    engine = _make_engine()
    SQLModel.metadata.create_all(engine)
    calls: list[dict] = []

    class FakeClient:
        async def chat(
            self,
            prompt: str,  # noqa: ARG002
            model: str,
            max_tokens: int = 1024,
            request_timeout: float | None = None,
        ):
            calls.append(
                {
                    "model": model,
                    "max_tokens": max_tokens,
                    "request_timeout": request_timeout,
                }
            )
            return '{"translated_title_zh":"天际服装包","translated_summary":"增加一套适合天际的服装。"}'

    monkeypatch.setattr(
        SummaryService,
        "_get_provider_chain",
        lambda self: _provider_chain(),
    )
    monkeypatch.setattr("app.services.summary_service.create_llm_client", lambda *args: FakeClient())

    with Session(engine) as session:
        mod = _make_mod("fast-translation")
        session.add(mod)
        session.commit()

        result = await SummaryService(session).generate_summary(
            mod.id or 0,
            language="zh-CN",
            summary_type="brief",
        )

    assert result["content"] == "增加一套适合天际的服装。"
    assert calls == [
        {
            "model": "deepseek-chat",
            "max_tokens": SUMMARY_BRIEF_MAX_TOKENS,
            "request_timeout": SUMMARY_BRIEF_LLM_TIMEOUT_SECONDS,
        }
    ]


@pytest.mark.asyncio
async def test_generate_chinese_brief_summary_retries_reasoning_empty_content(monkeypatch):
    engine = _make_engine()
    SQLModel.metadata.create_all(engine)
    calls: list[dict] = []

    class FakeClient:
        def __init__(self):
            self.last_error = ""
            self.last_detail = ""

        async def chat(
            self,
            prompt: str,  # noqa: ARG002
            model: str,
            max_tokens: int = 1024,
            request_timeout: float | None = None,
        ):
            calls.append(
                {
                    "model": model,
                    "max_tokens": max_tokens,
                    "request_timeout": request_timeout,
                }
            )
            if len(calls) == 1:
                self.last_detail = (
                    "HTTP OK but content was empty; finish_reason=length; "
                    "model returned reasoning text before final content."
                )
                return ""
            self.last_detail = ""
            return '{"translated_title_zh":"天际服装包","translated_summary":"增加一套适合天际的服装。"}'

    fake_client = FakeClient()
    monkeypatch.setattr(SummaryService, "_get_provider_chain", lambda self: _provider_chain())
    monkeypatch.setattr("app.services.summary_service.create_llm_client", lambda *args: fake_client)

    with Session(engine) as session:
        mod = _make_mod("reasoning-retry")
        session.add(mod)
        session.commit()

        result = await SummaryService(session).generate_summary(
            mod.id or 0,
            language="zh-CN",
            summary_type="brief",
        )

    assert result["provider"] == "deepseek"
    assert result["content"] == "增加一套适合天际的服装。"
    assert calls == [
        {
            "model": "deepseek-chat",
            "max_tokens": SUMMARY_BRIEF_MAX_TOKENS,
            "request_timeout": SUMMARY_BRIEF_LLM_TIMEOUT_SECONDS,
        },
        {
            "model": "deepseek-chat",
            "max_tokens": SUMMARY_BRIEF_REASONING_RETRY_MAX_TOKENS,
            "request_timeout": SUMMARY_BRIEF_LLM_TIMEOUT_SECONDS,
        },
    ]
    assert result["provider_attempts"] == [
        {
            "provider": "deepseek",
            "model": "deepseek-chat",
            "success": True,
            "reason": "ok",
            "max_tokens": SUMMARY_BRIEF_REASONING_RETRY_MAX_TOKENS,
        }
    ]


@pytest.mark.asyncio
async def test_generate_chinese_brief_summary_repairs_translated_proper_nouns(monkeypatch):
    engine = _make_engine()
    SQLModel.metadata.create_all(engine)
    prompts: list[str] = []

    class FakeClient:
        async def chat(
            self,
            prompt: str,
            model: str,  # noqa: ARG002
            max_tokens: int = 1024,  # noqa: ARG002
            request_timeout: float | None = None,  # noqa: ARG002
        ):
            prompts.append(prompt)
            if len(prompts) == 1:
                return (
                    '{"translated_title_zh":"灰烬之歌 - 有魅力的HPH重制",'
                    '"translated_summary":"对《灰烬之歌》女性NPC进行重制，赋予她们灵魂。"}'
                )
            return (
                '{"translated_title_zh":"Bimbos of Skyrim - 有魅力的 HPH 重制",'
                '"translated_summary":"重制 Bimbos of Skyrim 的女性 NPC，让她们更有灵魂；尚未包含所有 NPC。"}'
            )

    monkeypatch.setattr(SummaryService, "_get_provider_chain", lambda self: _provider_chain())
    monkeypatch.setattr("app.services.summary_service.create_llm_client", lambda *args: FakeClient())

    with Session(engine) as session:
        mod = _make_mod("proper-noun-repair")
        mod.title = "Bimbos of Skyrim - Charismatic HPH Overhaul"
        mod.original_summary = (
            "Overhaul of Bimbos of Skyrim female NPCs to give them 'soul'. "
            "Not all NPCs are yet included."
        )
        session.add(mod)
        session.commit()

        result = await SummaryService(session).generate_summary(
            mod.id or 0,
            language="zh-CN",
            summary_type="brief",
        )

        updated = session.get(Mod, mod.id)
        summary = session.exec(select(ModSummary).where(ModSummary.mod_id == mod.id)).first()

    assert len(prompts) == 2
    assert "Preserve these exact terms" in prompts[1]
    assert "Bimbos of Skyrim" in prompts[1]
    assert result["translated_title_zh"] == "Bimbos of Skyrim - 有魅力的 HPH 重制"
    assert result["content"] == "重制 Bimbos of Skyrim 的女性 NPC，让她们更有灵魂；尚未包含所有 NPC。"
    assert updated is not None
    assert updated.translated_title_zh == "Bimbos of Skyrim - 有魅力的 HPH 重制"
    assert summary is not None
    assert summary.content == "重制 Bimbos of Skyrim 的女性 NPC，让她们更有灵魂；尚未包含所有 NPC。"


@pytest.mark.asyncio
async def test_generate_chinese_brief_summary_does_not_persist_english_source_when_protected_repair_fails(monkeypatch):
    engine = _make_engine()
    SQLModel.metadata.create_all(engine)

    class FakeClient:
        async def chat(
            self,
            prompt: str,  # noqa: ARG002
            model: str,  # noqa: ARG002
            max_tokens: int = 1024,  # noqa: ARG002
            request_timeout: float | None = None,  # noqa: ARG002
        ):
            return (
                '{"translated_title_zh":"灰烬之歌 LE/SE 1.9.0.7",'
                '"translated_summary":"这个模组添加了女性 NPC、任务和诅咒内容。"}'
            )

    monkeypatch.setattr(SummaryService, "_get_provider_chain", lambda self: _provider_chain("ollama", "qwen3:8b"))
    monkeypatch.setattr("app.services.summary_service.create_llm_client", lambda *args: FakeClient())

    with Session(engine) as session:
        mod = _make_mod("protected-repair-fails")
        mod.title = "Bimbos Of Skyrim LE/SE 1.9.0.7"
        mod.original_summary = (
            "BIMBOS OF SKYRIM This mod adds three main things: "
            ">A variety of female NPCs around Skyrim."
        )
        session.add(mod)
        session.commit()

        result = await SummaryService(session).generate_summary(
            mod.id or 0,
            language="zh-CN",
            summary_type="brief",
        )

        summary = session.exec(select(ModSummary).where(ModSummary.mod_id == mod.id)).first()

    assert result["model"] == "none"
    assert result["error"] == "protected_terms_missing"
    assert result["content"] == ""
    assert summary is None


@pytest.mark.asyncio
async def test_generate_chinese_brief_summary_tries_next_provider_after_semantic_rejection(monkeypatch):
    engine = _make_engine()
    SQLModel.metadata.create_all(engine)

    class BadProviderClient:
        async def chat(
            self,
            prompt: str,  # noqa: ARG002
            model: str,  # noqa: ARG002
            max_tokens: int = 1024,  # noqa: ARG002
            request_timeout: float | None = None,  # noqa: ARG002
        ):
            return (
                '{"translated_title_zh":"灰烬之歌 LE/SE 1.9.0.7",'
                '"translated_summary":"这个模组添加了女性 NPC、任务和诅咒内容。"}'
            )

    class GoodProviderClient:
        async def chat(
            self,
            prompt: str,  # noqa: ARG002
            model: str,  # noqa: ARG002
            max_tokens: int = 1024,  # noqa: ARG002
            request_timeout: float | None = None,  # noqa: ARG002
        ):
            return (
                '{"translated_title_zh":"Bimbos Of Skyrim LE/SE 1.9.0.7",'
                '"translated_summary":"BIMBOS OF SKYRIM 增加女性 NPC、任务和诅咒内容。"}'
            )

    monkeypatch.setattr(
        SummaryService,
        "_get_provider_chain",
        lambda self: [
            {"provider": "bad", "api_key": "test-key", "model": "bad-model", "base_url": ""},
            {"provider": "good", "api_key": "test-key", "model": "good-model", "base_url": ""},
        ],
    )
    monkeypatch.setattr(
        "app.services.summary_service.create_llm_client",
        lambda provider, *args: BadProviderClient() if provider == "bad" else GoodProviderClient(),
    )

    with Session(engine) as session:
        mod = _make_mod("semantic-fallback")
        mod.title = "Bimbos Of Skyrim LE/SE 1.9.0.7"
        mod.original_summary = "BIMBOS OF SKYRIM This mod adds female NPCs, quests, and a curse."
        session.add(mod)
        session.commit()

        result = await SummaryService(session).generate_summary(
            mod.id or 0,
            language="zh-CN",
            summary_type="brief",
        )

        summary = session.exec(select(ModSummary).where(ModSummary.mod_id == mod.id)).first()

    assert result["provider"] == "good"
    assert result["model"] == "good-model"
    assert result["content"] == "BIMBOS OF SKYRIM 增加女性 NPC、任务和诅咒内容。"
    assert result["provider_attempts"][0]["reason"] == "protected_terms_missing"
    assert result["provider_attempts"][1]["reason"] == "ok"
    assert summary is not None
    assert summary.content == "BIMBOS OF SKYRIM 增加女性 NPC、任务和诅咒内容。"


@pytest.mark.asyncio
async def test_generate_chinese_brief_summary_does_not_treat_empty_provider_chain_as_success(monkeypatch):
    engine = _make_engine()
    SQLModel.metadata.create_all(engine)

    class FakeClient:
        last_error = ""
        last_detail = "Empty response"

        async def chat(
            self,
            prompt: str,  # noqa: ARG002
            model: str,  # noqa: ARG002
            max_tokens: int = 1024,  # noqa: ARG002
            request_timeout: float | None = None,  # noqa: ARG002
        ):
            return ""

    monkeypatch.setattr(SummaryService, "_get_provider_chain", lambda self: _provider_chain())
    monkeypatch.setattr("app.services.summary_service.create_llm_client", lambda *args: FakeClient())

    with Session(engine) as session:
        mod = _make_mod("empty-provider-chain")
        session.add(mod)
        session.commit()

        result = await SummaryService(session).generate_summary(
            mod.id or 0,
            language="zh-CN",
            summary_type="brief",
        )

        summary = session.exec(select(ModSummary).where(ModSummary.mod_id == mod.id)).first()

    assert result["model"] == "none"
    assert result["error"] == "llm_empty_or_unavailable"
    assert result["content"] == ""
    assert summary is None


@pytest.mark.asyncio
async def test_generate_chinese_brief_summary_rejects_non_chinese_translation(monkeypatch):
    engine = _make_engine()
    SQLModel.metadata.create_all(engine)

    class FakeClient:
        async def chat(
            self,
            prompt: str,  # noqa: ARG002
            model: str,  # noqa: ARG002
            max_tokens: int = 1024,  # noqa: ARG002
            request_timeout: float | None = None,  # noqa: ARG002
        ):
            return '{"translated_title_zh":"Skyrim Outfit Pack","translated_summary":"Adds an outfit for Skyrim."}'

    monkeypatch.setattr(SummaryService, "_get_provider_chain", lambda self: _provider_chain())
    monkeypatch.setattr("app.services.summary_service.create_llm_client", lambda *args: FakeClient())

    with Session(engine) as session:
        mod = _make_mod("non-chinese-output")
        session.add(mod)
        session.commit()

        result = await SummaryService(session).generate_summary(
            mod.id or 0,
            language="zh-CN",
            summary_type="brief",
        )

        summary = session.exec(select(ModSummary).where(ModSummary.mod_id == mod.id)).first()

    assert result["model"] == "none"
    assert result["error"] == "target_language_missing"
    assert result["content"] == ""
    assert summary is None


@pytest.mark.asyncio
async def test_generate_single_summary_payload_raises_when_translation_not_generated(monkeypatch):
    engine = _make_engine()
    SQLModel.metadata.create_all(engine)

    async def fake_generate_summary(self, mod_id: int, **kwargs):  # noqa: ARG001
        return {
            "content": "",
            "model": "none",
            "provider": "deepseek",
            "error": "target_language_missing",
            "provider_attempts": [{"provider": "deepseek", "success": False}],
        }

    monkeypatch.setattr(SummaryService, "generate_summary", fake_generate_summary)

    with Session(engine) as session:
        mod = _make_mod("payload-raises")
        session.add(mod)
        session.commit()

        with pytest.raises(RuntimeError, match="target_language_missing"):
            await generate_single_summary_payload(
                session,
                mod_id=mod.id or 0,
                language="zh-CN",
                summary_type="brief",
            )


@pytest.mark.asyncio
async def test_generate_single_summary_payload_locked_waits_for_summary_lock(monkeypatch):
    engine = _make_engine()
    SQLModel.metadata.create_all(engine)
    generated_ids: list[int] = []

    async def fake_generate_summary(self, mod_id: int, **kwargs):  # noqa: ARG001
        generated_ids.append(mod_id)
        return {"content": "中文摘要", "model": "test-model", "provider": "test"}

    monkeypatch.setattr(SummaryService, "generate_summary", fake_generate_summary)

    with Session(engine) as session:
        mod = _make_mod("locked-single")
        session.add(mod)
        session.commit()
        session.refresh(mod)

        async with SUMMARY_GENERATION_LOCK:
            task = asyncio.create_task(
                generate_single_summary_payload_locked(
                    session,
                    mod_id=mod.id or 0,
                    language="zh-CN",
                    summary_type="brief",
                )
            )
            await asyncio.sleep(0)
            assert not task.done()
            assert generated_ids == []

        result = await task

    assert result["items_scanned"] == 1
    assert result["items_matched"] == 1
    assert generated_ids == [mod.id]
