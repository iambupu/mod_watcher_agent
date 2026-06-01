"""Tests for FilterService deterministic-first + LLM-post filtering."""

import json

import pytest
from sqlmodel import Session, SQLModel, create_engine

from app.models.mod import Mod
from app.schemas.watch_rule import CommonRuleFilters
from app.services.filter_service import FilterService


def _build_filters_json(**overrides):
    defaults = {
        "includeKeywords": [],
        "excludeKeywords": [],
        "minDownloads": None,
        "minEndorsements": None,
        "minLikes": None,
        "updatedWithinDays": None,
        "adultPolicy": "include",
        "missingMetricsPolicy": "pass",
        "llmFilter": {"enabled": False, "prompt": "", "mode": "assist_only", "minConfidence": 0.7},
    }
    defaults.update(overrides)
    return json.dumps(defaults)


class FakeRuleV2:
    def __init__(self, **kwargs):
        self.filters_json = _build_filters_json(**kwargs)


class FakeRawRule:
    def __init__(self, filters_json):
        self.filters_json = filters_json


_MOD_DEFAULTS = {
    "source": "nexusmods",
    "external_id": "1001",
    "title": "Test Mod",
    "original_summary": "A test mod description",
    "adult_content": False,
    "downloads": 100,
    "endorsements": 10,
    "likes": 5,
    "game": "skyrim",
    "url": "https://example.com",
}


def _make_mod(**kwargs):
    data = dict(_MOD_DEFAULTS)
    data.update(kwargs)
    return data


@pytest.fixture
def service():
    return FilterService()


@pytest.fixture(name="engine")
def engine_fixture():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
    )
    SQLModel.metadata.create_all(engine)
    yield engine


@pytest.fixture(name="session")
def session_fixture(engine):
    with Session(engine) as session:
        yield session


# ---------------------------------------------------------------------------
# Integration tests via apply_filters
# ---------------------------------------------------------------------------


class TestApplyFiltersV2:
    def test_invalid_stored_filters_fall_back_to_defaults(self, service, session):
        mods = [_make_mod(title="Unfiltered Mod")]

        result = service.apply_filters(FakeRawRule("[not-object]"), mods, session)

        assert result == mods
        assert service.stats == {"passed_deterministic": 1, "passed_llm": 1}

    def test_keyword_include(self, service, session):
        """includeKeywords: keep only mods matching at least one keyword."""
        rule = FakeRuleV2(includeKeywords=["sword"])
        mods = [
            _make_mod(external_id="1", title="Sword of Light"),
            _make_mod(external_id="2", title="Armor of Steel"),
        ]
        result = service.apply_filters(rule, mods, session)
        assert len(result) == 1
        assert result[0]["external_id"] == "1"

    def test_keyword_exclude(self, service, session):
        """excludeKeywords: drop mods containing any excluded keyword."""
        rule = FakeRuleV2(excludeKeywords=["cheat"])
        mods = [
            _make_mod(external_id="1", title="Cheat Sword"),
            _make_mod(external_id="2", title="Legit Sword"),
        ]
        result = service.apply_filters(rule, mods, session)
        assert len(result) == 1
        assert result[0]["external_id"] == "2"

    def test_min_downloads_filter(self, service, session):
        rule = FakeRuleV2(minDownloads=500)
        mods = [
            _make_mod(external_id="1", downloads=1000),
            _make_mod(external_id="2", downloads=200),
            _make_mod(external_id="3", downloads=None),
        ]
        result = service.apply_filters(rule, mods, session)
        assert len(result) == 1
        assert result[0]["external_id"] == "1"

    def test_min_metric_filters_tolerate_string_values(self, service, session):
        rule = FakeRuleV2(minDownloads=500, minEndorsements=20, minLikes=5)
        mods = [
            _make_mod(external_id="1", downloads="1000", endorsements="25", likes="6"),
            _make_mod(external_id="2", downloads="many", endorsements="25", likes="6"),
            _make_mod(external_id="3", downloads="1000", endorsements="-1", likes="6"),
            _make_mod(external_id="4", downloads="1000", endorsements="25", likes="unknown"),
        ]

        result = service.apply_filters(rule, mods, session)

        assert [item["external_id"] for item in result] == ["1"]

    def test_min_endorsements_filter(self, service, session):
        rule = FakeRuleV2(minEndorsements=20)
        mods = [
            _make_mod(external_id="1", endorsements=50),
            _make_mod(external_id="2", endorsements=5),
        ]
        result = service.apply_filters(rule, mods, session)
        assert len(result) == 1
        assert result[0]["external_id"] == "1"

    def test_adult_content_block(self, service, session):
        """adultPolicy='exclude' drops adult mods."""
        rule = FakeRuleV2(adultPolicy="exclude")
        mods = [
            _make_mod(external_id="1", title="Clean Mod", adult_content=False),
            _make_mod(external_id="2", title="Adult Mod", adult_content=True),
        ]
        result = service.apply_filters(rule, mods, session)
        assert len(result) == 1
        assert result[0]["external_id"] == "1"

    def test_adult_content_string_false_is_not_treated_as_adult(self, service, session):
        rule = FakeRuleV2(adultPolicy="exclude")
        mods = [
            _make_mod(external_id="1", title="String False Mod", adult_content="false"),
            _make_mod(external_id="2", title="String True Mod", adult_content="true"),
        ]

        result = service.apply_filters(rule, mods, session)

        assert [item["external_id"] for item in result] == ["1"]

    def test_adult_content_allow(self, service, session):
        """adultPolicy='include' keeps everything regardless of adult flag."""
        rule = FakeRuleV2(adultPolicy="include")
        mods = [
            _make_mod(external_id="1", title="Clean Mod", adult_content=False),
            _make_mod(external_id="2", title="Adult Mod", adult_content=True),
        ]
        result = service.apply_filters(rule, mods, session)
        assert len(result) == 2

    def test_llm_filter_assist_only(self, service, session):
        """LLM in assist_only mode: pass-through regardless of LLM verdict? No —
        assist_only means LLM result is advisory; mods still pass both
        deterministic AND LLM stages. Since we mock the LLM to approve all,
        everything should pass."""

        def llm_mock(mods, config):
            return mods

        svc = FilterService(llm_client=llm_mock)
        rule = FakeRuleV2(
            llmFilter={
                "enabled": True,
                "prompt": "test",
                "mode": "assist_only",
                "minConfidence": 0.5,
            },
        )
        mods = [
            _make_mod(external_id="1", title="Mod A"),
            _make_mod(external_id="2", title="Mod B"),
        ]
        result = svc.apply_filters(rule, mods, session)
        assert len(result) == 2

    def test_llm_filter_must_pass(self, service, session):
        """LLM in must_pass mode: mods rejected by LLM are dropped."""

        def reject_second(mods, config):
            return [m for m in mods if m["external_id"] != "2"]

        svc = FilterService(llm_client=reject_second)
        rule = FakeRuleV2(
            llmFilter={
                "enabled": True,
                "prompt": "test",
                "mode": "must_pass",
                "minConfidence": 0.5,
            },
        )
        mods = [
            _make_mod(external_id="1", title="Mod A"),
            _make_mod(external_id="2", title="Mod B"),
        ]
        result = svc.apply_filters(rule, mods, session)
        assert len(result) == 1
        assert result[0]["external_id"] == "1"

    def test_missing_metrics_pass(self, service, session):
        """missingMetricsPolicy='pass': mod with no metrics still passes."""
        rule = FakeRuleV2(
            missingMetricsPolicy="pass",
            minDownloads=100,
        )
        mods = [
            _make_mod(external_id="1", downloads=500),
            _make_mod(external_id="2", downloads=None, endorsements=None, likes=None),
        ]
        result = service.apply_filters(rule, mods, session)
        assert len(result) == 1
        assert result[0]["external_id"] == "1"

    def test_missing_metrics_reject(self, service, session):
        """missingMetricsPolicy='reject': mod with no metrics is dropped."""
        rule = FakeRuleV2(missingMetricsPolicy="reject")
        mods = [
            _make_mod(external_id="1", downloads=100, endorsements=10, likes=5),
            _make_mod(external_id="2", downloads=None, endorsements=None, likes=None),
        ]
        result = service.apply_filters(rule, mods, session)
        assert len(result) == 1
        assert result[0]["external_id"] == "1"

    def test_missing_metrics_reject_tolerates_string_values(self, service, session):
        rule = FakeRuleV2(missingMetricsPolicy="reject")
        mods = [
            _make_mod(external_id="1", downloads="0", endorsements="0", likes="0"),
            _make_mod(external_id="2", downloads="unknown", endorsements=None, likes=None),
            _make_mod(external_id="3", downloads="1", endorsements="0", likes="0"),
        ]

        result = service.apply_filters(rule, mods, session)

        assert [item["external_id"] for item in result] == ["3"]

    def test_no_filters_pass_all(self, service, session):
        """Default filters (all None/empty) pass every mod through."""
        rule = FakeRuleV2()
        mods = [
            _make_mod(external_id="1"),
            _make_mod(external_id="2"),
            _make_mod(external_id="3"),
        ]
        result = service.apply_filters(rule, mods, session)
        assert len(result) == 3

    def test_updated_within_days_passes_recent(self, service, session):
        rule = FakeRuleV2(updatedWithinDays=30)
        mods = [
            _make_mod(external_id="1", updated_at_remote="2026-05-10T00:00:00+00:00"),
            _make_mod(external_id="2", updated_at_remote="2020-01-01T00:00:00+00:00"),
        ]
        result = service.apply_filters(rule, mods, session)
        assert len(result) == 1
        assert result[0]["external_id"] == "1"

    def test_combined_filters(self, service, session):
        """Multiple deterministic filters together: includeKeywords + adultPolicy + minDownloads."""
        rule = FakeRuleV2(
            includeKeywords=["sword"],
            adultPolicy="exclude",
            minDownloads=300,
        )
        mods = [
            _make_mod(external_id="1", title="Sword of Power", adult_content=False, downloads=500),
            _make_mod(external_id="2", title="Sword of Flame", adult_content=True, downloads=500),
            _make_mod(external_id="3", title="Axe of Might", adult_content=False, downloads=500),
            _make_mod(external_id="4", title="Sword of Wind", adult_content=False, downloads=100),
        ]
        result = service.apply_filters(rule, mods, session)
        assert len(result) == 1
        assert result[0]["external_id"] == "1"


# ---------------------------------------------------------------------------
# Unit tests for internal helper methods
# ---------------------------------------------------------------------------


class TestKeywordFilter:
    def test_include_match(self, service):
        mod = _make_mod(title="Awesome Sword Mod")
        filters = CommonRuleFilters(includeKeywords=["sword"], excludeKeywords=[])
        assert service._get_deterministic_reject_reason(mod, filters) is None

    def test_include_no_match(self, service):
        mod = _make_mod(title="Awesome Armor Mod")
        filters = CommonRuleFilters(includeKeywords=["sword"], excludeKeywords=[])
        assert service._get_deterministic_reject_reason(mod, filters) == "include_keywords_mismatch"

    def test_exclude_match(self, service):
        mod = _make_mod(title="Cheat Sword Mod")
        filters = CommonRuleFilters(includeKeywords=[], excludeKeywords=["cheat"])
        assert service._get_deterministic_reject_reason(mod, filters) == "exclude_keywords_hit"

    def test_exclude_no_match(self, service):
        mod = _make_mod(title="Legit Sword Mod")
        filters = CommonRuleFilters(includeKeywords=[], excludeKeywords=["cheat"])
        assert service._get_deterministic_reject_reason(mod, filters) is None

    def test_empty_keywords_pass(self, service):
        mod = _make_mod(title="Anything")
        filters = CommonRuleFilters(includeKeywords=[], excludeKeywords=[])
        assert service._get_deterministic_reject_reason(mod, filters) is None


class TestAdultFilter:
    def test_include_passes_all(self, service):
        filters = CommonRuleFilters(adultPolicy="include")
        assert (
            service._get_deterministic_reject_reason(_make_mod(adult_content=True), filters) is None
        )
        assert (
            service._get_deterministic_reject_reason(_make_mod(adult_content=False), filters)
            is None
        )

    def test_exclude_blocks_adult(self, service):
        filters = CommonRuleFilters(adultPolicy="exclude")
        assert (
            service._get_deterministic_reject_reason(_make_mod(adult_content=True), filters)
            == "adult_content_excluded"
        )
        assert (
            service._get_deterministic_reject_reason(_make_mod(adult_content=False), filters)
            is None
        )

    def test_only_blocks_non_adult(self, service):
        filters = CommonRuleFilters(adultPolicy="only")
        assert (
            service._get_deterministic_reject_reason(_make_mod(adult_content=True), filters) is None
        )
        assert (
            service._get_deterministic_reject_reason(_make_mod(adult_content=False), filters)
            == "adult_content_only_not_met"
        )


class TestDeduplicate:
    def test_removes_existing_mods(self, service, session):
        existing = Mod(
            source="nexusmods",
            external_id="1001",
            game="skyrim",
            title="Existing Mod",
            url="https://example.com",
            first_seen_at="2025-01-01T00:00:00",
            last_seen_at="2025-01-01T00:00:00",
        )
        session.add(existing)
        session.commit()

        mods = [
            _make_mod(external_id="1001", title="Should Be Removed"),
            _make_mod(external_id="1002", title="New Mod"),
        ]
        result = service._deduplicate(mods, session)
        assert len(result) == 1
        assert result[0]["external_id"] == "1002"

    def test_empty_returns_empty(self, service, session):
        assert service._deduplicate([], session) == []

    def test_all_new_passes_through(self, service, session):
        mods = [_make_mod(external_id="2001"), _make_mod(external_id="2002")]
        result = service._deduplicate(mods, session)
        assert len(result) == 2

    def test_existing_mod_with_new_version_is_kept(self, service, session):
        existing = Mod(
            source="nexusmods",
            external_id="3001",
            game="skyrim",
            title="Existing Mod",
            url="https://example.com/3001",
            version="1.0.0",
            updated_at_remote="2025-01-01T00:00:00+00:00",
            first_seen_at="2025-01-01T00:00:00",
            last_seen_at="2025-01-01T00:00:00",
        )
        session.add(existing)
        session.commit()

        mods = [
            _make_mod(
                external_id="3001", version="1.1.0", updated_at_remote="2025-01-01T00:00:00+00:00"
            )
        ]
        result = service._deduplicate(mods, session)
        assert len(result) == 1
        assert result[0]["external_id"] == "3001"

    def test_existing_mod_with_new_updated_at_is_kept(self, service, session):
        existing = Mod(
            source="nexusmods",
            external_id="3002",
            game="skyrim",
            title="Existing Mod",
            url="https://example.com/3002",
            version="1.0.0",
            updated_at_remote="2025-01-01T00:00:00+00:00",
            first_seen_at="2025-01-01T00:00:00",
            last_seen_at="2025-01-01T00:00:00",
        )
        session.add(existing)
        session.commit()

        mods = [
            _make_mod(
                external_id="3002", version="1.0.0", updated_at_remote="2025-01-02T00:00:00+00:00"
            )
        ]
        result = service._deduplicate(mods, session)
        assert len(result) == 1
        assert result[0]["external_id"] == "3002"
