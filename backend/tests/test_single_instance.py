from __future__ import annotations

import importlib
import threading
import time
from pathlib import Path
from types import ModuleType

import pytest


def _single_instance_module() -> ModuleType:
    try:
        return importlib.import_module("app.desktop.single_instance")
    except ModuleNotFoundError:
        pytest.fail("app.desktop.single_instance is not implemented", pytrace=False)


class FakeMutexBackend:
    def __init__(self, handles: list[object | None]) -> None:
        self.handles = iter(handles)
        self.names: list[str] = []
        self.released: list[object] = []

    def acquire(self, name: str) -> object | None:
        self.names.append(name)
        return next(self.handles)

    def release(self, handle: object) -> None:
        self.released.append(handle)


class FakeFileLockBackend:
    def __init__(self, *, release_error: BaseException | None = None) -> None:
        self.release_error = release_error
        self.held_handle: object | None = None
        self.acquisitions: list[tuple[Path, bytes]] = []
        self.released: list[object] = []

    def acquire(self, path: Path, diagnostic: bytes) -> object | None:
        self.acquisitions.append((path, diagnostic))
        if self.held_handle is not None:
            return None
        self.held_handle = object()
        return self.held_handle

    def release(self, handle: object) -> None:
        self.released.append(handle)
        self.held_handle = None
        if self.release_error is not None:
            raise self.release_error


def test_windows_guard_uses_named_mutex_and_releases_it_once(tmp_path: Path) -> None:
    module = _single_instance_module()
    handle = object()
    backend = FakeMutexBackend([handle])
    guard = module.SingleInstanceGuard(
        tmp_path / "desktop.lock",
        platform_name="win32",
        mutex_backend=backend,
    )

    assert guard.acquire() is True
    assert guard.acquire() is True
    guard.release()
    guard.release()

    assert backend.names == [r"Local\ModWatcherAgentDesktop"]
    assert backend.released == [handle]


def test_existing_windows_mutex_reports_second_instance(tmp_path: Path) -> None:
    module = _single_instance_module()
    backend = FakeMutexBackend([None])
    guard = module.SingleInstanceGuard(
        tmp_path / "desktop.lock",
        platform_name="win32",
        mutex_backend=backend,
    )

    assert guard.acquire() is False

    guard.release()
    assert backend.released == []


def test_file_fallback_blocks_a_live_instance_then_allows_reacquire(
    tmp_path: Path,
) -> None:
    module = _single_instance_module()
    lock_path = tmp_path / "desktop.lock"
    first = module.SingleInstanceGuard(lock_path, platform_name="linux")
    second = module.SingleInstanceGuard(lock_path, platform_name="linux")

    assert first.acquire() is True
    assert second.acquire() is False

    first.release()

    assert second.acquire() is True
    second.release()
    assert lock_path.exists()
    assert lock_path.read_text(encoding="ascii").partition(":")[0].isdigit()


def test_file_fallback_recovers_a_stale_or_invalid_lock(tmp_path: Path) -> None:
    module = _single_instance_module()
    lock_path = tmp_path / "desktop.lock"
    lock_path.write_text("not-a-process-id", encoding="ascii")
    guard = module.SingleInstanceGuard(lock_path, platform_name="linux")

    assert guard.acquire() is True

    guard.release()
    assert lock_path.exists()
    assert lock_path.read_text(encoding="ascii") != "not-a-process-id"


def test_file_release_is_idempotent_and_releases_the_held_handle_once(
    tmp_path: Path,
) -> None:
    module = _single_instance_module()
    lock_path = tmp_path / "desktop.lock"
    backend = FakeFileLockBackend()
    guard = module.SingleInstanceGuard(
        lock_path,
        platform_name="linux",
        file_lock_backend=backend,
    )
    assert guard.acquire() is True

    guard.release()
    guard.release()

    assert len(backend.released) == 1


def test_file_release_error_still_makes_subsequent_release_a_noop(
    tmp_path: Path,
) -> None:
    module = _single_instance_module()
    backend = FakeFileLockBackend(release_error=RuntimeError("unlock failed"))
    guard = module.SingleInstanceGuard(
        tmp_path / "desktop.lock",
        platform_name="linux",
        file_lock_backend=backend,
    )
    assert guard.acquire() is True

    with pytest.raises(RuntimeError, match="unlock failed"):
        guard.release()
    guard.release()

    assert len(backend.released) == 1


def test_file_fallback_holds_the_backend_lock_until_release(tmp_path: Path) -> None:
    module = _single_instance_module()
    lock_path = tmp_path / "desktop.lock"
    backend = FakeFileLockBackend()
    first = module.SingleInstanceGuard(
        lock_path,
        platform_name="linux",
        file_lock_backend=backend,
    )
    second = module.SingleInstanceGuard(
        lock_path,
        platform_name="linux",
        file_lock_backend=backend,
    )

    assert first.acquire() is True
    assert second.acquire() is False
    assert len(backend.acquisitions) == 2
    assert all(path == lock_path for path, _diagnostic in backend.acquisitions)
    assert all(diagnostic for _path, diagnostic in backend.acquisitions)

    first.release()
    assert second.acquire() is True
    second.release()


def test_stale_file_recovery_cannot_let_two_contenders_both_acquire(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _single_instance_module()
    lock_path = tmp_path / "desktop.lock"
    lock_path.write_text("stale-owner", encoding="ascii")
    first = module.SingleInstanceGuard(lock_path, platform_name="linux")
    second = module.SingleInstanceGuard(lock_path, platform_name="linux")
    first_about_to_unlink = threading.Event()
    release_first_unlink = threading.Event()
    first_finished = threading.Event()
    results: dict[str, bool] = {}
    real_unlink = Path.unlink

    def controlled_unlink(path: Path, *args: object, **kwargs: object) -> None:
        if path == lock_path and threading.current_thread().name == "first-contender":
            first_about_to_unlink.set()
            assert release_first_unlink.wait(1)
        real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", controlled_unlink)

    def acquire_first() -> None:
        try:
            results["first"] = first.acquire()
        finally:
            first_finished.set()

    contender = threading.Thread(target=acquire_first, name="first-contender")
    contender.start()
    try:
        deadline = time.monotonic() + 1
        while not first_about_to_unlink.wait(0.01) and not first_finished.is_set():
            if time.monotonic() >= deadline:
                pytest.fail("first contender did not reach a deterministic acquisition point")

        results["second"] = second.acquire()
    finally:
        release_first_unlink.set()
        contender.join(1)

    try:
        assert not contender.is_alive()
        assert sorted(results.values()) == [False, True]
    finally:
        first.release()
        second.release()
