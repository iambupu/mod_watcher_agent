from __future__ import annotations

import json
import logging
import os
import sqlite3
import tempfile
from collections.abc import Iterable
from contextlib import closing, suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from app.runtime_paths import RuntimePaths

logger = logging.getLogger(__name__)

_DATABASE_NAME = "mod_watcher.db"
_METADATA_NAME = "migration.json"
_SQLITE_SIDECAR_SUFFIXES = ("-journal", "-shm", "-wal")


class DatabaseMigrationError(RuntimeError):
    """Raised when a legacy database cannot be migrated safely."""


@dataclass(frozen=True)
class MigrationResult:
    migrated: bool
    source: Path | None
    target: Path
    metadata_path: Path | None


def _path_key(path: Path) -> str:
    return os.path.normcase(os.path.abspath(os.fspath(path)))


def _unique_candidates(candidates: Iterable[Path], *, target: Path) -> tuple[Path, ...]:
    target_key = _path_key(target)
    seen: set[str] = set()
    unique: list[Path] = []
    for value in candidates:
        candidate = Path(value)
        key = _path_key(candidate)
        if key == target_key or key in seen:
            continue
        seen.add(key)
        unique.append(candidate)
    return tuple(unique)


def legacy_database_candidates(
    paths: RuntimePaths,
    cwd: Path | None = None,
) -> tuple[Path, ...]:
    """Return legacy database locations in first-release discovery order."""
    working_directory = Path.cwd() if cwd is None else Path(cwd)
    return _unique_candidates(
        (
            paths.executable_dir / "backend" / _DATABASE_NAME,
            paths.executable_dir / _DATABASE_NAME,
            working_directory / "backend" / _DATABASE_NAME,
        ),
        target=paths.database_path,
    )


def _temporary_path(directory: Path, *, prefix: str, suffix: str) -> Path:
    descriptor, name = tempfile.mkstemp(prefix=prefix, suffix=suffix, dir=directory)
    os.close(descriptor)
    return Path(name)


def _remove_sqlite_artifacts(database_path: Path) -> list[str]:
    failures: list[str] = []
    for artifact in (
        database_path,
        *(Path(f"{database_path}{suffix}") for suffix in _SQLITE_SIDECAR_SUFFIXES),
    ):
        try:
            artifact.unlink(missing_ok=True)
        except OSError as exc:
            failures.append(f"{artifact}: {exc}")
    return failures


def _write_bytes_atomically(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = _temporary_path(
        path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    try:
        with temporary_path.open("wb") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary_path, path)
    finally:
        with suppress(OSError):
            temporary_path.unlink(missing_ok=True)


def _write_migration_metadata(path: Path, metadata: dict[str, object]) -> None:
    serialized = json.dumps(
        metadata,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ).encode("utf-8")
    _write_bytes_atomically(path, serialized + b"\n")


def _restore_metadata(
    metadata_path: Path,
    *,
    existed: bool,
    previous_content: bytes | None,
) -> list[str]:
    try:
        if existed:
            assert previous_content is not None
            _write_bytes_atomically(metadata_path, previous_content)
        else:
            metadata_path.unlink(missing_ok=True)
    except (OSError, AssertionError) as exc:
        return [f"{metadata_path}: {exc}"]
    return []


def _check_integrity(database: sqlite3.Connection) -> str:
    try:
        result = database.execute("PRAGMA integrity_check").fetchall()
    except sqlite3.DatabaseError as exc:
        raise DatabaseMigrationError(f"integrity_check failed: {exc}") from exc
    if result != [("ok",)]:
        raise DatabaseMigrationError(f"integrity_check failed: {result!r}")
    return "ok"


def _source_uri(source: Path) -> str:
    return f"{source.resolve(strict=True).as_uri()}?mode=ro"


def _add_cleanup_note(error: BaseException, failures: list[str]) -> None:
    if failures:
        error.add_note("Cleanup also failed: " + "; ".join(failures))


def migrate_legacy_database(
    paths: RuntimePaths,
    candidates: Iterable[Path] | None = None,
) -> MigrationResult:
    """Migrate the first existing legacy SQLite database into the runtime path."""
    target = paths.database_path
    if target.exists():
        return MigrationResult(False, None, target, None)

    available_candidates = (
        legacy_database_candidates(paths)
        if candidates is None
        else _unique_candidates(candidates, target=target)
    )
    source = next((candidate for candidate in available_candidates if candidate.is_file()), None)
    if source is None:
        return MigrationResult(False, None, target, None)

    metadata_path = paths.backup_dir / _METADATA_NAME
    temporary_target: Path | None = None
    metadata_existed = False
    previous_metadata: bytes | None = None
    metadata_published = False

    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        for suffix in _SQLITE_SIDECAR_SUFFIXES:
            Path(f"{target}{suffix}").unlink(missing_ok=True)
        temporary_target = _temporary_path(
            target.parent,
            prefix=f".{target.name}.migration-",
            suffix=".tmp",
        )

        with (
            closing(sqlite3.connect(_source_uri(source), uri=True)) as source_database,
            closing(sqlite3.connect(temporary_target)) as target_database,
        ):
            source_database.backup(target_database)
            integrity = _check_integrity(target_database)

        metadata_existed = metadata_path.exists()
        if metadata_existed:
            previous_metadata = metadata_path.read_bytes()
        metadata = {
            "source": str(source),
            "target": str(target),
            "migrated_at": datetime.now(UTC).isoformat(),
            "source_size": source.stat().st_size,
            "target_size": temporary_target.stat().st_size,
            "integrity": integrity,
        }
        _write_migration_metadata(metadata_path, metadata)
        metadata_published = True

        os.replace(temporary_target, target)
        logger.info("Migrated legacy SQLite database from %s to %s", source, target)
        return MigrationResult(True, source, target, metadata_path)
    except DatabaseMigrationError as exc:
        cleanup_failures: list[str] = []
        if temporary_target is not None:
            cleanup_failures.extend(_remove_sqlite_artifacts(temporary_target))
        cleanup_failures.extend(_remove_sqlite_artifacts(target))
        if metadata_published:
            cleanup_failures.extend(
                _restore_metadata(
                    metadata_path,
                    existed=metadata_existed,
                    previous_content=previous_metadata,
                )
            )
        _add_cleanup_note(exc, cleanup_failures)
        raise
    except Exception as exc:
        cleanup_failures = []
        if temporary_target is not None:
            cleanup_failures.extend(_remove_sqlite_artifacts(temporary_target))
        cleanup_failures.extend(_remove_sqlite_artifacts(target))
        if metadata_published:
            cleanup_failures.extend(
                _restore_metadata(
                    metadata_path,
                    existed=metadata_existed,
                    previous_content=previous_metadata,
                )
            )
        error = DatabaseMigrationError(
            f"Failed to migrate legacy database from {source} to {target}: {exc}"
        )
        _add_cleanup_note(error, cleanup_failures)
        raise error from exc
