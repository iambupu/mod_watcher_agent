"""Tests for LoversLabFeedAdapter single-source mode."""

from unittest.mock import patch

import pytest

from app.adapters.loverslab_feed import LoversLabFeedAdapter, feedparser
from app.models.mod_item import ModItem
from app.schemas.watch_rule import LoversLabRuleConfig


def _make_valid_source_config_json(*, feed_urls=None):
    """Build a valid LoversLabRuleConfig JSON string for tests."""
    config = LoversLabRuleConfig(
        gameLabel="Skyrim SE",
        accessMode="rss",
        feedUrls=feed_urls or ["https://www.loverslab.com/files/rss/1-skyrim-se.xml/"],
    )
    return config.model_dump_json()


def _make_mock_feed(entries):
    """Build a mock feedparser parse result with given entries."""

    class MockFeed:
        def __init__(self, entries_list):
            self.entries = entries_list

    return MockFeed(entries)


def _make_feed_entry(
    link="/files/file/12345-test-mod/",
    title="Test Mod",
    summary="A test mod description.",
    author="TestAuthor",
    tag_term="Skyrim",
):
    """Build a minimal mock feedparser entry dict."""
    return {
        "link": link,
        "title": title,
        "summary": summary,
        "author": author,
        "tags": [{"term": tag_term}],
        "media_thumbnail": [{"url": "https://example.com/thumb.jpg"}],
    }


class TestLoversLabFeedAdapterV2:
    """Single-source mode tests for LoversLabFeedAdapter."""

    # ------------------------------------------------------------------
    # 1. test_fetch_returns_mod_items
    # ------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_fetch_returns_mod_items(self):
        adapter = LoversLabFeedAdapter()
        config_json = _make_valid_source_config_json()
        entry = _make_feed_entry()
        mock_feed = _make_mock_feed([entry])

        with patch.object(feedparser, "parse", return_value=mock_feed):
            results = await adapter.fetch(config_json)

        assert isinstance(results, list)
        assert len(results) == 1
        assert isinstance(results[0], ModItem)
        assert results[0].source == "loverslab"
        assert results[0].source_id == "12345"
        assert results[0].name == "Test Mod"

    # ------------------------------------------------------------------
    # 2. test_normalize_maps_fields
    # ------------------------------------------------------------------
    def test_normalize_maps_fields(self):
        adapter = LoversLabFeedAdapter()
        raw = {
            "external_id": "99999",
            "source": "loverslab",
            "title": "Cool Mod",
            "game": "Skyrim SE",
            "url": "https://example.com/mod/99999",
            "original_summary": "Best mod ever.",
            "author": "AuthorX",
            "downloads": 500,
            "endorsements": 10,
            "likes": 25,
            "categories": ["armor"],
            "tags": ["cool"],
            "thumbnail_url": "https://img.example.com/thumb.png",
            "updated_at_remote": "2025-06-01T12:00:00+00:00",
            "adult_content": True,
        }

        result = adapter.normalize(raw)

        assert isinstance(result, ModItem)
        assert result.source_id == "99999"
        assert result.source == "loverslab"
        assert result.name == "Cool Mod"
        assert result.game == "Skyrim SE"
        assert result.url == "https://example.com/mod/99999"
        assert result.summary == "Best mod ever."
        assert result.author == "AuthorX"
        assert result.downloads == 500
        assert result.endorsements == 10
        assert result.likes == 25
        assert result.categories == ["armor"]
        assert result.tags == ["cool"]
        assert result.thumbnail_url == "https://img.example.com/thumb.png"
        assert result.updated_at == "2025-06-01T12:00:00+00:00"
        assert result.is_adult is True
        assert result.raw is raw

    # ------------------------------------------------------------------
    # 3. test_default_values_applied
    # ------------------------------------------------------------------
    def test_default_values_applied(self):
        adapter = LoversLabFeedAdapter()
        raw = {
            "external_id": "42",
            "name": "Minimal Mod",
        }

        result = adapter.normalize(raw)

        assert result.source_id == "42"
        assert result.source == "loverslab"
        assert result.name == ""
        assert result.game == ""
        assert result.url == ""
        assert result.summary == ""
        assert result.author == ""
        assert result.downloads == 0
        assert result.endorsements == 0
        assert result.likes == 0
        assert result.categories == []
        assert result.tags == []
        assert result.thumbnail_url == ""
        assert result.updated_at is None
        assert result.is_adult is False

    # ------------------------------------------------------------------
    # 4. test_source_config_parsed
    # ------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_source_config_parsed(self):
        adapter = LoversLabFeedAdapter()
        config_json = _make_valid_source_config_json(
            feed_urls=[
                "https://www.loverslab.com/files/rss/1-skyrim-se.xml/",
                "https://www.loverslab.com/files/rss/2-fallout-4.xml/",
            ]
        )
        entry = _make_feed_entry()
        mock_feed = _make_mock_feed([entry])

        with patch.object(feedparser, "parse", return_value=mock_feed) as mock_parse:
            results = await adapter.fetch(config_json)

        assert len(results) == 2
        assert mock_parse.call_count == 2
        call_urls = [call_args[0][0] for call_args in mock_parse.call_args_list]
        assert "1-skyrim-se.xml" in call_urls[0]
        assert "2-fallout-4.xml" in call_urls[1]

    # ------------------------------------------------------------------
    # 5. test_empty_result_returns_empty_list
    # ------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_empty_result_returns_empty_list(self):
        adapter = LoversLabFeedAdapter()
        config_json = _make_valid_source_config_json()
        mock_feed = _make_mock_feed([])

        with patch.object(feedparser, "parse", return_value=mock_feed):
            results = await adapter.fetch(config_json)

        assert results == []

