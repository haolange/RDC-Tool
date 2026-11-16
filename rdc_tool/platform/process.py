"""Process identity, liveness, spawning and termination.

A process is identified by ``(pid, birth)``: the birth token is the OS
creation time, so a reused PID never matches a recorded identity. Every
liveness and kill decision goes through ``probe``. An identity that cannot
be read is ``UNKNOWN``, which is never treated as proof of exit and never
authorizes a kill.
"""

from __future__ import annotations

import os
import subprocess
import threading
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable

from rdc_tool.platform import host

_os = host.backend()


@dataclass(frozen=True)
class ProcessIdentity:
    pid: int
    birth: str = ""


class Liveness(Enum):
    ALIVE = "alive"
    EXITED = "exited"
    UNKNOWN = "unknown"


class SpawnProfile(Enum):
    DAEMON = "daemon"  # detached owner of a context; leads its own process group
    WORKER = "worker"  # native replay child; stays in the daemon's group
    TOOL = "tool"      # short-lived host utility such as adb or spirv-dis


def identify(pid: int) -> ProcessIdentity:
    """Return the identity of a live ``pid``; the birth is empty when unreadable."""
    try:
        birth = _os.process_birth(int(pid))
    except OSError:
        return ProcessIdentity(int(pid))
    if birth is None:
        raise ProcessLookupError(pid)
    return ProcessIdentity(int(pid), birth)


def self_identity() -> ProcessIdentity:
    return identify(os.getpid())


def probe(identity: ProcessIdentity) -> Liveness:
    if identity.pid <= 0:
        return Liveness.EXITED
    try:
        birth = _os.process_birth(identity.pid)
    except OSError:
        return Liveness.UNKNOWN
    if birth is None or (identity.birth and birth != identity.birth):
        return Liveness.EXITED
    return Liveness.ALIVE


def is_alive(identity: ProcessIdentity) -> bool:
    return probe(identity) is not Liveness.EXITED


def wait_exit(identity: ProcessIdentity, timeout: float, *, interval: float = 0.2) -> bool:
    deadline = time.monotonic() + max(0.0, timeout)
    while is_alive(identity):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        time.sleep(min(interval, remaining))
    return True


def kill_tree(identity: ProcessIdentity) -> bool:
    """Forcefully terminate a confirmed live process and its descendants."""
    if not identity.birth or probe(identity) is not Liveness.ALIVE:
        return False
    return _os.kill_tree(identity.pid)


def popen_options(profile: SpawnProfile) -> dict[str, Any]:
    return _os.popen_options(profile.value)


def run_tool(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
    kwargs.setdefault("stdin", subprocess.DEVNULL)
    for key, value in popen_options(SpawnProfile.TOOL).items():
        kwargs.setdefault(key, value)
    return subprocess.run(command, **kwargs)


def launcher_argv(launcher: str) -> list[str]:
    """Command prefix that runs a launcher script or a command on PATH."""
    return _os.launcher_argv(launcher)


def memory_bytes() -> int | None:
    """Resident memory of this process, or ``None`` when the host cannot report it."""
    return _os.memory_bytes()


def raw_command_line() -> str | None:
    """The unparsed command line where the OS keeps one (Windows), else ``None``."""
    return _os.raw_command_line()


def watch_parent(identity: ProcessIdentity, on_exit: Callable[[], None], *, interval: float = 1.0) -> threading.Thread:
    def watch() -> None:
        while is_alive(identity):
            time.sleep(interval)
        on_exit()

    thread = threading.Thread(target=watch, name="rdc-tool-parent-watch", daemon=True)
    thread.start()
    return thread
