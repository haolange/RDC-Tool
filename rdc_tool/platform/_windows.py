"""Windows primitives behind the platform contracts."""

from __future__ import annotations

import ctypes
import errno
import msvcrt
import os
import subprocess
import uuid
from ctypes import wintypes
from functools import cache
from pathlib import Path
from typing import Any

from rdc_tool.platform.dxc import DxcError

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
        # Keep the replay worker and its redirected diagnostics off the desktop.
        return {"creationflags": subprocess.CREATE_NEW_CONSOLE | subprocess.CREATE_NEW_PROCESS_GROUP,
                "startupinfo": _hidden_window()}
    # ADB can exit successfully with empty redirected output when started with
    # CREATE_NO_WINDOW or when it inherits a console from a background process.
    return {"creationflags": subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
            "startupinfo": _hidden_window()}


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


class _Guid(ctypes.Structure):
    _fields_ = [("data1", ctypes.c_uint32), ("data2", ctypes.c_uint16),
                ("data3", ctypes.c_uint16), ("data4", ctypes.c_ubyte * 8)]


def _guid(value: str) -> _Guid:
    return _Guid.from_buffer_copy(uuid.UUID(value).bytes_le)


def _method(obj: ctypes.c_void_p, slot: int, result: object, *args: object) -> object:
    table = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    return ctypes.WINFUNCTYPE(result, ctypes.c_void_p, *args)(table[slot])


def _diagnostic_line(source: str, diagnostics: str) -> int | None:
    # DXC's IR parser often returns the source line and caret, but no line number.
    lines = diagnostics.splitlines()
    for index in range(1, len(lines)):
        if lines[index].strip().startswith("^"):
            matches = [number for number, value in enumerate(source.splitlines(), 1)
                       if value == lines[index - 1]]
            if len(matches) == 1:
                return matches[0]
    return None


def assemble_and_validate_dxil(library: Path, source: str) -> bytes:
    dll = ctypes.WinDLL(str(library))
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetModuleFileNameW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_uint]
    kernel.GetModuleFileNameW.restype = ctypes.c_uint
    loaded = ctypes.create_unicode_buffer(32768)
    if not kernel.GetModuleFileNameW(dll._handle, loaded, len(loaded)) or Path(loaded.value).resolve() != library.resolve():
        raise OSError(f"Loaded DXC library does not match the selected path: {loaded.value}")
    create = dll.DxcCreateInstance
    create.argtypes = [ctypes.POINTER(_Guid), ctypes.POINTER(_Guid), ctypes.POINTER(ctypes.c_void_p)]
    create.restype = ctypes.c_int32
    owned: list[ctypes.c_void_p] = []

    def check(stage: str, status: int) -> None:
        if status < 0:
            raise DxcError(stage, f"{stage} HRESULT=0x{status & 0xffffffff:08x}")

    def new(stage: str, clsid: str, iid: str) -> ctypes.c_void_p:
        a, b, obj = _guid(clsid), _guid(iid), ctypes.c_void_p()
        check(stage, create(ctypes.byref(a), ctypes.byref(b), ctypes.byref(obj)))
        if not obj.value:
            raise DxcError(stage, "DXC returned a null interface")
        owned.append(obj)
        return obj

    def blob_bytes(obj: ctypes.c_void_p) -> bytes:
        ptr = _method(obj, 3, ctypes.c_void_p)(obj)
        size = _method(obj, 4, ctypes.c_size_t)(obj)
        return ctypes.string_at(ptr, size) if size else b""

    def result_blob(stage: str, result: ctypes.c_void_p) -> ctypes.c_void_p:
        status = ctypes.c_int32()
        check(stage, _method(result, 3, ctypes.c_int32, ctypes.POINTER(ctypes.c_int32))(
            result, ctypes.byref(status)))
        errors = ctypes.c_void_p()
        check(stage, _method(result, 5, ctypes.c_int32, ctypes.POINTER(ctypes.c_void_p))(
            result, ctypes.byref(errors)))
        diagnostics = ""
        if errors.value:
            owned.append(errors)
            diagnostics = blob_bytes(errors).decode("utf-8", errors="replace").rstrip("\0")
        if status.value < 0:
            raise DxcError(stage, diagnostics or f"DXC failed: 0x{status.value & 0xffffffff:08x}",
                           _diagnostic_line(source, diagnostics) if stage == "assembly" else None)
        blob = ctypes.c_void_p()
        check(stage, _method(result, 4, ctypes.c_int32, ctypes.POINTER(ctypes.c_void_p))(
            result, ctypes.byref(blob)))
        if not blob.value:
            raise DxcError(stage, "DXC returned no output")
        owned.append(blob)
        return blob

    try:
        utils = new("assembly", "6245D6AF-66E0-48FD-80B4-4D271796748C", "4605C4CB-2019-492A-ADA4-65F20BB7D67F")
        assembler = new("assembly", "D728DB68-F903-4F80-94CD-DCCF76EC7151", "091f7a26-1c1f-4948-904b-e6e3a8a771d5")
        validator = new("validation", "8CA3E215-F728-4CF3-8CDD-88AF917587A1", "A6E82BD2-1FD7-4826-9811-2857E797F49A")
        raw = source.encode("utf-8")
        buf = ctypes.create_string_buffer(raw)
        input_blob = ctypes.c_void_p()
        check("assembly", _method(utils, 6, ctypes.c_int32, ctypes.c_void_p, ctypes.c_uint32,
                                  ctypes.c_uint32, ctypes.POINTER(ctypes.c_void_p))(
                                      utils, buf, len(raw), 65001, ctypes.byref(input_blob)))
        owned.append(input_blob)
        assembled = ctypes.c_void_p()
        check("assembly", _method(assembler, 3, ctypes.c_int32, ctypes.c_void_p,
                                   ctypes.POINTER(ctypes.c_void_p))(assembler, input_blob, ctypes.byref(assembled)))
        owned.append(assembled)
        module = result_blob("assembly", assembled)
        validated = ctypes.c_void_p()
        check("validation", _method(validator, 3, ctypes.c_int32, ctypes.c_void_p, ctypes.c_uint32,
                                    ctypes.POINTER(ctypes.c_void_p))(validator, module, 0, ctypes.byref(validated)))
        owned.append(validated)
        output = blob_bytes(result_blob("validation", validated))
        if len(output) < 20 or output[:4] != b"DXBC" or not any(output[4:20]):
            raise DxcError("validation", "DXC validator returned an unsigned container")
        return output
    finally:
        for obj in reversed(owned):
            if obj.value:
                _method(obj, 2, ctypes.c_uint32)(obj)
