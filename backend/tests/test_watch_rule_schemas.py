"""Tests for watch rule schemas.

Tests will fail until backend/app/schemas/watch_rule.py is rewritten with the
11 new Pydantic models.
"""

import pytest
from pydantic import ValidationError


class TestNexusModsRuleConfig:
    def test_valid_minimal_nexusmods_config(self):
        """Minimal valid NexusMods config: only required fields."""
        from app.schemas.watch_rule import NexusModsRuleConfig

        cfg = NexusModsRuleConfig(
            gameDomainName="skyrimspecialedition",
            updatedSinceDays=7,
        )
        assert cfg.gameDomainName == "skyrimspecialedition"
        assert cfg.updatedSinceDays == 7
        assert cfg.queryMode == "updated"
        assert cfg.sortBy == "updatedAt_desc"
        assert cfg.categoryNames == []
        assert cfg.tags == []

    def test_valid_full_nexusmods_config(self):
        """Full NexusMods config with all optional fields."""
        from app.schemas.watch_rule import NexusModsRuleConfig

        cfg = NexusModsRuleConfig(
            gameDomainName="skyrimspecialedition",
            gameName="Skyrim Special Edition",
            gameId="1704",
            updatedSinceDays=14,
            queryMode="created",
            sortBy="downloads_desc",
            categoryNames=["animation", "combat"],
            tags=["SKSE", "OAR"],
        )
        assert cfg.gameName == "Skyrim Special Edition"
        assert cfg.gameId == "1704"
        assert cfg.queryMode == "created"
        assert cfg.sortBy == "downloads_desc"
        assert cfg.categoryNames == ["animation", "combat"]
        assert cfg.tags == ["SKSE", "OAR"]

    def test_missing_required_field_raises(self):
        """gameDomainName is required — missing it should raise ValidationError."""
        from app.schemas.watch_rule import NexusModsRuleConfig

        with pytest.raises(ValidationError):
            NexusModsRuleConfig(updatedSinceDays=7)

    def test_invalid_query_mode_raises(self):
        """queryMode must be 'updated' or 'created'."""
        from app.schemas.watch_rule import NexusModsRuleConfig

        with pytest.raises(ValidationError):
            NexusModsRuleConfig(
                gameDomainName="skyrimspecialedition",
                updatedSinceDays=7,
                queryMode="bad_mode",
            )


class TestLoversLabRuleConfig:
    def test_valid_minimal_loverslab_config(self):
        """Minimal valid LoversLab config: only required field (gameLabel)."""
        from app.schemas.watch_rule import LoversLabRuleConfig

        cfg = LoversLabRuleConfig(
            accessMode="rss",
            gameLabel="Skyrim SE",
        )
        assert cfg.gameLabel == "Skyrim SE"
        assert cfg.accessMode == "rss"
        assert cfg.feedUrls == []
        assert cfg.pageUrls == []
        assert cfg.maxItemsPerRun == 50
        assert cfg.updateDetection == "published_time"

    def test_valid_full_loverslab_config(self):
        """Full LoversLab config with feed URLs and custom settings."""
        from app.schemas.watch_rule import LoversLabRuleConfig

        cfg = LoversLabRuleConfig(
            gameLabel="Fallout 4",
            accessMode="rss",
            feedUrls=["https://www.loverslab.com/forum/123-feed.xml"],
            maxItemsPerRun=30,
            updateDetection="updated_time",
        )
        assert cfg.gameLabel == "Fallout 4"
        assert cfg.accessMode == "rss"
        assert len(cfg.feedUrls) == 1
        assert cfg.maxItemsPerRun == 30
        assert cfg.updateDetection == "updated_time"

    def test_missing_game_label_raises(self):
        """gameLabel is required for LoversLab."""
        from app.schemas.watch_rule import LoversLabRuleConfig

        with pytest.raises(ValidationError):
            LoversLabRuleConfig(accessMode="rss")

    def test_missing_access_mode_raises(self):
        """accessMode is required for LoversLab."""
        from app.schemas.watch_rule import LoversLabRuleConfig

        with pytest.raises(ValidationError):
            LoversLabRuleConfig(gameLabel="Skyrim SE")


class TestLlmFilterConfig:
    def test_default_llm_filter(self):
        """Default LLM filter: disabled, empty prompt, assist_only."""
        from app.schemas.watch_rule import LlmFilterConfig

        cfg = LlmFilterConfig()
        assert cfg.enabled is False
        assert cfg.prompt == ""
        assert cfg.mode == "assist_only"
        assert cfg.minConfidence == 0.7

    def test_invalid_llm_mode_raises(self):
        """LLM filter mode must be 'assist_only' or 'must_pass'."""
        from app.schemas.watch_rule import LlmFilterConfig

        with pytest.raises(ValidationError):
            LlmFilterConfig(mode="force_pass")

    def test_valid_must_pass_llm_filter(self):
        """LLM filter with must_pass mode and custom confidence."""
        from app.schemas.watch_rule import LlmFilterConfig

        cfg = LlmFilterConfig(
            enabled=True,
            prompt="Only pass mods that add new animations.",
            mode="must_pass",
            minConfidence=0.85,
        )
        assert cfg.enabled is True
        assert cfg.prompt == "Only pass mods that add new animations."
        assert cfg.mode == "must_pass"
        assert cfg.minConfidence == 0.85


class TestCommonRuleFilters:
    def test_default_filters(self):
        """Default common filters: all lists empty, policies default."""
        from app.schemas.watch_rule import CommonRuleFilters

        f = CommonRuleFilters()
        assert f.includeKeywords == []
        assert f.excludeKeywords == []
        assert f.minDownloads is None
        assert f.minEndorsements is None
        assert f.minLikes is None
        assert f.updatedWithinDays is None
        assert f.adultPolicy == "include"
        assert f.missingMetricsPolicy == "pass"

    def test_full_filters(self):
        """Full common filters with keywords, metrics, and LLM filter."""
        from app.schemas.watch_rule import CommonRuleFilters, LlmFilterConfig

        f = CommonRuleFilters(
            includeKeywords=["animation", "combat"],
            excludeKeywords=["preset", "translation"],
            minDownloads=1000,
            minEndorsements=50,
            minLikes=10,
            updatedWithinDays=30,
            adultPolicy="exclude",
            missingMetricsPolicy="reject",
            llmFilter=LlmFilterConfig(enabled=True, mode="assist_only"),
        )
        assert f.includeKeywords == ["animation", "combat"]
        assert f.excludeKeywords == ["preset", "translation"]
        assert f.minDownloads == 1000
        assert f.adultPolicy == "exclude"
        assert f.missingMetricsPolicy == "reject"
        assert f.llmFilter.enabled is True

    def test_invalid_adult_policy_raises(self):
        """adultPolicy must be 'include', 'exclude', or 'only'."""
        from app.schemas.watch_rule import CommonRuleFilters

        with pytest.raises(ValidationError):
            CommonRuleFilters(adultPolicy="block_all")


class TestNotificationConfig:
    def test_default_notification(self):
        """Default notification: disabled, daily_digest, no channels."""
        from app.schemas.watch_rule import NotificationConfig

        cfg = NotificationConfig()
        assert cfg.enabled is False
        assert cfg.mode == "daily_digest"
        assert cfg.channels == []

    def test_enabled_with_channels(self):
        """Notification enabled with specific channels."""
        from app.schemas.watch_rule import NotificationConfig

        cfg = NotificationConfig(
            enabled=True,
            mode="instant",
            channels=["telegram", "discord"],
        )
        assert cfg.enabled is True
        assert cfg.mode == "instant"
        assert cfg.channels == ["telegram", "discord"]

    def test_invalid_notification_mode_raises(self):
        """mode must be 'instant', 'daily_digest', or 'weekly_digest'."""
        from app.schemas.watch_rule import NotificationConfig

        with pytest.raises(ValidationError):
            NotificationConfig(mode="hourly")


class TestWatchRuleCreate:
    def test_valid_nexusmods_rule_create(self):
        """Create a complete NexusMods watch rule."""
        from app.schemas.watch_rule import (
            WatchRuleCreate,
            NexusModsRuleConfig,
            CommonRuleFilters,
            NotificationConfig,
        )

        rule = WatchRuleCreate(
            name="Skyrim SE Animation Monitor",
            enabled=True,
            source="nexusmods",
            sourceConfig=NexusModsRuleConfig(
                gameDomainName="skyrimspecialedition",
                updatedSinceDays=7,
            ),
            filters=CommonRuleFilters(
                includeKeywords=["animation"],
                minDownloads=1000,
            ),
            notification=NotificationConfig(
                enabled=True,
                mode="daily_digest",
                channels=["telegram"],
            ),
        )
        assert rule.name == "Skyrim SE Animation Monitor"
        assert rule.source == "nexusmods"
        assert rule.enabled is True
        assert rule.sourceConfig.gameDomainName == "skyrimspecialedition"
        assert rule.filters.includeKeywords == ["animation"]
        assert rule.notification.enabled is True

    def test_valid_loverslab_rule_create(self):
        """Create a complete LoversLab watch rule."""
        from app.schemas.watch_rule import (
            WatchRuleCreate,
            LoversLabRuleConfig,
        )

        rule = WatchRuleCreate(
            name="LL Fallout Monitor",
            source="loverslab",
            sourceConfig=LoversLabRuleConfig(
                gameLabel="Fallout 4",
                accessMode="page",
                pageUrls=["https://www.loverslab.com/forum/123-list"],
            ),
        )
        assert rule.name == "LL Fallout Monitor"
        assert rule.source == "loverslab"
        assert rule.sourceConfig.gameLabel == "Fallout 4"

    def test_invalid_source_raises(self):
        """source must be 'nexusmods' or 'loverslab'."""
        from app.schemas.watch_rule import (
            WatchRuleCreate,
            NexusModsRuleConfig,
        )

        with pytest.raises(ValidationError):
            WatchRuleCreate(
                name="bad rule",
                source="steam",
                sourceConfig=NexusModsRuleConfig(
                    gameDomainName="skyrimspecialedition",
                    updatedSinceDays=7,
                ),
            )

    def test_missing_name_raises(self):
        """name is required for WatchRuleCreate."""
        from app.schemas.watch_rule import (
            WatchRuleCreate,
            NexusModsRuleConfig,
        )

        with pytest.raises(ValidationError):
            WatchRuleCreate(
                source="nexusmods",
                sourceConfig=NexusModsRuleConfig(
                    gameDomainName="skyrimspecialedition",
                    updatedSinceDays=7,
                ),
            )

    def test_missing_source_config_raises(self):
        """sourceConfig is required for WatchRuleCreate."""
        from app.schemas.watch_rule import WatchRuleCreate

        with pytest.raises(ValidationError):
            WatchRuleCreate(
                name="no config",
                source="nexusmods",
            )

    def test_defaults_on_create(self):
        """Default values for enabled, filters, notification on create."""
        from app.schemas.watch_rule import (
            WatchRuleCreate,
            NexusModsRuleConfig,
        )

        rule = WatchRuleCreate(
            name="Minimal Rule",
            source="nexusmods",
            sourceConfig=NexusModsRuleConfig(
                gameDomainName="skyrimspecialedition",
                updatedSinceDays=7,
            ),
        )
        assert rule.enabled is True
        assert rule.filters.adultPolicy == "include"
        assert rule.notification.mode == "daily_digest"


class TestWatchRuleUpdate:
    def test_partial_update_all_optional(self):
        """All fields in WatchRuleUpdate are Optional."""
        from app.schemas.watch_rule import WatchRuleUpdate

        # Empty update should be valid — all fields Optional
        update = WatchRuleUpdate()
        assert update.name is None
        assert update.enabled is None
        assert update.source is None
        assert update.sourceConfig is None
        assert update.filters is None
        assert update.notification is None

    def test_partial_update_name_only(self):
        """Update only the rule name."""
        from app.schemas.watch_rule import WatchRuleUpdate

        update = WatchRuleUpdate(name="Renamed Rule")
        assert update.name == "Renamed Rule"
        assert update.enabled is None


class TestWatchRuleRead:
    def test_read_from_attributes(self):
        """WatchRuleRead supports from_attributes for ORM mapping."""
        from app.schemas.watch_rule import WatchRuleRead

        # Verify model_config is set
        assert hasattr(WatchRuleRead, "model_config")
        assert WatchRuleRead.model_config.get("from_attributes") is True

    def test_read_fields(self):
        """WatchRuleRead has id, created_at, updated_at plus config fields."""
        from app.schemas.watch_rule import (
            WatchRuleRead,
            NexusModsRuleConfig,
            CommonRuleFilters,
            NotificationConfig,
        )

        data = {
            "id": 1,
            "name": "Test Rule",
            "enabled": True,
            "source": "nexusmods",
            "sourceConfig": {
                "gameDomainName": "skyrimspecialedition",
                "updatedSinceDays": 7,
            },
            "filters": {},
            "notification": {},
            "created_at": "2026-05-01T00:00:00Z",
            "updated_at": "2026-05-10T00:00:00Z",
        }
        rule = WatchRuleRead(**data)
        assert rule.id == 1
        assert rule.name == "Test Rule"
        assert rule.source == "nexusmods"
        assert rule.created_at == "2026-05-01T00:00:00Z"
        assert rule.updated_at == "2026-05-10T00:00:00Z"
        assert isinstance(rule.sourceConfig, NexusModsRuleConfig)
        assert isinstance(rule.filters, CommonRuleFilters)
        assert isinstance(rule.notification, NotificationConfig)


class TestRuleTestRequest:
    def test_rule_test_request(self):
        """RuleTestRequest wraps a rule with dryRun flag."""
        from app.schemas.watch_rule import (
            RuleTestRequest,
            WatchRuleCreate,
            NexusModsRuleConfig,
        )

        req = RuleTestRequest(
            rule=WatchRuleCreate(
                name="Test Rule",
                source="nexusmods",
                sourceConfig=NexusModsRuleConfig(
                    gameDomainName="skyrimspecialedition",
                    updatedSinceDays=7,
                ),
            ),
            dryRun=True,
        )
        assert req.dryRun is True
        assert req.rule.name == "Test Rule"
        assert req.rule.source == "nexusmods"

    def test_rule_test_request_dry_run_default(self):
        """dryRun defaults to True."""
        from app.schemas.watch_rule import (
            RuleTestRequest,
            WatchRuleCreate,
            NexusModsRuleConfig,
        )

        req = RuleTestRequest(
            rule=WatchRuleCreate(
                name="Test Rule",
                source="nexusmods",
                sourceConfig=NexusModsRuleConfig(
                    gameDomainName="skyrimspecialedition",
                    updatedSinceDays=7,
                ),
            ),
        )
        assert req.dryRun is True


class TestRuleTestResponse:
    def test_rule_test_response(self):
        """RuleTestResponse with full dry-run results."""
        from app.schemas.watch_rule import RuleTestResponse

        resp = RuleTestResponse(
            scanned=50,
            normalized=50,
            passedDeterministicFilters=12,
            passedLlmFilters=8,
            rejectedReasons={
                "keyword_not_match": 20,
                "metric_not_match": 10,
            },
            items=[
                {
                    "title": "Example Mod",
                    "source": "nexusmods",
                    "game": "Skyrim Special Edition",
                    "downloads": 12000,
                }
            ],
        )
        assert resp.scanned == 50
        assert resp.normalized == 50
        assert resp.passedDeterministicFilters == 12
        assert resp.passedLlmFilters == 8
        assert resp.rejectedReasons == {
            "keyword_not_match": 20,
            "metric_not_match": 10,
        }
        assert len(resp.items) == 1
        assert resp.items[0]["title"] == "Example Mod"


class TestBackwardCompatibility:
    """Ensure old class names are preserved for backward compatibility."""

    def test_old_class_names_exist(self):
        """WatchRuleCreate, WatchRuleUpdate, WatchRuleRead should still be importable."""
        from app.schemas.watch_rule import (
            WatchRuleCreate,
            WatchRuleUpdate,
            WatchRuleRead,
        )

        assert WatchRuleCreate is not None
        assert WatchRuleUpdate is not None
        assert WatchRuleRead is not None
