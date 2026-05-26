from app.services.agent.planning.context_inheritance_application import merge_context_keywords


def test_merge_context_keywords_keeps_context_anchor_and_current_constraints():
    merged = merge_context_keywords(
        current_keywords=["curvy", "body", "mod"],
        context_keywords=["bimbo", "style", "mods"],
    )

    assert merged[:3] == ["bimbo", "curvy", "body"]
    assert "mod" not in merged
    assert "style" not in merged
