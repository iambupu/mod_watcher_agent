from app.services.agent.planning.context_memory_selection import (
    backfill_query_context_for_planning,
    diagnosis_context_from_last_query,
    has_query_context_signal,
    history_context_for_diagnosis,
    select_effective_last_query_context,
)


class _HistoryItem:
    def __init__(self, role: str, text: str):
        self.role = role
        self.text = text


def test_select_effective_context_prefers_good_current_context_for_new_question():
    selected = select_effective_last_query_context(
        "Skyrim pregnancy gameplay mod",
        {"source": "current", "keywords": ["pregnancy"], "quality_score": 0.4},
        {
            "long_term": {
                "last_query_context": {
                    "keywords": ["bimbo"],
                    "semantic_anchors": ["roleplay"],
                    "quality_score": 0.9,
                }
            }
        },
    )

    assert selected["keywords"] == ["pregnancy"]
    assert selected["source"] == "current"


def test_select_effective_context_uses_long_term_when_short_context_is_weak_followup():
    selected = select_effective_last_query_context(
        "有什么相关风格的mod",
        {"source": "current", "keywords": [], "quality_score": 0.0},
        {
            "long_term": {
                "last_query_context": {
                    "keywords": ["bimbo"],
                    "semantic_anchors": ["roleplay"],
                    "quality_score": 0.82,
                }
            }
        },
    )

    assert selected["keywords"] == ["bimbo"]
    assert selected["source"] == "long_term_writeback"


def test_select_effective_context_tolerates_invalid_quality_scores():
    selected = select_effective_last_query_context(
        "有什么相关风格的mod",
        {"source": "current", "keywords": [], "quality_score": "bad"},
        {
            "long_term": {
                "last_query_context": {
                    "keywords": ["bimbo"],
                    "semantic_anchors": ["roleplay"],
                    "quality_score": "0.82",
                }
            }
        },
    )

    assert selected["source"] == "long_term_writeback"


def test_select_effective_context_does_not_use_long_term_for_strong_new_question():
    selected = select_effective_last_query_context(
        "换成 Skyrim 的正常服装 mod",
        {"source": "current", "keywords": [], "quality_score": 0.0},
        {
            "long_term": {
                "last_query_context": {
                    "keywords": ["bimbo", "pregnancy"],
                    "semantic_anchors": ["pregnancy"],
                    "quality_score": 0.9,
                }
            }
        },
    )

    assert selected["source"] == "current"
    assert selected["keywords"] == []


def test_current_context_is_not_treated_as_inheritable_query_context():
    assert (
        has_query_context_signal(
            {
                "source": "current",
                "keywords": ["skyrim", "outfit"],
                "game": "Skyrim",
                "category": "Outfit",
            },
            ["skyrim", "outfit"],
        )
        is False
    )


def test_backfill_query_context_uses_recent_user_history_for_followup():
    backfill = backfill_query_context_for_planning(
        query="继续找相关的",
        last_query_context={"source": "current", "keywords": [], "quality_score": 0.0},
        history=[
            _HistoryItem("user", "Skyrim Special Edition bimbo roleplay mod"),
            _HistoryItem("assistant", "ok"),
        ],
    )

    assert backfill.context["source"] == "history_backfill"
    assert "bimbo" in backfill.keywords
    assert backfill.context["game"] == "Skyrim Special Edition"


def test_history_context_recognizes_game_alias_from_recent_user_turn():
    context = history_context_for_diagnosis(
        [
            _HistoryItem("user", "天际有什么扮演 bimbo 的 MOD"),
            _HistoryItem("assistant", "ok"),
        ]
    )

    assert context["game"] == "Skyrim Special Edition"
    assert "bimbo" in context["keywords"]


def test_diagnosis_context_replaces_current_low_value_context_with_recent_user():
    keywords, slots = diagnosis_context_from_last_query(
        {"source": "current", "keywords": []},
        [_HistoryItem("user", "Skyrim bimbo mod")],
    )

    assert "bimbo" in keywords
    assert slots["source"] == "recent_user"
    assert slots["game"] == "Skyrim"


def test_history_context_skips_low_signal_followup_turns():
    context = history_context_for_diagnosis(
        [
            _HistoryItem("user", "Skyrim bimbo mod"),
            _HistoryItem("assistant", "ok"),
            _HistoryItem("user", "继续找相关的"),
        ]
    )

    assert context["keywords"] == ["skyrim", "bimbo"]
