"""Restoring sessions and handles recorded in persisted context state."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from rdc_tool import remote_bootstrap
from rdc_tool.context_snapshot import normalize_context_id
from rdc_tool.core.errors import CoreError, RuntimeToolError
from rdc_tool.models import _new_id
from rdc_tool.runtime import (
    action_index,
    coerce,
    context_records,
    live_state,
    oplog,
    remote_records,
    remote_session,
    remote_target,
    renderdoc_api,
    replay_access,
    settings,
    shader_patches,
    visual_target,
)


async def _pipeline_snapshot(session_id: str, event_id: Optional[int] = None) -> Any:
    assert live_state._pipeline_service is not None
    evt = await replay_access._ensure_event(session_id, event_id)
    return await live_state._pipeline_service.snapshot_pipeline(
        session_id=session_id,
        event_id=evt,
        session_manager=live_state._session_manager,
    )


def _recovery_payload(ok: bool, *, duration_ms: int, message: str = "", code: str = "") -> Dict[str, Any]:
    return {
        "ok": ok,
        "meta": {"duration_ms": int(duration_ms)},
        "error": ({"code": str(code or "runtime_error"), "message": str(message)} if (not ok and message) else {}),
    }


async def _restore_capture_handle_from_state(
    context_id: str,
    capture_file_id: str,
    record: Dict[str, Any],
) -> Optional[live_state.CaptureFileHandle]:
    handle = live_state._runtime.captures.get(str(capture_file_id))
    if handle is not None:
        return handle
    file_path = str(record.get("file_path") or "").strip()
    meta = context_records._capture_file_metadata(file_path)
    if not meta.get("file_path") or not Path(str(meta.get("file_path"))).is_file():
        return None
    handle = live_state.CaptureFileHandle(
        capture_file_id=str(capture_file_id),
        file_path=str(meta.get("file_path") or file_path),
        read_only=bool(record.get("read_only", True)),
        driver=str(record.get("driver") or ""),
    )
    live_state._runtime.captures[str(capture_file_id)] = handle
    return handle


async def _restore_remote_handle_from_session_record(
    session_id: str,
    session_record: Dict[str, Any],
) -> live_state.RemoteHandle:
    remote_record = remote_records._session_record_remote_metadata(session_record)
    transport = str(remote_record.get("transport") or "renderdoc").strip() or "renderdoc"
    endpoint = str(remote_record.get("endpoint") or "").strip()
    endpoint_host = str(remote_record.get("host") or "").strip()
    endpoint_port = coerce._as_int(remote_record.get("port"), 0)
    origin_remote_id = str(remote_record.get("origin_remote_id") or "").strip()
    scope = remote_records._remote_context_scope(
        origin_remote_id,
        origin_context_id=str(remote_record.get("origin_context_id") or ""),
        context_id=live_state._runtime_context_id(),
    )
    if scope["origin_context_id"] != scope["current_context_id"]:
        raise RuntimeToolError("Persisted remote context ownership does not match")
    requested = coerce._as_dict(remote_record.get("requested"), default={})
    requested_host = str(requested.get("host") or endpoint_host or "127.0.0.1").strip() or "127.0.0.1"
    requested_port = coerce._as_int(
        requested.get("port"),
        coerce._as_int(coerce._as_dict(remote_record.get("bootstrap"), default={}).get("remote_port"), endpoint_port or 38920),
    )
    device_serial = str(remote_record.get("device_serial") or "").strip()
    options = coerce._as_dict(remote_record.get("options"), default={})
    bootstrap_result = None
    bootstrap_detail = coerce._as_dict(remote_record.get("bootstrap"), default={})

    if transport == "adb_android":
        # The original request port can differ from the socket actually opened
        # by RenderDocCmd. A persisted local forward belongs to the old
        # connection and must not be claimed again during recovery.
        requested_port = coerce._as_int(
            bootstrap_detail.get("remote_port"),
            coerce._as_int(options.get("remote_port"), requested_port),
        )
        options = {**options, "local_port": 0}

    if origin_remote_id and origin_remote_id in live_state._runtime.remotes:
        live_handle = live_state._runtime.remotes.get(origin_remote_id)
        if live_handle is not None and live_handle.connected:
            live_handle.requested_host = requested_host
            live_handle.requested_port = requested_port
            if device_serial:
                live_handle.device_serial = device_serial
            if bootstrap_detail:
                live_handle.bootstrap = dict(bootstrap_detail)
            return live_handle

    if transport != "adb_android":
        if (not endpoint_host or endpoint_port <= 0) and endpoint:
            endpoint_host, endpoint_port = remote_session._parse_remote_endpoint(endpoint)
        endpoint_host = endpoint_host or requested_host
        endpoint_port = endpoint_port if endpoint_port > 0 else requested_port
    prior_android = await renderdoc_api._offload(remote_session._retire_recovery_android_forward, remote_record, live_state._runtime_context_id()) if transport == "adb_android" else None
    bootstrap_result, remote_server, server_info = await remote_target._connect_remote_endpoint(
        "127.0.0.1" if transport == "adb_android" else endpoint_host,
        requested_port if transport == "adb_android" else endpoint_port,
        transport, {**options, "device_serial": device_serial})
    if bootstrap_result is not None:
        if prior_android is not None:
            await remote_session._retain_recovered_android_ownership(bootstrap_result, prior_android, remote_server)
        bootstrap_detail = remote_bootstrap.describe_android_remote(bootstrap_result)
        endpoint_host, endpoint_port = bootstrap_result.host, bootstrap_result.port
        requested_host, requested_port = "127.0.0.1", bootstrap_result.remote_port

    return live_state.RemoteHandle(
        remote_id=origin_remote_id or _new_id("remote"),
        host=endpoint_host,
        port=endpoint_port,
        connected=True,
        origin_context_id=scope["origin_context_id"],
        context_locality=scope["context_locality"],
        reuse_policy=scope["reuse_policy"],
        transport=transport,
        remote_server=remote_server,
        server_info=server_info,
        bootstrap=bootstrap_detail,
        bootstrap_result=bootstrap_result,
        leased_session_id="",
        leased_session_ids=[],
        requested_host=requested_host,
        requested_port=requested_port,
        device_serial=device_serial,
        detail={
            "connected": True,
            "transport": transport,
            "endpoint": remote_records._remote_url(endpoint_host, endpoint_port),
            "requires_remote_device": transport == "adb_android",
            "bootstrap": dict(bootstrap_detail) if bootstrap_detail else {},
        },
    )


async def _recover_single_session_from_state(
    context_id: str,
    session_id: str,
    *,
    trace_id: str = "",
) -> Dict[str, Any]:
    ctx = normalize_context_id(context_id)
    state = context_records._context_state(ctx)
    sessions = state.setdefault("sessions", {})
    captures = state.setdefault("captures", {})
    session_record = dict(sessions.get(str(session_id)) or {})
    if not session_record:
        raise CoreError(
            code="session_not_found",
            message=f"Unknown session_id: {session_id}",
            category="not_found",
            details={"session_id": str(session_id)},
        )
    if str(session_record.get("backend_type") or "local") == "remote" and not remote_records._session_record_remote_metadata(session_record):
        raise RuntimeToolError(
            "Remote session recovery metadata is missing",
            details={"session_id": str(session_id)},
        )

    try:
        existing = live_state._session_manager.get_state(str(session_id))
    except Exception:
        existing = None
    if existing is not None:
        try:
            await live_state._session_manager.close_session(str(session_id))
        except Exception:
            pass

    capture_file_id = str(session_record.get("capture_file_id") or "")
    capture_record = captures.get(capture_file_id) if capture_file_id else None
    capture_path = str(session_record.get("rdc_path") or (capture_record or {}).get("file_path") or "").strip()
    capture_meta = context_records._capture_file_metadata(capture_path)
    if not capture_meta.get("file_path") or not Path(str(capture_meta.get("file_path"))).is_file():
        raise RuntimeToolError(
            "capture file missing",
            details={"session_id": str(session_id), "capture_path": capture_path},
        )

    if not capture_file_id:
        capture_file_id = _new_id("capf")
        session_record["capture_file_id"] = capture_file_id

    capture_handle = await _restore_capture_handle_from_state(
        ctx,
        capture_file_id,
        {
            "capture_file_id": capture_file_id,
            "file_path": str(capture_meta.get("file_path") or capture_path),
            "read_only": True,
            "driver": str((capture_record or {}).get("driver") or ""),
        },
    )
    if capture_handle is None:
        raise RuntimeToolError(
            "capture handle restore failed",
            details={"session_id": str(session_id), "capture_file_id": capture_file_id},
        )

    backend_type = str(session_record.get("backend_type") or "local")
    backend_config: Dict[str, Any] = {"type": "local"}
    remote_handle_for_session: Optional[live_state.RemoteHandle] = None
    remote_endpoint = ""
    if backend_type == "remote":
        remote_handle_for_session = await _restore_remote_handle_from_session_record(
            str(session_id),
            session_record,
        )
        remote_endpoint = str(remote_handle_for_session.detail.get("endpoint") or remote_records._remote_url(remote_handle_for_session.host, remote_handle_for_session.port))
        live_state._runtime.remotes[str(remote_handle_for_session.remote_id)] = remote_handle_for_session
        backend_config = {
            "type": "remote",
            "host": remote_handle_for_session.host,
            "port": remote_handle_for_session.port,
            "transport": remote_handle_for_session.transport,
            "remote_id": remote_handle_for_session.remote_id,
            "remote_server": remote_handle_for_session.remote_server,
            "close_remote_server_on_cleanup": False,
            "bootstrap": dict(remote_handle_for_session.bootstrap or {}),
            "bootstrap_result": remote_handle_for_session.bootstrap_result,
            "device_serial": remote_handle_for_session.device_serial,
        }

    if trace_id:
        oplog._record_operation_stage(
            ctx,
            trace_id=trace_id,
            stage="resume_session",
            message=f"Reopening {backend_type} session {session_id}",
            details={"session_id": session_id, "capture_file_id": capture_file_id, "backend_type": backend_type},
        )

    try:
        await live_state._session_manager.create_session(
            backend_config=backend_config,
            replay_config={},
            preferred_session_id=str(session_id),
        )
        await live_state._session_manager.open_capture(str(session_id), str(capture_handle.file_path))
        controller = live_state._session_manager.get_controller(str(session_id))
        roots = await renderdoc_api._offload(controller.GetRootActions)
        _, by_event = action_index._build_action_index(roots)
        desired_event_id = int(session_record.get("active_event_id") or 0)
        replay = live_state.ReplayHandle(
            session_id=str(session_id),
            capture_file_id=str(capture_file_id),
            frame_index=int(session_record.get("frame_index") or 0),
            active_event_id=0,
        )
        live_state._runtime.replays[str(session_id)] = replay
        if desired_event_id <= 0 or desired_event_id not in by_event:
            desired_event_id = await visual_target._pick_previewable_default_event_id(
                str(session_id),
                roots,
                fallback_event_id=action_index._pick_default_event_id(roots),
            )
        elif desired_event_id > 0:
            await renderdoc_api._offload(controller.SetFrameEvent, desired_event_id, True)
        replay = live_state.ReplayHandle(
            session_id=str(session_id),
            capture_file_id=str(capture_file_id),
            frame_index=int(session_record.get("frame_index") or 0),
            active_event_id=int(desired_event_id or 0),
        )
        live_state._runtime.replays[str(session_id)] = replay
        captures[str(capture_file_id)] = context_records._capture_record_from_runtime(str(capture_file_id))
        remote_metadata: Dict[str, Any] = {}
        if remote_handle_for_session is not None:
            origin_remote_id = str(remote_records._session_record_remote_metadata(session_record).get("origin_remote_id") or remote_handle_for_session.remote_id or _new_id("remote"))
            remote_handle_for_session.remote_id = origin_remote_id
            live_state._runtime.remotes[origin_remote_id] = remote_handle_for_session
            remote_session._register_remote_session_lease(str(session_id), remote_handle_for_session, context_id=ctx)
            remote_metadata = remote_records._remote_session_metadata(
                remote_handle_for_session,
                remote_id=origin_remote_id,
                endpoint=remote_endpoint,
            )
        restored_replacements = await shader_patches._reapply_session_replacements_from_record(str(session_id), session_record)
        if restored_replacements and desired_event_id > 0:
            await renderdoc_api._offload(controller.SetFrameEvent, int(desired_event_id), True)
        session_record["rdc_path"] = str(capture_handle.file_path)
        session_record["file_fingerprint"] = str(capture_meta.get("file_fingerprint") or "")
        session_record["file_size_bytes"] = int(capture_meta.get("file_size_bytes") or 0)
        session_record["active_event_id"] = int(desired_event_id or 0)
        session_record["state"] = "active"
        session_record["is_live"] = True
        session_record["last_error"] = ""
        session_record["shader_replacements"] = restored_replacements or list(session_record.get("shader_replacements") or [])
        session_record["updated_at_ms"] = settings._now_ms()
        if remote_metadata:
            session_record["remote"] = remote_metadata
        session_record["recovery"] = {
            **dict(session_record.get("recovery") or {}),
            "status": "recovered",
            "last_attempt_ms": settings._now_ms(),
            "last_success_ms": settings._now_ms(),
            "attempt_count": int(dict(session_record.get("recovery") or {}).get("attempt_count") or 0) + 1,
            "last_error": "",
        }
        sessions[str(session_id)] = session_record
        state["captures"] = captures
        state["sessions"] = sessions
        state = context_records._select_session_from_state(state, session_id=str(session_id), capture_file_id=str(capture_file_id))
        context_records._store_context_state(state, ctx)
        context_records._sync_context_metrics(ctx)
        context_records._set_context_runtime_session(
            str(session_id),
            capture_file_id=str(capture_file_id),
            backend_type=backend_type,
            frame_index=int(session_record.get("frame_index") or 0),
            active_event_id=int(desired_event_id or 0),
            remote_metadata=session_record.get("remote") if isinstance(session_record.get("remote"), dict) else {},
            context_id=ctx,
        )
        return sessions[str(session_id)]
    except Exception as exc:
        try:
            await live_state._session_manager.close_session(str(session_id))
        except Exception:
            pass
        live_state._runtime.replays.pop(str(session_id), None)
        cleanup_errors: List[str] = []
        if remote_handle_for_session is not None:
            remote_session._release_remote_session_lease(str(session_id), context_id=ctx)
            try:
                cleanup_errors = await renderdoc_api._offload(remote_target._disconnect_remote_handle_sync, remote_handle_for_session)
            except Exception as cleanup_exc:
                cleanup_errors = [str(cleanup_exc)]
            if not cleanup_errors and live_state._runtime.remotes.get(remote_handle_for_session.remote_id) is remote_handle_for_session:
                live_state._runtime.remotes.pop(remote_handle_for_session.remote_id, None)
        session_record["state"] = "degraded"
        session_record["is_live"] = False
        session_record["last_error"] = str(exc) if not cleanup_errors else f"{exc}; remote cleanup: {'; '.join(cleanup_errors)}"
        session_record["updated_at_ms"] = settings._now_ms()
        session_record["recovery"] = {
            **dict(session_record.get("recovery") or {}),
            "status": "degraded",
            "last_attempt_ms": settings._now_ms(),
            "attempt_count": int(dict(session_record.get("recovery") or {}).get("attempt_count") or 0) + 1,
            "last_error": session_record["last_error"],
        }
        sessions[str(session_id)] = session_record
        state["sessions"] = sessions
        context_records._store_context_state(state, ctx)
        context_records._sync_context_metrics(ctx)
        context_records._sync_context_snapshot_from_state(ctx)
        raise


async def _recover_context_sessions(context_id: str, *, recover_remote: bool = False) -> Dict[str, Any]:
    ctx = normalize_context_id(context_id)
    state = context_records._context_state(ctx)
    start_ms = settings._now_ms()
    trace_id = f"rcv_{ctx}_{start_ms}"
    recovered: list[str] = []
    degraded: list[str] = []
    deferred: list[str] = []
    oplog._record_operation_start(ctx, trace_id=trace_id, operation="rd.session.resume", transport="recovery", args={"context_id": ctx})
    oplog._record_operation_stage(ctx, trace_id=trace_id, stage="scan", message="Scanning persisted local sessions for recovery")
    recovery = dict(state.get("recovery") or {})
    recovery["status"] = "scanning"
    recovery["last_scan_ms"] = start_ms
    recovery["last_attempt_ms"] = start_ms
    recovery["attempt_count"] = int(recovery.get("attempt_count") or 0) + 1
    recovery["last_error"] = ""
    metrics = dict(state.get("metrics") or {})
    metrics["recovery_attempt_count"] = int(metrics.get("recovery_attempt_count") or 0) + 1
    state["recovery"] = recovery
    state["metrics"] = metrics
    context_records._store_context_state(state, ctx)

    session_limit = int(settings._runtime_limits().get("max_sessions_per_context", 4) or 4)
    sessions = state.get("sessions", {}) if isinstance(state.get("sessions"), dict) else {}
    captures = state.get("captures", {}) if isinstance(state.get("captures"), dict) else {}
    live_count = len(live_state._runtime.replays)
    for capture_file_id, capture_record in list(captures.items()):
        handle = await _restore_capture_handle_from_state(ctx, str(capture_file_id), dict(capture_record or {}))
        if handle is None:
            capture_record["recovery_status"] = "missing"
            capture_record["last_error"] = "capture file missing"
        else:
            capture_record["recovery_status"] = "ready"
            capture_record["last_error"] = ""
        capture_record["updated_at_ms"] = settings._now_ms()
        captures[str(capture_file_id)] = capture_record

    for session_id, session_record in list(sessions.items()):
        session_record = dict(session_record or {})
        backend_type = str(session_record.get("backend_type") or "local")
        if dict(session_record.get("recovery") or {}).get("status") == "requires_restart":
            session_record["state"] = "degraded"
            session_record["is_live"] = False
            sessions[str(session_id)] = session_record
            degraded.append(str(session_id))
            continue
        if live_count >= session_limit and session_id not in live_state._runtime.replays:
            session_record["state"] = "degraded"
            session_record["is_live"] = False
            session_record["last_error"] = "session limit exceeded during recovery"
            session_record["recovery"] = {
                **dict(session_record.get("recovery") or {}),
                "status": "degraded",
                "last_attempt_ms": settings._now_ms(),
                "attempt_count": int(dict(session_record.get("recovery") or {}).get("attempt_count") or 0) + 1,
                "last_error": "session limit exceeded during recovery",
            }
            sessions[str(session_id)] = session_record
            degraded.append(str(session_id))
            continue
        if session_id in live_state._runtime.replays:
            recovered.append(str(session_id))
            continue
        if backend_type == "remote" and not recover_remote:
            session_record["state"] = "degraded"
            session_record["is_live"] = False
            session_record["last_error"] = "remote session recovery deferred until an explicit live remote operation"
            session_record["updated_at_ms"] = settings._now_ms()
            session_record["recovery"] = {
                **dict(session_record.get("recovery") or {}),
                "status": "deferred",
                "last_attempt_ms": settings._now_ms(),
                "attempt_count": int(dict(session_record.get("recovery") or {}).get("attempt_count") or 0),
                "last_error": session_record["last_error"],
            }
            sessions[str(session_id)] = session_record
            deferred.append(str(session_id))
            continue
        try:
            updated_record = await _recover_single_session_from_state(
                ctx,
                str(session_id),
                trace_id=trace_id,
            )
            sessions[str(session_id)] = updated_record
            live_count += 1
            recovered.append(str(session_id))
        except Exception:
            sessions[str(session_id)] = dict(state.get("sessions", {}).get(str(session_id)) or session_record)
            degraded.append(str(session_id))

    recovery = dict(state.get("recovery") or {})
    recovery["status"] = "degraded" if degraded else "ready"
    recovery["last_scan_ms"] = settings._now_ms()
    recovery["last_success_ms"] = settings._now_ms() if recovered else int(recovery.get("last_success_ms") or 0)
    recovery["recovered_session_ids"] = recovered
    recovery["degraded_session_ids"] = degraded
    recovery["deferred_session_ids"] = deferred
    recovery["last_error"] = "" if not degraded else str((sessions.get(degraded[0]) or {}).get("last_error") or "")
    state["captures"] = captures
    state["sessions"] = sessions
    state["recovery"] = recovery
    metrics = dict(state.get("metrics") or {})
    if recovered:
        metrics["recovery_success_count"] = int(metrics.get("recovery_success_count") or 0) + len(recovered)
    if degraded:
        metrics["recovery_failure_count"] = int(metrics.get("recovery_failure_count") or 0) + len(degraded)
    metrics["last_recovery_ms"] = settings._now_ms()
    state["metrics"] = metrics
    state = context_records._select_session_from_state(state)
    context_records._store_context_state(state, ctx)
    context_records._sync_context_metrics(ctx)
    context_records._sync_context_snapshot_from_state(ctx)
    duration_ms = settings._now_ms() - start_ms
    oplog._record_operation_finish(
        ctx,
        trace_id=trace_id,
        payload=_recovery_payload(not degraded, duration_ms=duration_ms, message=recovery.get("last_error") or "", code="recovery_degraded"),
    )
    return context_records._context_state(ctx)


async def ensure_context_ready(context_id: Optional[str] = None) -> Dict[str, Any]:
    ctx = normalize_context_id(context_id or live_state._runtime_context_id())
    context_records._context_state(ctx)
    if ctx in live_state._runtime.hydrated_contexts:
        return context_records._sync_context_metrics(ctx)
    await _recover_context_sessions(ctx)
    live_state._runtime.hydrated_contexts.add(ctx)
    return context_records._context_state(ctx)
