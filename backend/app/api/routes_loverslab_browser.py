from pathlib import Path
from threading import Lock
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from app.services.browser import BrowserPageFetcher
from app.services.loverslab.category_parser import parse_category_items
from app.services.loverslab.constants import LOVERSLAB_HOSTS

router = APIRouter(prefix="/api/loverslab/browser", tags=["loverslab-browser"])

fetcher = BrowserPageFetcher()
INSTALL_CHROMIUM_LOCK = Lock()


class TestCategoryRequest(BaseModel):
    url: str = Field(min_length=1)
    gameLabel: str = Field(default="LoversLab")
    maxItems: int = Field(default=20, ge=1, le=100)


class SaveSnapshotRequest(BaseModel):
    url: str = Field(min_length=1)
    profileName: str = Field(default="loverslab")


@router.get("/status")
def browser_status():
    """返回 LoversLab 浏览器 profile、Playwright 和浏览器安装状态。"""
    return BrowserPageFetcher.status_payload("loverslab")


@router.post("/install-chromium")
async def install_chromium():
    """串行触发 Playwright Chromium 安装，避免多个安装进程并发写目录。"""
    if not INSTALL_CHROMIUM_LOCK.acquire(blocking=False):
        return {
            "success": False,
            "status": "unknown_error",
            "message": "Chromium install is already running.",
            "stdout": "",
            "stderr": "",
        }
    try:
        return await run_in_threadpool(BrowserPageFetcher.install_chromium)
    finally:
        INSTALL_CHROMIUM_LOCK.release()


@router.post("/open-login")
async def open_login():
    """打开可见浏览器窗口，让用户完成 LoversLab 登录。"""
    result = await fetcher.open_login(profile_name="loverslab")
    return {
        "status": result.status,
        "url": result.url,
        "finalUrl": result.final_url,
        "title": result.title,
        "error": result.error,
    }


@router.post("/check-session")
async def check_session():
    """访问 LoversLab 文件页检查当前 profile 是否已登录且可用。"""
    result = await fetcher.fetch_html(
        "https://www.loverslab.com/files/",
        profile_name="loverslab",
        headless=False,
        timeout_ms=60000,
    )
    if result.status == "ok":
        await fetcher.close_login()
    return {
        "status": result.status,
        "url": result.url,
        "finalUrl": result.final_url,
        "title": result.title,
        "checkedAt": BrowserPageFetcher.now_iso(),
        "error": result.error,
    }


@router.post("/test-category")
async def test_category(body: TestCategoryRequest):
    """抓取并解析一个 LoversLab 分类页，用于设置页验证选择器是否仍可用。"""
    _require_loverslab_url(body.url)
    result = await fetcher.fetch_html(
        body.url,
        profile_name="loverslab",
        headless=False,
        timeout_ms=60000,
    )
    if result.status != "ok":
        return {
            "status": result.status,
            "title": result.title,
            "finalUrl": result.final_url,
            "itemsCount": 0,
            "items": [],
            "error": result.error,
        }
    _require_loverslab_url(result.final_url)

    items = parse_category_items(
        result.html,
        result.final_url or body.url,
        game_label=body.gameLabel,
        max_items=body.maxItems,
    )
    status = "ok" if items else "structure_changed"
    return {
        "status": status,
        "title": result.title,
        "finalUrl": result.final_url,
        "itemsCount": len(items),
        "error": None if items else "Page is reachable, but no LoversLab file items were parsed.",
        "items": [
            {
                "fileId": item.source_id,
                "title": item.name,
                "url": item.url,
                "author": item.author,
                "updatedAt": item.updated_at.isoformat() if item.updated_at else None,
                "thumbnailUrl": item.thumbnail_url,
                "summary": item.summary,
                "contentHash": (item.raw or {}).get("content_hash"),
            }
            for item in items
        ],
    }


@router.post("/save-snapshot")
async def save_snapshot(body: SaveSnapshotRequest):
    """保存当前 LoversLab 页面 HTML 快照，便于后续解析规则排查。"""
    _require_loverslab_url(body.url)
    result = await fetcher.fetch_html(
        body.url,
        profile_name=body.profileName,
        headless=False,
        timeout_ms=60000,
    )
    if result.status != "ok":
        raise HTTPException(status_code=502, detail=result.error or result.status)
    _require_loverslab_url(result.final_url)

    snapshot_dir = Path("data") / "snapshots" / "loverslab"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    filename = BrowserPageFetcher.now_iso().replace(":", "-").replace("+", "Z")
    path = snapshot_dir / f"{filename}.html"
    path.write_text(result.html, encoding="utf-8")
    return {
        "status": "ok",
        "path": str(path),
        "title": result.title,
        "finalUrl": result.final_url,
    }


def _require_loverslab_url(url: str) -> None:
    """只允许 HTTPS LoversLab URL，防止浏览器抓取接口访问任意站点。"""
    parsed = urlsplit((url or "").strip())
    if parsed.scheme != "https" or (parsed.hostname or "").lower() not in LOVERSLAB_HOSTS:
        raise HTTPException(status_code=422, detail="Only https LoversLab URLs are allowed")
