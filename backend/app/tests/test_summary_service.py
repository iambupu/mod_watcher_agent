import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.models.mod import Mod
from app.models.summary import ModSummary
from app.services.summary_service import SummaryService


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
async def test_generate_chinese_brief_summary_persists_translated_title(monkeypatch):
    engine = _make_engine()
    SQLModel.metadata.create_all(engine)

    class FakeClient:
        async def chat(self, prompt: str, model: str, max_tokens: int = 1024):  # noqa: ARG002
            assert "translated_title_zh" in prompt
            assert "Translate this mod title and summary into Simplified Chinese" in prompt
            return '{"translated_title_zh":"天际服装包","translated_summary":"增加一套适合天际的服装。"}'

    monkeypatch.setattr(
        SummaryService,
        "_get_provider_chain",
        lambda self: [{"provider": "openai", "api_key": "test-key", "model": "test-model", "base_url": ""}],
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
