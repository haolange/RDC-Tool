"""A read-only view of one context: daemon and worker identities, the running request and replay recovery.

Building it never starts a daemon or a worker, never writes a state file and
takes no state lock: persisted files are replaced atomically, so a plain read
sees either the old or the new version.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from rdc_tool.context_snapshot import context_snapshot_path, normalize_context_id, normalize_context_snapshot
from rdc_tool.daemon.state import load_json_with_status, process_identity, state_path
from rdc_tool.platform import process
from rdc_tool.runtime_state import context_state_path, normalize_context_state
from rdc_tool.runtime_worker_state import worker_log_path, worker_state_path


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def probe_identity(pid: Any, birth: Any) -> Dict[str, Any]:
    """A recorded process identity and what the OS says about it now."""
    identity = process_identity(pid, birth)
    state = "absent" if identity.pid <= 0 else process.probe(identity).value
    return {"state": state, "pid": identity.pid, "start_generation": identity.birth}


def worker_from_state_file(context: str) -> Dict[str, Any]:
    status, record = load_json_with_status(worker_state_path(context))
    if status == "invalid":
        return {"state": "unknown", "pid": 0, "start_generation": "", "reason": "worker_state_invalid"}
    return probe_identity(record.get("pid"), record.get("birth"))


def _session_view(session_id: str, record: Dict[str, Any]) -> Dict[str, Any]:
    recovery = dict(record.get("recovery") or {})
    return {
        "session_id": session_id,
        "capture_file_id": str(record.get("capture_file_id") or ""),
        "rdc_path": str(record.get("rdc_path") or ""),
        "backend_type": str(record.get("backend_type") or ""),
        "state": str(record.get("state") or ""),
        "is_live": bool(record.get("is_live")),
        "frame_index": _int(record.get("frame_index")),
        "active_event_id": _int(record.get("active_event_id")),
        "recovery": {
            "status": str(recovery.get("status") or ""),
            "requires_restart": recovery.get("status") == "requires_restart",
            "last_error": str(recovery.get("last_error") or ""),
            "worker_exit": recovery.get("worker_exit"),
        },
    }


def report(context: Optional[str], *, source: str, daemon: Dict[str, Any], worker: Dict[str, Any],
           active_operation: Dict[str, Any], worker_lifecycle: list[Any]) -> Dict[str, Any]:
    ctx = normalize_context_id(context)
    _, raw_state = load_json_with_status(context_state_path(ctx))
    _, raw_snapshot = load_json_with_status(context_snapshot_path(ctx))
    state = normalize_context_state(raw_state or None, ctx)
    snapshot = normalize_context_snapshot(raw_snapshot or None, ctx)
    sessions = state.get("sessions") or {}
    captures = state.get("captures") or {}
    current_session_id = str(state.get("current_session_id") or "")
    current = sessions.get(current_session_id) or {}
    capture = captures.get(str(state.get("current_capture_file_id") or current.get("capture_file_id") or "")) or {}
    return {
        "context_id": ctx,
        "source": source,
        "daemon": daemon,
        "worker": {**worker, "log_path": str(worker_log_path(ctx))},
        "active_operation": dict(active_operation or {}),
        "worker_lifecycle": [dict(item) for item in worker_lifecycle or [] if isinstance(item, dict)],
        "backend": str(state.get("backend") or "local"),
        "current_session_id": current_session_id,
        "current_capture_file_id": str(state.get("current_capture_file_id") or ""),
        "session_locator": {
            "rdc_path": str(current.get("rdc_path") or capture.get("file_path") or ""),
            "session_id": current_session_id,
            "frame_index": _int(current.get("frame_index")),
            "active_event_id": _int(current.get("active_event_id")),
        },
        "sessions": [_session_view(session_id, record) for session_id, record in sessions.items()],
        "recovery": dict(state.get("recovery") or {}),
        "preview": dict(snapshot.get("preview") or {}),
        "notes": str(snapshot.get("notes") or ""),
        "focus": dict(snapshot.get("focus") or {}),
    }


def from_state_files(context: Optional[str], *, daemon_error: str = "") -> Dict[str, Any]:
    """The report when no daemon answered: recorded identities, probed now."""
    ctx = normalize_context_id(context)
    status, daemon_state = load_json_with_status(state_path(ctx))
    if status == "ok":
        daemon = probe_identity(daemon_state.get("pid"), daemon_state.get("birth"))
        daemon.update(started_at=str(daemon_state.get("started_at") or ""),
                      last_activity_at=str(daemon_state.get("last_activity_at") or ""))
    else:
        daemon = {"state": "absent" if status == "missing" else "unknown", "pid": 0, "start_generation": "",
                  **({"reason": "daemon_state_invalid"} if status == "invalid" else {})}
    if daemon_error:
        daemon["reason"] = daemon_error
    active = daemon_state.get("active_operation") if status == "ok" else {}
    return report(ctx, source="state_files", daemon=daemon, worker=worker_from_state_file(ctx),
                  active_operation=active if isinstance(active, dict) else {},
                  worker_lifecycle=list(daemon_state.get("worker_lifecycle") or []) if status == "ok" else [])
