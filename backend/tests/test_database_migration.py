from __future__ import annotations

import json
import os
import sqlite3
from collections.abc import Iterator
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from app.desktop import database_migration
from app.desktop.database_migration import (
    DatabaseMigrationError,
    MigrationResult,
    legacy_database_candidates,
    migrate_legacy_database,
)
from app.runtime_paths import RuntimePaths, build_runtime_paths


@pytest.fixture
def runtime_paths(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> RuntimePaths:
    monkeypatch.setenv("MW_USER_DATA_DIR", str(tmp_path / "current user data"))
    return build_runtime_paths(
        frozen=True,
        bundle_root=tmp_path / "bundle",
        executable_dir=tmp_path / "installed app",
    )


@pytest.fixture
def legacy_db(tmp_path: Path) -> Iterator[Path]:
    database_path = tmp_path / "legacy install" / "mod_watcher.db"
    database_path.parent.mkdir(parents=True)
    database = sqlite3.connect(database_path)
    try:
        assert database.execute("PRAGMA journal_mode=WAL").fetchone() == ("wal",)
        database.execute("PRAGMA wal_autocheckpoint=0")
        database.execute("CREATE TABLE sample (value TEXT NOT NULL)")
        database.execute("INSERT INTO sample VALUES ('main database row')")
        database.commit()
        database.execute("PRAGMA wal_checkpoint(TRUNCATE)")

        database.execute("INSERT INTO sample VALUES ('committed WAL row')")
        database.commit()
        assert Path(f"{database_path}-wal").stat().st_size > 0
        yield database_path
    finally:
        database.close()


def _create_database(database_path: Path, value: str = "legacy row") -> None:
    database_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(database_path) as database:
        database.execute("CREATE TABLE sample (value TEXT NOT NULL)")
        database.execute("INSERT INTO sample VALUES (?)", (value,))


def _target_artifacts(target: Path) -> list[Path]:
    return [
        target,
        Path(f"{target}-journal"),
        Path(f"{target}-shm"),
        Path(f"{target}-wal"),
    ]


def test_legacy_candidates_are_ordered_deduplicated_and_exclude_target(
    runtime_paths: RuntimePaths,
    tmp_path: Path,
) -> None:
    executable_dir = runtime_paths.executable_dir
    working_dir = tmp_path / "working tree"

    assert list(legacy_database_candidates(runtime_paths, cwd=working_dir)) == [
        executable_dir / "backend" / "mod_watcher.db",
        executable_dir / "mod_watcher.db",
        working_dir / "backend" / "mod_watcher.db",
    ]
    assert list(legacy_database_candidates(runtime_paths, cwd=executable_dir)) == [
        executable_dir / "backend" / "mod_watcher.db",
        executable_dir / "mod_watcher.db",
    ]

    target_is_second_candidate = replace(
        runtime_paths,
        database_path=executable_dir / "mod_watcher.db",
    )
    assert list(legacy_database_candidates(target_is_second_candidate, cwd=executable_dir)) == [
        executable_dir / "backend" / "mod_watcher.db"
    ]


def test_existing_target_skips_migration_without_changing_files(
    runtime_paths: RuntimePaths,
    tmp_path: Path,
) -> None:
    source = tmp_path / "legacy" / "mod_watcher.db"
    _create_database(source)
    runtime_paths.database_path.parent.mkdir(parents=True)
    runtime_paths.database_path.write_bytes(b"existing target")
    runtime_paths.backup_dir.mkdir(parents=True)
    metadata_path = runtime_paths.backup_dir / "migration.json"
    metadata_path.write_text("existing metadata", encoding="utf-8")
    source_before = source.read_bytes()

    result = migrate_legacy_database(runtime_paths, candidates=[source])

    assert result == MigrationResult(
        migrated=False,
        source=None,
        target=runtime_paths.database_path,
        metadata_path=None,
    )
    assert runtime_paths.database_path.read_bytes() == b"existing target"
    assert source.read_bytes() == source_before
    assert metadata_path.read_text(encoding="utf-8") == "existing metadata"


def test_missing_candidates_skip_migration_without_creating_files(
    runtime_paths: RuntimePaths,
    tmp_path: Path,
) -> None:
    result = migrate_legacy_database(
        runtime_paths,
        candidates=[tmp_path / "missing" / "mod_watcher.db"],
    )

    assert result.migrated is False
    assert result.source is None
    assert result.target == runtime_paths.database_path
    assert result.metadata_path is None
    assert not runtime_paths.database_path.parent.exists()
    assert not runtime_paths.backup_dir.exists()


def test_default_migration_uses_first_existing_legacy_candidate(
    runtime_paths: RuntimePaths,
) -> None:
    first, second, *_ = legacy_database_candidates(runtime_paths)
    _create_database(first, "first candidate")
    _create_database(second, "second candidate")

    result = migrate_legacy_database(runtime_paths)

    assert result.source == first
    with sqlite3.connect(runtime_paths.database_path) as database:
        assert database.execute("SELECT value FROM sample").fetchone() == ("first candidate",)


def test_migration_uses_backup_api_preserves_wal_rows_and_records_metadata(
    runtime_paths: RuntimePaths,
    legacy_db: Path,
) -> None:
    result = migrate_legacy_database(runtime_paths, candidates=[legacy_db])

    metadata_path = runtime_paths.backup_dir / "migration.json"
    assert result == MigrationResult(
        migrated=True,
        source=legacy_db,
        target=runtime_paths.database_path,
        metadata_path=metadata_path,
    )
    with sqlite3.connect(runtime_paths.database_path) as database:
        assert database.execute("SELECT value FROM sample ORDER BY rowid").fetchall() == [
            ("main database row",),
            ("committed WAL row",),
        ]
    assert legacy_db.exists()

    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    migrated_at = datetime.fromisoformat(metadata["migrated_at"])
    assert metadata == {
        "source": str(legacy_db),
        "target": str(runtime_paths.database_path),
        "migrated_at": metadata["migrated_at"],
        "source_size": legacy_db.stat().st_size,
        "target_size": runtime_paths.database_path.stat().st_size,
        "integrity": "ok",
    }
    assert migrated_at.utcoffset() == timedelta(0)


def test_failed_integrity_check_removes_partial_target_and_preserves_source(
    runtime_paths: RuntimePaths,
    tmp_path: Path,
) -> None:
    corrupt_db = tmp_path / "legacy" / "corrupt.db"
    _create_database(corrupt_db)
    with sqlite3.connect(corrupt_db) as database:
        database.execute("PRAGMA writable_schema=ON")
        database.execute("UPDATE sqlite_schema SET rootpage = 999999 WHERE name = 'sample'")

    with pytest.raises(DatabaseMigrationError) as error:
        migrate_legacy_database(runtime_paths, candidates=[corrupt_db])

    assert "integrity_check" in str(error.value)
    assert isinstance(error.value.__cause__, sqlite3.DatabaseError)
    assert corrupt_db.exists()
    assert all(not artifact.exists() for artifact in _target_artifacts(runtime_paths.database_path))
    assert not list(runtime_paths.database_path.parent.glob(".mod_watcher.db.migration-*"))
    assert not (runtime_paths.backup_dir / "migration.json").exists()


def test_metadata_write_failure_does_not_publish_target(
    runtime_paths: RuntimePaths,
    legacy_db: Path,
) -> None:
    runtime_paths.backup_dir.parent.mkdir(parents=True)
    runtime_paths.backup_dir.write_text("blocks backup directory", encoding="utf-8")

    with pytest.raises(DatabaseMigrationError) as error:
        migrate_legacy_database(runtime_paths, candidates=[legacy_db])

    assert isinstance(error.value.__cause__, OSError)
    assert legacy_db.exists()
    assert all(not artifact.exists() for artifact in _target_artifacts(runtime_paths.database_path))
    assert not list(runtime_paths.database_path.parent.glob(".mod_watcher.db.migration-*"))


def test_final_replace_failure_rolls_back_metadata_and_partial_target(
    runtime_paths: RuntimePaths,
    legacy_db: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_replace = os.replace
    metadata_path = runtime_paths.backup_dir / "migration.json"

    def fail_final_replace(source: str | Path, target: str | Path) -> None:
        if Path(target) == runtime_paths.database_path:
            assert metadata_path.is_file()
            raise OSError("target replace failed")
        real_replace(source, target)

    monkeypatch.setattr(database_migration.os, "replace", fail_final_replace)

    with pytest.raises(DatabaseMigrationError) as error:
        migrate_legacy_database(runtime_paths, candidates=[legacy_db])

    assert isinstance(error.value.__cause__, OSError)
    assert "target replace failed" in str(error.value.__cause__)
    assert legacy_db.exists()
    assert not metadata_path.exists()
    assert all(not artifact.exists() for artifact in _target_artifacts(runtime_paths.database_path))
    assert not list(runtime_paths.database_path.parent.glob(".mod_watcher.db.migration-*"))
