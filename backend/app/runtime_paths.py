from __future__ import annotations

import json
import logging
import os
import sqlite3
import sys
import tempfile
from contextlib import closing, suppress
from dataclasses import dataclass
from pathlib import Path

_APPLICATION_DIRECTORY = "ModWatcherAgent"
_GAME_ALIAS_FILENAME = "game_aliases.json"
_DATABASE_SELECTION_FILENAME = "database-selection.json"
logger = logging.getLogger(__name__)


class RuntimePathError(RuntimeError):
    """Raised when a required writable runtime path cannot be prepared."""


class MissingDatabaseSelectionError(RuntimePathError):
    """Raised when an explicitly selected SQLite database no longer exists."""


@dataclass(frozen=True)
class RuntimePaths:
    bundle_root: Path
    executable_dir: Path
    user_root: Path
    data_dir: Path
    config_dir: Path
    log_dir: Path
    cache_dir: Path
    webview_dir: Path
    runtime_dir: Path
    backup_dir: Path
    default_database_path: Path
    database_path: Path
    frontend_dist_dir: Path
    alembic_ini_path: Path


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def _bundle_root(frozen: bool) -> Path:
    if not frozen:
        return Path(__file__).resolve().parents[2]

    pyinstaller_root = getattr(sys, "_MEIPASS", None)
    if pyinstaller_root:
        return Path(pyinstaller_root)
    return Path(sys.executable).resolve().parent


def _user_root(*, frozen: bool, bundle_root: Path) -> tuple[Path, bool]:
    override = os.getenv("MW_USER_DATA_DIR")
    if override:
        return Path(override), True
    if not frozen:
        return bundle_root, False

    local_app_data = os.getenv("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / _APPLICATION_DIRECTORY, True

    try:
        home = Path.home()
    except (OSError, RuntimeError) as exc:
        raise RuntimePathError(
            "Cannot determine the runtime user directory because LOCALAPPDATA "
            "and the user home directory are unavailable"
        ) from exc
    return home / "AppData" / "Local" / _APPLICATION_DIRECTORY, True


def _database_selection_path(config_dir: Path) -> Path:
    return config_dir / _DATABASE_SELECTION_FILENAME


def _normalize_database_path(raw_value: str, *, config_dir: Path) -> Path | None:
    value = str(raw_value or "").strip()
    if not value:
        return None
    if "://" in value and not value.lower().startswith("sqlite:///"):
        raise RuntimePathError("Only SQLite database paths are supported")
    if value.lower().startswith("sqlite:///"):
        value = value[len("sqlite:///") :]
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        candidate = config_dir / candidate
    resolved = candidate.resolve(strict=False)
    if str(resolved).startswith("\\\\"):
        raise RuntimePathError("SQLite database paths must use a local filesystem path")
    if resolved.exists() and not resolved.is_file():
        raise RuntimePathError(f"SQLite database path is not a file: {resolved}")
    return resolved


def _resolve_database_path(raw_value: str, *, config_dir: Path) -> Path | None:
    resolved = _normalize_database_path(raw_value, config_dir=config_dir)
    if resolved is None:
        return None
    if not resolved.is_file():
        raise MissingDatabaseSelectionError(f"Selected SQLite database does not exist: {resolved}")
    return resolved


def _create_empty_sqlite_database(database_path: Path) -> None:
    """Create a valid empty SQLite file without replacing a concurrent file."""
    if database_path.is_file():
        return

    temporary_path: Path | None = None
    descriptor: int | None = None
    try:
        database_path.parent.mkdir(parents=True, exist_ok=True)
        if database_path.exists():
            if database_path.is_file():
                return
            raise RuntimePathError(f"SQLite database path is not a file: {database_path}")

        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{database_path.name}.create-",
            suffix=".tmp",
            dir=database_path.parent,
        )
        temporary_path = Path(temporary_name)
        os.close(descriptor)
        descriptor = None

        with closing(sqlite3.connect(temporary_path)) as database:
            database.execute("VACUUM")
            integrity = database.execute("PRAGMA integrity_check").fetchone()
        if integrity != ("ok",):
            raise RuntimePathError(f"Unable to create a valid SQLite database: {database_path}")

        try:
            if os.name == "nt":
                os.rename(temporary_path, database_path)
            else:
                os.link(temporary_path, database_path)
        except FileExistsError:
            if not database_path.is_file():
                raise RuntimePathError(
                    f"SQLite database path is not a file: {database_path}"
                ) from None
    except RuntimePathError:
        raise
    except (OSError, sqlite3.Error) as exc:
        raise RuntimePathError(f"Unable to create SQLite database {database_path}: {exc}") from exc
    finally:
        if descriptor is not None:
            with suppress(OSError):
                os.close(descriptor)
        if temporary_path is not None:
            with suppress(OSError):
                temporary_path.unlink(missing_ok=True)


def _load_database_path_selection(config_dir: Path) -> Path | None:
    selection_path = _database_selection_path(config_dir)
    if not selection_path.is_file():
        return None
    try:
        payload = json.loads(selection_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimePathError(f"Unable to read database selection: {selection_path}") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("database_path"), str):
        raise RuntimePathError(f"Invalid database selection file: {selection_path}")
    try:
        return _resolve_database_path(payload["database_path"], config_dir=config_dir)
    except MissingDatabaseSelectionError as exc:
        logger.warning("%s; falling back to the default database", exc)
        return None


def save_database_path_selection(paths: RuntimePaths, raw_value: str) -> Path | None:
    """Persist the next-start database path outside the active database."""

    selection_path = _database_selection_path(paths.config_dir)
    selected_path = _normalize_database_path(raw_value, config_dir=paths.config_dir)
    paths.config_dir.mkdir(parents=True, exist_ok=True)
    if selected_path is None:
        with suppress(OSError):
            selection_path.unlink(missing_ok=True)
        return None

    _create_empty_sqlite_database(selected_path)

    descriptor: int | None = None
    temporary_path: Path | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{selection_path.name}.",
            suffix=".tmp",
            dir=paths.config_dir,
        )
        temporary_path = Path(temporary_name)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as output:
            descriptor = None
            json.dump({"database_path": str(selected_path)}, output, ensure_ascii=False, indent=2)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary_path, selection_path)
        temporary_path = None
    except OSError as exc:
        raise RuntimePathError(f"Unable to save database selection: {selection_path}") from exc
    finally:
        if descriptor is not None:
            with suppress(OSError):
                os.close(descriptor)
        if temporary_path is not None:
            with suppress(OSError):
                temporary_path.unlink(missing_ok=True)
    return selected_path


def migrate_legacy_database_path_setting(paths: RuntimePaths) -> bool:
    """Move the formerly inert database setting into the bootstrap configuration."""

    config_dir = getattr(paths, "config_dir", None)
    database_path = getattr(paths, "database_path", None)
    if not isinstance(config_dir, Path) or not isinstance(database_path, Path):
        return False
    if _database_selection_path(config_dir).exists() or not database_path.is_file():
        return False
    try:
        with sqlite3.connect(f"file:{database_path.as_posix()}?mode=ro", uri=True) as connection:
            row = connection.execute(
                "SELECT value FROM settings WHERE key = ?",
                ("database_path",),
            ).fetchone()
    except sqlite3.Error:
        return False
    if not row or not str(row[0] or "").strip():
        return False
    try:
        selected_path = _resolve_database_path(str(row[0]), config_dir=config_dir)
    except RuntimePathError:
        return False
    if selected_path is None or _path_key(selected_path) == _path_key(database_path):
        return False
    save_database_path_selection(paths, str(selected_path))
    return True


def build_runtime_paths(
    *,
    frozen: bool | None = None,
    bundle_root: Path | None = None,
    executable_dir: Path | None = None,
) -> RuntimePaths:
    frozen_runtime = is_frozen() if frozen is None else frozen
    resolved_bundle_root = (
        Path(bundle_root) if bundle_root is not None else _bundle_root(frozen_runtime)
    )
    resolved_executable_dir = (
        Path(executable_dir)
        if executable_dir is not None
        else (
            Path(sys.executable).resolve().parent
            if frozen_runtime
            else resolved_bundle_root / "backend"
        )
    )
    user_root, portable_layout = _user_root(
        frozen=frozen_runtime,
        bundle_root=resolved_bundle_root,
    )

    if portable_layout:
        data_dir = user_root / "data"
        config_dir = user_root / "config"
        log_dir = user_root / "logs"
        cache_dir = user_root / "cache"
        webview_dir = user_root / "webview"
        runtime_dir = user_root / "runtime"
        backup_dir = user_root / "backups"
        default_database_path = data_dir / "mod_watcher.db"
    else:
        data_dir = resolved_bundle_root / "backend" / "data"
        config_dir = resolved_bundle_root / "backend"
        log_dir = resolved_bundle_root / "log"
        cache_dir = data_dir / "cache"
        webview_dir = data_dir / "webview"
        runtime_dir = resolved_bundle_root / ".runtime"
        backup_dir = data_dir / "backups"
        default_database_path = config_dir / "mod_watcher.db"

    database_path = _load_database_path_selection(config_dir) or default_database_path

    return RuntimePaths(
        bundle_root=resolved_bundle_root,
        executable_dir=resolved_executable_dir,
        user_root=user_root,
        data_dir=data_dir,
        config_dir=config_dir,
        log_dir=log_dir,
        cache_dir=cache_dir,
        webview_dir=webview_dir,
        runtime_dir=runtime_dir,
        backup_dir=backup_dir,
        default_database_path=default_database_path,
        database_path=database_path,
        frontend_dist_dir=resolved_bundle_root / "frontend" / "dist",
        alembic_ini_path=resolved_bundle_root / "backend" / "alembic.ini",
    )


def ensure_runtime_directories(paths: RuntimePaths) -> None:
    directories = (
        paths.user_root,
        paths.data_dir,
        paths.config_dir,
        paths.log_dir,
        paths.cache_dir,
        paths.webview_dir,
        paths.runtime_dir,
        paths.backup_dir,
    )
    for directory in directories:
        try:
            directory.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise RuntimePathError(
                f"Unable to create runtime directory {directory}: {exc}"
            ) from exc


def _path_key(path: Path) -> str:
    return os.path.normcase(os.path.abspath(os.fspath(path)))


def _publish_seed_without_overwrite(source: Path, target: Path) -> None:
    if _path_key(source) == _path_key(target) or target.exists():
        return
    if not source.is_file():
        return

    temporary_path: Path | None = None
    descriptor: int | None = None
    try:
        content = source.read_bytes()
        target.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{target.name}.seed-",
            suffix=".tmp",
            dir=target.parent,
        )
        temporary_path = Path(temporary_name)
        with os.fdopen(descriptor, "wb") as output:
            descriptor = None
            output.write(content)
            output.flush()
            os.fsync(output.fileno())

        try:
            if os.name == "nt":
                os.rename(temporary_path, target)
            else:
                os.link(temporary_path, target)
        except FileExistsError:
            return
    except OSError as exc:
        raise RuntimePathError(
            f"Unable to seed game aliases from {source} to {target}: {exc}"
        ) from exc
    finally:
        if descriptor is not None:
            with suppress(OSError):
                os.close(descriptor)
        if temporary_path is not None:
            with suppress(OSError):
                temporary_path.unlink(missing_ok=True)


def configure_desktop_environment(paths: RuntimePaths) -> None:
    game_alias_file = paths.config_dir / _GAME_ALIAS_FILENAME
    game_alias_seed = paths.bundle_root / "backend" / _GAME_ALIAS_FILENAME
    _publish_seed_without_overwrite(game_alias_seed, game_alias_file)
    os.environ.update(
        {
            "MW_DESKTOP_MODE": "true",
            "MW_USER_DATA_DIR": str(paths.user_root),
            "DATABASE_URL": f"sqlite:///{paths.database_path.as_posix()}",
            "LOG_DIR": str(paths.log_dir),
            "MW_ENV_FILE": str(paths.config_dir / ".env"),
            "GAME_ALIAS_FILE": str(game_alias_file),
            "MW_BIND_HOST": "127.0.0.1",
            "MW_ALLOW_LAN": "false",
            "LOCAL_ONLY_API": "true",
        }
    )
