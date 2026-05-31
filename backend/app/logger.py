import logging
import logging.handlers
import os
import re
from collections import deque
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock

from app.config import settings

_SENSITIVE_PATTERNS = [
    (re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._\-]+\b"), "Bearer ********"),
    (re.compile(r"\b(?:sk|dsk)-[A-Za-z0-9_\-]{8,}\b"), "********"),
    (re.compile(r"([?&]key=)[^&\s]+", re.IGNORECASE), r"\1********"),
    (re.compile(r"(https://api\.telegram\.org/bot)[^/\s]+", re.IGNORECASE), r"\1********"),
    (
        re.compile(r"https://discord\.com/api/webhooks/[^\s\"']+", re.IGNORECASE),
        "https://discord.com/api/webhooks/********",
    ),
    (
        re.compile(r'(?i)\b(api_key|token|password)\b(\s*[:=]\s*)(["\']?)[^,"\'}\s]+(["\']?)'),
        r"\1\2\3********\4",
    ),
]

_QUIET_THIRD_PARTY_LOGGERS = ("alembic.",)
_FILE_LOG_PATTERN = re.compile(
    r"^\[(?P<timestamp>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]\s+"
    r"(?P<level>[A-Z]+)\s+"
    r"(?P<name>[^:\s]+)(?::\d+)?\s+-\s+"
    r"(?P<message>.*)$"
)
_SERVICE_LOG_PATTERN = re.compile(
    r"^(?P<level>DEBUG|INFO|WARNI(?:NG)?|ERROR|CRITI(?:CAL)?)\s+\[(?P<name>[^\]]+)\]\s+(?P<message>.*)$"
)
_PLAIN_LOG_PATTERN = re.compile(
    r"^(?P<level>DEBUG|INFO|WARNING|ERROR|CRITICAL):\s+(?P<message>.*)$"
)
_LOG_FILE_NAMES = ("mod_watcher.log", "backend_service.log")


def _resolve_log_dir() -> Path:
    configured = Path(str(settings.LOG_DIR or "log"))
    if configured.is_absolute():
        return configured
    # Resolve relative log dir from backend dir, not process cwd.
    backend_root = Path(__file__).resolve().parents[1]
    return (backend_root / configured).resolve()


def redact_sensitive_text(text: str) -> str:
    """处理当前模块的业务逻辑并返回结果。"""
    redacted = text
    for pattern, replacement in _SENSITIVE_PATTERNS:
        redacted = pattern.sub(replacement, redacted)
    return redacted


class SensitiveDataFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        """处理当前模块的业务逻辑并返回结果。"""
        message = record.getMessage()
        record.msg = redact_sensitive_text(message)
        record.args = ()
        return True


class ThirdPartyNoiseFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        """处理当前模块的业务逻辑并返回结果。"""
        if record.levelno >= logging.WARNING:
            return True
        return not record.name.startswith(_QUIET_THIRD_PARTY_LOGGERS)


class RingBufferHandler(logging.Handler):
    def __init__(self, capacity=2000):
        """初始化实例并保存运行所需的依赖。"""
        super().__init__()
        self._buffer: deque[dict] = deque(maxlen=capacity)
        self._lock = Lock()

    def emit(self, record: logging.LogRecord) -> None:
        """处理当前模块的业务逻辑并返回结果。"""
        try:
            entry = {
                "timestamp": datetime.fromtimestamp(record.created, tz=UTC)
                .astimezone()
                .strftime("%Y-%m-%d %H:%M:%S"),
                "level": record.levelname,
                "name": record.name,
                "message": redact_sensitive_text(record.getMessage()),
            }
            with self._lock:
                self._buffer.append(entry)
        except Exception:
            self.handleError(record)

    def get_entries(
        self, level: str | None = None, search: str | None = None, limit: int = 200
    ) -> list[dict]:
        """读取并返回对应的数据。"""
        with self._lock:
            entries = list(self._buffer)
        if level:
            level_upper = level.upper()
            entries = [e for e in entries if e["level"] == level_upper]
        if search:
            search_lower = search.lower()
            entries = [
                e
                for e in entries
                if search_lower in e["name"].lower() or search_lower in e["message"].lower()
            ]
        return entries[-limit:]


_ring_buffer: RingBufferHandler | None = None
_logging_initialized = False


def setup_logging() -> None:
    """处理当前模块的业务逻辑并返回结果。"""
    global _ring_buffer, _logging_initialized
    if _logging_initialized:
        return

    log_dir = _resolve_log_dir()
    try:
        os.makedirs(log_dir, exist_ok=True)
    except OSError:
        log_dir = (Path.cwd() / "log").resolve()
        os.makedirs(log_dir, exist_ok=True)

    formatter = logging.Formatter(
        "[%(asctime)s] %(levelname)-7s %(name)s:%(lineno)d - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    redaction_filter = SensitiveDataFilter()
    noise_filter = ThirdPartyNoiseFilter()

    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO))
    root_logger.addFilter(noise_filter)
    root_logger.addFilter(redaction_filter)

    console = logging.StreamHandler()
    console.addFilter(noise_filter)
    console.addFilter(redaction_filter)
    console.setFormatter(formatter)
    root_logger.addHandler(console)

    log_file = os.path.join(str(log_dir), "mod_watcher.log")
    try:
        file_handler = logging.handlers.RotatingFileHandler(
            log_file, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
        )
    except OSError:
        fallback_file = os.path.join(str(log_dir), f"mod_watcher_{os.getpid()}.log")
        file_handler = logging.handlers.RotatingFileHandler(
            fallback_file, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
        )
    file_handler.addFilter(noise_filter)
    file_handler.addFilter(redaction_filter)
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)

    _ring_buffer = RingBufferHandler(capacity=2000)
    _ring_buffer.addFilter(noise_filter)
    _ring_buffer.addFilter(redaction_filter)
    _ring_buffer.setFormatter(formatter)
    root_logger.addHandler(_ring_buffer)
    _logging_initialized = True


def get_log_entries(
    level: str | None = None, search: str | None = None, limit: int = 200
) -> list[dict]:
    """读取并返回对应的数据。"""
    entries = _ring_buffer.get_entries(limit=limit) if _ring_buffer is not None else []
    entries.extend(_read_file_log_entries(limit=limit))
    entries = _dedupe_entries(entries)

    if level:
        level_upper = level.upper()
        entries = [entry for entry in entries if entry["level"] == level_upper]
    if search:
        search_lower = search.lower()
        entries = [
            entry
            for entry in entries
            if search_lower in entry["name"].lower() or search_lower in entry["message"].lower()
        ]
    entries.sort(
        key=lambda entry: (entry.get("timestamp", ""), entry.get("_order", 0)), reverse=True
    )
    return [_public_log_entry(entry) for entry in entries[:limit]]


def _read_file_log_entries(limit: int) -> list[dict]:
    """内部辅助函数，用于拆分上层流程中的局部规则。"""
    log_dir = _resolve_log_dir()
    entries: list[dict] = []
    for file_name in _LOG_FILE_NAMES:
        log_file = log_dir / file_name
        if not log_file.is_file():
            continue
        entries.extend(
            _parse_log_lines(
                _tail_lines(log_file, max(limit * 3, 200)),
                source=file_name,
                fallback_timestamp=_file_timestamp(log_file),
            )
        )
    return entries


def _tail_lines(path: Path, limit: int) -> list[str]:
    """内部辅助函数，用于拆分上层流程中的局部规则。"""
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            return list(deque(handle, maxlen=limit))
    except OSError:
        return []


def _parse_log_lines(lines: list[str], *, source: str, fallback_timestamp: str = "") -> list[dict]:
    """解析原始内容并返回结构化结果。"""
    entries: list[dict] = []
    last_timestamp = fallback_timestamp
    for order, raw_line in enumerate(lines):
        line = raw_line.strip()
        if not line or line.startswith("==="):
            continue

        entry = _parse_log_line(line, source=source, fallback_timestamp=last_timestamp)
        if entry is None:
            if entries:
                entries[-1]["message"] = f"{entries[-1]['message']}\n{redact_sensitive_text(line)}"
            continue
        entry["_order"] = order
        last_timestamp = entry["timestamp"]
        entries.append(entry)
    return entries


def _parse_log_line(line: str, *, source: str, fallback_timestamp: str = "") -> dict | None:
    """解析原始内容并返回结构化结果。"""
    matched = _FILE_LOG_PATTERN.match(line)
    if matched:
        return {
            "timestamp": matched.group("timestamp"),
            "level": _normalize_level(matched.group("level")),
            "name": matched.group("name"),
            "message": redact_sensitive_text(matched.group("message")),
        }

    matched = _SERVICE_LOG_PATTERN.match(line)
    if matched:
        return {
            "timestamp": fallback_timestamp,
            "level": _normalize_level(matched.group("level")),
            "name": matched.group("name"),
            "message": redact_sensitive_text(matched.group("message")),
        }

    matched = _PLAIN_LOG_PATTERN.match(line)
    if matched:
        return {
            "timestamp": fallback_timestamp,
            "level": _normalize_level(matched.group("level")),
            "name": source,
            "message": redact_sensitive_text(matched.group("message")),
        }

    return None


def _file_timestamp(path: Path) -> str:
    """内部辅助函数，用于拆分上层流程中的局部规则。"""
    try:
        return (
            datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
            .astimezone()
            .strftime("%Y-%m-%d %H:%M:%S")
        )
    except OSError:
        return ""


def _normalize_level(level: str) -> str:
    """规范化内部数据，供后续流程使用。"""
    normalized = level.upper()
    if normalized == "WARNI":
        return "WARNING"
    if normalized == "CRITI":
        return "CRITICAL"
    return normalized


def _dedupe_entries(entries: list[dict]) -> list[dict]:
    """内部辅助函数，用于拆分上层流程中的局部规则。"""
    seen: set[tuple[str, str, str, str]] = set()
    unique: list[dict] = []
    for entry in entries:
        key = (
            entry.get("timestamp", ""),
            entry.get("level", ""),
            entry.get("name", ""),
            entry.get("message", ""),
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(entry)
    return unique


def _public_log_entry(entry: dict) -> dict:
    """内部辅助函数，用于拆分上层流程中的局部规则。"""
    return {
        "timestamp": entry.get("timestamp", ""),
        "level": entry.get("level", ""),
        "name": entry.get("name", ""),
        "message": entry.get("message", ""),
    }
