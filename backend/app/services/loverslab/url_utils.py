import re
from urllib.parse import urlsplit


def extract_loverslab_file_id_from_url(url: str, allowed_hosts: set[str] | None = None) -> str | None:
    """Extract LoversLab numeric file id from an absolute URL or /files/file path."""
    value = str(url or "").strip()
    parsed = urlsplit(value)
    host = (parsed.hostname or "").lower()
    if allowed_hosts is not None and host and host not in allowed_hosts:
        return None
    path = parsed.path or value
    matched = re.search(r"^/files/file/(\d+)(?:[-/]|$)", path, flags=re.IGNORECASE)
    return matched.group(1) if matched else None


def extract_loverslab_file_id_from_external_id(external_id: str) -> str:
    value = str(external_id or "").strip()
    matched = re.fullmatch(r"[a-z0-9][a-z0-9_-]*:(\d+)", value, flags=re.IGNORECASE)
    return matched.group(1) if matched else value
