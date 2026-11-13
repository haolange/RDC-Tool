"""Process-lifetime daemon ownership and serialized state publication."""

from __future__ import annotations

from rdc_tool.file_lock import lock, unlock
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, BinaryIO


class DaemonOwnerUnavailable(RuntimeError):
    def __init__(self, context: str, path: Path, reason: str) -> None:
        super().__init__(f"Daemon owner unavailable for context {context!r}: {reason}")
        self.code = "daemon_owner_unavailable"
        self.category = "runtime"
        self.details = {
            "context_id": context,
            "state_path": str(path),
            "reason": reason,
            "recovery_hint": "Preserve the owner and its state. Retry status; explicitly clear/stop the identified owner and confirm process exit before starting a replacement.",
        }


def try_lock(handle: BinaryIO) -> bool:
    return lock(handle, blocking=False)


class OwnerLease:
    """Keep this handle alive until the owning process exits, including teardown."""

    def __init__(self, path: Path, context: str) -> None:
        self.path = path.resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = path.with_suffix(".owner.lock").open("a+b")
        try:
            acquired = try_lock(self.handle)
        except BaseException:
            self.handle.close()
            raise
        if not acquired:
            self.handle.close()
            raise DaemonOwnerUnavailable(context, path, "owner_lock_busy")

    def close(self) -> None:
        if not self.handle.closed:
            unlock(self.handle)
            self.handle.close()


def owner_is_busy(path: Path, context: str) -> bool:
    try:
        lease = OwnerLease(path, context)
    except DaemonOwnerUnavailable:
        return True
    lease.close()
    return False


def wait_for_owner_exit(path: Path, context: str, timeout: float = 3.0) -> bool:
    deadline = time.monotonic() + timeout
    while owner_is_busy(path, context):
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.05)
    return True


@contextmanager
def locked_publication(path: Path, context: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_suffix(".publish.lock").open("a+b") as handle:
        deadline = time.monotonic() + 5.0
        while not try_lock(handle):
            if time.monotonic() >= deadline:
                raise DaemonOwnerUnavailable(context, path, "state_publication_busy")
            time.sleep(0.01)
        try:
            yield
        finally:
            unlock(handle)


def owner_identity(state: dict[str, Any]) -> tuple[int, str, str]:
    return int(state.get("pid") or 0), str(state.get("pipe_name") or ""), str(state.get("token") or "")
