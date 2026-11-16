"""Worker attestation of its own and its daemon parent's process births."""

from __future__ import annotations

import os
from typing import Any

from rdc_tool.platform import process


def runtime_process_identity() -> dict[str, Any]:
    """Only the actual daemon child may attest its own and its parent's birth."""
    try:
        parent = int(os.environ.get("RDC_TOOL_DAEMON_PID", ""))
    except ValueError:
        return {"status": "unavailable", "reason": "not_daemon_worker"}
    if parent <= 0 or parent != os.getppid():
        return {"status": "unavailable", "reason": "daemon_parent_mismatch"}
    try:
        daemon = process.identify(parent)
        worker = process.self_identity()
    except ProcessLookupError as exc:
        return {"status": "unavailable", "reason": "process_birth_unavailable", "detail": str(exc)}
    if not daemon.birth or not worker.birth:
        return {"status": "unavailable", "reason": "process_birth_unavailable", "detail": "birth unreadable"}
    return {
        "status": "available",
        "daemon": {"pid": daemon.pid, "start_generation": daemon.birth},
        "worker": {"pid": worker.pid, "start_generation": worker.birth},
    }
