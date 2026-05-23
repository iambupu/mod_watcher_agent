from fastapi.testclient import TestClient

from app.api import routes_loverslab_browser
from app.main import app as fastapi_app
from app.services.browser import BrowserFetchResult


class _FakeFetcher:
    def __init__(self, result: BrowserFetchResult):
        self.result = result
        self.closed = False

    async def fetch_html(self, *args, **kwargs):
        return self.result

    async def open_login(self, *args, **kwargs):
        return self.result

    async def close_login(self):
        self.closed = True


def test_test_category_parses_items_without_real_browser(monkeypatch):
    html = """
    <html><body>
      <li class="ipsDataItem">
        <a href="/files/file/12345-sample-mod/">Sample Mod</a>
        <a href="/profile/1-author/">Author</a>
        <time datetime="2026-05-01T10:00:00Z">May 1</time>
      </li>
    </body></html>
    """
    fake = _FakeFetcher(
        BrowserFetchResult(
            url="https://www.loverslab.com/files/category/319-x-change-life/",
            final_url="https://www.loverslab.com/files/category/319-x-change-life/",
            title="Category",
            html=html,
            status="ok",
        )
    )
    monkeypatch.setattr(routes_loverslab_browser, "fetcher", fake)

    client = TestClient(fastapi_app)
    response = client.post(
        "/api/loverslab/browser/test-category",
        json={
            "url": "https://www.loverslab.com/files/category/319-x-change-life/",
            "gameLabel": "X-Change Life",
            "maxItems": 20,
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["itemsCount"] == 1
    assert data["items"][0]["fileId"] == "12345"
    assert data["items"][0]["title"] == "Sample Mod"


def test_test_category_rejects_non_loverslab_url():
    client = TestClient(fastapi_app)
    response = client.post(
        "/api/loverslab/browser/test-category",
        json={
            "url": "https://example.com/files/category/319-x-change-life/",
            "gameLabel": "X-Change Life",
            "maxItems": 20,
        },
    )

    assert response.status_code == 422


def test_test_category_rejects_disallowed_final_url(monkeypatch):
    fake = _FakeFetcher(
        BrowserFetchResult(
            url="https://www.loverslab.com/files/category/319-x-change-life/",
            final_url="https://example.com/files/category/319-x-change-life/",
            title="Category",
            html="<html><body>ok</body></html>",
            status="ok",
        )
    )
    monkeypatch.setattr(routes_loverslab_browser, "fetcher", fake)

    client = TestClient(fastapi_app)
    response = client.post(
        "/api/loverslab/browser/test-category",
        json={
            "url": "https://www.loverslab.com/files/category/319-x-change-life/",
            "gameLabel": "X-Change Life",
            "maxItems": 20,
        },
    )

    assert response.status_code == 422


def test_test_category_returns_structure_changed_for_empty_parse(monkeypatch):
    fake = _FakeFetcher(
        BrowserFetchResult(
            url="https://www.loverslab.com/files/category/319-x-change-life/",
            final_url="https://www.loverslab.com/files/category/319-x-change-life/",
            title="Category",
            html="<html><body>No file links</body></html>",
            status="ok",
        )
    )
    monkeypatch.setattr(routes_loverslab_browser, "fetcher", fake)

    client = TestClient(fastapi_app)
    response = client.post(
        "/api/loverslab/browser/test-category",
        json={
            "url": "https://www.loverslab.com/files/category/319-x-change-life/",
            "gameLabel": "X-Change Life",
            "maxItems": 20,
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "structure_changed"
    assert data["itemsCount"] == 0
    assert "no LoversLab file items" in data["error"]


def test_install_chromium_returns_install_result(monkeypatch):
    monkeypatch.setattr(
        routes_loverslab_browser.BrowserPageFetcher,
        "install_chromium",
        lambda: {
            "success": True,
            "status": "ok",
            "message": "Chromium installed",
            "stdout": "",
            "stderr": "",
        },
    )

    client = TestClient(fastapi_app)
    response = client.post("/api/loverslab/browser/install-chromium")

    assert response.status_code == 200
    assert response.json()["success"] is True


def test_install_chromium_returns_busy_when_install_lock_is_held(monkeypatch):
    class _LockedInstall:
        def acquire(self, blocking=True):
            return False

    monkeypatch.setattr(routes_loverslab_browser, "INSTALL_CHROMIUM_LOCK", _LockedInstall())

    client = TestClient(fastapi_app)
    response = client.post("/api/loverslab/browser/install-chromium")

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is False
    assert data["message"] == "Chromium install is already running."


def test_check_session_closes_login_browser_after_ok(monkeypatch):
    fake = _FakeFetcher(
        BrowserFetchResult(
            url="https://www.loverslab.com/files/",
            final_url="https://www.loverslab.com/files/",
            title="Files",
            html="<html><body>ok</body></html>",
            status="ok",
        )
    )
    monkeypatch.setattr(routes_loverslab_browser, "fetcher", fake)

    client = TestClient(fastapi_app)
    response = client.post("/api/loverslab/browser/check-session")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert fake.closed is True
