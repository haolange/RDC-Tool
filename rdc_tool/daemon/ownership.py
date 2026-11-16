"""Process-lifetime daemon ownership and serialized state publication."""

from __future__ import annotations

import time
from contextlib import ExitStack, contextmanager
from pathlib import Path
from typing import Any

from rdc_tool.platform.locks import HeldLock, LockTimeout, path_lock

PUBLICATION_LOCK_TIMEOUT_S = 5.0
PUBLICATION_LOCK_POLL_S = 0.01


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


class OwnerLease:
    """Keep the owner lock until the owning process exits, including teardown."""

    def __init__(self, path: Path, context: str) -> None:
        self.path = path.resolve()
        held = HeldLock.try_open(path.with_suffix(".owner.lock"))
        if held is None:
            raise DaemonOwnerUnavailable(context, path, "owner_lock_busy")
        self._held = held

    def close(self) -> None:
        self._held.release()


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
    with ExitStack() as stack:
        try:
            stack.enter_context(path_lock(path.with_suffix(".publish.lock"), timeout=PUBLICATION_LOCK_TIMEOUT_S,
                                          poll_interval=PUBLICATION_LOCK_POLL_S))
        except LockTimeout as exc:
            raise DaemonOwnerUnavailable(context, path, "state_publication_busy") from exc
        yield


def owner_identity(state: dict[str, Any]) -> tuple[int, str, str]:
    return int(state.get("pid") or 0), str(state.get("pipe_name") or ""), str(state.get("token") or "")
