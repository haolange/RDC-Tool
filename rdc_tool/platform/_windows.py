"""Windows primitives behind the platform contracts."""

from __future__ import annotations

import ctypes
import errno
import msvcrt
import os
from pathlib import Path
from typing import Any

_ERROR_LOCK_VIOLATION = 33


def try_lock(fd: int) -> bool:
    # LK_LOCK silently gives up after ~10 s, so only non-blocking attempts are used.
    os.lseek(fd, 0, os.SEEK_SET)
    try:
        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
    except OSError as exc:
        if exc.errno == errno.EACCES and getattr(exc, "winerror", None) in (None, _ERROR_LOCK_VIOLATION):
            return False
        raise
    return True


def unlock(fd: int) -> None:
    os.lseek(fd, 0, os.SEEK_SET)
    msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)


_DLL_DIRECTORIES: dict[str, Any] = {}


def prepare_loader(native_library: Path, binding_dir: Path, report: Any) -> None:
    for directory in (native_library.parent, binding_dir):
        key = os.path.normcase(str(directory.resolve()))
        if key in _DLL_DIRECTORIES:
            continue
        if not directory.is_dir():
            report.errors.append(f"missing directory: {directory}")
            continue
        try:
            _DLL_DIRECTORIES[key] = os.add_dll_directory(str(directory))
        except OSError as exc:
            report.errors.append(f"{directory}: {exc}")
            continue
        report.prepared.append(str(directory))
    native_dir = os.path.normcase(str(native_library.parent.resolve()))
    entries = [entry for entry in os.environ.get("PATH", "").split(os.pathsep) if entry]
    if not any(os.path.normcase(os.path.abspath(entry)) == native_dir for entry in entries):
        os.environ["PATH"] = os.pathsep.join([str(native_library.parent), *entries])


def loaded_library_path(file_name: str) -> Path | None:
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetModuleHandleW.argtypes = [ctypes.c_wchar_p]
    kernel.GetModuleHandleW.restype = ctypes.c_void_p
    kernel.GetModuleFileNameW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_uint]
    kernel.GetModuleFileNameW.restype = ctypes.c_uint
    handle = kernel.GetModuleHandleW(file_name)
    if not handle:
        return None
    buffer = ctypes.create_unicode_buffer(32768)
    if not kernel.GetModuleFileNameW(handle, buffer, len(buffer)):
        raise OSError(f"loaded {file_name} path is unavailable")
    return Path(buffer.value).resolve()
