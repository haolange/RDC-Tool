"""Windows primitives behind the platform contracts."""

from __future__ import annotations

import ctypes
import errno
import msvcrt
import os
import subprocess
from ctypes import wintypes
from functools import cache
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


_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_STILL_ACTIVE = 259
_ERROR_INVALID_PARAMETER = 87


@cache
def _kernel32() -> Any:
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel.GetExitCodeProcess.restype = wintypes.BOOL
    kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
    kernel.GetProcessTimes.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    kernel.GetCommandLineW.restype = ctypes.c_wchar_p
    return kernel


def process_birth(pid: int) -> str | None:
    kernel = _kernel32()
    handle = kernel.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        error = ctypes.get_last_error()
        if error == _ERROR_INVALID_PARAMETER:
            return None
        raise OSError(error, "process identity unavailable")
    try:
        code = wintypes.DWORD()
        if not kernel.GetExitCodeProcess(handle, ctypes.byref(code)):
            raise OSError(ctypes.get_last_error(), "process exit state unavailable")
        if code.value != _STILL_ACTIVE:
            return None
        created, exited, kernel_time, user_time = (wintypes.FILETIME() for _ in range(4))
        if not kernel.GetProcessTimes(handle, ctypes.byref(created), ctypes.byref(exited),
                                      ctypes.byref(kernel_time), ctypes.byref(user_time)):
            raise OSError(ctypes.get_last_error(), "process birth unavailable")
        return f"windows-filetime:{(created.dwHighDateTime << 32) | created.dwLowDateTime}"
    finally:
        kernel.CloseHandle(handle)


def kill_tree(pid: int) -> bool:
    try:
        completed = subprocess.run(["taskkill", "/PID", str(pid), "/F", "/T"], stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL, check=False, timeout=3,
                                   creationflags=subprocess.CREATE_NO_WINDOW)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return completed.returncode == 0


def _hidden_window() -> subprocess.STARTUPINFO:
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = subprocess.SW_HIDE
    return startup


def popen_options(profile: str) -> dict[str, Any]:
    if profile == "daemon":
        return {"creationflags": subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP}
    if profile == "worker":
        # ADB children need a real console for reliable captured output: the
        # worker owns a hidden one and its children inherit it.
        return {"creationflags": subprocess.CREATE_NEW_CONSOLE | subprocess.CREATE_NEW_PROCESS_GROUP,
                "startupinfo": _hidden_window()}
    # Tools need normal redirected stdio, not CREATE_NO_WINDOW or an explicit
    # console; hide any console Windows creates.
    return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP, "startupinfo": _hidden_window()}


class _ProcessMemoryCounters(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("PageFaultCount", wintypes.DWORD),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
    ]


def memory_bytes() -> int | None:
    counters = _ProcessMemoryCounters()
    counters.cb = ctypes.sizeof(_ProcessMemoryCounters)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    if not psapi.GetProcessMemoryInfo(ctypes.windll.kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
        return None
    return int(counters.WorkingSetSize)


def raw_command_line() -> str | None:
    return str(_kernel32().GetCommandLineW() or "")


def launcher_argv(launcher: str) -> list[str]:
    system_root = os.environ.get("SystemRoot") or os.environ.get("WINDIR") or r"C:\Windows"
    return [str(Path(system_root) / "System32" / "cmd.exe"), "/c", launcher]
