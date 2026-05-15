import logging
import logging.handlers
import os
from collections import deque
from datetime import datetime
from threading import Lock

from app.config import settings


class RingBufferHandler(logging.Handler):
    def __init__(self, capacity=2000):
        super().__init__()
        self._buffer: deque[dict] = deque(maxlen=capacity)
        self._lock = Lock()

    def emit(self, record: logging.LogRecord) -> None:
        try:
            entry = {
                "timestamp": datetime.fromtimestamp(record.created).strftime(
                    "%Y-%m-%d %H:%M:%S"
                ),
                "level": record.levelname,
                "name": record.name,
                "message": record.getMessage(),
            }
            with self._lock:
                self._buffer.append(entry)
        except Exception:
            self.handleError(record)

    def get_entries(
        self, level: str | None = None, search: str | None = None, limit: int = 200
    ) -> list[dict]:
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
                if search_lower in e["name"].lower()
                or search_lower in e["message"].lower()
            ]
        return entries[-limit:]


_ring_buffer: RingBufferHandler | None = None
_logging_initialized = False


def setup_logging() -> None:
    global _ring_buffer, _logging_initialized
    if _logging_initialized:
        return

    log_dir = settings.LOG_DIR
    os.makedirs(log_dir, exist_ok=True)

    formatter = logging.Formatter(
        "[%(asctime)s] %(levelname)-7s %(name)s:%(lineno)d - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO))

    console = logging.StreamHandler()
    console.setFormatter(formatter)
    root_logger.addHandler(console)

    log_file = os.path.join(log_dir, "mod_watcher.log")
    try:
        file_handler = logging.handlers.RotatingFileHandler(
            log_file, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
        )
    except OSError:
        fallback_file = os.path.join(log_dir, f"mod_watcher_{os.getpid()}.log")
        file_handler = logging.handlers.RotatingFileHandler(
            fallback_file, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
        )
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)

    _ring_buffer = RingBufferHandler(capacity=2000)
    _ring_buffer.setFormatter(formatter)
    root_logger.addHandler(_ring_buffer)
    _logging_initialized = True


def get_log_entries(
    level: str | None = None, search: str | None = None, limit: int = 200
) -> list[dict]:
    if _ring_buffer is None:
        return []
    return _ring_buffer.get_entries(level=level, search=search, limit=limit)
