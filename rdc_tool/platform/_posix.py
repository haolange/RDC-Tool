"""POSIX primitives behind the platform contracts."""

from __future__ import annotations

import ctypes
import errno
import fcntl
import os
import signal
from functools import cache
from pathlib import Path
from typing import Any

_LOCK_BUSY = frozenset({errno.EWOULDBLOCK, errno.EAGAIN, errno.EACCES})


def try_lock(fd: int) -> bool:
    # flock is per open file description, matching per-handle Windows locks.
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        if exc.errno in _LOCK_BUSY:
            return False
        raise
    return True


def unlock(fd: int) -> None:
    fcntl.flock(fd, fcntl.LOCK_UN)


_PRELOADED: dict[str, Any] = {}


def prepare_loader(native_library: Path, binding_dir: Path, report: Any) -> None:
    # LD_LIBRARY_PATH cannot change after start-up, so the exact library is
    # preloaded globally and the binding's DT_NEEDED entry resolves to it.
    key = str(native_library.resolve())
    if key in _PRELOADED:
        return
    if not native_library.is_file():
        report.errors.append(f"missing native library: {native_library}")
        return
    try:
        _PRELOADED[key] = ctypes.CDLL(key, mode=ctypes.RTLD_GLOBAL)
    except OSError as exc:
        report.errors.append(f"{native_library}: {exc}")
        return
    report.prepared.append(key)


def loaded_library_path(file_name: str) -> Path | None:
    paths = set()
    for line in Path("/proc/self/maps").read_text(encoding="utf-8", errors="replace").splitlines():
        fields = line.split(None, 5)
        if len(fields) == 6 and Path(fields[5]).name == file_name:
            paths.add(Path(fields[5]).resolve())
    if len(paths) > 1:
        raise OSError(f"multiple {file_name} libraries are loaded: {sorted(map(str, paths))}")
    return next(iter(paths), None)


_PROC = Path("/proc")


@cache
def _boot_id() -> str:
    return (_PROC / "sys/kernel/random/boot_id").read_text(encoding="ascii").strip()


def process_birth(pid: int) -> str | None:
    if not (_PROC / "self/stat").is_file():
        raise OSError("process birth requires /proc")
    try:
        stat = (_PROC / str(pid) / "stat").read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return None
    fields = stat[stat.rindex(")") + 2:].split()
    if fields[0] in {"Z", "X"}:
        return None
    return f"linux-start-ticks:{_boot_id()}:{fields[19]}"


def kill_tree(pid: int) -> bool:
    try:
        group = os.getpgid(pid)
        if group == pid and group != os.getpgrp():
            os.killpg(group, signal.SIGKILL)
        else:
            os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        return False
    return True


def popen_options(profile: str) -> dict[str, Any]:
    # A detached daemon leads its own group; its worker stays in that group so
    # one killpg reaps both, matching taskkill /T on Windows.
    return {"start_new_session": True} if profile == "daemon" else {}


def memory_bytes() -> int | None:
    try:
        status = (_PROC / "self/status").read_text(encoding="ascii", errors="replace")
    except OSError:
        return None
    for line in status.splitlines():
        if line.startswith("VmRSS:"):
            return int(line.split()[1]) * 1024
    return None


def raw_command_line() -> str | None:
    return None


def launcher_argv(launcher: str) -> list[str]:
    return [launcher]
