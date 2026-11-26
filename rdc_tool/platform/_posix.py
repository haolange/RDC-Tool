"""POSIX primitives behind the platform contracts."""

from __future__ import annotations


def assemble_and_validate_dxil(library, source):
    raise OSError("The DXIL compiler is unavailable on this host")

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


def prepare_loader(native_library: Path, binding_dir: Path, report: Any) -> None:
    # The binding's RUNPATH resolves the library as its DT_NEEDED dependency. Loading the library
    # first would run RenderDoc's constructor before the binding's replay marker exists, which
    # makes it install capture hooks and crash during replay, so nothing is preloaded here.
    if not native_library.is_file():
        report.errors.append(f"missing native library: {native_library}")
        return
    if not binding_dir.is_dir():
        report.errors.append(f"missing directory: {binding_dir}")
        return
    report.prepared.append(str(native_library.resolve()))


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


def _stat_fields(pid: int) -> list[str] | None:
    """The /proc stat fields after the command name, or ``None`` once the process is gone."""
    try:
        stat = (_PROC / str(pid) / "stat").read_text(encoding="utf-8", errors="replace")
    except (FileNotFoundError, ProcessLookupError):
        # ESRCH: the process was reaped between open and read. It is gone, not unreadable.
        return None
    return stat[stat.rindex(")") + 2:].split()


def process_birth(pid: int) -> str | None:
    if not (_PROC / "self/stat").is_file():
        raise OSError("process birth requires /proc")
    fields = _stat_fields(pid)
    if fields is None or fields[0] in {"Z", "X"}:
        return None
    return f"linux-start-ticks:{_boot_id()}:{fields[19]}"


def _children(pid: int, session: str) -> list[tuple[int, str]]:
    """Live children of ``pid`` that stayed in its session, with their births.

    A child that started its own session detached itself on purpose (an adb
    server, for example) and is not part of the tree, exactly as a process
    group kill would leave it alone.
    """
    found = []
    for entry in _PROC.iterdir():
        if not entry.name.isdigit():
            continue
        fields = _stat_fields(int(entry.name))
        if fields is None or fields[0] in {"Z", "X"} or fields[1] != str(pid) or fields[3] != session:
            continue
        found.append((int(entry.name), f"linux-start-ticks:{_boot_id()}:{fields[19]}"))
    return found


def _signal_confirmed(pid: int, birth: str, signum: int) -> bool:
    # Re-read the identity right before signalling: a reused PID is never signalled.
    if process_birth(pid) != birth:
        return False
    try:
        os.kill(pid, signum)
    except ProcessLookupError:
        return False
    return True


def kill_tree(pid: int) -> bool:
    try:
        group = os.getpgid(pid)
    except ProcessLookupError:
        return False
    if group == pid and group != os.getpgrp():
        # A detached daemon leads its own group; its worker and tools share it.
        try:
            os.killpg(group, signal.SIGKILL)
        except ProcessLookupError:
            return False
        return True
    # A process inside a shared group (the worker in its daemon's group) is
    # killed with its descendants only. Each process is stopped before its
    # children are read so the tree cannot grow, then the tree is killed
    # leaves first, every signal behind a fresh identity check.
    root_fields = _stat_fields(pid)
    root_birth = process_birth(pid)
    if root_fields is None or root_birth is None or not _signal_confirmed(pid, root_birth, signal.SIGSTOP):
        return False
    session = root_fields[3]
    tree = [(pid, root_birth)]
    index = 0
    while index < len(tree):
        for child, birth in _children(tree[index][0], session):
            if _signal_confirmed(child, birth, signal.SIGSTOP):
                tree.append((child, birth))
        index += 1
    for member, birth in reversed(tree):
        _signal_confirmed(member, birth, signal.SIGKILL)
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
