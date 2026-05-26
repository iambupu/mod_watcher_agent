from app.services.agent.planning.context_plan_normalization import normalize_context_query_plan


class _Session:
    pass


def test_normalize_context_query_plan_returns_raw_without_session():
    raw = {"keywords": ["bimbo"], "_agent_context_signal": {"inherited": True}}

    assert normalize_context_query_plan(raw=raw, query="bimbo mod", constraints={}, session=None) is raw


def test_normalize_context_query_plan_preserves_context_signal(monkeypatch):
    raw = {"keywords": ["bimbo"], "_agent_context_signal": {"inherited": True}}

    monkeypatch.setattr(
        "app.services.agent.planning.context_plan_normalization.load_slot_options",
        lambda session: {"games": [], "sources": [], "categories": []},
    )

    def fake_normalize(plan, query, slot_options):
        return {"keywords": list(plan.get("keywords") or [])}

    monkeypatch.setattr(
        "app.services.agent.planning.context_plan_normalization.normalize_query_plan",
        fake_normalize,
    )

    normalized = normalize_context_query_plan(
        raw=raw,
        query="bimbo mod",
        constraints={},
        session=_Session(),
    )

    assert normalized["_agent_context_signal"] == {"inherited": True}


def test_normalize_context_query_plan_replaces_context_game_when_query_has_new_game(monkeypatch):
    raw = {"keywords": ["vehicle"], "games": ["Skyrim Special Edition"]}

    monkeypatch.setattr(
        "app.services.agent.planning.context_plan_normalization.load_slot_options",
        lambda session: {"games": [], "sources": [], "categories": []},
    )
    monkeypatch.setattr(
        "app.services.agent.planning.context_plan_normalization.build_fallback_query_plan",
        lambda query: {"keywords": ["cyberpunk"], "games": ["Cyberpunk 2077"]},
    )

    def fake_normalize(plan, query, slot_options):
        return dict(plan)

    monkeypatch.setattr(
        "app.services.agent.planning.context_plan_normalization.normalize_query_plan",
        fake_normalize,
    )

    normalized = normalize_context_query_plan(
        raw=raw,
        query="cyberpunk vehicle mod",
        constraints={"game": "Skyrim Special Edition"},
        session=_Session(),
    )

    assert normalized["games"] == ["Cyberpunk 2077"]


def test_normalize_context_query_plan_returns_raw_on_normalization_error(monkeypatch):
    raw = {"keywords": ["bimbo"]}

    def fail_load(session):
        raise RuntimeError("boom")

    monkeypatch.setattr(
        "app.services.agent.planning.context_plan_normalization.load_slot_options",
        fail_load,
    )

    assert normalize_context_query_plan(raw=raw, query="bimbo", constraints={}, session=_Session()) is raw
