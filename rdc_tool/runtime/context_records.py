"""Context state and snapshot records: captures, sessions, active event and focus."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from rdc_tool import context_snapshot
from rdc_tool.context_snapshot import (
    default_context_snapshot,
    merge_recent_artifacts,
    normalize_context_id,
    normalize_context_snapshot,
    normalize_preview_state,
    save_context_snapshot,
)
from rdc_tool.core.errors import CoreError
from rdc_tool.runtime import live_state, remote_records, settings
from rdc_tool.runtime_state import (
    clear_context_state,
    context_state_path,
    default_context_state,
    list_context_ids,
    load_context_state,
    save_context_state,
)


def _context_state_exists(context_id: Optional[str] = None) -> bool:
    return context_state_path(normalize_context_id(context_id or live_state._runtime_context_id())).is_file()


def _occupying_context_ids() -> set[str]:
    from rdc_tool.daemon.client import list_occupying_context_ids

    occupying = {normalize_context_id(item) for item in list_occupying_context_ids()}
    if live_state._runtime.replays or live_state._runtime.previews:
        occupying.add(normalize_context_id(live_state._runtime_context_id()))
    occupying.update(normalize_context_id(item) for item in live_state._runtime.previews.keys())
    return occupying


def _ensure_context_capacity(context_id: Optional[str] = None) -> None:
    ctx = normalize_context_id(context_id or live_state._runtime_context_id())
    if _context_state_exists(ctx) or ctx in live_state._runtime.context_states:
        return
    max_contexts = int(settings._runtime_limits().get("max_contexts", 8) or 8)
    occupying = _occupying_context_ids()
    if ctx in occupying:
        return
    if len(occupying) >= max_contexts:
        known = {normalize_context_id(item) for item in list_context_ids()}
        raise CoreError(
            code="context_limit_exceeded",
            message=f"Context limit exceeded for {ctx}",
            category="runtime",
            details={
                "context_id": ctx,
                "max_contexts": max_contexts,
                "occupying_contexts": sorted(occupying),
                "known_contexts": sorted(known),
            },
        )


def _context_state(context_id: Optional[str] = None) -> Dict[str, Any]:
    ctx = normalize_context_id(context_id or live_state._runtime_context_id())
    state = live_state._runtime.context_states.get(ctx)
    if not isinstance(state, dict):
        if not _context_state_exists(ctx):
            _ensure_context_capacity(ctx)
            state = default_context_state(ctx, limits=settings._runtime_limits())
        else:
            state = load_context_state(ctx, limits=settings._runtime_limits())
    state["limits"] = {**dict(state.get("limits") or {}), **settings._runtime_limits()}
    live_state._runtime.context_states[ctx] = state
    return state


def _store_context_state(state: Dict[str, Any], context_id: Optional[str] = None) -> Dict[str, Any]:
    ctx = normalize_context_id(context_id or live_state._runtime_context_id())
    saved = save_context_state(state, ctx, limits=settings._runtime_limits())
    live_state._runtime.context_states[ctx] = saved
    return saved


def _capture_file_metadata(file_path: str) -> Dict[str, Any]:
    path = Path(str(file_path or "")).resolve()
    if not path.is_file():
        return {
            "file_path": str(path),
            "file_size_bytes": 0,
            "file_mtime_ms": 0,
            "file_fingerprint": "",
        }
    stat = path.stat()
    return {
        "file_path": str(path),
        "file_size_bytes": int(stat.st_size),
        "file_mtime_ms": int(stat.st_mtime * 1000),
        "file_fingerprint": f"{int(stat.st_size)}:{int(stat.st_mtime * 1000)}",
    }


def _estimated_replay_memory_bytes(file_size_bytes: int) -> int:
    multiplier = float(settings._runtime_limits().get("replay_memory_multiplier", 3.0) or 3.0)
    return int(max(0, int(file_size_bytes or 0)) * max(multiplier, 1.0))


def _sync_context_metrics(context_id: Optional[str] = None) -> Dict[str, Any]:
    ctx = normalize_context_id(context_id or live_state._runtime_context_id())
    state = _context_state(ctx)
    metrics = dict(state.get("metrics") or {})
    metrics["active_session_count"] = len([item for item in state.get("sessions", {}).values() if isinstance(item, dict)])
    metrics["active_capture_count"] = len([item for item in state.get("captures", {}).values() if isinstance(item, dict)])
    state["metrics"] = metrics
    return _store_context_state(state, ctx)


def _session_record_from_runtime(session_id: str, *, context_id: Optional[str] = None) -> Dict[str, Any]:
    ctx = normalize_context_id(context_id or live_state._runtime_context_id())
    replay = live_state._runtime.replays.get(str(session_id))
    if replay is None:
        raise KeyError(f"unknown session_id: {session_id}")
    state = _context_state(ctx)
    state_sessions = state.get("sessions", {}) if isinstance(state.get("sessions"), dict) else {}
    existing = dict(state_sessions.get(str(session_id)) or {})
    capture = live_state._runtime.captures.get(replay.capture_file_id)
    capture_meta = _capture_file_metadata(capture.file_path if capture is not None else "")
    backend_type = str(existing.get("backend_type") or state.get("backend") or "").strip()
    if not backend_type:
        backend_type = "remote" if str(session_id) in live_state._runtime.session_owned_remotes else "local"
    return {
        "session_id": str(session_id),
        "capture_file_id": str(replay.capture_file_id),
        "rdc_path": str(capture.file_path if capture is not None else ""),
        "file_fingerprint": str(capture_meta.get("file_fingerprint") or ""),
        "file_size_bytes": int(capture_meta.get("file_size_bytes") or 0),
        "frame_index": int(replay.frame_index or 0),
        "active_event_id": int(replay.active_event_id or 0),
        "backend_type": live_state._normalize_backend(backend_type, default="local"),
        "state": "active",
        "is_live": True,
        "last_error": "",
        "shader_replacements": _replacement_metadata_entries(str(session_id)),
        "updated_at_ms": settings._now_ms(),
        "recovery": {
            "status": "ready",
            "last_attempt_ms": 0,
            "last_success_ms": 0,
            "attempt_count": 0,
            "last_error": "",
        },
    }


def _capture_record_from_runtime(capture_file_id: str) -> Dict[str, Any]:
    capture = live_state._runtime.captures.get(str(capture_file_id))
    if capture is None:
        raise KeyError(f"unknown capture_file_id: {capture_file_id}")
    meta = _capture_file_metadata(capture.file_path)
    return {
        "capture_file_id": str(capture.capture_file_id),
        "file_path": str(capture.file_path),
        "read_only": bool(capture.read_only),
        "driver": str(capture.driver or ""),
        "file_size_bytes": int(meta.get("file_size_bytes") or 0),
        "file_mtime_ms": int(meta.get("file_mtime_ms") or 0),
        "file_fingerprint": str(meta.get("file_fingerprint") or ""),
        "recovery_status": "ready",
        "last_error": "",
        "updated_at_ms": settings._now_ms(),
    }


def _select_session_from_state(
    state: Dict[str, Any],
    session_id: str = "",
    *,
    capture_file_id: str = "",
) -> Dict[str, Any]:
    sessions = state.get("sessions", {})
    captures = state.get("captures", {})
    chosen_session_id = str(session_id or state.get("current_session_id") or "").strip()
    chosen_capture_id = str(capture_file_id or state.get("current_capture_file_id") or "").strip()
    if chosen_session_id and chosen_session_id not in sessions:
        chosen_session_id = ""
    if not chosen_session_id and sessions:
        chosen_session_id = next(iter(sessions.keys()))
    if chosen_capture_id and chosen_capture_id not in captures:
        chosen_capture_id = ""
    if chosen_session_id and not chosen_capture_id:
        chosen_capture_id = str((sessions.get(chosen_session_id) or {}).get("capture_file_id") or "")
    if not chosen_capture_id and captures:
        chosen_capture_id = next(iter(captures.keys()))
    state["current_session_id"] = chosen_session_id
    state["current_capture_file_id"] = chosen_capture_id
    selected_session = sessions.get(chosen_session_id) if isinstance(sessions, dict) and chosen_session_id else None
    if isinstance(selected_session, dict):
        state["backend"] = live_state._normalize_backend(
            selected_session.get("backend_type"),
            default=str(state.get("backend") or "local"),
        )
    return state


def _infer_context_backend(snapshot: Dict[str, Any], state: Dict[str, Any]) -> str:
    backend = live_state._normalize_backend(state.get("backend"), default="")
    if backend:
        return backend
    runtime_payload = snapshot.get("runtime") if isinstance(snapshot.get("runtime"), dict) else {}
    remote_payload = snapshot.get("remote") if isinstance(snapshot.get("remote"), dict) else {}
    if str(runtime_payload.get("backend_type") or "").strip() == "remote":
        return "remote"
    if str(remote_payload.get("state") or "none").strip() != "none":
        return "remote"
    return "local"


def _apply_backend_projection(snapshot: Dict[str, Any], state: Dict[str, Any]) -> Dict[str, Any]:
    backend = _infer_context_backend(snapshot, state)
    snapshot["backend"] = backend
    state["backend"] = backend
    return snapshot


def _sync_context_snapshot_from_state(context_id: Optional[str] = None) -> Dict[str, Any]:
    ctx = normalize_context_id(context_id or live_state._runtime_context_id())
    state = _context_state(ctx)
    state = _select_session_from_state(state)
    sessions = state.get("sessions", {})
    captures = state.get("captures", {})
    current_session = sessions.get(state.get("current_session_id")) if isinstance(sessions, dict) else None
    current_capture = captures.get(state.get("current_capture_file_id")) if isinstance(captures, dict) else None
    snapshot = live_state._runtime.context_snapshots.get(ctx)
    if not isinstance(snapshot, dict):
        snapshot = context_snapshot.load_context_snapshot(ctx, retention=settings._snapshot_retention())
    snapshot = normalize_context_snapshot(snapshot, ctx, retention=settings._snapshot_retention())
    if isinstance(current_session, dict):
        snapshot["runtime"].update(
            {
                "session_id": str(current_session.get("session_id") or ""),
                "capture_file_id": str(current_session.get("capture_file_id") or ""),
                "frame_index": int(current_session.get("frame_index") or 0),
                "active_event_id": int(current_session.get("active_event_id") or 0),
                "backend_type": str(current_session.get("backend_type") or "none"),
            }
        )
    elif isinstance(current_capture, dict):
        snapshot["runtime"].update(
            {
                "session_id": "",
                "capture_file_id": str(current_capture.get("capture_file_id") or ""),
                "frame_index": 0,
                "active_event_id": 0,
                "backend_type": "none",
            }
        )
    else:
        snapshot["runtime"] = default_context_snapshot(ctx).get("runtime", {})
    snapshot = _apply_backend_projection(snapshot, state)
    snapshot["preview"] = normalize_preview_state(
        state.get("preview"),
        backend=str(snapshot.get("backend") or state.get("backend") or "local"),
    )
    _store_context_state(state, ctx)
    return _store_context_snapshot(snapshot, ctx)


def _upsert_context_capture(capture_file_id: str, *, context_id: Optional[str] = None) -> Dict[str, Any]:
    ctx = normalize_context_id(context_id or live_state._runtime_context_id())
    state = _context_state(ctx)
    state.setdefault("captures", {})[str(capture_file_id)] = _capture_record_from_runtime(capture_file_id)
    state = _select_session_from_state(state, capture_file_id=str(capture_file_id))
    _store_context_state(state, ctx)
    _sync_context_metrics(ctx)
    return _sync_context_snapshot_from_state(ctx)


def _remove_context_capture(capture_file_id: str, *, context_id: Optional[str] = None) -> Dict[str, Any]:
    ctx = normalize_context_id(context_id or live_state._runtime_context_id())
    state = _context_state(ctx)
    state.get("captures", {}).pop(str(capture_file_id), None)
    sessions = state.get("sessions", {})
    if isinstance(sessions, dict):
        for session_id, record in list(sessions.items()):
            if isinstance(record, dict) and str(record.get("capture_file_id") or "") == str(capture_file_id):
                sessions.pop(session_id, None)
    state = _select_session_from_state(state)
    _store_context_state(state, ctx)
    _sync_context_metrics(ctx)
    return _sync_context_snapshot_from_state(ctx)


def _update_context_session_record(
    session_id: str,
    *,
    context_id: Optional[str] = None,
    backend_type: Optional[str] = None,
    frame_index: Optional[int] = None,
    active_event_id: Optional[int] = None,
    state_name: Optional[str] = None,
    is_live: Optional[bool] = None,
    last_error: Optional[str] = None,
    recovery_status: Optional[str] = None,
) -> Dict[str, Any]:
    ctx = normalize_context_id(context_id or live_state._runtime_context_id())
    state = _context_state(ctx)
    sessions = state.setdefault("sessions", {})
    record = dict(sessions.get(str(session_id)) or {})
    if not record:
        try:
            record = _session_record_from_runtime(str(session_id), context_id=ctx)
        except KeyError as exc:
            raise CoreError(
                code="session_not_found",
                message=f"Unknown session_id: {session_id}",
                category="not_found",
                details={"session_id": str(session_id)},
            ) from exc
    resolved_backend = live_state._normalize_backend(
        backend_type or record.get("backend_type") or state.get("backend"),
        default="local",
    )
    state["backend"] = resolved_backend
    record["backend_type"] = resolved_backend
    if frame_index is not None:
        record["frame_index"] = int(frame_index)
    if active_event_id is not None:
        record["active_event_id"] = int(active_event_id)
    if state_name is not None:
        record["state"] = str(state_name)
    if is_live is not None:
        record["is_live"] = bool(is_live)
    if last_error is not None:
        record["last_error"] = str(last_error)
    recovery = dict(record.get("recovery") or {})
    if recovery_status is not None:
        recovery["status"] = str(recovery_status)
    if last_error is not None:
        recovery["last_error"] = str(last_error)
    record["recovery"] = recovery
    record["updated_at_ms"] = settings._now_ms()
    sessions[str(session_id)] = record
    _store_context_state(state, ctx)
    return _sync_context_snapshot_from_state(ctx)


def _remove_context_session(session_id: str, *, context_id: Optional[str] = None) -> Dict[str, Any]:
    ctx = normalize_context_id(context_id or live_state._runtime_context_id())
    state = _context_state(ctx)
    state.get("sessions", {}).pop(str(session_id), None)
    state = _select_session_from_state(state)
    _store_context_state(state, ctx)
    _sync_context_metrics(ctx)
    return _sync_context_snapshot_from_state(ctx)


def _select_context_session_state(session_id: str, *, context_id: Optional[str] = None) -> Dict[str, Any]:
    ctx = normalize_context_id(context_id or live_state._runtime_context_id())
    state = _context_state(ctx)
    if str(session_id) not in state.get("sessions", {}):
        raise CoreError(
            code="session_not_found",
            message=f"Unknown session_id: {session_id}",
            category="not_found",
            details={"session_id": str(session_id)},
        )
    state = _select_session_from_state(state, session_id=str(session_id))
    _store_context_state(state, ctx)
    return _sync_context_snapshot_from_state(ctx)


def _context_snapshot(context_id: Optional[str] = None) -> Dict[str, Any]:
    ctx = normalize_context_id(context_id or live_state._runtime_context_id())
    snapshot = live_state._runtime.context_snapshots.get(ctx)
    if not isinstance(snapshot, dict):
        snapshot = context_snapshot.load_context_snapshot(ctx, retention=settings._snapshot_retention())
    snapshot = normalize_context_snapshot(snapshot, ctx, retention=settings._snapshot_retention())
    state = _context_state(ctx)
    sessions = state.get("sessions", {}) if isinstance(state, dict) else {}
    captures = state.get("captures", {}) if isinstance(state, dict) else {}

    runtime_payload = snapshot.get("runtime", {})
    session_id = str(runtime_payload.get("session_id") or "").strip()
    capture_file_id = str(runtime_payload.get("capture_file_id") or "").strip()
    if session_id and session_id not in live_state._runtime.replays:
        state_session = sessions.get(session_id) if isinstance(sessions, dict) else None
        if isinstance(state_session, dict):
            runtime_payload["session_id"] = str(state_session.get("session_id") or "")
            runtime_payload["capture_file_id"] = str(state_session.get("capture_file_id") or "")
            runtime_payload["frame_index"] = int(state_session.get("frame_index") or 0)
            runtime_payload["active_event_id"] = int(state_session.get("active_event_id") or 0)
            runtime_payload["backend_type"] = str(state_session.get("backend_type") or "none")
        else:
            runtime_payload["session_id"] = ""
            runtime_payload["frame_index"] = 0
            runtime_payload["active_event_id"] = 0
            runtime_payload["backend_type"] = "none"
    if capture_file_id and capture_file_id not in live_state._runtime.captures:
        if capture_file_id in captures:
            runtime_payload["capture_file_id"] = capture_file_id
        else:
            runtime_payload["capture_file_id"] = ""

    current_session_id = str(state.get("current_session_id") or "").strip()
    if current_session_id and not runtime_payload.get("session_id"):
        state_session = sessions.get(current_session_id) if isinstance(sessions, dict) else None
        if isinstance(state_session, dict):
            runtime_payload["session_id"] = str(state_session.get("session_id") or "")
            runtime_payload["capture_file_id"] = str(state_session.get("capture_file_id") or "")
            runtime_payload["frame_index"] = int(state_session.get("frame_index") or 0)
            runtime_payload["active_event_id"] = int(state_session.get("active_event_id") or 0)
            runtime_payload["backend_type"] = str(state_session.get("backend_type") or "none")
    current_capture_file_id = str(state.get("current_capture_file_id") or "").strip()
    if current_capture_file_id and not runtime_payload.get("capture_file_id"):
        runtime_payload["capture_file_id"] = current_capture_file_id

    remote_payload = snapshot.get("remote", {})
    remote_state = str(remote_payload.get("state") or "none")
    remote_id = str(remote_payload.get("remote_id") or "")
    owned_session_id = str(remote_payload.get("consumed_by_session_id") or "")
    if remote_state == "live_handle" and (not remote_id or remote_id not in live_state._runtime.remotes):
        snapshot["remote"] = remote_records._remote_snapshot_payload_expired(remote_payload, context_id=ctx)
    elif remote_state == "live_handle" and remote_id in live_state._runtime.remotes:
        live_handle = live_state._runtime.remotes.get(remote_id)
        if live_handle is not None:
            snapshot["remote"] = remote_records._remote_snapshot_payload_from_handle(live_handle)
    elif remote_state == "session_owned" and owned_session_id not in live_state._runtime.session_owned_remotes:
        state_session = sessions.get(owned_session_id) if isinstance(sessions, dict) else None
        state_remote = remote_records._session_record_remote_metadata(state_session) if isinstance(state_session, dict) else {}
        state_endpoint = str(state_remote.get("endpoint") or "")
        state_origin_remote_id = str(state_remote.get("origin_remote_id") or "")
        if state_remote and str(state_session.get("backend_type") or "") == "remote":
            origin_remote_id = state_origin_remote_id or str(remote_payload.get("origin_remote_id") or "")
            scope = remote_records._remote_context_scope(
                origin_remote_id,
                origin_context_id=str(state_remote.get("origin_context_id") or remote_payload.get("origin_context_id") or ""),
                context_id=ctx,
            )
            snapshot["remote"] = {
                "state": "session_owned",
                "remote_id": "",
                "origin_remote_id": origin_remote_id,
                "endpoint": state_endpoint or str(remote_payload.get("endpoint") or ""),
                "consumed_by_session_id": owned_session_id,
                "active_session_ids": [owned_session_id] if owned_session_id else [],
                "origin_context_id": scope["origin_context_id"],
                "context_locality": scope["context_locality"],
                "reuse_policy": scope["reuse_policy"],
                "transport": str(state_remote.get("transport") or remote_payload.get("transport") or ""),
                "requested": dict(state_remote.get("requested") or remote_payload.get("requested") or {}),
                "options": dict(state_remote.get("options") or remote_payload.get("options") or {}),
                "bootstrap": dict(state_remote.get("bootstrap") or remote_payload.get("bootstrap") or {}),
                "device_serial": str(state_remote.get("device_serial") or remote_payload.get("device_serial") or ""),
            }
            live_state._runtime.context_snapshots[ctx] = snapshot
            return snapshot
        origin_remote_id = str(remote_payload.get("origin_remote_id") or "")
        if origin_remote_id and origin_remote_id in live_state._runtime.remotes:
            live_handle = live_state._runtime.remotes.get(origin_remote_id)
            if live_handle is not None:
                snapshot["remote"] = remote_records._remote_snapshot_payload_from_handle(live_handle)
        elif origin_remote_id and origin_remote_id in live_state._runtime.consumed_remotes:
            tombstone = live_state._runtime.consumed_remotes[origin_remote_id]
            scope = remote_records._remote_context_scope(
                str(tombstone.remote_id or origin_remote_id),
                origin_context_id=str(tombstone.origin_context_id or ""),
                context_id=ctx,
            )
            snapshot["remote"] = {
                "state": "consumed",
                "remote_id": "",
                "origin_remote_id": tombstone.remote_id,
                "endpoint": tombstone.endpoint,
                "consumed_by_session_id": tombstone.consumed_by_session_id,
                "active_session_ids": [],
                "origin_context_id": scope["origin_context_id"],
                "context_locality": scope["context_locality"],
                "reuse_policy": scope["reuse_policy"],
            }
        else:
            snapshot["remote"] = default_context_snapshot(ctx).get("remote", {})

    snapshot = _apply_backend_projection(snapshot, state)
    _store_context_state(state, ctx)
    live_state._runtime.context_snapshots[ctx] = snapshot
    return snapshot


def _store_context_snapshot(snapshot: Dict[str, Any], context_id: Optional[str] = None) -> Dict[str, Any]:
    ctx = normalize_context_id(context_id or live_state._runtime_context_id())
    normalized = save_context_snapshot(snapshot, ctx, retention=settings._snapshot_retention())
    live_state._runtime.context_snapshots[ctx] = normalized
    return normalized


def _set_context_capture_file(capture_file_id: str, *, context_id: Optional[str] = None) -> Dict[str, Any]:
    return _upsert_context_capture(str(capture_file_id or ""), context_id=context_id)


def _clear_context_capture_file(capture_file_id: str, *, context_id: Optional[str] = None) -> Dict[str, Any]:
    return _remove_context_capture(str(capture_file_id or ""), context_id=context_id)


def _set_context_runtime_session(
    session_id: str,
    *,
    capture_file_id: str,
    backend_type: str,
    frame_index: int,
    active_event_id: int,
    remote_metadata: Optional[Dict[str, Any]] = None,
    context_id: Optional[str] = None,
) -> Dict[str, Any]:
    ctx = normalize_context_id(context_id or live_state._runtime_context_id())
    state = _context_state(ctx)
    sessions = state.setdefault("sessions", {})
    existing = dict(sessions.get(str(session_id)) or {})
    sessions[str(session_id)] = {
        **existing,
        "session_id": str(session_id or ""),
        "capture_file_id": str(capture_file_id or ""),
        "rdc_path": str((live_state._runtime.captures.get(str(capture_file_id)) or live_state.CaptureFileHandle("", "", True)).file_path or existing.get("rdc_path") or ""),
        "file_fingerprint": str(existing.get("file_fingerprint") or _capture_file_metadata(str((live_state._runtime.captures.get(str(capture_file_id)) or live_state.CaptureFileHandle("", "", True)).file_path or "")).get("file_fingerprint") or ""),
        "file_size_bytes": int(existing.get("file_size_bytes") or _capture_file_metadata(str((live_state._runtime.captures.get(str(capture_file_id)) or live_state.CaptureFileHandle("", "", True)).file_path or "")).get("file_size_bytes") or 0),
        "frame_index": int(frame_index or 0),
        "active_event_id": int(active_event_id or 0),
        "backend_type": str(backend_type or "none"),
        "state": "active",
        "is_live": True,
        "last_error": "",
        "shader_replacements": list(existing.get("shader_replacements") or _replacement_metadata_entries(str(session_id))),
        "updated_at_ms": settings._now_ms(),
        "remote": dict(remote_metadata or existing.get("remote") or {}),
        "recovery": {
            "status": "ready",
            "last_attempt_ms": int(existing.get("recovery", {}).get("last_attempt_ms") if isinstance(existing.get("recovery"), dict) else 0 or 0),
            "last_success_ms": int(existing.get("recovery", {}).get("last_success_ms") if isinstance(existing.get("recovery"), dict) else 0 or 0),
            "attempt_count": int(existing.get("recovery", {}).get("attempt_count") if isinstance(existing.get("recovery"), dict) else 0 or 0),
            "last_error": "",
        },
    }
    if str(capture_file_id or "") in live_state._runtime.captures:
        state.setdefault("captures", {})[str(capture_file_id)] = _capture_record_from_runtime(str(capture_file_id))
    state = _select_session_from_state(state, session_id=str(session_id), capture_file_id=str(capture_file_id))
    _store_context_state(state, ctx)
    _sync_context_metrics(ctx)
    return _sync_context_snapshot_from_state(ctx)


def _set_context_active_event(session_id: str, event_id: int, *, context_id: Optional[str] = None) -> Dict[str, Any]:
    return _update_context_session_record(
        str(session_id or ""),
        context_id=context_id,
        active_event_id=int(event_id or 0),
    )


def _set_context_frame(session_id: str, frame_index: int, active_event_id: int, *, context_id: Optional[str] = None) -> Dict[str, Any]:
    return _update_context_session_record(
        str(session_id or ""),
        context_id=context_id,
        frame_index=int(frame_index or 0),
        active_event_id=int(active_event_id or 0),
    )


def _clear_context_runtime(session_id: str, *, context_id: Optional[str] = None) -> Dict[str, Any]:
    ctx = normalize_context_id(context_id or live_state._runtime_context_id())
    snapshot = _context_snapshot(ctx)
    remote = snapshot.get("remote", {})
    if remote.get("state") == "live_handle":
        active_session_ids = [
            item
            for item in [str(value or "").strip() for value in list(remote.get("active_session_ids") or [])]
            if item and item != str(session_id or "").strip()
        ]
        if active_session_ids or str(remote.get("remote_id") or "").strip():
            snapshot["remote"]["active_session_ids"] = active_session_ids
            snapshot["remote"]["consumed_by_session_id"] = active_session_ids[0] if active_session_ids else ""
            _store_context_snapshot(snapshot, ctx)
    elif remote.get("state") == "session_owned" and remote.get("consumed_by_session_id") == str(session_id or ""):
        snapshot["remote"]["state"] = "consumed"
        snapshot["remote"]["active_session_ids"] = []
        _store_context_snapshot(snapshot, ctx)
    result = _remove_context_session(str(session_id or ""), context_id=ctx)
    state = _context_state(ctx)
    if not any(str((record or {}).get("backend_type") or "") == "remote" for record in (state.get("sessions") or {}).values()):
        state["backend"] = "local"
        _store_context_state(state, ctx)
        result = _sync_context_snapshot_from_state(ctx)
    return result


def _reset_context_snapshot(context_id: Optional[str] = None) -> Dict[str, Any]:
    ctx = normalize_context_id(context_id or live_state._runtime_context_id())
    clear_context_state(ctx)
    live_state._runtime.context_states.pop(ctx, None)
    snapshot = default_context_snapshot(ctx)
    return _store_context_snapshot(snapshot, ctx)


def _append_context_artifacts(artifacts: Sequence[Dict[str, Any]], source_tool: str, *, context_id: Optional[str] = None) -> Dict[str, Any]:
    if not artifacts:
        return _context_snapshot(context_id)
    snapshot = _context_snapshot(context_id)
    snapshot = merge_recent_artifacts(snapshot, artifacts, source_tool=source_tool, retention=settings._snapshot_retention())
    return _store_context_snapshot(snapshot, context_id)


def _sync_focus_from_args(operation: str, args: Dict[str, Any], *, context_id: Optional[str] = None) -> Dict[str, Any]:
    snapshot = _context_snapshot(context_id)
    changed = False
    if operation in {"rd.texture.get_pixel_history", "rd.texture.get_pixel_history"}:
        if args.get("x") is not None and args.get("y") is not None:
            pixel = {"x": int(args.get("x") or 0), "y": int(args.get("y") or 0)}
            target = args.get("target")
            if isinstance(target, dict):
                pixel["target"] = dict(target)
            snapshot["focus"]["pixel"] = pixel
            changed = True
    for key in ("resource_id", "texture_id"):
        if args.get(key):
            snapshot["focus"]["resource_id"] = str(args.get(key) or "")
            changed = True
            break
    if args.get("shader_id"):
        snapshot["focus"]["shader_id"] = str(args.get("shader_id") or "")
        changed = True
    if changed:
        return _store_context_snapshot(snapshot, context_id)
    return snapshot


def _postprocess_context_snapshot(operation: str, args: Dict[str, Any], payload: Dict[str, Any], ctx: live_state.ExecutionContext) -> None:
    context_id = normalize_context_id((ctx.metadata or {}).get("context_id") or live_state._runtime_context_id())
    artifacts = payload.get("artifacts") if isinstance(payload, dict) else []
    if isinstance(artifacts, list) and artifacts:
        _append_context_artifacts(artifacts, operation, context_id=context_id)
    _sync_focus_from_args(operation, args, context_id=context_id)


def _replacement_metadata_entries(session_id: str) -> List[Dict[str, Any]]:
    entries = live_state._runtime.shader_replacements.get(session_id, [])
    if not isinstance(entries, list):
        return []
    return [dict(item) for item in entries if isinstance(item, dict)]
