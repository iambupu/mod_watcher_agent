import json
from pathlib import Path
from uuid import uuid4

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.api.routes_agent import _apply_query_plan, _normalize_query_plan, _query_mods_with_plan
from app.models.mod import Mod
from app.models.summary import ModSummary
from app.services.agent.query_planner import build_fallback_query_plan, detect_query_intent


def _make_engine():
    return create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


def _alias_file(name: str) -> Path:
    root = Path("backend/.test_aliases")
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{name}-{uuid4().hex}.json"
    return path.resolve()


def _agent_mod(
    external_id: str,
    title: str,
    *,
    game: str = "Stellar Blade",
    source: str = "nexusmods",
    author: str = "Author",
    adult_content: bool = False,
    updated_at_remote: str = "2026-05-20T00:00:00",
    first_seen_at: str = "2026-05-20T00:00:00",
) -> Mod:
    return Mod(
        id=abs(hash(external_id)) % 100000,
        source=source,
        external_id=external_id,
        game=game,
        title=title,
        author=author,
        url=f"https://example.com/{external_id}",
        adult_content=adult_content,
        updated_at_remote=updated_at_remote,
        first_seen_at=first_seen_at,
        last_seen_at=first_seen_at,
    )


def test_chinese_game_alias_maps_to_database_game_and_does_not_remain_keyword(monkeypatch):
    alias_file = _alias_file("existing")
    alias_file.write_text(json.dumps({"aliases": {"剑星": ["Stellar Blade"]}}, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr("app.services.game_alias_service.settings.GAME_ALIAS_FILE", str(alias_file))
    slot_options = {
        "games": ["Skyrim Special Edition", "Stellar Blade"],
        "game_domains": [],
        "categories": [],
        "sources": ["nexusmods"],
    }

    try:
        plan = _normalize_query_plan(
            {"intent": "recent", "keywords": ["剑星"], "sort_field": "updated_at_remote"},
            "最近有什么剑星的成人 mod 更新吗",
            slot_options,
        )
    finally:
        alias_file.unlink(missing_ok=True)

    assert plan["games"] == ["Stellar Blade"]
    assert "剑星" not in plan["keywords"]


def test_agent_intent_does_not_treat_popular_or_recommendation_search_as_comparison():
    assert detect_query_intent("帮我找最近比较火的剑星成人服装 Mod") == "recent"
    assert detect_query_intent("recommend Skyrim Special Edition body mods") == "preference_summary"
    assert detect_query_intent("推荐更安全的 Skyrim Special Edition body mod") == "preference_summary"
    assert detect_query_intent("推荐更安全的替代品") == "alternative"
    assert detect_query_intent("这两个哪个更适合新手") == "comparison"
    assert detect_query_intent("Skyrim Special Edition utility mod no script extender requirement") == "search"


def test_apply_query_plan_fallback_filters_by_score_and_explicit_adult_constraint():
    clean = _agent_mod("clean", "XXTB Prototype Suit", adult_content=False)
    adult = _agent_mod("adult", "XXTB Adult Suit", adult_content=True)
    unrelated = _agent_mod("other", "Kawaii War Dress", adult_content=False)

    results = _apply_query_plan([clean, adult, unrelated], "XXTB 非成人 mod", None)

    assert [mod.external_id for _, mod in results] == ["clean"]


def test_apply_query_plan_recent_sorts_by_remote_update_then_first_seen():
    older = _agent_mod(
        "older",
        "Stellar Armor",
        updated_at_remote="2026-05-20T00:00:00",
        first_seen_at="2026-05-21T00:00:00",
    )
    newest_seen_later = _agent_mod(
        "newer-b",
        "Stellar Armor B",
        updated_at_remote="2026-05-22T00:00:00",
        first_seen_at="2026-05-22T02:00:00",
    )
    newest_seen_earlier = _agent_mod(
        "newer-a",
        "Stellar Armor A",
        updated_at_remote="2026-05-22T00:00:00",
        first_seen_at="2026-05-22T01:00:00",
    )

    results = _apply_query_plan(
        [older, newest_seen_earlier, newest_seen_later],
        "最近有什么 mod 更新",
        {"intent": "recent", "limit": 8},
    )

    assert [mod.external_id for _, mod in results] == ["newer-b", "newer-a", "older"]


def test_apply_query_plan_explicit_constraints_return_empty_without_match():
    unrelated = _agent_mod("skyrim", "Skyrim Armor", game="Skyrim Special Edition")

    results = _apply_query_plan(
        [unrelated],
        "Stellar Blade armor",
        {"intent": "search", "game": "Stellar Blade", "keywords": ["armor"], "limit": 8},
    )

    assert results == []


def test_apply_query_plan_keywords_match_extra_text_and_increase_score():
    plain = _agent_mod("plain", "Generic Outfit")
    translated = _agent_mod("translated", "Generic Dress")

    results = _apply_query_plan(
        [plain, translated],
        "玻尿酸",
        {"intent": "search", "keywords": ["玻尿酸"], "limit": 8},
        extra_text_by_mod={translated.id or 0: "玻尿酸化面部网格"},
    )

    assert [mod.external_id for _, mod in results] == ["translated"]


def test_agent_scope_constraints_override_source_game_domain_and_sort():
    slot_options = {
        "games": ["Skyrim Special Edition"],
        "game_domains": ["skyrimspecialedition"],
        "categories": [],
        "sources": ["nexusmods", "loverslab"],
    }

    plan = _normalize_query_plan(
        {"intent": "recent", "keywords": ["armor"]},
        "最近更新的护甲 Mod\n\n[scope]\nsource=nexusmods\ngame=skyrimspecialedition\nsort_field=downloads",
        slot_options,
    )

    assert plan["sources"] == ["nexusmods"]
    assert plan["game_domains"] == ["skyrimspecialedition"]
    assert plan["sort_field"] == "downloads"


def test_agent_infers_natural_language_source_include_and_exclude():
    slot_options = {
        "games": ["Skyrim Special Edition"],
        "game_domains": ["skyrimspecialedition"],
        "categories": [],
        "sources": ["nexusmods", "loverslab"],
    }

    include_plan = _normalize_query_plan(
        {"intent": "search", "keywords": ["bimbo"], "sources": ["nexusmods"], "excluded_sources": ["loverslab"]},
        "排除 LoversLab，只看 Nexus bimbo mod",
        slot_options,
    )
    exclude_plan = _normalize_query_plan(
        {"intent": "search", "keywords": ["bimbo"], "excluded_sources": ["loverslab"]},
        "不要 LoversLab 的 bimbo mod",
        slot_options,
    )

    assert include_plan["sources"] == ["nexusmods"]
    assert include_plan["excluded_sources"] == ["loverslab"]
    assert exclude_plan["sources"] == ["nexusmods"]
    assert exclude_plan["excluded_sources"] == ["loverslab"]


def test_agent_fallback_plan_infers_source_constraints_without_source_keywords():
    slot_options = {
        "games": ["Skyrim Special Edition"],
        "game_domains": ["skyrimspecialedition"],
        "categories": [],
        "sources": ["nexusmods", "loverslab"],
    }

    raw_plan = build_fallback_query_plan("排除 LoversLab，只看 Nexus bimbo mod")
    plan = _normalize_query_plan(raw_plan, "排除 LoversLab，只看 Nexus bimbo mod", slot_options)

    assert plan["keywords"] == ["bimbo"]
    assert plan["sources"] == ["nexusmods"]
    assert plan["excluded_sources"] == ["loverslab"]


def test_agent_source_aliases_are_shared_by_source_and_identity_inference():
    slot_options = {
        "games": [],
        "game_domains": [],
        "categories": [],
        "sources": ["nexusmods", "loverslab"],
    }

    source_plan = _normalize_query_plan(build_fallback_query_plan("只看 ll bimbo mod"), "只看 ll bimbo mod", slot_options)
    identity_plan = _normalize_query_plan(build_fallback_query_plan("ll file 48837"), "ll file 48837", slot_options)

    assert source_plan["sources"] == ["loverslab"]
    assert identity_plan["sources"] == ["loverslab"]
    assert identity_plan["external_id"] == "48837"


def test_agent_fallback_plan_infers_popularity_sort_without_sort_keywords():
    slot_options = {
        "games": ["Skyrim Special Edition"],
        "game_domains": ["skyrimspecialedition"],
        "categories": [],
        "sources": ["nexusmods", "loverslab"],
    }

    raw_plan = build_fallback_query_plan("下载最多的 Skyrim Special Edition bimbo mod")
    plan = _normalize_query_plan(raw_plan, "下载最多的 Skyrim Special Edition bimbo mod", slot_options)

    assert plan["keywords"] == ["bimbo"]
    assert plan["games"] == ["Skyrim Special Edition"]
    assert plan["sort_field"] == "downloads"
    assert plan["sort_order"] == "desc"


def test_agent_fallback_plan_infers_download_threshold_without_threshold_keywords():
    slot_options = {
        "games": ["Skyrim Special Edition"],
        "game_domains": ["skyrimspecialedition"],
        "categories": [],
        "sources": ["nexusmods", "loverslab"],
    }

    raw_plan = build_fallback_query_plan("Skyrim Special Edition bimbo mod 下载至少 1000")
    plan = _normalize_query_plan(raw_plan, "Skyrim Special Edition bimbo mod 下载至少 1000", slot_options)

    assert plan["keywords"] == ["bimbo"]
    assert plan["games"] == ["Skyrim Special Edition"]
    assert plan["min_downloads"] == 1000


def test_agent_fallback_plan_infers_explicit_time_window_without_time_keywords():
    slot_options = {
        "games": ["Skyrim Special Edition"],
        "game_domains": ["skyrimspecialedition"],
        "categories": [],
        "sources": ["nexusmods", "loverslab"],
    }

    raw_plan = build_fallback_query_plan("最近7天的 Skyrim Special Edition bimbo mod")
    plan = _normalize_query_plan(raw_plan, "最近7天的 Skyrim Special Edition bimbo mod", slot_options)

    assert plan["keywords"] == ["bimbo"]
    assert plan["games"] == ["Skyrim Special Edition"]
    assert plan["updated_since_days"] == 7
    assert plan["sort_field"] == "updated_at_remote"


def test_agent_fallback_plan_infers_absolute_updated_after_date_without_date_keywords():
    slot_options = {
        "games": ["Skyrim Special Edition"],
        "game_domains": ["skyrimspecialedition"],
        "categories": [],
        "sources": ["nexusmods", "loverslab"],
    }
    query = "2024\u5e74\u4ee5\u540e\u66f4\u65b0\u7684 Skyrim Special Edition body mod"

    raw_plan = build_fallback_query_plan(query)
    plan = _normalize_query_plan(raw_plan, query, slot_options)

    assert plan["games"] == ["Skyrim Special Edition"]
    assert plan["updated_after"] == "2024-01-01T00:00:00+00:00"
    assert "body" in plan["keywords"]
    assert "2024" not in plan["keywords"]
    assert "\u66f4\u65b0" not in plan["keywords"]


def test_agent_fallback_plan_infers_published_year_range_without_date_keywords():
    slot_options = {
        "games": ["Skyrim Special Edition"],
        "game_domains": ["skyrimspecialedition"],
        "categories": [],
        "sources": ["nexusmods", "loverslab"],
    }
    query = "2024\u5e74\u53d1\u5e03\u7684 Skyrim Special Edition body mod"

    raw_plan = build_fallback_query_plan(query)
    plan = _normalize_query_plan(raw_plan, query, slot_options)

    assert plan["games"] == ["Skyrim Special Edition"]
    assert plan["published_after"] == "2024-01-01T00:00:00+00:00"
    assert plan["published_before"] == "2024-12-31T23:59:59+00:00"
    assert "body" in plan["keywords"]
    assert "2024" not in plan["keywords"]
    assert "\u53d1\u5e03" not in plan["keywords"]


def test_agent_fallback_plan_infers_explicit_tag_filter_without_tag_keywords():
    slot_options = {
        "games": ["Skyrim Special Edition"],
        "game_domains": ["skyrimspecialedition"],
        "categories": [],
        "sources": ["nexusmods", "loverslab"],
    }

    raw_plan = build_fallback_query_plan("Skyrim Special Edition body mod with CBBE tag")
    plan = _normalize_query_plan(raw_plan, "Skyrim Special Edition body mod with CBBE tag", slot_options)

    assert plan["games"] == ["Skyrim Special Edition"]
    assert plan["tags"] == ["CBBE"]


def test_agent_fallback_plan_infers_chinese_explicit_tag_filter():
    slot_options = {
        "games": ["Skyrim Special Edition"],
        "game_domains": ["skyrimspecialedition"],
        "categories": [],
        "sources": ["nexusmods", "loverslab"],
    }
    query = "\u5e26 CBBE \u6807\u7b7e\u7684 Skyrim Special Edition body mod"

    raw_plan = build_fallback_query_plan(query)
    plan = _normalize_query_plan(raw_plan, query, slot_options)

    assert plan["games"] == ["Skyrim Special Edition"]
    assert plan["tags"] == ["CBBE"]


def test_agent_normalizer_does_not_trust_implicit_llm_tags_as_hard_filters():
    slot_options = {
        "games": ["Skyrim Special Edition"],
        "game_domains": ["skyrimspecialedition"],
        "categories": ["Gameplay"],
        "sources": ["nexusmods", "loverslab"],
    }
    query = "有什么在玩法上可以扮演bimbo的MOD"
    raw_plan = {
        "intent": "search",
        "keywords": ["bimbo"],
        "games": ["Skyrim Special Edition"],
        "categories": ["Gameplay"],
        "tags": ["bimbo"],
    }

    plan = _normalize_query_plan(raw_plan, query, slot_options)

    assert "tags" not in plan
    assert "bimbo" in plan["keywords"]


def test_agent_fallback_plan_infers_exact_title_from_named_query():
    slot_options = {
        "games": ["Skyrim Special Edition"],
        "game_domains": ["skyrimspecialedition"],
        "categories": [],
        "sources": ["nexusmods", "loverslab"],
    }

    raw_plan = build_fallback_query_plan('Skyrim Special Edition mod named "Bimbo Body Morph"')
    plan = _normalize_query_plan(raw_plan, 'Skyrim Special Edition mod named "Bimbo Body Morph"', slot_options)

    assert plan["games"] == ["Skyrim Special Edition"]
    assert plan["exact_title"] == "Bimbo Body Morph"


def test_agent_fallback_plan_infers_explicit_version_without_version_keywords():
    slot_options = {
        "games": ["Skyrim Special Edition"],
        "game_domains": ["skyrimspecialedition"],
        "categories": [],
        "sources": ["nexusmods", "loverslab"],
    }

    raw_plan = build_fallback_query_plan("Skyrim Special Edition bimbo preset version 1.2.0")
    plan = _normalize_query_plan(raw_plan, "Skyrim Special Edition bimbo preset version 1.2.0", slot_options)

    assert plan["games"] == ["Skyrim Special Edition"]
    assert plan["version"] == "1.2.0"
    assert "version" not in plan["keywords"]
    assert "1.2.0" not in plan["keywords"]


def test_agent_fallback_plan_infers_source_url_identity_without_url_keywords():
    slot_options = {
        "games": ["Skyrim Special Edition"],
        "game_domains": ["skyrimspecialedition"],
        "categories": [],
        "sources": ["nexusmods", "loverslab"],
    }
    query = "看看 https://www.nexusmods.com/skyrimspecialedition/mods/1001?tab=files"

    raw_plan = build_fallback_query_plan(query)
    plan = _normalize_query_plan(raw_plan, query, slot_options)

    assert plan["sources"] == ["nexusmods"]
    assert plan["external_id"] == "skyrimspecialedition:1001"
    assert plan["source_url"] == "https://www.nexusmods.com/skyrimspecialedition/mods/1001?tab=files"
    assert not any("nexusmods" in keyword or "1001" in keyword for keyword in plan["keywords"])


def test_agent_fallback_plan_canonicalizes_nexus_numeric_id_with_game_domain():
    slot_options = {
        "games": ["Skyrim Special Edition"],
        "game_domains": ["skyrimspecialedition"],
        "categories": [],
        "sources": ["nexusmods", "loverslab"],
    }
    query = "Nexus Skyrim Special Edition mod id 1001"

    raw_plan = build_fallback_query_plan(query)
    plan = _normalize_query_plan(raw_plan, query, slot_options)

    assert plan["sources"] == ["nexusmods"]
    assert plan["games"] == ["Skyrim Special Edition"]
    assert plan["external_id"] == "skyrimspecialedition:1001"
    assert not any(keyword in {"nexus", "1001"} for keyword in plan["keywords"])


def test_agent_fallback_plan_infers_loverslab_file_identity():
    slot_options = {
        "games": [],
        "game_domains": [],
        "categories": [],
        "sources": ["nexusmods", "loverslab"],
    }

    raw_plan = build_fallback_query_plan("LoversLab file 48837")
    plan = _normalize_query_plan(raw_plan, "LoversLab file 48837", slot_options)

    assert plan["sources"] == ["loverslab"]
    assert plan["external_id"] == "48837"
    assert not any(keyword in {"loverslab", "file", "48837"} for keyword in plan["keywords"])


def test_agent_fallback_plan_infers_requirement_terms_without_requirement_keywords():
    slot_options = {
        "games": ["Skyrim Special Edition"],
        "game_domains": ["skyrimspecialedition"],
        "categories": [],
        "sources": ["nexusmods", "loverslab"],
    }
    query = "需要 SKSE 前置的 Skyrim Special Edition utility mod"

    raw_plan = build_fallback_query_plan(query)
    plan = _normalize_query_plan(raw_plan, query, slot_options)

    assert plan["intent"] == "search"
    assert plan["games"] == ["Skyrim Special Edition"]
    assert plan["requirement_terms"] == ["SKSE"]
    assert "skse" not in plan["keywords"]
    assert "需要" not in plan["keywords"]


def test_agent_fallback_plan_infers_compatibility_terms_without_compatibility_keywords():
    slot_options = {
        "games": ["Skyrim Special Edition"],
        "game_domains": ["skyrimspecialedition"],
        "categories": [],
        "sources": ["nexusmods", "loverslab"],
    }
    query = "\u652f\u6301 AE \u7684 Skyrim Special Edition body mod"

    raw_plan = build_fallback_query_plan(query)
    plan = _normalize_query_plan(raw_plan, query, slot_options)

    assert plan["intent"] == "search"
    assert plan["games"] == ["Skyrim Special Edition"]
    assert plan["compatibility_terms"] == ["AE"]
    assert "ae" not in plan["keywords"]
    assert "\u652f\u6301" not in plan["keywords"]
    assert "body" in plan["keywords"]


def test_agent_fallback_plan_treats_gameplay_support_as_search_keyword_not_compatibility():
    slot_options = {
        "games": ["Skyrim Special Edition"],
        "game_domains": ["skyrimspecialedition"],
        "categories": [],
        "sources": ["nexusmods", "loverslab"],
    }
    query = "有什么mod支持怀孕玩法"

    raw_plan = build_fallback_query_plan(query)
    plan = _normalize_query_plan(raw_plan, query, slot_options)

    assert plan["intent"] == "search"
    assert plan.get("compatibility_terms", []) == []
    assert "怀孕" in plan["keywords"] or "pregnancy" in plan["keywords"]


def test_agent_normalize_plan_rejects_llm_gameplay_support_as_compatibility():
    slot_options = {
        "games": ["Skyrim Special Edition"],
        "game_domains": ["skyrimspecialedition"],
        "categories": [],
        "sources": ["nexusmods", "loverslab"],
    }
    query = "有什么mod支持怀孕玩法"

    plan = _normalize_query_plan(
        {"intent": "install_risk", "keywords": ["pregnancy"], "compatibility_terms": ["怀孕"]},
        query,
        slot_options,
    )

    assert plan["intent"] == "search"
    assert plan.get("compatibility_terms", []) == []
    assert "pregnancy" in plan["keywords"]


def test_agent_fallback_plan_keeps_explicit_risk_question_as_install_risk():
    assert build_fallback_query_plan("这个安装风险高吗，会不会有前置依赖冲突？")["intent"] == "install_risk"
    assert build_fallback_query_plan("SKSE 前置安装风险怎么样？")["intent"] == "install_risk"


def test_agent_fallback_plan_infers_summary_language_without_language_keywords():
    slot_options = {
        "games": ["Skyrim Special Edition"],
        "game_domains": ["skyrimspecialedition"],
        "categories": [],
        "sources": ["nexusmods", "loverslab"],
    }
    query = "\u6709\u4e2d\u6587\u6458\u8981\u7684 Skyrim Special Edition body mod"

    raw_plan = build_fallback_query_plan(query)
    plan = _normalize_query_plan(raw_plan, query, slot_options)

    assert plan["games"] == ["Skyrim Special Edition"]
    assert plan["summary_languages"] == ["zh-CN"]
    assert "body" in plan["keywords"]
    assert "\u4e2d\u6587" not in plan["keywords"]
    assert "\u6458\u8981" not in plan["keywords"]


def test_agent_fallback_plan_infers_author_without_author_keywords():
    slot_options = {
        "games": ["Skyrim Special Edition"],
        "game_domains": ["skyrimspecialedition"],
        "categories": [],
        "sources": ["nexusmods", "loverslab"],
    }

    raw_plan = build_fallback_query_plan("作者 Ousnius 的 Skyrim Special Edition body mod")
    plan = _normalize_query_plan(raw_plan, "作者 Ousnius 的 Skyrim Special Edition body mod", slot_options)

    assert plan["author"] == "Ousnius"
    assert plan["games"] == ["Skyrim Special Edition"]
    assert "ousnius" not in plan["keywords"]
    assert "作者" not in plan["keywords"]
    assert "body" in plan["keywords"]


def test_agent_fallback_plan_infers_excluded_content_keywords():
    slot_options = {
        "games": ["Skyrim Special Edition"],
        "game_domains": ["skyrimspecialedition"],
        "categories": ["Armor", "Body"],
        "sources": ["nexusmods", "loverslab"],
    }

    raw_plan = build_fallback_query_plan("Skyrim Special Edition body mod 不要 armor")
    plan = _normalize_query_plan(raw_plan, "Skyrim Special Edition body mod 不要 armor", slot_options)

    assert plan["games"] == ["Skyrim Special Edition"]
    assert "body" in plan["keywords"]
    assert "armor" not in plan["keywords"]
    assert "armor" in plan["excluded_keywords"]


def test_agent_fallback_plan_treats_negative_requirement_as_exclusion():
    slot_options = {
        "games": ["Skyrim Special Edition"],
        "game_domains": ["skyrimspecialedition"],
        "categories": [],
        "sources": ["nexusmods", "loverslab"],
    }
    query = "不需要 SKSE 前置的 Skyrim Special Edition utility mod"

    raw_plan = build_fallback_query_plan(query)
    plan = _normalize_query_plan(raw_plan, query, slot_options)

    assert plan["intent"] == "search"
    assert plan["games"] == ["Skyrim Special Edition"]
    assert "SKSE" not in plan.get("requirement_terms", [])
    assert "skse" not in plan["keywords"]
    assert "skse" in [keyword.lower() for keyword in plan["excluded_keywords"]]
    assert "utility" in plan["keywords"]


def test_agent_fallback_plan_treats_negative_compatibility_as_exclusion():
    slot_options = {
        "games": ["Skyrim Special Edition"],
        "game_domains": ["skyrimspecialedition"],
        "categories": [],
        "sources": ["nexusmods", "loverslab"],
    }
    query = "不支持 AE 的 Skyrim Special Edition body mod"

    raw_plan = build_fallback_query_plan(query)
    plan = _normalize_query_plan(raw_plan, query, slot_options)

    assert plan["intent"] == "search"
    assert plan["games"] == ["Skyrim Special Edition"]
    assert "AE" not in plan.get("compatibility_terms", [])
    assert "ae" not in plan["keywords"]
    assert "ae" in [keyword.lower() for keyword in plan["excluded_keywords"]]
    assert "body" in plan["keywords"]


def test_agent_fallback_plan_infers_views_and_likes_thresholds_without_metric_keywords():
    slot_options = {
        "games": ["Skyrim Special Edition"],
        "game_domains": ["skyrimspecialedition"],
        "categories": [],
        "sources": ["nexusmods", "loverslab"],
    }
    query = "\u6d4f\u89c8\u91cf\u81f3\u5c11 1000\u3001\u559c\u6b22\u6570\u81f3\u5c11 20 \u7684 Skyrim Special Edition body mod"

    raw_plan = build_fallback_query_plan(query)
    plan = _normalize_query_plan(raw_plan, query, slot_options)

    assert plan["min_views"] == 1000
    assert plan["min_likes"] == 20
    assert "body" in plan["keywords"]
    assert "1000" not in plan["keywords"]
    assert "20" not in plan["keywords"]
    assert "\u6d4f\u89c8\u91cf" not in plan["keywords"]
    assert "\u559c\u6b22\u6570" not in plan["keywords"]
    assert "Armor" not in plan["categories"]


def test_agent_ignores_llm_adult_guess_without_explicit_user_marker():
    slot_options = {
        "games": ["Stellar Blade"],
        "game_domains": [],
        "categories": [],
        "sources": ["nexusmods"],
    }

    plan = _normalize_query_plan(
        {"intent": "search", "keywords": ["XXTB"], "adult_content": True},
        "XXTB的mod\n\n[scope]\nsource=nexusmods\ngame=Stellar Blade",
        slot_options,
    )

    assert plan["adult_content"] is None


def test_agent_keeps_explicit_adult_marker():
    slot_options = {
        "games": ["Stellar Blade"],
        "game_domains": [],
        "categories": [],
        "sources": ["nexusmods"],
    }

    plan = _normalize_query_plan(
        {"intent": "search", "keywords": ["XXTB"], "adult_content": None},
        "XXTB的成人mod\n\n[scope]\nsource=nexusmods\ngame=Stellar Blade",
        slot_options,
    )

    assert plan["adult_content"] is True


def test_chinese_semantic_query_infers_existing_categories_and_keywords():
    slot_options = {
        "games": ["Skyrim Special Edition"],
        "game_domains": ["skyrimspecialedition"],
        "categories": ["Outfits", "Clothing and Accessories", "Body, Face, and Hair", "Gameplay", "Visuals and Graphics"],
        "sources": ["nexusmods", "loverslab"],
    }

    plan = _normalize_query_plan(
        {"intent": "search", "keywords": []},
        "只看女性服装",
        slot_options,
    )

    assert plan["categories"] == ["Outfits", "Clothing and Accessories"]
    assert plan["category_match_mode"] == "db_fuzzy"
    assert "female" in plan["keywords"]
    assert "outfit" in plan["keywords"]


def test_chinese_weapon_query_infers_existing_weapon_category():
    slot_options = {
        "games": ["Skyrim Special Edition"],
        "game_domains": ["skyrimspecialedition"],
        "categories": ["Weapons", "Armor", "Gameplay"],
        "sources": ["nexusmods", "loverslab"],
    }

    plan = _normalize_query_plan(
        {"intent": "search", "keywords": []},
        "Skyrim Special Edition \u6b66\u5668\u7c7b mod",
        slot_options,
    )

    assert plan["categories"] == ["Weapons"]
    assert "weapon" in plan["keywords"]


def test_semantic_query_filters_unrelated_llm_categories_against_db_values():
    slot_options = {
        "games": ["Skyrim Special Edition"],
        "game_domains": ["skyrimspecialedition"],
        "categories": ["Outfits", "Clothing and Accessories", "Skills and Leveling"],
        "sources": ["nexusmods", "loverslab"],
    }

    plan = _normalize_query_plan(
        {"intent": "search", "keywords": [], "categories": ["Outfits", "Skills and Leveling"]},
        "只看女性服装",
        slot_options,
    )

    assert plan["categories"] == ["Outfits", "Clothing and Accessories"]


def test_specific_keyword_query_drops_broad_llm_category_guess():
    slot_options = {
        "games": ["Skyrim Special Edition"],
        "game_domains": ["skyrimspecialedition"],
        "categories": ["Body, Face, and Hair", "NPC"],
        "sources": ["nexusmods", "loverslab"],
    }

    plan = _normalize_query_plan(
        {"intent": "search", "keywords": [], "categories": ["Body, Face, and Hair"]},
        "有什么和玻尿酸相关的mod",
        slot_options,
    )

    assert plan["categories"] == []
    assert "玻尿酸" in plan["keywords"]
    assert "botox" in plan["keywords"]


def test_db_fuzzy_category_query_returns_category_match_without_keyword_hit():
    engine = _make_engine()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        session.add_all(
            [
                Mod(
                    source="nexusmods",
                    external_id="outfit-1",
                    game="Stellar Blade",
                    category="Outfits",
                    title="Ocean String",
                    url="https://example.com/outfit",
                    updated_at_remote="2026-05-20T00:00:00",
                    first_seen_at="2026-05-20T00:00:00",
                    last_seen_at="2026-05-20T00:00:00",
                ),
                Mod(
                    source="nexusmods",
                    external_id="patch-1",
                    game="Stellar Blade",
                    category="Patches",
                    title="Patch Collection",
                    url="https://example.com/patch",
                    updated_at_remote="2026-05-20T00:00:00",
                    first_seen_at="2026-05-20T00:00:00",
                    last_seen_at="2026-05-20T00:00:00",
                ),
            ]
        )
        session.commit()
        slot_options = {
            "games": ["Stellar Blade"],
            "game_domains": [],
            "categories": ["Outfits", "Patches"],
            "sources": ["nexusmods"],
        }

        plan = _normalize_query_plan(
            {"intent": "search", "keywords": [], "sources": ["nexusmods"]},
            "只看女性服装",
            slot_options,
        )
        results = _query_mods_with_plan(session, "只看女性服装", plan)

    assert [mod.external_id for _, mod in results] == ["outfit-1"]


def test_agent_query_matches_translated_summary_text():
    engine = _make_engine()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        mod = Mod(
            source="loverslab",
            external_id="botox-1",
            game="skyrimspecialedition",
            title="Paradise Halls Enhanced - Botoxed",
            url="https://example.com/botoxed",
            original_summary="Botoxed face meshes and textures.",
            adult_content=True,
            updated_at_remote="2026-05-22T00:00:00",
            first_seen_at="2026-05-22T00:00:00",
            last_seen_at="2026-05-22T00:00:00",
        )
        other = Mod(
            source="nexusmods",
            external_id="face-1",
            game="Skyrim Special Edition",
            category="Body, Face, and Hair",
            title="Generic Face Preset",
            url="https://example.com/face",
            updated_at_remote="2026-05-22T00:00:00",
            first_seen_at="2026-05-22T00:00:00",
            last_seen_at="2026-05-22T00:00:00",
        )
        session.add_all([mod, other])
        session.commit()
        session.refresh(mod)
        session.add(
            ModSummary(
                mod_id=mod.id or 0,
                language="zh-CN",
                summary_type="brief",
                content="天堂大厅增强版-玻尿酸化，包含面部网格和纹理。",
                generated_at="2026-05-22T00:00:00",
            )
        )
        session.commit()
        slot_options = {
            "games": ["Skyrim Special Edition", "skyrimspecialedition"],
            "game_domains": [],
            "categories": ["Body, Face, and Hair"],
            "sources": ["nexusmods", "loverslab"],
        }

        plan = _normalize_query_plan(
            {"intent": "search", "keywords": []},
            "有什么和玻尿酸相关的mod",
            slot_options,
        )
        results = _query_mods_with_plan(session, "有什么和玻尿酸相关的mod", plan)

    assert [mod.external_id for _, mod in results] == ["botox-1"]


def test_llm_discovered_game_alias_is_persisted_and_used(monkeypatch):
    alias_file = _alias_file("learned")
    monkeypatch.setattr("app.services.game_alias_service.settings.GAME_ALIAS_FILE", str(alias_file))
    slot_options = {
        "games": ["Skyrim Special Edition", "Stellar Blade"],
        "game_domains": [],
        "categories": [],
        "sources": ["nexusmods"],
    }

    try:
        plan = _normalize_query_plan(
            {
                "intent": "recent",
                "keywords": ["星刃"],
                "game_aliases": [{"alias": "星刃", "game": "Stellar Blade"}],
            },
            "最近有什么星刃 mod 更新吗",
            slot_options,
        )
        stored = json.loads(alias_file.read_text(encoding="utf-8"))
    finally:
        alias_file.unlink(missing_ok=True)

    assert stored["aliases"]["星刃"] == ["Stellar Blade"]
    assert plan["games"] == ["Stellar Blade"]
    assert "星刃" not in plan["keywords"]


def test_chinese_game_alias_query_returns_stellar_blade_mods(monkeypatch):
    alias_file = _alias_file("query")
    alias_file.write_text(json.dumps({"aliases": {"剑星": ["Stellar Blade"]}}, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr("app.services.game_alias_service.settings.GAME_ALIAS_FILE", str(alias_file))
    engine = _make_engine()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        session.add_all(
            [
                Mod(
                    source="nexusmods",
                    external_id="stellar-1",
                    game="Stellar Blade",
                    title="Twinkie NSFW",
                    url="https://example.com/stellar",
                    adult_content=True,
                    updated_at_remote="2026-05-20T00:00:00",
                    first_seen_at="2026-05-20T00:00:00",
                    last_seen_at="2026-05-20T00:00:00",
                ),
                Mod(
                    source="nexusmods",
                    external_id="skyrim-1",
                    game="Skyrim Special Edition",
                    title="Skyrim NSFW",
                    url="https://example.com/skyrim",
                    adult_content=True,
                    updated_at_remote="2026-05-20T00:00:00",
                    first_seen_at="2026-05-20T00:00:00",
                    last_seen_at="2026-05-20T00:00:00",
                ),
            ]
        )
        session.commit()

        slot_options = {
            "games": ["Skyrim Special Edition", "Stellar Blade"],
            "game_domains": [],
            "categories": [],
            "sources": ["nexusmods"],
        }
        try:
            plan = _normalize_query_plan(
                {"intent": "recent", "keywords": ["剑星"], "adult_content": True, "sort_field": "updated_at_remote"},
                "最近有什么剑星的成人 mod 更新吗",
                slot_options,
            )
            results = _query_mods_with_plan(session, "最近有什么剑星的成人 mod 更新吗", plan)
        finally:
            alias_file.unlink(missing_ok=True)

    assert [mod.game for _, mod in results] == ["Stellar Blade"]


def test_agent_fallback_plan_infers_thumbnail_filter_without_media_keywords():
    plan = build_fallback_query_plan(
        "\u6709\u9884\u89c8\u56fe\u7684 Skyrim Special Edition body mod"
    )

    assert plan["has_thumbnail"] is True
    assert "body" in [keyword.lower() for keyword in plan["keywords"]]
    media_keywords = {"image", "images", "thumbnail", "preview", "\u9884\u89c8\u56fe", "\u56fe\u7247"}
    assert not media_keywords.intersection({keyword.lower() for keyword in plan["keywords"]})


def test_agent_fallback_plan_infers_negative_thumbnail_filter():
    plan = build_fallback_query_plan("\u65e0\u56fe Skyrim Special Edition body mod")

    assert plan["has_thumbnail"] is False
    assert "body" in [keyword.lower() for keyword in plan["keywords"]]
