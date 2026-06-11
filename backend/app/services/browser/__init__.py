# 中文注释：标记 browser 包，保证后端模块可以按包路径导入。

from app.services.browser.page_fetcher import BrowserFetchResult, BrowserPageFetcher

__all__ = ["BrowserFetchResult", "BrowserPageFetcher"]
