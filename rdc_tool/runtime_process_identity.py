"""Read process birth identities without opening or recovering a replay."""

from __future__ import annotations

import ctypes
import os
import sys
from pathlib import Path
from typing import Any


def _process_birth(pid: int) -> str:
    if sys.platform == "win32":
        from ctypes import wintypes

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
        kernel.GetProcessTimes.restype = wintypes.BOOL
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.CloseHandle.restype = wintypes.BOOL
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            raise OSError(ctypes.get_last_error(), "process identity unavailable")
        try:
            created, exited, kernel_time, user_time = (wintypes.FILETIME() for _ in range(4))
            if not kernel.GetProcessTimes(handle, ctypes.byref(created), ctypes.byref(exited),
                                          ctypes.byref(kernel_time), ctypes.byref(user_time)):
                raise OSError(ctypes.get_last_error(), "process birth unavailable")
            value = (created.dwHighDateTime << 32) | created.dwLowDateTime
            if value <= 0 or exited.dwHighDateTime or exited.dwLowDateTime:
                raise OSError("process is not live")
            return f"windows-filetime:{value}"
        finally:
            kernel.CloseHandle(handle)
    if sys.platform.startswith("linux"):
        boot = Path("/proc/sys/kernel/random/boot_id").read_text(encoding="ascii").strip()
        stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
        fields = stat[stat.rindex(")") + 2:].split()
        if not boot or fields[0] in {"Z", "X"} or int(fields[19]) <= 0:
            raise OSError("process is not live")
        return f"linux-start-ticks:{boot}:{fields[19]}"
    raise OSError("process birth unsupported on this platform")


def runtime_process_identity() -> dict[str, Any]:
    """Only the actual daemon child may attest its own and its parent's birth."""
    raw_parent = os.environ.get("RDC_TOOL_DAEMON_PID", "")
    try:
        parent = int(raw_parent)
    except ValueError:
        return {"status": "unavailable", "reason": "not_daemon_worker"}
    if parent <= 0 or parent != os.getppid():
        return {"status": "unavailable", "reason": "daemon_parent_mismatch"}
    worker = os.getpid()
    try:
        daemon_birth = _process_birth(parent)
        worker_birth = _process_birth(worker)
    except (OSError, ValueError, IndexError) as exc:
        return {"status": "unavailable", "reason": "process_birth_unavailable", "detail": str(exc)}
    return {
        "status": "available",
        "daemon": {"pid": parent, "start_generation": daemon_birth},
        "worker": {"pid": worker, "start_generation": worker_birth},
    }
