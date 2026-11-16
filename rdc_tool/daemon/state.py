"""The per-context daemon state file.

This module is the only owner of the state file's path, shape, publication
and generation identity. The file holds the daemon's IPC key and is written
with owner-only permissions; every view leaving the daemon or the CLI goes
through ``public_view``, which removes that key.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple

from rdc_tool.context_snapshot import context_file_token, normalize_context_id
from rdc_tool.daemon.ownership import DaemonOwnerUnavailable, OwnerLease, locked_publication, owner_is_busy
from rdc_tool.io_utils import atomic_write_json
from rdc_tool.platform.process import ProcessIdentity
from rdc_tool.runtime_paths import cli_runtime_dir

DEFAULT_LEASE_TIMEOUT_S = 120
DEFAULT_IDLE_TIMEOUT_S = 15 * 60
_DEFAULT_STATE_FILE = "daemon_state.json"
_SECRET_FIELDS = frozenset({"token"})


def epoch_ms() -> int:
    return int(time.time() * 1000)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def iso_to_ms(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, (int, float)):
        return int(float(value))
    text = str(value).strip()
    if not text:
        return 0
    try:
        return int(float(text))
    except ValueError:
        pass
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return 0
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return int(parsed.timestamp() * 1000)


def normalize_timeout(value: Any, *, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return int(default)
    return parsed if parsed > 0 else int(default)


def state_path(context: Optional[str]) -> Path:
    ctx = normalize_context_id(context)
    name = _DEFAULT_STATE_FILE if ctx == "default" else f"daemon_state_{context_file_token(ctx)}.json"
    return cli_runtime_dir() / name


def context_from_state_path(path: Path) -> str:
    name = path.name
    prefix, suffix = "daemon_state_", ".json"
    if name.startswith(prefix) and name.endswith(suffix):
        return name[len(prefix):-len(suffix)] or "default"
    return "default"


def load_json_with_status(path: Path) -> Tuple[str, Dict[str, Any]]:
    if not path.is_file():
        return "missing", {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return "invalid", {}
    if not isinstance(payload, dict):
        return "invalid", {}
    return "ok", payload


def process_identity(pid: Any, birth: Any) -> ProcessIdentity:
    return ProcessIdentity(int(pid or 0), str(birth or ""))


def daemon_process(state: Dict[str, Any]) -> ProcessIdentity:
    return process_identity(state.get("pid"), state.get("birth"))


def owner_process(state: Dict[str, Any]) -> ProcessIdentity:
    return process_identity(state.get("owner_pid"), state.get("owner_birth"))


def worker_process(state: Dict[str, Any]) -> ProcessIdentity:
    worker = state.get("worker") if isinstance(state.get("worker"), dict) else {}
    return process_identity(worker.get("pid"), worker.get("birth"))


def owner_identity(state: Dict[str, Any]) -> tuple[int, str, str]:
    """The generation key: one daemon process listening on one endpoint with one key."""
    return int(state.get("pid") or 0), str(state.get("endpoint") or ""), str(state.get("token") or "")


def public_view(state: Dict[str, Any]) -> Dict[str, Any]:
    return {key: value for key, value in state.items() if key not in _SECRET_FIELDS}


def normalize_attached_clients(value: Any) -> list[Dict[str, Any]]:
    items = value if isinstance(value, list) else []
    normalized: list[Dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        attached_at = str(item.get("attached_at") or utc_now_iso())
        normalized.append({
            "client_id": str(item.get("client_id") or "").strip(),
            "client_type": str(item.get("client_type") or "unknown").strip() or "unknown",
            "pid": int(item.get("pid") or 0),
            "birth": str(item.get("birth") or ""),
            "attached_at": attached_at,
            "last_heartbeat_at": str(item.get("last_heartbeat_at") or attached_at),
            "lease_timeout_seconds": normalize_timeout(item.get("lease_timeout_seconds"), default=DEFAULT_LEASE_TIMEOUT_S),
        })
    return normalized


def normalize_state(payload: Dict[str, Any], context: Optional[str]) -> Dict[str, Any]:
    started_at = str(payload.get("started_at") or utc_now_iso())
    worker = payload.get("worker") if isinstance(payload.get("worker"), dict) else {}
    active_operation = payload.get("active_operation")
    return {
        **payload,
        "context_id": normalize_context_id(context or payload.get("context_id")),
        "endpoint": str(payload.get("endpoint") or "").strip(),
        "token": str(payload.get("token") or "").strip(),
        "pid": int(payload.get("pid") or 0),
        "birth": str(payload.get("birth") or ""),
        "started_at": started_at,
        "last_activity_at": str(payload.get("last_activity_at") or started_at),
        "owner_pid": int(payload.get("owner_pid") or 0),
        "owner_birth": str(payload.get("owner_birth") or ""),
        "lease_timeout_seconds": normalize_timeout(payload.get("lease_timeout_seconds"), default=DEFAULT_LEASE_TIMEOUT_S),
        "idle_timeout_seconds": normalize_timeout(payload.get("idle_timeout_seconds"), default=DEFAULT_IDLE_TIMEOUT_S),
        "attached_clients": normalize_attached_clients(payload.get("attached_clients")),
        "active_request_count": int(payload.get("active_request_count") or 0),
        "active_operation": dict(active_operation) if isinstance(active_operation, dict) else {},
        "session_id": str(payload.get("session_id") or "").strip(),
        "capture_file_id": str(payload.get("capture_file_id") or "").strip(),
        "capture_path": str(payload.get("capture_path") or "").strip(),
        "active_event_id": int(payload.get("active_event_id") or 0),
        "frame_index": int(payload.get("frame_index") or 0),
        "session_count": int(payload.get("session_count") or 0),
        "capture_count": int(payload.get("capture_count") or 0),
        "recovery_status": str(payload.get("recovery_status") or "").strip(),
        "backend": str(payload.get("backend") or "local").strip() or "local",
        "worker": {
            "running": bool(worker.get("running")),
            "pid": int(worker.get("pid") or 0),
            "birth": str(worker.get("birth") or ""),
            "binaries_dir": str(worker.get("binaries_dir") or ""),
            "pymodules_dir": str(worker.get("pymodules_dir") or ""),
            "source_manifest": str(worker.get("source_manifest") or ""),
        },
    }


def is_complete(state: Dict[str, Any]) -> bool:
    return int(state.get("pid") or 0) > 0 and bool(state.get("endpoint")) and bool(state.get("token"))


def load_state(context: Optional[str] = "default") -> Dict[str, Any]:
    path = state_path(context)
    status, payload = load_json_with_status(path)
    if status == "missing":
        return {}
    try:
        state = normalize_state(payload, context)
        valid = status == "ok" and is_complete(state)
    except (TypeError, ValueError, OverflowError):
        valid = False
    if not valid:
        raise DaemonOwnerUnavailable(normalize_context_id(context), path, "invalid_state")
    return state


def list_daemon_context_ids() -> list[str]:
    root = cli_runtime_dir()
    if not root.is_dir():
        return []
    ids = {context_from_state_path(path) for path in root.glob("daemon_state*.json") if path.is_file()}
    for lock in root.glob("daemon_state*.owner.lock"):
        path = lock.with_name(lock.name.removesuffix(".owner.lock") + ".json")
        context = context_from_state_path(path)
        if owner_is_busy(path, context):
            ids.add(context)
    return sorted(ids)


def _check_lease(lease: OwnerLease, path: Path, pid: int, context: str) -> None:
    if lease.closed or lease.path != path.resolve() or pid != os.getpid():
        raise DaemonOwnerUnavailable(context, path, "owner_lease_closed")


def save_state(payload: Dict[str, Any], context: Optional[str] = "default", *, lease: OwnerLease | None = None) -> None:
    ctx = normalize_context_id(context)
    path = state_path(ctx)
    normalized = normalize_state(payload, ctx)
    with locked_publication(path, ctx):
        status, current = load_json_with_status(path)
        if status == "ok" and current and owner_identity(current) != owner_identity(normalized):
            raise DaemonOwnerUnavailable(ctx, path, "state_owner_changed")
        if lease is None and (status == "invalid" or owner_is_busy(path, ctx)):
            raise DaemonOwnerUnavailable(ctx, path, "state_owner_unconfirmed")
        if lease is not None:
            _check_lease(lease, path, int(normalized.get("pid") or 0), ctx)
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(path, normalized)


def clear_state(context: Optional[str] = "default", *, expected: Dict[str, Any] | None = None,
                lease: OwnerLease | None = None) -> None:
    ctx = normalize_context_id(context)
    path = state_path(ctx)
    # Capture the identity before waiting for publication, so a late cleanup
    # cannot remove a successor's state.
    previous = expected if expected is not None else load_state(ctx)
    with locked_publication(path, ctx):
        status, current = load_json_with_status(path)
        if status == "missing":
            if lease is None and owner_is_busy(path, ctx):
                raise DaemonOwnerUnavailable(ctx, path, "owner_lock_busy")
            return
        if status != "ok" or owner_identity(current) != owner_identity(previous):
            raise DaemonOwnerUnavailable(ctx, path, "state_owner_changed")
        if lease is None and owner_is_busy(path, ctx):
            raise DaemonOwnerUnavailable(ctx, path, "owner_lock_busy")
        if lease is not None:
            _check_lease(lease, path, int(previous.get("pid") or 0), ctx)
        path.unlink(missing_ok=True)


def retire_incomplete_state(context: str, expected: Dict[str, Any], verify: Callable[[Dict[str, Any]], None]) -> None:
    """Retire one unchanged state only while owning its publication and owner locks."""
    ctx = normalize_context_id(context)
    path = state_path(ctx)
    lease = OwnerLease(path, ctx)
    try:
        with locked_publication(path, ctx):
            status, current = load_json_with_status(path)
            if status != "ok" or current != expected:
                raise DaemonOwnerUnavailable(ctx, path, "state_owner_changed")
            verify(current)
            path.unlink()
    finally:
        lease.close()
