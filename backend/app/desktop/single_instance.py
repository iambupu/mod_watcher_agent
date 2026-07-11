from __future__ import annotations

import ctypes
import errno
import os
import sys
import uuid
from contextlib import suppress
from pathlib import Path
from typing import Protocol

_DEFAULT_MUTEX_NAME = r"Local\ModWatcherAgentDesktop"
_ERROR_ALREADY_EXISTS = 183


class _MutexBackend(Protocol):
    def acquire(self, name: str) -> object | None: ...

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


class SingleInstanceGuard:
    """Hold the process-wide desktop instance mutex or a recoverable file lock."""

    def __init__(
        self,
        lock_path: Path,
        *,
        mutex_name: str = _DEFAULT_MUTEX_NAME,
        platform_name: str | None = None,
        mutex_backend: _MutexBackend | None = None,
    ) -> None:
        self.lock_path = Path(lock_path)
        self.mutex_name = mutex_name
        self._platform_name = platform_name or sys.platform
        self._mutex_backend = mutex_backend
        self._mutex_handle: object | None = None
        self._file_token: str | None = None
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

        token = self._file_token
        self._file_token = None
        if token is None:
            return
        try:
            current = self.lock_path.read_text(encoding="ascii")
        except (FileNotFoundError, OSError, UnicodeError):
            return
        if current != token:
            return
        with suppress(FileNotFoundError):
            self.lock_path.unlink()

    def __enter__(self) -> SingleInstanceGuard:
        if not self.acquire():
            raise RuntimeError("Another desktop instance is already running")
        return self

    def __exit__(self, *_args: object) -> None:
        self.release()

    def _acquire_file_lock(self) -> bool:
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        token = f"{os.getpid()}:{uuid.uuid4().hex}"
        staging_path = self.lock_path.with_name(f".{self.lock_path.name}.{uuid.uuid4().hex}.tmp")
        descriptor = os.open(
            staging_path,
            os.O_CREAT | os.O_EXCL | os.O_WRONLY,
            0o600,
        )
        try:
            try:
                os.write(descriptor, token.encode("ascii"))
            finally:
                os.close(descriptor)

            for _attempt in range(2):
                try:
                    os.link(staging_path, self.lock_path)
                except FileExistsError:
                    if not self._remove_stale_file_lock():
                        return False
                    continue
                self._file_token = token
                self._acquired = True
                return True
            return False
        finally:
            with suppress(FileNotFoundError):
                staging_path.unlink()

    def _remove_stale_file_lock(self) -> bool:
        try:
            owner = self.lock_path.read_text(encoding="ascii")
        except FileNotFoundError:
            return True
        except (OSError, UnicodeError):
            owner = ""

        try:
            pid = int(owner.partition(":")[0])
        except ValueError:
            pid = -1
        if pid > 0 and _process_is_alive(pid):
            return False

        try:
            if self.lock_path.read_text(encoding="ascii") != owner:
                return False
            self.lock_path.unlink()
        except FileNotFoundError:
            pass
        except (OSError, UnicodeError):
            return False
        return True


def _process_is_alive(pid: int) -> bool:
    if pid == os.getpid():
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError as exc:
        return exc.errno == errno.EPERM
    return True
