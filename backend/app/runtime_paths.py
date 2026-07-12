from __future__ import annotations

import os
import sys
import tempfile
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

_APPLICATION_DIRECTORY = "ModWatcherAgent"
_GAME_ALIAS_FILENAME = "game_aliases.json"


class RuntimePathError(RuntimeError):
    """Raised when a required writable runtime path cannot be prepared."""


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
    browser_profile_dir: Path
    snapshot_dir: Path
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
        database_path = data_dir / "mod_watcher.db"
    else:
        data_dir = resolved_bundle_root / "backend" / "data"
        config_dir = resolved_bundle_root / "backend"
        log_dir = resolved_bundle_root / "log"
        cache_dir = data_dir / "cache"
        webview_dir = data_dir / "webview"
        runtime_dir = resolved_bundle_root / ".runtime"
        backup_dir = data_dir / "backups"
        database_path = config_dir / "mod_watcher.db"

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
        browser_profile_dir=data_dir / "browser_profiles",
        snapshot_dir=data_dir / "snapshots",
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
        paths.browser_profile_dir,
        paths.snapshot_dir,
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
            "MW_BROWSER_PROFILE_ROOT": str(paths.browser_profile_dir),
            "MW_SNAPSHOT_ROOT": str(paths.snapshot_dir),
            "MW_ENV_FILE": str(paths.config_dir / ".env"),
            "GAME_ALIAS_FILE": str(game_alias_file),
            "MW_BIND_HOST": "127.0.0.1",
            "MW_ALLOW_LAN": "false",
            "LOCAL_ONLY_API": "true",
        }
    )
