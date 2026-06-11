import hashlib
import re
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urljoin

from selectolax.parser import HTMLParser

from app.models.mod_item import ModItem
from app.services.loverslab.constants import LOVERSLAB_HOSTS
from app.services.loverslab.url_utils import extract_loverslab_file_id_from_url
from app.utils.time import parse_utc_datetime


def parse_category_items(
    html: str,
    base_url: str,
    *,
    game_label: str,
    max_items: int = 50,
) -> list[ModItem]:
    """从 LoversLab 分类页 HTML 中解析文件条目列表。"""
    tree = HTMLParser(html)
    items: list[ModItem] = []
    seen: set[str] = set()

    for link in tree.css('a[href*="/files/file/"]'):
        href = (link.attributes.get("href", "") or "").strip()
        url = urljoin(base_url, href)
        file_id = extract_file_id(url)
        if not file_id or file_id in seen:
            continue
        seen.add(file_id)

        container = _find_item_container(link)
        title = _extract_title(link)
        raw_text = _compact_text(container.text(separator=" ", strip=True) if container else link.text(strip=True))
        author = _extract_author(container)
        updated_at_text = _extract_time(container)
        updated_at = parse_datetime(updated_at_text)
        thumbnail_url = _extract_thumbnail(container, base_url)
        summary = _extract_summary(container, title, author)
        content_hash = hashlib.sha256(
            "|".join([file_id, title, raw_text, updated_at_text or ""]).encode("utf-8")
        ).hexdigest()

        raw = {
            "source": "loverslab",
            "external_id": file_id,
            "game": game_label,
            "title": title,
            "url": url,
            "author": author,
            "original_summary": summary,
            "updated_at_remote": updated_at_text,
            "thumbnail_url": thumbnail_url,
            "adult_content": True,
            "content_hash": content_hash,
            "category_url": base_url,
            "page_url": url,
            "raw_text": raw_text,
            "fetch_mode": "browser_html",
        }
        items.append(
            ModItem(
                source_id=file_id,
                source="loverslab",
                name=title,
                game=game_label,
                url=url,
                summary=summary,
                author=author,
                thumbnail_url=thumbnail_url,
                updated_at=updated_at,
                is_adult=True,
                raw=raw,
            )
        )
        if len(items) >= max_items:
            break

    return items


def extract_file_id(url: str) -> str | None:
    """从输入内容中提取目标字段。"""
    return extract_loverslab_file_id_from_url(url, LOVERSLAB_HOSTS)


def parse_datetime(value: str | None) -> datetime | None:
    """解析分类页上的更新时间文本。"""
    if not value:
        return None
    text = value.strip()
    parsed = parse_utc_datetime(text)
    if parsed is not None:
        return parsed
    for fmt in ("%b %d, %Y %H:%M", "%b %d, %Y", "%B %d, %Y %H:%M", "%B %d, %Y"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=UTC)
        except ValueError:
            continue
    return None


def _find_item_container(node: Any) -> Any:
    """从文件链接向上寻找包含作者、时间和摘要的列表项容器。"""
    current = node
    for _ in range(6):
        parent = current.parent
        if parent is None:
            return current
        classes = parent.attributes.get("class", "")
        if any(
            marker in classes
            for marker in (
                "ipsDataItem",
                "ipsStreamItem",
                "cFile",
                "ipsBox",
                "ipsComment",
            )
        ):
            return parent
        if parent.tag in {"li", "article", "tr"}:
            return parent
        current = parent
    return current


def _extract_title(link: Any) -> str:
    """从文件链接文本或 title 属性提取条目标题。"""
    text = link.text(separator=" ", strip=True)
    return _compact_text(text) or (link.attributes.get("title") or "").strip()


def _extract_author(container: Any | None) -> str:
    """从条目容器中的个人主页链接提取作者名。"""
    if container is None:
        return ""
    for selector in ('a[href*="/profile/"]', 'a[href*="/members/"]'):
        author = container.css_first(selector)
        if author:
            text = _compact_text(author.text(separator=" ", strip=True))
            if text:
                return text
    return ""


def _extract_time(container: Any | None) -> str | None:
    """从 time 节点或 datetime 属性提取远端更新时间文本。"""
    if container is None:
        return None
    for time_node in container.css("time, [datetime]"):
        value = time_node.attributes.get("datetime") or time_node.attributes.get("title")
        if value:
            return value.strip()
        text = _compact_text(time_node.text(separator=" ", strip=True))
        if text:
            return text
    return None


def _extract_thumbnail(container: Any | None, base_url: str) -> str:
    """从图片节点提取缩略图 URL，并补全相对地址。"""
    if container is None:
        return ""
    for img in container.css("img"):
        src = img.attributes.get("src") or img.attributes.get("data-src") or ""
        if not src and img.attributes.get("srcset"):
            src = img.attributes["srcset"].split(",")[0].strip().split(" ")[0]
        if src:
            return urljoin(base_url, src)
    return ""


def _extract_summary(container: Any | None, title: str, author: str) -> str:
    """从常见正文或元信息节点提取条目摘要。"""
    if container is None:
        return ""
    for selector in (".ipsType_richText", ".ipsDataItem_meta", ".ipsType_light", "p"):
        el = container.css_first(selector)
        if not el:
            continue
        text = _compact_text(el.text(separator=" ", strip=True))
        if text and text not in {title, author}:
            return text[:500]
    raw = _compact_text(container.text(separator=" ", strip=True))
    for part in (title, author):
        if part:
            raw = raw.replace(part, " ")
    return _compact_text(raw)[:500]


def _compact_text(value: str) -> str:
    """折叠 HTML 文本中的连续空白。"""
    return re.sub(r"\s+", " ", value or "").strip()
