"""Foreground pipe transport using the same runtime worker as the daemon.

Explicit mode, not an automatic fallback. A shared owner lease prevents concurrent
stdio and daemon workers from owning the same context. EOF closes native sessions.
"""
from __future__ import annotations
from rdc_tool.daemon.client import _daemon_state_path
from rdc_tool.daemon.ownership import OwnerLease
from rdc_tool.runtime_identity import host_native_manifest_status
from rdc_tool.runtime_paths import tools_root
from rdc_tool.replay_lifecycle import mark_replay_requires_restart


def run_stdio(context: str) -> int:
    identity = host_native_manifest_status(tools_root())
    if identity["status"] == "invalid":
        raise RuntimeError(f"Native runtime integrity failed: {identity['reason']}")
    lease = OwnerLease(_daemon_state_path(context), context)
    try:
        mark_replay_requires_restart(context, "Replay worker changed; close and reopen the capture through its owning lifecycle")
        from rdc_tool.runtime_worker import main
        return main(["--context-id", context])
    finally:
        lease.close()
