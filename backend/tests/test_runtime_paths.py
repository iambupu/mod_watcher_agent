from __future__ import annotations

import os
import sys
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

import app.runtime_paths as runtime_paths_module
from app.runtime_paths import (
    RuntimePathError,
    RuntimePaths,
    build_runtime_paths,
    configure_desktop_environment,
    ensure_runtime_directories,
    is_frozen,
)


def test_is_frozen_follows_interpreter_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delattr(sys, "frozen", raising=False)
    assert is_frozen() is False

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert is_frozen() is True


def test_source_paths_preserve_existing_layout(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv("MW_USER_DATA_DIR", raising=False)
    repo_root = tmp_path / "source tree"
    backend_dir = repo_root / "backend"

    paths = build_runtime_paths(
        frozen=False,
        bundle_root=repo_root,
        executable_dir=backend_dir,
    )

    assert paths == RuntimePaths(
        bundle_root=repo_root,
        executable_dir=backend_dir,
        user_root=repo_root,
        data_dir=backend_dir / "data",
        config_dir=backend_dir,
        log_dir=repo_root / "log",
        cache_dir=backend_dir / "data" / "cache",
        webview_dir=backend_dir / "data" / "webview",
        runtime_dir=repo_root / ".runtime",
        backup_dir=backend_dir / "data" / "backups",
        browser_profile_dir=backend_dir / "data" / "browser_profiles",
        snapshot_dir=backend_dir / "data" / "snapshots",
        database_path=backend_dir / "mod_watcher.db",
        frontend_dist_dir=repo_root / "frontend" / "dist",
        alembic_ini_path=backend_dir / "alembic.ini",
    )

    with pytest.raises(FrozenInstanceError):
        paths.user_root = tmp_path  # type: ignore[misc]


def test_source_defaults_are_derived_from_module_location(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("MW_USER_DATA_DIR", raising=False)
    repo_root = Path(__file__).resolve().parents[2]

    paths = build_runtime_paths(frozen=False)

    assert paths.bundle_root == repo_root
    assert paths.executable_dir == repo_root / "backend"


def test_frozen_paths_use_local_app_data(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    local_app_data = tmp_path / "本地 数据"
    bundle_root = tmp_path / "bundle"
    executable_dir = tmp_path / "app"
    monkeypatch.delenv("MW_USER_DATA_DIR", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(local_app_data))

    paths = build_runtime_paths(
        frozen=True,
        bundle_root=bundle_root,
        executable_dir=executable_dir,
    )

    assert paths == RuntimePaths(
        bundle_root=bundle_root,
        executable_dir=executable_dir,
        user_root=local_app_data / "ModWatcherAgent",
        data_dir=local_app_data / "ModWatcherAgent" / "data",
        config_dir=local_app_data / "ModWatcherAgent" / "config",
        log_dir=local_app_data / "ModWatcherAgent" / "logs",
        cache_dir=local_app_data / "ModWatcherAgent" / "cache",
        webview_dir=local_app_data / "ModWatcherAgent" / "webview",
        runtime_dir=local_app_data / "ModWatcherAgent" / "runtime",
        backup_dir=local_app_data / "ModWatcherAgent" / "backups",
        browser_profile_dir=local_app_data / "ModWatcherAgent" / "data" / "browser_profiles",
        snapshot_dir=local_app_data / "ModWatcherAgent" / "data" / "snapshots",
        database_path=local_app_data / "ModWatcherAgent" / "data" / "mod_watcher.db",
        frontend_dist_dir=bundle_root / "frontend" / "dist",
        alembic_ini_path=bundle_root / "backend" / "alembic.ini",
    )


def test_detected_frozen_roots_use_pyinstaller_locations(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    bundle_root = tmp_path / "bundle root"
    executable = tmp_path / "安装 目录" / "ModWatcherAgent.exe"
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(bundle_root), raising=False)
    monkeypatch.setattr(sys, "executable", str(executable))
    monkeypatch.delenv("MW_USER_DATA_DIR", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local App Data"))

    paths = build_runtime_paths()

    assert paths.bundle_root == bundle_root
    assert paths.executable_dir == executable.parent


def test_user_data_override_uses_portable_layout_in_source_mode(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    user_root = tmp_path / "用户 数据"
    monkeypatch.setenv("MW_USER_DATA_DIR", str(user_root))

    paths = build_runtime_paths(
        frozen=False,
        bundle_root=repo_root,
        executable_dir=repo_root / "backend",
    )

    assert paths.user_root == user_root
    assert paths.data_dir == user_root / "data"
    assert paths.config_dir == user_root / "config"
    assert paths.log_dir == user_root / "logs"
    assert paths.cache_dir == user_root / "cache"
    assert paths.webview_dir == user_root / "webview"
    assert paths.runtime_dir == user_root / "runtime"
    assert paths.backup_dir == user_root / "backups"
    assert paths.browser_profile_dir == user_root / "data" / "browser_profiles"
    assert paths.snapshot_dir == user_root / "data" / "snapshots"
    assert paths.database_path == user_root / "data" / "mod_watcher.db"
    assert paths.frontend_dist_dir == repo_root / "frontend" / "dist"
    assert paths.alembic_ini_path == repo_root / "backend" / "alembic.ini"


def test_missing_local_app_data_falls_back_to_user_home(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    home = tmp_path / "用户 Home"
    monkeypatch.delenv("MW_USER_DATA_DIR", raising=False)
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))

    paths = build_runtime_paths(
        frozen=True,
        bundle_root=tmp_path / "bundle",
        executable_dir=tmp_path / "app",
    )

    assert paths.user_root == home / "AppData" / "Local" / "ModWatcherAgent"


def test_missing_local_app_data_reports_unavailable_home(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def unavailable_home(cls: type[Path]) -> Path:
        raise RuntimeError("home lookup failed")

    monkeypatch.delenv("MW_USER_DATA_DIR", raising=False)
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.setattr(Path, "home", classmethod(unavailable_home))

    with pytest.raises(RuntimePathError, match="LOCALAPPDATA"):
        build_runtime_paths(
            frozen=True,
            bundle_root=tmp_path / "bundle",
            executable_dir=tmp_path / "app",
        )


def test_ensure_runtime_directories_creates_every_writable_directory(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("MW_USER_DATA_DIR", str(tmp_path / "运行 数据"))
    paths = build_runtime_paths(
        frozen=True,
        bundle_root=tmp_path / "bundle",
        executable_dir=tmp_path / "app",
    )

    ensure_runtime_directories(paths)

    writable_directories = (
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
    assert all(path.is_dir() for path in writable_directories)


def test_ensure_runtime_directories_reports_creation_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    blocked_root = tmp_path / "blocked"
    blocked_root.write_text("not a directory", encoding="utf-8")
    monkeypatch.setenv("MW_USER_DATA_DIR", str(blocked_root))
    paths = build_runtime_paths(
        frozen=True,
        bundle_root=tmp_path / "bundle",
        executable_dir=tmp_path / "app",
    )

    with pytest.raises(RuntimePathError, match="blocked"):
        ensure_runtime_directories(paths)


def test_desktop_environment_points_to_runtime_paths_and_is_local_only(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    environment_names = (
        "MW_DESKTOP_MODE",
        "DATABASE_URL",
        "LOG_DIR",
        "MW_BROWSER_PROFILE_ROOT",
        "MW_SNAPSHOT_ROOT",
        "MW_ENV_FILE",
        "MW_BIND_HOST",
        "MW_ALLOW_LAN",
        "LOCAL_ONLY_API",
    )
    for name in environment_names:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("GAME_ALIAS_FILE", "original-game-alias-file")
    monkeypatch.setenv("MW_USER_DATA_DIR", str(tmp_path / "本地 数据"))
    paths = build_runtime_paths(
        frozen=True,
        bundle_root=tmp_path / "bundle",
        executable_dir=tmp_path / "app",
    )

    configure_desktop_environment(paths)

    assert os.environ["MW_DESKTOP_MODE"] == "true"
    assert os.environ["MW_USER_DATA_DIR"] == str(paths.user_root)
    assert os.environ["DATABASE_URL"] == f"sqlite:///{paths.database_path.as_posix()}"
    assert os.environ["LOG_DIR"] == str(paths.log_dir)
    assert os.environ["MW_BROWSER_PROFILE_ROOT"] == str(paths.browser_profile_dir)
    assert os.environ["MW_SNAPSHOT_ROOT"] == str(paths.snapshot_dir)
    assert os.environ["MW_ENV_FILE"] == str(paths.config_dir / ".env")
    assert os.environ["MW_BIND_HOST"] == "127.0.0.1"
    assert os.environ["MW_ALLOW_LAN"] == "false"
    assert os.environ["LOCAL_ONLY_API"] == "true"


def test_desktop_environment_seeds_game_aliases_into_user_config(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    bundle_root = tmp_path / "bundle"
    seed_path = bundle_root / "backend" / "game_aliases.json"
    seed_path.parent.mkdir(parents=True)
    seed_content = '{"aliases":{"天际":["Skyrim Special Edition"]}}\n'
    seed_path.write_text(seed_content, encoding="utf-8")
    monkeypatch.setenv("MW_USER_DATA_DIR", str(tmp_path / "用户 数据"))
    monkeypatch.setenv("GAME_ALIAS_FILE", "original-game-alias-file")
    paths = build_runtime_paths(
        frozen=True,
        bundle_root=bundle_root,
        executable_dir=tmp_path / "app",
    )
    ensure_runtime_directories(paths)

    configure_desktop_environment(paths)

    alias_file = paths.config_dir / "game_aliases.json"
    assert os.environ["GAME_ALIAS_FILE"] == str(alias_file)
    assert alias_file.read_text(encoding="utf-8") == seed_content
    assert list(paths.config_dir.glob(".game_aliases.json.*.tmp")) == []


def test_desktop_environment_preserves_existing_user_game_aliases(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    bundle_root = tmp_path / "bundle"
    seed_path = bundle_root / "backend" / "game_aliases.json"
    seed_path.parent.mkdir(parents=True)
    seed_path.write_text('{"aliases":{"seed":["Skyrim"]}}\n', encoding="utf-8")
    monkeypatch.setenv("MW_USER_DATA_DIR", str(tmp_path / "用户 数据"))
    monkeypatch.setenv("GAME_ALIAS_FILE", "original-game-alias-file")
    paths = build_runtime_paths(
        frozen=True,
        bundle_root=bundle_root,
        executable_dir=tmp_path / "app",
    )
    ensure_runtime_directories(paths)
    alias_file = paths.config_dir / "game_aliases.json"
    user_content = '{"aliases":{"用户别名":["Stellar Blade"]}}\n'
    alias_file.write_text(user_content, encoding="utf-8")

    configure_desktop_environment(paths)

    assert os.environ["GAME_ALIAS_FILE"] == str(alias_file)
    assert alias_file.read_text(encoding="utf-8") == user_content


def test_desktop_environment_preserves_alias_file_created_during_seed_race(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    bundle_root = tmp_path / "bundle"
    seed_path = bundle_root / "backend" / "game_aliases.json"
    seed_path.parent.mkdir(parents=True)
    seed_path.write_text('{"aliases":{"seed":["Skyrim"]}}\n', encoding="utf-8")
    monkeypatch.setenv("MW_USER_DATA_DIR", str(tmp_path / "用户 数据"))
    monkeypatch.setenv("GAME_ALIAS_FILE", "original-game-alias-file")
    paths = build_runtime_paths(
        frozen=True,
        bundle_root=bundle_root,
        executable_dir=tmp_path / "app",
    )
    ensure_runtime_directories(paths)
    alias_file = paths.config_dir / "game_aliases.json"
    user_content = b'{"aliases":{"race-winner":["Stellar Blade"]}}\n'

    def publish_collision(_source: object, destination: object) -> None:
        Path(destination).write_bytes(user_content)  # type: ignore[arg-type]
        raise FileExistsError("simulated concurrent publication")

    publish_name = "rename" if os.name == "nt" else "link"
    monkeypatch.setattr(runtime_paths_module.os, publish_name, publish_collision)

    configure_desktop_environment(paths)

    assert alias_file.read_bytes() == user_content
    assert list(paths.config_dir.glob(".game_aliases.json.*.tmp")) == []
