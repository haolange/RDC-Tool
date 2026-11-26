"""rd.session.* operations."""

from __future__ import annotations

from typing import Any, Dict

from rdc_tool import remote_bootstrap
from rdc_tool.context_snapshot import normalize_context_id, update_user_context
from rdc_tool.core.errors import CoreError
from rdc_tool.core.session_manager import SessionError
from rdc_tool.platform import process
from rdc_tool.platform.process import ProcessIdentity
from rdc_tool.remote_bootstrap import AndroidBootstrapResult
from rdc_tool.runtime import (
    coerce,
    context_records,
    discovery,
    envelope,
    live_state,
    observation,
    preview_sync,
    remote_session,
    remote_target,
    renderdoc_api,
    replay_access,
    session_recovery,
    settings,
    truth_matrix,
)
from rdc_tool.runtime_state import list_context_ids


@replay_access._guard_rejection
async def dispatch(action: str, args: Dict[str, Any]) -> envelope.Outcome:
    if action in {"get_replay_events", "observe"}:
        outcome = await observation.handle(action, args)
        if action == "observe" and isinstance(outcome, envelope.Failure) and outcome.code == "observation_event_invalid":
            scope = live_state._CURRENT_EVENT_REJECTION_SCOPE.get()
            if scope is not None:
                return replay_access._event_rejection_failure(
                    CoreError(code=outcome.code, message=outcome.message, category="validation",
                              details=dict(outcome.details)), scope, scope["session_id"])
        return outcome
    context_id = normalize_context_id(args.get("context_id") or live_state._runtime_context_id())

    if action == "get_context":
        await preview_sync._auto_sync_preview_if_enabled(context_id)
        snapshot = context_records._context_snapshot(context_id)
        state = context_records._sync_context_metrics(context_id)
        current_session_id = str(state.get("current_session_id") or "").strip()
        sessions = state.get("sessions", {}) if isinstance(state.get("sessions"), dict) else {}
        current_session_record = dict(sessions.get(current_session_id) or {}) if isinstance(sessions, dict) else {}
        current_backend = live_state._normalize_backend(
            str(current_session_record.get("backend_type") or snapshot.get("backend") or "local"),
            default="local",
        )
        remote_snapshot = dict(snapshot.get("remote") or {})
        remote_capability_matrix = (
            truth_matrix._session_remote_capability_matrix(
                current_session_id,
                context_id=context_id,
                probe_live=False,
            )
            if current_session_id and current_backend == "remote"
            else {}
        )
        active_operation: Dict[str, Any] = {}
        try:
            from rdc_tool.daemon.state import load_state

            daemon_state = load_state(context=context_id)
            active_operation = dict(daemon_state.get("active_operation") or {})
        except Exception:
            active_operation = {}
        from rdc_tool.runtime_process_identity import runtime_process_identity

        return envelope.success(
            **snapshot,
            session_locator=discovery._session_locator_projection(snapshot, state),
            current_session_id=current_session_id,
            sessions=list(state.get("sessions", {}).values()),
            recovery=dict(state.get("recovery") or {}),
            limits=dict(state.get("limits") or {}),
            active_operation=active_operation,
            process_identity=runtime_process_identity(),
            recent_operations=list(state.get("recent_operations") or []),
            remote_capability_matrix=remote_capability_matrix,
            remote_context_locality=str(remote_snapshot.get("context_locality") or "strict"),
            remote_handle_origin_context=str(remote_snapshot.get("origin_context_id") or ""),
            remote_handle_reuse_policy=str(remote_snapshot.get("reuse_policy") or "must_reconnect"),
        )

    if action == "create_context":
        requested_context = normalize_context_id(args["new_context_id"])
        context_records._ensure_context_capacity(requested_context)
        state = context_records._context_state(requested_context)
        context_records._store_context_state(state, requested_context)
        snapshot = context_records._sync_context_snapshot_from_state(requested_context)
        return envelope.success(
            **snapshot,
            current_session_id=str(state.get("current_session_id") or ""),
            sessions=list(state.get("sessions", {}).values()),
            recovery=dict(state.get("recovery") or {}),
            limits=dict(state.get("limits") or {}),
        )

    if action == "list_contexts":
        context_ids = sorted({normalize_context_id(item) for item in list_context_ids()} | {context_id})
        return envelope.success(context_id=context_id, contexts=[discovery._context_summary(item) for item in context_ids])


    if action == "clear_context":
        requested_context = normalize_context_id(args.get("target_context_id") or args.get("context_id") or context_id)
        await preview_sync._close_preview_binding(requested_context)
        # Release live resources before discarding the only ownership record.
        current = context_records._context_state(requested_context)
        cleanup_errors = []
        lost_remote_sessions = set()
        for sid, record in list(current.get("sessions", {}).items()):
            try:
                try:
                    live_state._session_manager.get_state(sid)
                except SessionError as exc:
                    # Recovery can leave a remote session deferred or degraded after
                    # closing its native handle. Keep the durable ownership record
                    # until all remaining remote resources are verified and released.
                    recovery = record.get("recovery") or {} if isinstance(record, dict) else {}
                    worker_exit = recovery.get("worker_exit") if isinstance(recovery, dict) else None
                    restart_exit_confirmed = (
                        isinstance(worker_exit, dict)
                        and type(worker_exit.get("pid")) is int and worker_exit["pid"] > 0
                        and isinstance(worker_exit.get("birth"), str)
                        and process.probe(ProcessIdentity(worker_exit["pid"], worker_exit["birth"])) is process.Liveness.EXITED
                    )
                    if not (
                        exc.detail.code == "session_not_found"
                        and isinstance(record, dict)
                        and record.get("backend_type") == "remote"
                        and record.get("is_live") is False
                        and recovery.get("status") in {"deferred", "degraded", "requires_restart"}
                        and (
                            recovery.get("status") == "deferred"
                            or record.get("state") == "degraded"
                        )
                        and (recovery.get("status") != "requires_restart" or restart_exit_confirmed)
                        and not record.get("shader_replacements")
                        and not live_state._runtime.shader_replacements.get(sid)
                        and sid not in live_state._runtime.replays
                        and sid not in live_state._runtime.session_owned_remotes
                    ):
                        raise
                    if recovery.get("status") == "requires_restart":
                        lost_remote_sessions.add(sid)
                else:
                    await live_state._session_manager.close_session(sid)
                remote_session._release_remote_session_lease(sid, context_id=requested_context)
                live_state._runtime.replays.pop(sid, None)
            except Exception as exc:
                cleanup_errors.append(str(exc))
        if cleanup_errors:
            return envelope.failure("Context cleanup failed", code="context_cleanup_failed", details={"cleanup_errors": cleanup_errors, "cleanup_reason_code": "session_cleanup_failed"})
        for rid, handle in list(live_state._runtime.remotes.items()):
            if normalize_context_id(handle.origin_context_id) != requested_context:
                continue
            errors = await renderdoc_api._offload(remote_target._disconnect_remote_handle_sync, handle)
            if errors:
                cleanup_errors.extend(errors)
            else:
                live_state._runtime.remotes.pop(rid, None)
        if cleanup_errors:
            return envelope.failure("Context cleanup failed", code="context_cleanup_failed", details={"cleanup_errors": cleanup_errors, "cleanup_reason_code": "remote_handle_cleanup_failed"})
        # A restarted daemon has no RemoteHandle, but the persisted snapshot
        # still owns the exact ADB forward created by this context. Reuse the
        # bootstrap cleanup, which verifies the current forward identity.
        remote = dict(context_records._context_snapshot(requested_context).get("remote") or {})
        bootstrap = dict(remote.get("bootstrap") or {})
        remote_state = remote.get("state")
        if lost_remote_sessions:
            recorded_sessions = set(remote.get("active_session_ids") or [])
            consumed = str(remote.get("consumed_by_session_id") or "")
            if (remote_state not in {"expired", "session_owned"} or remote.get("transport") != "adb_android"
                    or remote.get("origin_context_id") != requested_context
                    or not recorded_sessions.issubset(lost_remote_sessions)
                    or (consumed and consumed not in lost_remote_sessions)):
                cleanup_errors.append("Lost remote session ownership or release is unconfirmed")
        if remote_state in {"expired", "session_owned"} and remote.get("transport") == "adb_android" and not cleanup_errors:
            if bootstrap.get("started_activity") or bootstrap.get("created_forward"):
                serial = str(bootstrap.get("device_serial") or "")
                port = coerce._as_int(bootstrap.get("port"), 0)
                remote_port = coerce._as_int(bootstrap.get("remote_port"), 0)
                if not (
                    remote.get("origin_context_id") == requested_context
                    and serial
                    and serial == remote.get("device_serial")
                    and serial == (remote.get("options") or {}).get("device_serial")
                    and port > 0
                    and port == coerce._as_int((remote.get("options") or {}).get("local_port"), 0)
                    and remote_port > 0
                    and remote_port == coerce._as_int((remote.get("options") or {}).get("remote_port"), 0)
                    and bootstrap.get("forward_spec") == f"tcp:{port}"
                    and remote.get("endpoint") == f"127.0.0.1:{port}"
                ):
                    cleanup_errors.append("Expired ADB forward ownership is incomplete or inconsistent")
                else:
                    try:
                        cleanup_errors.extend(await renderdoc_api._offload(remote_bootstrap.cleanup_android_remote, AndroidBootstrapResult(
                            adb_path=remote_bootstrap.resolve_adb_path(),
                            device_serial=serial,
                            package_name=str(bootstrap.get("package_name") or ""),
                            activity_name=str(bootstrap.get("activity_name") or ""),
                            abi=str(bootstrap.get("abi") or ""),
                            host="127.0.0.1",
                            port=port,
                            remote_port=remote_port,
                            apk_path=str(bootstrap.get("apk_path") or ""),
                            forward_spec=f"tcp:{port}",
                            created_forward=bool(bootstrap.get("created_forward")),
                            started_activity=bool(bootstrap.get("started_activity")),
                            owned_pids=[int(pid) for pid in list(bootstrap.get("owned_pids") or []) if isinstance(pid, int) and not isinstance(pid, bool) and pid > 0],
                        )))
                    except Exception as exc:
                        cleanup_errors.append(str(exc))
        if cleanup_errors:
            return envelope.failure("Context cleanup failed", code="context_cleanup_failed", details={"cleanup_errors": cleanup_errors, "cleanup_reason_code": "expired_remote_cleanup_failed"})
        cleanup_errors = await remote_session._release_device_transfers(requested_context)
        if cleanup_errors:
            return envelope.failure("Context cleanup failed", code="context_cleanup_failed", details={"cleanup_errors": cleanup_errors, "cleanup_reason_code": "device_transfer_cleanup_failed"})
        snapshot = context_records._reset_context_snapshot(requested_context)
        state = context_records._context_state(requested_context)
        return envelope.success(
            **snapshot,
            current_session_id=str(state.get("current_session_id") or ""),
            sessions=list(state.get("sessions", {}).values()),
            recovery=dict(state.get("recovery") or {}),
            limits=dict(state.get("limits") or {}),
        )

    if action == "update_context":
        coerce._require(args, "key")
        key = str(args["key"] or "").strip()
        try:
            snapshot = update_user_context(
                context_records._context_snapshot(context_id),
                key,
                args.get("value"),
                retention=settings._snapshot_retention(),
            )
        except ValueError as exc:
            return envelope.failure(str(exc), code="validation_error", category="validation")
        snapshot = context_records._store_context_snapshot(snapshot, context_id)
        return envelope.success(**snapshot)

    if action == "open_preview":
        requested_session_id = str(args.get("session_id") or "").strip()
        try:
            payload = await preview_sync._open_context_preview(context_id, requested_session_id=requested_session_id)
        except CoreError as exc:
            return envelope.failure(exc.message, code=exc.code, category=exc.category, details=dict(exc.details))
        return envelope.success(**payload)

    if action == "close_preview":
        payload = await preview_sync._close_context_preview(context_id)
        return envelope.success(**payload)

    if action == "list_sessions":
        state = context_records._sync_context_metrics(context_id)
        snapshot = context_records._context_snapshot(context_id)
        return envelope.success(
            context_id=context_id,
            current_session_id=str(state.get("current_session_id") or ""),
            sessions=list(state.get("sessions", {}).values()),
            recovery=dict(state.get("recovery") or {}),
            limits=dict(state.get("limits") or {}),
            backend=str(snapshot.get("backend") or "local"),
        )

    if action == "select_session":
        coerce._require(args, "session_id")
        session_id = str(args["session_id"] or "").strip()
        state = context_records._context_state(context_id)
        if session_id in state.get("sessions", {}):
            if session_id not in live_state._runtime.replays:
                try:
                    await replay_access._ensure_live_session(session_id)
                except CoreError as exc:
                    if exc.code == "session_resume_failed":
                        return envelope.failure(
                            exc.message,
                            code=exc.code,
                            category=exc.category,
                            details=dict(exc.details),
                        )
        snapshot = context_records._select_context_session_state(session_id, context_id=context_id)
        await preview_sync._auto_sync_preview_if_enabled(context_id)
        snapshot = context_records._context_snapshot(context_id)
        state = context_records._context_state(context_id)
        return envelope.success(
            **snapshot,
            current_session_id=str(state.get("current_session_id") or ""),
            sessions=list(state.get("sessions", {}).values()),
            recovery=dict(state.get("recovery") or {}),
            limits=dict(state.get("limits") or {}),
            recent_operations=list(state.get("recent_operations") or []),
        )

    if action == "resume":
        requested_session_id = str(args.get("session_id") or "").strip()
        await session_recovery._recover_context_sessions(context_id, recover_remote=True)
        if requested_session_id:
            state = context_records._context_state(context_id)
            session = dict(state.get("sessions", {}).get(requested_session_id) or {})
            if not session:
                return envelope.failure(
                    f"Unknown session_id: {requested_session_id}",
                    code="session_not_found",
                    category="not_found",
                    details={"session_id": requested_session_id},
                )
            if not bool(session.get("is_live")):
                try:
                    await replay_access._ensure_live_session(requested_session_id)
                except CoreError as exc:
                    if exc.code == "session_resume_failed":
                        return envelope.failure(
                            exc.message,
                            code=exc.code,
                            category=exc.category,
                            details=dict(exc.details),
                        )
                state = context_records._context_state(context_id)
                session = dict(state.get("sessions", {}).get(requested_session_id) or {})
                if not bool(session.get("is_live")):
                    return envelope.failure(
                        f"Session could not be resumed: {requested_session_id}",
                        code="session_resume_failed",
                        category="runtime",
                        details={"session_id": requested_session_id, "last_error": str(session.get("last_error") or "")},
                    )
            context_records._select_context_session_state(requested_session_id, context_id=context_id)
        await preview_sync._auto_sync_preview_if_enabled(context_id)
        state = context_records._context_state(context_id)
        snapshot = context_records._context_snapshot(context_id)
        return envelope.success(
            **snapshot,
            current_session_id=str(state.get("current_session_id") or ""),
            sessions=list(state.get("sessions", {}).values()),
            recovery=dict(state.get("recovery") or {}),
            limits=dict(state.get("limits") or {}),
            recent_operations=list(state.get("recent_operations") or []),
        )

    return envelope.failure(f"Unsupported session action: {action}", code="runtime_error")
