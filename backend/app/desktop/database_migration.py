from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
import tempfile
from collections.abc import Iterable, Iterator
from contextlib import closing, contextmanager, suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import BinaryIO

from app.runtime_paths import RuntimePaths

logger = logging.getLogger(__name__)

_DATABASE_NAME = "mod_watcher.db"
_LOCK_NAME = "database-migration.lock"
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


def _lock_file(file: BinaryIO) -> None:
    file.seek(0)
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(file.fileno(), msvcrt.LK_NBLCK, 1)
        return

    import fcntl

    fcntl.flock(file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock_file(file: BinaryIO) -> None:
    file.seek(0)
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(file.fileno(), msvcrt.LK_UNLCK, 1)
        return

    import fcntl

    fcntl.flock(file.fileno(), fcntl.LOCK_UN)


@contextmanager
def _migration_lock(lock_path: Path) -> Iterator[None]:
    try:
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock_file = lock_path.open("a+b", buffering=0)
    except OSError as exc:
        raise DatabaseMigrationError(f"Unable to prepare database migration lock: {exc}") from exc

    with lock_file:
        try:
            lock_file.seek(0, os.SEEK_END)
            if lock_file.tell() == 0:
                lock_file.write(b"\0")
                lock_file.flush()
        except OSError as exc:
            raise DatabaseMigrationError(
                f"Unable to initialize database migration lock: {exc}"
            ) from exc

        try:
            _lock_file(lock_file)
        except OSError as exc:
            raise DatabaseMigrationError(
                f"Database migration is already in progress: {lock_path}"
            ) from exc

        try:
            yield
        finally:
            with suppress(OSError):
                _unlock_file(lock_file)


def _remove_owned_stale_temporary_files(target: Path) -> None:
    escaped_target = re.escape(target.name)
    pattern = re.compile(
        rf"^(?P<base>\.{escaped_target}\.migration-[A-Za-z0-9_-]+\.tmp)"
        rf"(?:-(?:journal|shm|wal))?$"
    )
    stale_bases: set[Path] = set()
    for artifact in target.parent.iterdir():
        match = pattern.fullmatch(artifact.name)
        if match is not None:
            stale_bases.add(target.parent / match.group("base"))

    cleanup_failures: list[str] = []
    for stale_base in stale_bases:
        cleanup_failures.extend(_remove_sqlite_artifacts(stale_base))
    if cleanup_failures:
        raise DatabaseMigrationError(
            "Unable to remove stale database migration files: " + "; ".join(cleanup_failures)
        )


def _remove_owned_stale_metadata_files(metadata_path: Path) -> None:
    metadata_directory = metadata_path.parent
    if not metadata_directory.is_dir():
        return

    escaped_name = re.escape(metadata_path.name)
    pattern = re.compile(rf"^\.{escaped_name}\.[A-Za-z0-9_-]+\.tmp$")
    cleanup_failures: list[str] = []
    for artifact in metadata_directory.iterdir():
        if (
            pattern.fullmatch(artifact.name) is None
            or artifact.is_symlink()
            or not artifact.is_file()
        ):
            continue
        try:
            artifact.unlink()
        except OSError as exc:
            cleanup_failures.append(f"{artifact}: {exc}")
    if cleanup_failures:
        raise DatabaseMigrationError(
            "Unable to remove stale migration metadata files: " + "; ".join(cleanup_failures)
        )


def _publish_without_overwrite(source: Path, target: Path) -> None:
    if os.name == "nt":
        os.rename(source, target)
        return

    os.link(source, target)
    try:
        source.unlink()
    except OSError as exc:
        logger.warning(
            "Published migrated database at %s but could not remove temporary file %s: %s",
            target,
            source,
            exc,
        )


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


def _cleanup_failed_attempt(
    temporary_target: Path | None,
    *,
    metadata_path: Path,
    metadata_published: bool,
    metadata_existed: bool,
    previous_metadata: bytes | None,
) -> list[str]:
    cleanup_failures: list[str] = []
    if temporary_target is not None:
        cleanup_failures.extend(_remove_sqlite_artifacts(temporary_target))
    if metadata_published:
        cleanup_failures.extend(
            _restore_metadata(
                metadata_path,
                existed=metadata_existed,
                previous_content=previous_metadata,
            )
        )
    return cleanup_failures


def _migrate_locked_database(
    paths: RuntimePaths,
    *,
    source: Path,
) -> MigrationResult:
    target = paths.database_path
    metadata_path = paths.backup_dir / _METADATA_NAME
    temporary_target: Path | None = None
    metadata_existed = False
    previous_metadata: bytes | None = None
    metadata_published = False

    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        _remove_owned_stale_temporary_files(target)
        _remove_owned_stale_metadata_files(metadata_path)
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

        if target.exists():
            raise DatabaseMigrationError(f"Target database appeared during migration: {target}")
        _publish_without_overwrite(temporary_target, target)
    except DatabaseMigrationError as exc:
        cleanup_failures = _cleanup_failed_attempt(
            temporary_target,
            metadata_path=metadata_path,
            metadata_published=metadata_published,
            metadata_existed=metadata_existed,
            previous_metadata=previous_metadata,
        )
        _add_cleanup_note(exc, cleanup_failures)
        raise
    except Exception as exc:
        cleanup_failures = _cleanup_failed_attempt(
            temporary_target,
            metadata_path=metadata_path,
            metadata_published=metadata_published,
            metadata_existed=metadata_existed,
            previous_metadata=previous_metadata,
        )
        error = DatabaseMigrationError(
            f"Failed to migrate legacy database from {source} to {target}: {exc}"
        )
        _add_cleanup_note(error, cleanup_failures)
        raise error from exc

    logger.info("Migrated legacy SQLite database from %s to %s", source, target)
    return MigrationResult(True, source, target, metadata_path)


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

    with _migration_lock(paths.runtime_dir / _LOCK_NAME):
        if target.exists():
            return MigrationResult(False, None, target, None)
        return _migrate_locked_database(paths, source=source)
