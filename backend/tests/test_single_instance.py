from __future__ import annotations

import importlib
import threading
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
    assert not lock_path.exists()


def test_file_fallback_recovers_a_stale_or_invalid_lock(tmp_path: Path) -> None:
    module = _single_instance_module()
    lock_path = tmp_path / "desktop.lock"
    lock_path.write_text("not-a-process-id", encoding="ascii")
    guard = module.SingleInstanceGuard(lock_path, platform_name="linux")

    assert guard.acquire() is True

    guard.release()
    assert not lock_path.exists()


def test_file_release_is_idempotent_and_does_not_delete_a_replaced_lock(
    tmp_path: Path,
) -> None:
    module = _single_instance_module()
    lock_path = tmp_path / "desktop.lock"
    guard = module.SingleInstanceGuard(lock_path, platform_name="linux")
    assert guard.acquire() is True
    lock_path.write_text("replacement-owner", encoding="ascii")

    guard.release()
    guard.release()

    assert lock_path.read_text(encoding="ascii") == "replacement-owner"


def test_file_fallback_atomically_publishes_owner_before_contenders(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _single_instance_module()
    lock_path = tmp_path / "desktop.lock"
    first = module.SingleInstanceGuard(lock_path, platform_name="linux")
    second = module.SingleInstanceGuard(lock_path, platform_name="linux")
    write_entered = threading.Event()
    release_write = threading.Event()
    results: dict[str, bool] = {}
    real_write = module.os.write

    def controlled_write(descriptor: int, data: bytes) -> int:
        if threading.current_thread().name == "first-lock-owner":
            write_entered.set()
            assert release_write.wait(1)
        return real_write(descriptor, data)

    monkeypatch.setattr(module.os, "write", controlled_write)

    def acquire_first() -> None:
        results["first"] = first.acquire()

    owner = threading.Thread(target=acquire_first, name="first-lock-owner")
    owner.start()
    assert write_entered.wait(1)
    try:
        assert not lock_path.exists()
        results["second"] = second.acquire()
    finally:
        release_write.set()
        owner.join(1)

    try:
        assert not owner.is_alive()
        assert sorted(results.values()) == [False, True]
    finally:
        first.release()
        second.release()
