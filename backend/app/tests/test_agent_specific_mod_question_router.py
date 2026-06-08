import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

import app.models  # noqa: F401
from app.models.mod import Mod
from app.services.agent.routing.specific_mod_question_router import (
    SPECIFIC_MOD_ROUTER_TIMEOUT_SECONDS,
    SpecificModQuestionRouter,
    SpecificModRouteInput,
)
from app.services.settings_service import SettingsService


def _session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def _add_mod(session: Session) -> Mod:
    mod = Mod(
        source="nexusmods",
        external_id="layer-bikini",
        game="Skyrim Special Edition",
        game_domain="skyrimspecialedition",
        title="Layer Bikini",
        url="https://example.com/layer-bikini",
        original_summary="A bikini outfit with physics.",
        first_seen_at="2026-05-28T00:00:00+00:00",
        last_seen_at="2026-05-28T00:00:00+00:00",
    )
    session.add(mod)
    session.commit()
    session.refresh(mod)
    return mod


@pytest.mark.asyncio
async def test_specific_mod_router_degrades_to_search_when_reviewer_fails():
    async def failing_reviewer(message, candidates):
        raise TimeoutError("review timed out")

    with _session() as session:
        _add_mod(session)
        result = await SpecificModQuestionRouter(session, reviewer=failing_reviewer).route(
            SpecificModRouteInput(message="Layer Bikini 的物理效果怎么样？")
        )

    assert result.route == "search"
    assert result.mod_id is None
    assert result.reason == "router_degraded:TimeoutError"
    assert result.candidate_count == 1


@pytest.mark.asyncio
async def test_specific_mod_router_uses_bounded_llm_timeout():
    seen = {}

    class FakeClient:
        async def chat(self, prompt, model, max_tokens=1024, request_timeout=None):
            seen["request_timeout"] = request_timeout
            return '{"route":"search","selected_mod_id":null,"confidence":0.2,"reason":"broad"}'

    with _session() as session:
        _add_mod(session)
        SettingsService(session).set("llm_api_key", "test-key")
        result = await SpecificModQuestionRouter(
            session,
            client_factory=lambda provider, api_key, base_url: FakeClient(),
        ).route(SpecificModRouteInput(message="Layer Bikini 的物理效果怎么样？"))

    assert result.route == "search"
    assert seen["request_timeout"] == SPECIFIC_MOD_ROUTER_TIMEOUT_SECONDS
