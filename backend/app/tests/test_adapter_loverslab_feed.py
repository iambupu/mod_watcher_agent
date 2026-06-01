"""Tests for LoversLabFeedAdapter RSS mode."""

import time
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest

from app.adapters.loverslab_feed import LoversLabFeedAdapter, feedparser
from app.models.mod_item import ModItem
from app.schemas.watch_rule import LoversLabRuleConfig


def _make_valid_source_config_json(*, feed_urls=None, max_items=50, updated_since_days=None):
    config = LoversLabRuleConfig(
        gameLabel="Skyrim SE",
        accessMode="rss",
        feedUrls=feed_urls or ["https://www.loverslab.com/files/rss/1-skyrim-se.xml/"],
        maxItemsPerRun=max_items,
        updatedSinceDays=updated_since_days,
    )
    return config.model_dump_json()


def _make_mock_feed(entries):
    class MockFeed:
        def __init__(self, entries_list):
            self.entries = entries_list

    return MockFeed(entries)


def _make_feed_entry(
    *,
    link="/files/file/12345-test-mod/",
    title="Test Mod",
    summary="A <b>test</b> mod description.",
    author="TestAuthor",
    tag_term="Skyrim",
    updated_parsed=None,
    published_parsed=None,
    updated=None,
    published=None,
    entry_id=None,
):
    entry = {
        "link": link,
        "title": title,
        "summary": summary,
        "author": author,
        "tags": [{"term": tag_term}],
        "media_thumbnail": [{"url": "https://example.com/thumb.jpg"}],
    }
    if updated_parsed is not None:
        entry["updated_parsed"] = updated_parsed
    if published_parsed is not None:
        entry["published_parsed"] = published_parsed
    if updated is not None:
        entry["updated"] = updated
    if published is not None:
        entry["published"] = published
    if entry_id is not None:
        entry["id"] = entry_id
    return entry


class TestLoversLabFeedAdapterV2:
    @pytest.mark.asyncio
    async def test_fetch_returns_mod_items(self):
        adapter = LoversLabFeedAdapter()
        adapter._fetch_feed_bytes = AsyncMock(return_value=b"<rss/>")

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

    def test_normalize_maps_fields(self):
        adapter = LoversLabFeedAdapter()
        updated_dt = datetime(2025, 6, 1, 12, 0, tzinfo=UTC)
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
            "updated_at_remote": updated_dt,
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
        assert result.updated_at == updated_dt
        assert result.is_adult is True
        assert result.raw is raw

    def test_normalize_parses_string_adult_content(self):
        adapter = LoversLabFeedAdapter()
        raw = {
            "external_id": "99999",
            "title": "String Adult Flag",
            "adult_content": "false",
        }

        result = adapter.normalize(raw)

        assert result.is_adult is False

    @pytest.mark.asyncio
    async def test_source_config_parsed_calls_all_feed_urls(self):
        adapter = LoversLabFeedAdapter()
        adapter._fetch_feed_bytes = AsyncMock(return_value=b"<rss/>")

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

        assert len(results) == 1
        assert mock_parse.call_count == 2

    @pytest.mark.asyncio
    async def test_max_items_applied_after_sort(self):
        adapter = LoversLabFeedAdapter()
        adapter._fetch_feed_bytes = AsyncMock(return_value=b"<rss/>")
        now = time.gmtime()
        older = time.gmtime(time.time() - 86400)
        old = time.gmtime(time.time() - 172800)
        entries = [
            _make_feed_entry(link="/files/file/1-a/", title="A", updated_parsed=old),
            _make_feed_entry(link="/files/file/2-b/", title="B", updated_parsed=now),
            _make_feed_entry(link="/files/file/3-c/", title="C", updated_parsed=older),
        ]
        mock_feed = _make_mock_feed(entries)

        with patch.object(feedparser, "parse", return_value=mock_feed):
            results = await adapter.fetch(_make_valid_source_config_json(max_items=2))

        assert len(results) == 2
        assert [item.source_id for item in results] == ["2", "3"]

    @pytest.mark.asyncio
    async def test_single_feed_url_is_limited_to_20_entries(self):
        adapter = LoversLabFeedAdapter()
        adapter._fetch_feed_bytes = AsyncMock(return_value=b"<rss/>")
        now = time.gmtime()
        entries = [
            _make_feed_entry(link=f"/files/file/{1000 + i}-mod-{i}/", title=f"Mod {i}", updated_parsed=now)
            for i in range(25)
        ]
        mock_feed = _make_mock_feed(entries)

        with patch.object(feedparser, "parse", return_value=mock_feed):
            results = await adapter.fetch(_make_valid_source_config_json(max_items=100))

        assert len(results) == 20

    @pytest.mark.asyncio
    async def test_source_id_hash_fallback_is_stable(self):
        """Entries without a file link are now excluded (no hash fallback)."""
        adapter = LoversLabFeedAdapter()
        adapter._fetch_feed_bytes = AsyncMock(return_value=b"<rss/>")
        entry = _make_feed_entry(link="https://www.loverslab.com/mod/example")
        entry.pop("tags", None)
        mock_feed = _make_mock_feed([entry])

        with patch.object(feedparser, "parse", return_value=mock_feed):
            results = await adapter.fetch(_make_valid_source_config_json())

        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_summary_html_is_cleaned(self):
        adapter = LoversLabFeedAdapter()
        adapter._fetch_feed_bytes = AsyncMock(return_value=b"<rss/>")
        entry = _make_feed_entry(
            summary="<p>Hello <b>World</b></p><script>alert(1)</script>",
            published_parsed=time.gmtime(),
        )
        mock_feed = _make_mock_feed([entry])

        with patch.object(feedparser, "parse", return_value=mock_feed):
            results = await adapter.fetch(_make_valid_source_config_json())

        assert len(results) == 1
        assert "Hello World" in results[0].summary
        assert "alert(1)" not in results[0].summary
        assert isinstance(results[0].updated_at, datetime)

    @pytest.mark.asyncio
    async def test_string_feed_datetime_accepts_z_suffix(self):
        adapter = LoversLabFeedAdapter()
        adapter._fetch_feed_bytes = AsyncMock(return_value=b"<rss/>")
        entry = _make_feed_entry(updated="2026-05-01T10:30:00Z", published="2026-05-01T09:00:00Z")
        mock_feed = _make_mock_feed([entry])

        with patch.object(feedparser, "parse", return_value=mock_feed):
            results = await adapter.fetch(_make_valid_source_config_json())

        assert len(results) == 1
        assert results[0].updated_at == datetime(2026, 5, 1, 10, 30, tzinfo=UTC)
        assert results[0].raw["published_at_remote"] == "2026-05-01T09:00:00+00:00"

    @pytest.mark.asyncio
    async def test_invalid_feed_raises_value_error(self):
        adapter = LoversLabFeedAdapter()
        adapter._fetch_feed_bytes = AsyncMock(return_value=b"not-a-feed")

        class InvalidFeed:
            entries = []
            bozo = 1
            bozo_exception = ValueError("bad feed")

        with (
            patch.object(feedparser, "parse", return_value=InvalidFeed()),
            pytest.raises(ValueError, match="Invalid RSS/Atom feed"),
        ):
            await adapter.fetch(_make_valid_source_config_json())

    @pytest.mark.asyncio
    async def test_cloudflare_challenge_feed_raises_clear_error(self):
        adapter = LoversLabFeedAdapter()
        adapter._fetch_feed_bytes = AsyncMock(
            return_value=b"<html>Cloudflare challenge detected</html>"
        )

        with pytest.raises(ValueError, match="Cloudflare challenge detected"):
            await adapter.fetch(_make_valid_source_config_json())
