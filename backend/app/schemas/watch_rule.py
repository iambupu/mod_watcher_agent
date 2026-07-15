from ipaddress import ip_address
from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator, model_validator

from app.rule_constants import (
    DEFAULT_RULE_INTERVAL_MINUTES,
    MAX_RULE_INTERVAL_MINUTES,
    MIN_RULE_INTERVAL_MINUTES,
)
from app.services.loverslab.constants import LOVERSLAB_HOSTS

# ---------------------------------------------------------------------------
# Platform-specific source configs
# ---------------------------------------------------------------------------


class NexusModsRuleConfig(BaseModel):
    gameDomainName: str = Field(description="NexusMods game domain name, e.g. skyrimspecialedition")
    gameName: str | None = Field(default=None, description="Human-readable game name")
    gameId: str | None = Field(default=None, description="NexusMods internal game ID")
    updatedSinceDays: int = Field(
        ge=1, le=365, description="Monitor mods updated within this many days"
    )
    queryMode: Literal["updated", "created"] | None = Field(
        default=None, description="Query by updated or created time; omit for all"
    )
    categoryNames: list[str] = Field(
        default_factory=list, description="NexusMods category names to include"
    )
    tags: list[str] = Field(default_factory=list, description="Tags to filter by")
    sortBy: Literal[
        "updatedAt_desc",
        "createdAt_desc",
        "downloads_desc",
        "endorsements_desc",
    ] = Field(default="updatedAt_desc", description="Sort order for NexusMods API query")


class LoversLabRuleConfig(BaseModel):
    gameLabel: str = Field(description="Game label, e.g. Skyrim SE / Fallout 4")
    feedUrls: list[str] = Field(default_factory=list, description="LoversLab RSS feed URLs")
    updatedSinceDays: int | None = Field(
        default=None, ge=1, le=365, description="Monitor within this many days"
    )
    maxItemsPerRun: int = Field(default=50, ge=1, le=100, description="Max items per RSS run")
    updateDetection: Literal[
        "published_time",
        "updated_time",
    ] = Field(default="published_time", description="How to detect updates")

    @field_validator("feedUrls")
    @classmethod
    def validate_loverslab_urls(cls, value: list[str]) -> list[str]:
        """校验 LoversLab 规则 URL 只能使用 https 官方域名。"""
        validated: list[str] = []
        for raw_url in value:
            url = (raw_url or "").strip()
            if not url:
                continue
            parsed = urlparse(url)
            if parsed.scheme != "https":
                raise ValueError("Only https URLs are allowed")
            host = (parsed.hostname or "").lower()
            if not host or host not in LOVERSLAB_HOSTS:
                raise ValueError("Only loverslab.com URLs are allowed")
            try:
                ip = ip_address(host)
            except ValueError:
                ip = None
            if ip and (ip.is_private or ip.is_loopback or ip.is_link_local):
                raise ValueError("Private or loopback hosts are not allowed")
            validated.append(url)
        return validated

    @model_validator(mode="after")
    def validate_feed_urls_present(self):
        """LoversLab 发现仅保留 RSS，因此必须提供至少一个 Feed URL。"""
        if not self.feedUrls:
            raise ValueError("feedUrls is required for LoversLab RSS discovery")
        return self


# ---------------------------------------------------------------------------
# Filter / notification sub-models
# ---------------------------------------------------------------------------


class LlmFilterConfig(BaseModel):
    enabled: bool = Field(default=False, description="Enable LLM-assisted filtering")
    prompt: str = Field(default="", description="LLM prompt for filtering")
    mode: Literal["assist_only", "must_pass"] = Field(
        default="assist_only", description="LLM filter mode"
    )
    minConfidence: float = Field(
        default=0.7, ge=0.0, le=1.0, description="Minimum confidence threshold"
    )


class CommonRuleFilters(BaseModel):
    includeKeywords: list[str] = Field(
        default_factory=list, description="Keywords that must appear"
    )
    excludeKeywords: list[str] = Field(
        default_factory=list, description="Keywords that trigger exclusion"
    )
    minDownloads: int | None = Field(default=None, ge=0, description="Minimum download count")
    minEndorsements: int | None = Field(
        default=None, ge=0, description="Minimum endorsement count (NexusMods)"
    )
    minLikes: int | None = Field(default=None, ge=0, description="Minimum likes (LoversLab)")
    updatedWithinDays: int | None = Field(
        default=None, ge=1, description="Local time-window filter in days"
    )
    adultPolicy: Literal["include", "exclude", "only"] = Field(
        default="include", description="Adult content policy"
    )
    missingMetricsPolicy: Literal["pass", "reject"] = Field(
        default="pass", description="Policy for items missing metrics"
    )
    llmFilter: LlmFilterConfig = Field(
        default_factory=LlmFilterConfig, description="Optional LLM filter configuration"
    )


class NotificationConfig(BaseModel):
    enabled: bool = Field(default=False, description="Enable notifications for this rule")
    mode: Literal["instant", "daily_digest", "weekly_digest"] = Field(
        default="daily_digest", description="Notification mode"
    )
    channels: list[str] = Field(
        default_factory=list,
        description="Notification channels (desktop, telegram, discord, email)",
    )


# ---------------------------------------------------------------------------
# API request / response models
# ---------------------------------------------------------------------------


class WatchRuleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100, description="Rule name")
    enabled: bool = Field(default=True, description="Whether the rule is active")
    intervalMinutes: int = Field(
        default=DEFAULT_RULE_INTERVAL_MINUTES,
        ge=MIN_RULE_INTERVAL_MINUTES,
        le=MAX_RULE_INTERVAL_MINUTES,
        description="Polling interval for this rule in minutes",
    )
    source: Literal["nexusmods", "loverslab"] = Field(description="Data source platform")
    sourceConfig: NexusModsRuleConfig | LoversLabRuleConfig = Field(
        description="Platform-specific config"
    )
    filters: CommonRuleFilters = Field(
        default_factory=CommonRuleFilters, description="Common filtering rules"
    )
    notification: NotificationConfig = Field(
        default_factory=NotificationConfig, description="Notification settings"
    )

    @model_validator(mode="after")
    def validate_source_config_matches_source(self):
        """创建规则时校验 source 和 sourceConfig 类型一致。"""
        _validate_source_config_pair(self.source, self.sourceConfig)
        return self


class WatchRuleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100, description="Rule name")
    enabled: bool | None = Field(default=None, description="Whether the rule is active")
    intervalMinutes: int | None = Field(
        default=None,
        ge=MIN_RULE_INTERVAL_MINUTES,
        le=MAX_RULE_INTERVAL_MINUTES,
        description="Polling interval for this rule in minutes",
    )
    source: Literal["nexusmods", "loverslab"] | None = Field(
        default=None, description="Data source platform"
    )
    sourceConfig: NexusModsRuleConfig | LoversLabRuleConfig | None = Field(
        default=None, description="Platform-specific config"
    )
    filters: CommonRuleFilters | None = Field(default=None, description="Common filtering rules")
    notification: NotificationConfig | None = Field(
        default=None, description="Notification settings"
    )

    @model_validator(mode="after")
    def validate_source_config_matches_source(self):
        """更新规则时仅在二者同时出现时校验类型一致。"""
        if self.source is not None and self.sourceConfig is not None:
            _validate_source_config_pair(self.source, self.sourceConfig)
        return self


def _validate_source_config_pair(
    source: Literal["nexusmods", "loverslab"],
    source_config: NexusModsRuleConfig | LoversLabRuleConfig,
) -> None:
    """防止 Nexus/LoversLab 规则配置被错配到另一个来源。"""
    if source == "nexusmods" and not isinstance(source_config, NexusModsRuleConfig):
        raise ValueError("sourceConfig must be NexusModsRuleConfig when source is nexusmods")
    if source == "loverslab" and not isinstance(source_config, LoversLabRuleConfig):
        raise ValueError("sourceConfig must be LoversLabRuleConfig when source is loverslab")


class WatchRuleRead(BaseModel):
    id: int
    name: str
    enabled: bool
    intervalMinutes: int = Field(
        default=DEFAULT_RULE_INTERVAL_MINUTES,
        ge=MIN_RULE_INTERVAL_MINUTES,
        le=MAX_RULE_INTERVAL_MINUTES,
        description="Polling interval for this rule in minutes",
    )
    source: Literal["nexusmods", "loverslab"]
    sourceConfig: NexusModsRuleConfig | LoversLabRuleConfig
    filters: CommonRuleFilters
    notification: NotificationConfig
    created_at: str
    updated_at: str

    model_config = {"from_attributes": True}


class RuleTestRequest(BaseModel):
    rule: WatchRuleCreate = Field(description="The rule configuration to test")
    dryRun: bool = Field(default=True, description="If true, do not persist results")


class RuleTestRejectedItem(BaseModel):
    source: str = Field(default="", description="Source platform")
    externalId: str = Field(default="", description="Source item id")
    title: str = Field(default="", description="Mod title")
    game: str = Field(default="", description="Game name")
    url: str = Field(default="", description="Mod URL")
    reason: str = Field(default="", description="Machine-readable rejection reason")
    stage: str = Field(default="", description="deterministic | llm | deduplicate")
    llmFeedback: str = Field(default="", description="Optional LLM feedback text")


class RuleTestResponse(BaseModel):
    scanned: int = Field(description="Number of items scanned")
    normalized: int = Field(description="Number of items after normalization")
    passedDeterministicFilters: int = Field(description="Items that passed deterministic filters")
    passedLlmFilters: int = Field(description="Items that passed LLM filters")
    rejectedReasons: dict[str, int] = Field(
        default_factory=dict, description="Counts grouped by rejection reason"
    )
    rejectedItems: list[RuleTestRejectedItem] = Field(
        default_factory=list, description="Rejected items with reasons"
    )
    items: list[dict] = Field(
        default_factory=list, description="Preview items that passed all filters"
    )
