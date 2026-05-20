"""Tests for LoversLabPageAdapter single-source fetch/normalize pattern."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import ValidationError

from app.adapters.loverslab_page import LoversLabPageAdapter
from app.models.mod_item import ModItem

LISTING_HTML = """<!DOCTYPE html>
<html><body>
<ul class="ipsDataList">
    <li><a href="/files/file/12345-some-mod/">Mod One</a></li>
    <li><a href="/files/file/67890-another-mod/">Mod Two</a></li>
    <li><a href="https://www.loverslab.com/files/file/67890-another-mod/?tab=comments">Mod Two duplicate</a></li>
    <li><a href="https://example.com/files/file/99999-should-be-ignored/">Offsite</a></li>
</ul>
</body></html>"""

DETAIL_HTML = """<!DOCTYPE html>
<html lang="en">
<head><title>Test Mod - LoversLab</title></head>
<body>
    <article><div>
        <header>
            <h1 class="ipsType_pageTitle">Test Mod</h1>
            <div class="ipsType_light">
                By <a href="/profile/999-tester/">TestAuthor</a>,
                <time datetime="2025-06-01T12:00:00Z">June 1, 2025</time>
            </div>
        </header>
        <section><ul class="ipsDataList">
            <li><span data-role="version">1.2.3</span></li>
            <li><span data-role="downloads">500</span></li>
        </ul></section>
        <section>
            <div class="ipsType_richText" data-role="content">Full description here.</div>
        </section>
    </div></article>
</body></html>"""

SOURCE_CONFIG_JSON = (
    '{"gameLabel":"Skyrim SE","accessMode":"page",'
    '"pageUrls":["https://www.loverslab.com/files/category/110-skyrim/"],'
    '"maxItemsPerRun":5,"updateDetection":"published_time"}'
)


@pytest.fixture
def adapter():
    return LoversLabPageAdapter()


def _make_response(text, status=200):
    resp = AsyncMock()
    resp.text = text
    resp.status_code = status
    resp.raise_for_status = lambda: None
    return resp


class TestLoversLabPageAdapterV02:
    """Adapter tests: fetch via pageUrls + normalize to ModItem."""

    @pytest.mark.asyncio
    async def test_fetch_returns_mod_items(self, adapter):
        listing_resp = _make_response(LISTING_HTML)
        detail_resp = _make_response(DETAIL_HTML)
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=[listing_resp, detail_resp, detail_resp])

        with patch.object(adapter, "_get_client", return_value=mock_client):
            results = await adapter.fetch(SOURCE_CONFIG_JSON)

        assert len(results) == 2
        assert all(isinstance(r, ModItem) for r in results)
        assert results[0].source == "loverslab"
        assert results[0].source_id in ("12345", "67890")
        assert results[1].source_id in ("12345", "67890")

    @pytest.mark.asyncio
    async def test_normalize_maps_fields(self, adapter):
        raw = {
            "source": "loverslab",
            "external_id": "12345",
            "title": "Test Mod",
            "game": "Skyrim SE",
            "url": "https://www.loverslab.com/files/file/12345/",
            "original_summary": "A great mod.",
            "author": "AuthorName",
            "downloads": 1000,
            "endorsements": None,
            "likes": 42,
            "categories": ["Armor"],
            "tags": ["HDT"],
            "thumbnail_url": "https://example.com/thumb.jpg",
            "updated_at_remote": "2025-05-01T10:00:00Z",
            "adult_content": True,
        }

        item = adapter.normalize(raw)

        assert item.source_id == "12345"
        assert item.source == "loverslab"
        assert item.name == "Test Mod"
        assert item.game == "Skyrim SE"
        assert item.url == "https://www.loverslab.com/files/file/12345/"
        assert item.summary == "A great mod."
        assert item.author == "AuthorName"
        assert item.downloads == 1000
        assert item.endorsements == 0
        assert item.likes == 42
        assert item.categories == ["Armor"]
        assert item.tags == ["HDT"]
        assert item.thumbnail_url == "https://example.com/thumb.jpg"
        assert item.is_adult is True
        assert item.raw is raw

    @pytest.mark.asyncio
    async def test_default_values_applied(self, adapter):
        raw = {
            "external_id": "99999",
            "title": "Minimal Mod",
        }

        item = adapter.normalize(raw)

        assert item.source_id == "99999"
        assert item.source == "loverslab"
        assert item.name == "Minimal Mod"
        assert item.game == ""
        assert item.url == ""
        assert item.summary == ""
        assert item.author == ""
        assert item.downloads == 0
        assert item.endorsements == 0
        assert item.likes == 0
        assert item.categories == []
        assert item.tags == []
        assert item.thumbnail_url == ""
        assert item.updated_at is None
        assert item.is_adult is False

    @pytest.mark.asyncio
    async def test_source_config_parsed(self, adapter):
        listing_resp = _make_response(LISTING_HTML)
        detail_resp = _make_response(DETAIL_HTML)
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=[listing_resp, detail_resp, detail_resp])

        valid_json = '{"gameLabel":"Test","accessMode":"page","pageUrls":["https://www.loverslab.com/files/category/110-skyrim/"],"maxItemsPerRun":2,"updateDetection":"published_time"}'

        with patch.object(adapter, "_get_client", return_value=mock_client):
            results = await adapter.fetch(valid_json)

        assert mock_client.get.call_count >= 1
        listing_call = mock_client.get.call_args_list[0]
        assert listing_call[0][0] == "https://www.loverslab.com/files/category/110-skyrim/"
        assert len(results) == 2
        assert all(result.game == "Test" for result in results)

    @pytest.mark.asyncio
    async def test_empty_result_returns_empty_list(self, adapter):
        # Listing page with no file links
        empty_listing = "<html><body><ul></ul></body></html>"
        listing_resp = _make_response(empty_listing)
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=listing_resp)

        with patch.object(adapter, "_get_client", return_value=mock_client):
            results = await adapter.fetch(SOURCE_CONFIG_JSON)

        assert results == []

    @pytest.mark.asyncio
    async def test_cloudflare_challenge_on_listing_raises(self, adapter):
        cf_html = """<!doctype html><html><head><title>Just a moment...</title></head>
        <body>Enable JavaScript and cookies to continue<script>var x='__cf_chl_';</script>
        challenges.cloudflare.com</body></html>"""
        listing_resp = _make_response(cf_html)
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=listing_resp)

        with (
            patch.object(adapter, "_get_client", return_value=mock_client),
            pytest.raises(ValueError, match="Cloudflare challenge detected"),
        ):
            await adapter.fetch(SOURCE_CONFIG_JSON)

    def test_empty_page_urls_returns_empty(self, adapter):
        config_no_urls = (
            '{"gameLabel":"Test","accessMode":"page",'
            '"pageUrls":[],'
            '"maxItemsPerRun":10,"updateDetection":"published_time"}'
        )
        import asyncio
        with pytest.raises(ValidationError):
            asyncio.run(adapter.fetch(config_no_urls))

    def test_parse_listing_links_supports_base_file_url(self, adapter):
        html = "<html><body><p>No links</p></body></html>"
        ids = adapter._parse_listing_links(
            html,
            "https://www.loverslab.com/files/file/445566-sample-mod/",
        )
        assert ids == ["445566"]

    def test_normalize_parses_updated_at_to_datetime(self, adapter):
        raw = {
            "external_id": "101",
            "title": "Time Mod",
            "updated_at_remote": "Apr 29, 2026 16:30",
        }
        item = adapter.normalize(raw)
        assert item.updated_at == datetime(2026, 4, 29, 16, 30, tzinfo=UTC)
