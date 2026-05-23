from app.services.loverslab.category_parser import parse_category_items


def test_parse_category_items_extracts_stable_file_fields():
    html = """
    <html><body>
      <ol>
        <li class="ipsDataItem">
          <a class="ipsDataItem_title" href="/files/file/12345-sample-mod/">Sample Mod</a>
          <a href="/profile/77-author/">AuthorName</a>
          <time datetime="2026-05-01T10:30:00Z">May 1</time>
          <img src="/uploads/thumb.jpg" />
          <p>Short summary.</p>
        </li>
        <li><a href="https://example.com/files/file/99999-offsite/">Ignore</a></li>
      </ol>
    </body></html>
    """

    items = parse_category_items(
        html,
        "https://www.loverslab.com/files/category/319-x-change-life/",
        game_label="X-Change Life",
        max_items=20,
    )

    assert len(items) == 1
    item = items[0]
    assert item.source_id == "12345"
    assert item.source == "loverslab"
    assert item.name == "Sample Mod"
    assert item.game == "X-Change Life"
    assert item.author == "AuthorName"
    assert item.thumbnail_url == "https://www.loverslab.com/uploads/thumb.jpg"
    assert item.raw["content_hash"]
    assert item.raw["fetch_mode"] == "browser_html"
