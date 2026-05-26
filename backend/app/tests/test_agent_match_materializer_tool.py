import logging

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.models.mod import Mod
from app.models.summary import ModSummary
from app.services.agent.search_types import SearchResult
from app.services.agent.tools.match_materializer_tool import (
    MatchMaterializerInput,
    MatchMaterializerTool,
)


def test_match_materializer_builds_matches_with_summaries_and_rank_metadata(caplog):
    caplog.set_level(logging.INFO)
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    try:
        with Session(engine) as session:
            mod = Mod(
                source="nexusmods",
                external_id="bimbo-roleplay-1",
                game="Skyrim Special Edition",
                game_domain="skyrimspecialedition",
                title="Bimbo Roleplay Framework",
                translated_title_zh="Bimbo 扮演框架",
                url="https://example.com/bimbo-roleplay",
                category="Gameplay",
                original_summary="Roleplay framework for bimbo progression.",
                first_seen_at="2026-05-25T00:00:00+00:00",
                last_seen_at="2026-05-25T00:00:00+00:00",
                adult_content=False,
            )
            session.add(mod)
            session.commit()
            session.refresh(mod)
            session.add(
                ModSummary(
                    mod_id=mod.id or 0,
                    model="test",
                    language="zh-CN",
                    summary_type="brief",
                    content="中文简介",
                    generated_at="2026-05-25T00:00:00+00:00",
                )
            )
            session.commit()

            output = MatchMaterializerTool(session).run(
                MatchMaterializerInput(
                    results=[
                        SearchResult(
                            score=12,
                            mod=mod,
                            tool_name="local_db_search",
                            score_breakdown={"title": 5},
                            rank_reason="semantic match",
                        )
                    ],
                    limit=8,
                    evidence_id="ev_test",
                )
            )

        assert len(output.matches) == 1
        match = output.matches[0]
        assert match.title == "Bimbo Roleplay Framework"
        assert match.translated_title_zh == "Bimbo 扮演框架"
        assert match.translated_summary == "中文简介"
        assert match.score_breakdown == {"title": 5}
        assert match.rank_reason == "semantic match"
        assert any("agent.tool name=match_materializer status=succeeded input=1 output=1" in item.message for item in caplog.records)
    finally:
        SQLModel.metadata.drop_all(engine)
        engine.dispose()


def test_match_materializer_respects_limit():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    try:
        with Session(engine) as session:
            first = _mod("first", "First Match")
            second = _mod("second", "Second Match")
            session.add_all([first, second])
            session.commit()
            session.refresh(first)
            session.refresh(second)

            output = MatchMaterializerTool(session).run(
                MatchMaterializerInput(
                    results=[
                        SearchResult(score=10, mod=first, tool_name="local_db_search"),
                        SearchResult(score=9, mod=second, tool_name="local_db_search"),
                    ],
                    limit=1,
                )
            )

        assert [match.title for match in output.matches] == ["First Match"]
    finally:
        SQLModel.metadata.drop_all(engine)
        engine.dispose()


def _mod(external_id: str, title: str) -> Mod:
    return Mod(
        source="nexusmods",
        external_id=external_id,
        game="Skyrim Special Edition",
        game_domain="skyrimspecialedition",
        title=title,
        url=f"https://example.com/{external_id}",
        first_seen_at="2026-05-25T00:00:00+00:00",
        last_seen_at="2026-05-25T00:00:00+00:00",
    )
