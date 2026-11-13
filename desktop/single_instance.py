"""Prevent two desktop processes from sharing the automation browser."""

from __future__ import annotations

import ctypes
import hashlib
import os
import tempfile
from collections.abc import Callable
from ctypes import wintypes
from pathlib import Path


MUTEX_NAME = r"Global\QianNiuAutoListingDesktop"
_ERROR_ACCESS_DENIED = 5
_ERROR_ALREADY_EXISTS = 183


class InstanceLock:
    def __init__(self, release: Callable[[], object]):
        self._release: Callable[[], object] | None = release

    def close(self) -> None:
        release, self._release = self._release, None
        if release is not None:
            release()


def acquire(name: str = MUTEX_NAME) -> InstanceLock | None:
    """Return a process-lifetime lock, or None if another instance owns it."""
    if os.name == "nt":
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
        kernel.CreateMutexW.restype = wintypes.HANDLE
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.CloseHandle.restype = wintypes.BOOL
        handle = kernel.CreateMutexW(None, False, name)
        error = ctypes.get_last_error()
        if not handle:
            if error == _ERROR_ACCESS_DENIED:
                return None
            raise ctypes.WinError(error)
        if error == _ERROR_ALREADY_EXISTS:
            kernel.CloseHandle(handle)
            return None
        return InstanceLock(lambda: kernel.CloseHandle(handle))

    # Keep source runs on non-Windows hosts serialized too.
    import fcntl

    lock_path = Path(tempfile.gettempdir()) / (
        "qianniu-desktop-" + hashlib.sha256(name.encode("utf-8")).hexdigest() + ".lock"
    )
    stream = lock_path.open("a+b")
    try:
        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        stream.close()
        return None
    except Exception:
        stream.close()
        raise
    return InstanceLock(stream.close)


def activate_existing_window() -> None:
    """Bring the running window forward without keeping the second process alive."""
    if os.name != "nt":
        print("千牛自动上架已在运行，请切换到已有窗口。")
        return
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
    user32.FindWindowW.restype = wintypes.HWND
    user32.IsIconic.argtypes = [wintypes.HWND]
    user32.IsIconic.restype = wintypes.BOOL
    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    window = user32.FindWindowW(None, "千牛自动上架")
    if window:
        if user32.IsIconic(window):
            user32.ShowWindow(window, 9)  # SW_RESTORE
        user32.SetForegroundWindow(window)
