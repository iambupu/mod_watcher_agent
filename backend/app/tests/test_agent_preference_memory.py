from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

import app.models  # noqa: F401
from app.models.agent_message import AgentMessage
from app.models.favorite import Favorite
from app.models.mod import Mod
from app.services.agent.memory.favorite_preference_summarizer import summarize_favorite_preferences
from app.services.agent.memory.preference_service import AgentPreferenceService
from app.services.agent.memory.profile_refresh_service import (
    refresh_agent_preferences,
    summarize_conversation_preferences,
)


def _session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def _add_favorite(session: Session, index: int, **kwargs) -> None:
    defaults = {
        "source": "nexusmods",
        "external_id": str(index),
        "game": "Stellar Blade",
        "category": "Outfits",
        "title": f"Outfit {index}",
        "url": f"https://example.com/{index}",
        "first_seen_at": "2025-01-01T00:00:00",
        "last_seen_at": "2025-01-01T00:00:00",
        "adult_content": True,
    }
    defaults.update(kwargs)
    mod = Mod(**defaults)
    session.add(mod)
    session.commit()
    session.refresh(mod)
    session.add(
        Favorite(
            mod_id=mod.id,
            created_at="2025-01-01T00:00:00",
            updated_at="2025-01-01T00:00:00",
        )
    )
    session.commit()


def test_favorite_preference_summary_uses_deterministic_stats():
    with _session() as session:
        for index in range(1, 6):
            _add_favorite(session, index)
        _add_favorite(session, 6, source="loverslab", category="Visual", adult_content=False)

        summary = summarize_favorite_preferences(session)

    assert summary["top_games"] == ["Stellar Blade"]
    assert summary["top_sources"] == ["nexusmods", "loverslab"]
    assert summary["top_categories"] == ["Outfits", "Visual"]
    assert summary["adult_content_count"] == 5
    assert summary["adult_content_allowed"] is True
    assert "Stellar Blade" in summary["summary"]


def test_preference_service_persists_last_query_context_and_favorite_summary():
    with _session() as session:
        service = AgentPreferenceService(session)
        service.save_preferences(
            {
                "last_query_context": {"game": "Stellar Blade", "category": "Outfits"},
                "favorite_summary": {"top_games": ["Stellar Blade"]},
            }
        )

        loaded = service.load_preferences()

    assert loaded["last_query_context"]["game"] == "Stellar Blade"
    assert loaded["favorite_summary"]["top_games"] == ["Stellar Blade"]


def test_conversation_preference_summary_uses_recent_messages_and_matches():
    with _session() as session:
        outfit = Mod(
            source="nexusmods",
            external_id="100",
            game="Stellar Blade",
            game_domain="stellarblade",
            category="Outfits",
            title="Outfit",
            url="https://example.com/outfit",
            first_seen_at="2025-01-01T00:00:00",
            last_seen_at="2025-01-01T00:00:00",
            adult_content=True,
        )
        session.add(outfit)
        session.commit()
        session.add(
            AgentMessage(
                message_id="m1",
                role="user",
                text="推荐 Stellar Blade 的成人 outfits mod，优先 Nexus Mods",
                session_id="s1",
                created_at="2025-01-01T00:00:00",
                sort_index=0,
            )
        )
        session.add(
            AgentMessage(
                message_id="m2",
                role="assistant",
                text="找到一个候选。",
                session_id="s1",
                created_at="2025-01-01T00:00:01",
                matches_json='[{"id": 1, "title": "Outfit", "source": "nexusmods", "game": "Stellar Blade", "game_domain": "stellarblade", "category": "Outfits", "adult_content": true}]',
                sort_index=1,
            )
        )
        session.commit()

        summary = summarize_conversation_preferences(session)

    assert summary["top_games"][0] == "Stellar Blade"
    assert "nexusmods" in summary["top_sources"]
    assert summary["top_categories"][0] == "Outfits"
    assert summary["adult_content_preference"] is True
    assert summary["matched_mod_count"] == 1


def test_refresh_agent_preferences_combines_favorites_and_conversation():
    with _session() as session:
        _add_favorite(session, 1, game="Stellar Blade", category="Outfits")
        session.add(
            AgentMessage(
                message_id="m1",
                role="user",
                text="最近想看 Skyrim Special Edition immersion mod",
                session_id="s1",
                created_at="2025-01-01T00:00:00",
                sort_index=0,
            )
        )
        session.add(
            Mod(
                source="nexusmods",
                external_id="skyrim",
                game="Skyrim Special Edition",
                game_domain="skyrimspecialedition",
                category="Immersion",
                title="Immersion",
                url="https://example.com/skyrim",
                first_seen_at="2025-01-01T00:00:00",
                last_seen_at="2025-01-01T00:00:00",
            )
        )
        session.commit()

        result = refresh_agent_preferences(session)
        loaded = AgentPreferenceService(session).load_preferences()

    assert result["favorite_summary"]["top_games"] == ["Stellar Blade"]
    assert loaded["favorite_summary"]["top_categories"] == ["Outfits"]
    assert loaded["last_query_context"]["top_games"] == ["Skyrim Special Edition"]
    assert loaded["conversation_summary"]["top_categories"] == ["Immersion"]
