from __future__ import annotations

import ctypes
import errno
import os
import sys
import uuid
from pathlib import Path
from typing import Protocol

_DEFAULT_MUTEX_NAME = r"Local\ModWatcherAgentDesktop"
_ERROR_ALREADY_EXISTS = 183


class _MutexBackend(Protocol):
    def acquire(self, name: str) -> object | None: ...

    def release(self, handle: object) -> None: ...


class _FileLockBackend(Protocol):
    def acquire(self, path: Path, diagnostic: bytes) -> object | None: ...

    def release(self, handle: object) -> None: ...


class _Win32MutexBackend:
    def __init__(self) -> None:
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._kernel32.CreateMutexW.argtypes = (ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p)
        self._kernel32.CreateMutexW.restype = ctypes.c_void_p
        self._kernel32.CloseHandle.argtypes = (ctypes.c_void_p,)
        self._kernel32.CloseHandle.restype = ctypes.c_int

    def acquire(self, name: str) -> object | None:
        ctypes.set_last_error(0)
        handle = self._kernel32.CreateMutexW(None, False, name)
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        if ctypes.get_last_error() == _ERROR_ALREADY_EXISTS:
            self._kernel32.CloseHandle(handle)
            return None
        return handle

    def release(self, handle: object) -> None:
        if not self._kernel32.CloseHandle(handle):
            raise ctypes.WinError(ctypes.get_last_error())


def _open_lock_file(path: Path) -> int:
    flags = os.O_CREAT | os.O_RDWR
    flags |= getattr(os, "O_BINARY", 0)
    return os.open(path, flags, 0o600)


def _write_lock_diagnostic(descriptor: int, diagnostic: bytes) -> None:
    os.lseek(descriptor, 0, os.SEEK_SET)
    remaining = memoryview(diagnostic)
    while remaining:
        written = os.write(descriptor, remaining)
        if written <= 0:
            raise OSError(errno.EIO, "Unable to write the desktop lock diagnostic")
        remaining = remaining[written:]
    os.ftruncate(descriptor, len(diagnostic))


class _FcntlFileLockBackend:
    def acquire(self, path: Path, diagnostic: bytes) -> object | None:
        import fcntl

        descriptor = _open_lock_file(path)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            os.close(descriptor)
            if exc.errno in {errno.EACCES, errno.EAGAIN}:
                return None
            raise
        try:
            _write_lock_diagnostic(descriptor, diagnostic)
        except BaseException:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            finally:
                os.close(descriptor)
            raise
        return descriptor

    def release(self, handle: object) -> None:
        import fcntl

        descriptor = int(handle)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)


class _MsvcrtFileLockBackend:
    def acquire(self, path: Path, diagnostic: bytes) -> object | None:
        import msvcrt

        descriptor = _open_lock_file(path)
        try:
            if os.fstat(descriptor).st_size == 0:
                os.write(descriptor, b"\0")
            os.lseek(descriptor, 0, os.SEEK_SET)
            msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            os.close(descriptor)
            if exc.errno in {errno.EACCES, errno.EAGAIN, errno.EDEADLK}:
                return None
            raise
        try:
            _write_lock_diagnostic(descriptor, diagnostic)
        except BaseException:
            try:
                os.lseek(descriptor, 0, os.SEEK_SET)
                msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
            finally:
                os.close(descriptor)
            raise
        return descriptor

    def release(self, handle: object) -> None:
        import msvcrt

        descriptor = int(handle)
        try:
            os.lseek(descriptor, 0, os.SEEK_SET)
            msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
        finally:
            os.close(descriptor)


def _default_file_lock_backend() -> _FileLockBackend:
    if os.name == "nt":
        return _MsvcrtFileLockBackend()
    return _FcntlFileLockBackend()


class SingleInstanceGuard:
    """Hold the process-wide desktop instance mutex or a recoverable file lock."""

    def __init__(
        self,
        lock_path: Path,
        *,
        mutex_name: str = _DEFAULT_MUTEX_NAME,
        platform_name: str | None = None,
        mutex_backend: _MutexBackend | None = None,
        file_lock_backend: _FileLockBackend | None = None,
    ) -> None:
        self.lock_path = Path(lock_path)
        self.mutex_name = mutex_name
        self._platform_name = platform_name or sys.platform
        self._mutex_backend = mutex_backend
        self._file_lock_backend = file_lock_backend
        self._mutex_handle: object | None = None
        self._file_lock_handle: object | None = None
        self._acquired = False

    def acquire(self) -> bool:
        if self._acquired:
            return True
        if self._platform_name == "win32":
            backend = self._mutex_backend or _Win32MutexBackend()
            self._mutex_backend = backend
            handle = backend.acquire(self.mutex_name)
            if handle is None:
                return False
            self._mutex_handle = handle
            self._acquired = True
            return True
        return self._acquire_file_lock()

    def release(self) -> None:
        if not self._acquired:
            return
        self._acquired = False

        handle = self._mutex_handle
        self._mutex_handle = None
        if handle is not None:
            backend = self._mutex_backend
            if backend is not None:
                backend.release(handle)
            return

        handle = self._file_lock_handle
        self._file_lock_handle = None
        if handle is None:
            return
        backend = self._file_lock_backend
        if backend is not None:
            backend.release(handle)

    def __enter__(self) -> SingleInstanceGuard:
        if not self.acquire():
            raise RuntimeError("Another desktop instance is already running")
        return self

    def __exit__(self, *_args: object) -> None:
        self.release()

    def _acquire_file_lock(self) -> bool:
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        backend = self._file_lock_backend or _default_file_lock_backend()
        self._file_lock_backend = backend
        diagnostic = f"{os.getpid()}:{uuid.uuid4().hex}".encode("ascii")
        handle = backend.acquire(self.lock_path, diagnostic)
        if handle is None:
            return False
        self._file_lock_handle = handle
        self._acquired = True
        return True
