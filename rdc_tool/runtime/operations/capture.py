"""rd.capture.* operations."""

from __future__ import annotations

import base64
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from rdc_tool.core.errors import CoreError
from rdc_tool.models import _new_id
from rdc_tool.runtime import (
    action_index,
    coerce,
    context_records,
    envelope,
    live_state,
    oplog,
    remote_records,
    remote_session,
    renderdoc_api,
    replay_access,
    visual_target,
)


async def dispatch(action: str, args: Dict[str, Any]) -> envelope.Outcome:
    if action == "open_file":
        coerce._require(args, "file_path")
        file_path = str(args["file_path"])
        read_only = coerce._as_bool(args.get("read_only"), True)
        path = Path(file_path)
        if not path.is_file():
            return envelope.failure(f"Capture file not found: {file_path}", code="runtime_error")
        state = context_records._context_state(live_state._runtime_context_id())
        limits = dict(state.get("limits") or {})
        file_meta = context_records._capture_file_metadata(str(path))
        if int(file_meta.get("file_size_bytes") or 0) > int(limits.get("max_capture_size_bytes") or 0):
            metrics = dict(state.get("metrics") or {})
            metrics["rejection_count"] = int(metrics.get("rejection_count") or 0) + 1
            state["metrics"] = metrics
            context_records._store_context_state(state, live_state._runtime_context_id())
            return envelope.failure(
                f"Capture file exceeds limit: {file_path}",
                code="capture_file_too_large",
                category="runtime",
                details={
                    "file_path": str(path),
                    "file_size_bytes": int(file_meta.get("file_size_bytes") or 0),
                    "max_capture_size_bytes": int(limits.get("max_capture_size_bytes") or 0),
                },
            )
        if len(state.get("captures", {})) >= int(limits.get("max_capture_files") or 1):
            metrics = dict(state.get("metrics") or {})
            metrics["rejection_count"] = int(metrics.get("rejection_count") or 0) + 1
            state["metrics"] = metrics
            context_records._store_context_state(state, live_state._runtime_context_id())
            return envelope.failure(
                "Capture file limit exceeded",
                code="capture_limit_exceeded",
                category="runtime",
                details={
                    "max_capture_files": int(limits.get("max_capture_files") or 0),
                    "active_capture_count": len(state.get("captures", {})),
                },
            )
        oplog._progress(
            "capture_file_validated",
            "Capture file validated",
            progress_pct=0.1,
            details={
                "file_path": str(path),
                "file_size_bytes": int(file_meta.get("file_size_bytes") or 0),
            },
        )
        driver = ""
        try:
            rd = renderdoc_api._get_rd()
            cap = await renderdoc_api._offload(rd.OpenCaptureFile)
            status = await renderdoc_api._offload(cap.OpenFile, str(path), "", None)
            renderdoc_api._check_status(status, "OpenFile")
            try:
                if hasattr(cap, "DriverName"):
                    driver = str(await renderdoc_api._offload(cap.DriverName) or "")
            finally:
                if hasattr(cap, "CloseFile"):
                    await renderdoc_api._offload(cap.CloseFile)
                elif hasattr(cap, "Shutdown"):
                    await renderdoc_api._offload(cap.Shutdown)
        except Exception:
            driver = ""

        capture_file_id = _new_id("capf")
        live_state._runtime.captures[capture_file_id] = live_state.CaptureFileHandle(
            capture_file_id=capture_file_id,
            file_path=str(path),
            read_only=read_only,
            driver=driver,
        )
        context_records._set_context_capture_file(capture_file_id)
        return envelope.success(context_id=live_state._runtime_context_id(), capture_file_id=capture_file_id, driver=driver)

    if action == "close_file":
        coerce._require(args, "capture_file_id")
        capture_file_id = str(args["capture_file_id"])
        if capture_file_id not in live_state._runtime.captures:
            return envelope.failure(f"Unknown capture_file_id: {capture_file_id}", code="runtime_error")
        dependent_session_ids = replay_access._capture_dependent_session_ids(capture_file_id)
        if dependent_session_ids:
            return envelope.failure(
                f"Capture file still in use: {capture_file_id}",
                code="capture_file_in_use",
                category="runtime",
                details={
                    "capture_file_id": capture_file_id,
                    "dependent_session_ids": dependent_session_ids,
                    "dependent_session_count": len(dependent_session_ids),
                },
            )
        live_state._runtime.captures.pop(capture_file_id, None)
        context_records._clear_context_capture_file(capture_file_id)
        return envelope.success()

    if action == "get_thumbnail":
        from rdc_tool.core.capture_queries import read_thumbnail
        coerce._require(args, "capture_file_id")
        handle = live_state._runtime.captures.get(str(args["capture_file_id"]))
        if handle is None:
            return envelope.failure("Unknown capture_file_id", code="capture_not_found")
        image_format = str(args.get("format", "png")).lower()
        max_size = int(args.get("max_size", 256))
        if image_format not in {"png", "jpg"} or not 1 <= max_size <= 2048:
            return envelope.failure("Invalid thumbnail format or size", code="validation_error")
        data = await renderdoc_api._offload(read_thumbnail, renderdoc_api._get_rd(), handle.file_path, image_format, max_size)
        if not data:
            return envelope.failure("Capture has no embedded thumbnail", code="thumbnail_unavailable")
        result = {"capture_file_id": str(args["capture_file_id"]), "format": image_format,
                  "byte_size": len(data), "source": "embedded_capture_thumbnail"}
        if args.get("output_path"):
            path = Path(str(args["output_path"]))
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            result["saved_path"] = str(path)
        else:
            result["base64"] = base64.b64encode(data).decode("ascii")
        return envelope.success(**result)

    if action == "get_info":
        coerce._require(args, "capture_file_id")
        handle = live_state._runtime.captures.get(str(args["capture_file_id"]))
        if handle is None:
            return envelope.failure(f"Unknown capture_file_id: {args['capture_file_id']}", code="runtime_error")
        path = Path(handle.file_path)
        metadata = {
            "path": str(path),
            "name": path.name,
            "api": handle.driver,
            "size_bytes": int(path.stat().st_size) if path.exists() else 0,
            "mtime_utc": datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat() if path.exists() else None,
        }
        return envelope.success(metadata=coerce._sanitize_dict(metadata))


    if action == "open_replay":
        coerce._require(args, "capture_file_id")
        capture_file_id = str(args["capture_file_id"])
        handle = live_state._runtime.captures.get(capture_file_id)
        if handle is None:
            return envelope.failure(f"Unknown capture_file_id: {capture_file_id}", code="runtime_error")
        state = context_records._context_state(live_state._runtime_context_id())
        for existing_session_id, replay in list(live_state._runtime.replays.items()):
            if str(getattr(replay, "capture_file_id", "") or "") == capture_file_id:
                return envelope.success(
                    session_id=str(existing_session_id),
                    capture_file_id=capture_file_id,
                    active_event_id=int(getattr(replay, "active_event_id", 0) or 0),
                    recovery_status="ready",
                    reused_session=True,
                    frame_count=1,
                    api_properties={},
                )
        stale_session_ids = [
            str(sid)
            for sid, record in dict(state.get("sessions") or {}).items()
            if isinstance(record, dict) and str(record.get("capture_file_id") or "") == capture_file_id
        ]
        for stale_session_id in stale_session_ids:
            try:
                await live_state._session_manager.close_session(stale_session_id)
                live_state._runtime.replays.pop(stale_session_id, None)
                context_records._clear_context_runtime(stale_session_id)
            except Exception as exc:
                return envelope.failure(
                    "A stale replay session for this capture could not be cleaned up before reopen",
                    code="stale_session_requires_restart",
                    category="runtime",
                    details={
                        "capture_file_id": capture_file_id,
                        "stale_session_id": stale_session_id,
                        "context_id": live_state._runtime_context_id(),
                        "error": str(exc),
                        "recovery_steps": [
                            "rdc-tool context status --json",
                            "rdc-tool call rd.capture.close_replay --args-file close_replay_args.json --format json",
                            "rdc-tool daemon stop --daemon-context <context>",
                        ],
                    },
                )
        state = context_records._context_state(live_state._runtime_context_id())
        limits = dict(state.get("limits") or {})
        session_count = len(state.get("sessions", {}))
        if session_count >= int(limits.get("max_sessions_per_context") or 1):
            metrics = dict(state.get("metrics") or {})
            metrics["rejection_count"] = int(metrics.get("rejection_count") or 0) + 1
            state["metrics"] = metrics
            context_records._store_context_state(state, live_state._runtime_context_id())
            return envelope.failure(
                "Session limit exceeded for current context",
                code="session_limit_exceeded",
                category="runtime",
                details={
                    "max_sessions_per_context": int(limits.get("max_sessions_per_context") or 0),
                    "active_session_count": session_count,
                    "context_id": live_state._runtime_context_id(),
                },
            )
        file_meta = context_records._capture_file_metadata(handle.file_path)
        estimated_replay_memory_bytes = context_records._estimated_replay_memory_bytes(int(file_meta.get("file_size_bytes") or 0))
        if estimated_replay_memory_bytes > int(limits.get("max_estimated_replay_memory_bytes") or 0):
            metrics = dict(state.get("metrics") or {})
            metrics["rejection_count"] = int(metrics.get("rejection_count") or 0) + 1
            state["metrics"] = metrics
            context_records._store_context_state(state, live_state._runtime_context_id())
            return envelope.failure(
                "Estimated replay memory exceeds limit",
                code="replay_memory_limit_exceeded",
                category="runtime",
                details={
                    "capture_file_id": capture_file_id,
                    "file_size_bytes": int(file_meta.get("file_size_bytes") or 0),
                    "estimated_replay_memory_bytes": estimated_replay_memory_bytes,
                    "max_estimated_replay_memory_bytes": int(limits.get("max_estimated_replay_memory_bytes") or 0),
                },
            )
        oplog._progress("capture_open_started", "Opening replay session", progress_pct=0.55, details={"capture_file_id": capture_file_id})
        options = coerce._as_dict(args.get("options"), default={})
        remote_id = str(options.get("remote_id") or "").strip()
        backend_type = "local"
        backend_config: Dict[str, Any] = {"type": "local"}
        remote_handle_for_session: live_state.RemoteHandle | None = None
        remote_endpoint = ""
        if remote_id:
            consumed = remote_session._remote_consumed_payload(remote_id)
            if consumed is not None:
                return consumed
            remote_handle = live_state._runtime.remotes.get(remote_id)
            if remote_handle is None:
                remote_handle = await remote_session._rehydrate_remote_handle_from_snapshot(remote_id)
            if remote_handle is None:
                return remote_session._remote_handle_missing_payload(remote_id)
            if not remote_handle.connected or remote_handle.remote_server is None:
                return envelope.failure(
                    f"Remote handle {remote_id} is not connected",
                    code="remote_not_connected",
                    category="runtime",
                    details={"remote_id": remote_id, "endpoint": remote_records._remote_url(remote_handle.host, remote_handle.port)},
                )
            try:
                remote_session._assert_remote_handle_context(remote_handle)
            except CoreError as exc:
                return envelope.failure(exc.message, code=exc.code, category=exc.category, details=dict(exc.details))
            remote_handle_for_session = remote_handle
            remote_endpoint = remote_records._remote_url(remote_handle.host, remote_handle.port)
            backend_type = "remote"
            backend_config = {
                "type": "remote",
                "host": remote_handle.host,
                "port": remote_handle.port,
                "transport": remote_handle.transport,
                "remote_id": remote_id,
                "remote_server": remote_handle.remote_server,
                "close_remote_server_on_cleanup": False,
                "bootstrap": dict(remote_handle.bootstrap or {}),
                "bootstrap_result": remote_handle.bootstrap_result,
                "device_serial": remote_handle.device_serial,
            }
        session_info = await live_state._session_manager.create_session(
            backend_config=backend_config,
            replay_config={},
        )
        oplog._progress("session_created", "Replay session allocated", progress_pct=0.72, details={"session_id": session_info.session_id, "backend_type": backend_type})
        try:
            reporter = live_state._current_progress_reporter()
            if backend_type == "remote" and reporter is not None:
                live_state._session_manager.get_state(session_info.session_id).transfer_progress = lambda stage, fraction: reporter.emit(stage, "Transferring capture", progress_pct=fraction, details={"session_id": session_info.session_id})
            cap_info = await live_state._session_manager.open_capture(session_info.session_id, handle.file_path)
            oplog._progress("capture_open_done", "Capture opened for replay", progress_pct=0.82, details={"session_id": session_info.session_id})
            # The session already exists in SessionManager after open_capture().
            # Avoid recovery-aware helpers until _runtime.replays/context state is
            # populated for the first time, otherwise a fresh session can be
            # misclassified as missing and surface as session_not_found.
            controller = live_state._session_manager.get_controller(session_info.session_id)
            roots = await renderdoc_api._offload(controller.GetRootActions)
            live_state._runtime.replays[session_info.session_id] = live_state.ReplayHandle(
                session_id=session_info.session_id,
                capture_file_id=capture_file_id,
                frame_index=0,
                active_event_id=0,
            )
            active_event_id = await visual_target._pick_previewable_default_event_id(
                session_info.session_id,
                roots,
                fallback_event_id=action_index._pick_default_event_id(roots),
            )
            live_state._runtime.replays[session_info.session_id].active_event_id = int(active_event_id or 0)
            oplog._progress("root_actions_loaded", "Frame actions loaded", progress_pct=0.91, details={"active_event_id": active_event_id})
            if remote_handle_for_session is not None:
                remote_session._register_remote_session_lease(session_info.session_id, remote_handle_for_session)
            context_records._set_context_runtime_session(
                session_info.session_id,
                capture_file_id=capture_file_id,
                backend_type=backend_type,
                frame_index=0,
                active_event_id=active_event_id,
                remote_metadata=(
                    remote_records._remote_session_metadata(
                        remote_handle_for_session,
                        remote_id=remote_id,
                        endpoint=remote_endpoint,
                    )
                    if remote_handle_for_session is not None
                    else {}
                ),
            )
            oplog._progress(
                "open_replay_state_persisted",
                "Replay state persisted",
                progress_pct=0.98,
                details={
                    "session_id": session_info.session_id,
                    "capture_file_id": capture_file_id,
                    "active_event_id": active_event_id,
                    "recovery_status": "ready",
                },
            )
            api_properties = {}
            oplog._progress(
                "open_replay_response_ready",
                "Replay response ready",
                progress_pct=1.0,
                details={"session_id": session_info.session_id, "capture_file_id": capture_file_id},
            )
            return envelope.success(
                context_id=live_state._runtime_context_id(),
                session_id=session_info.session_id,
                capture_file_id=capture_file_id,
                remote_id=remote_id or None,
                active_event_id=int(active_event_id or 0),
                recovery_status="ready",
                frame_count=max(1, int(getattr(cap_info, "frame_count", 1))),
                api_properties=api_properties,
            )
        except Exception:
            try:
                await live_state._session_manager.close_session(session_info.session_id)
            except Exception:
                pass
            live_state._runtime.replays.pop(session_info.session_id, None)
            if remote_handle_for_session is not None:
                remote_session._release_remote_session_lease(session_info.session_id)
                remote_session._set_context_remote_live(remote_id, remote_endpoint)
            raise
    if action == "close_replay":
        coerce._require(args, "session_id")
        session_id = str(args["session_id"])
        owned_remote = remote_session._release_remote_session_lease(session_id)
        if live_state._patch_engine is not None:
            try:
                await live_state._patch_engine.revert_all(session_id, live_state._session_manager)
            except Exception:
                pass
        live_state._runtime.shader_replacements.pop(session_id, None)
        live_state._runtime.restored_shader_sessions.discard(session_id)
        live_state._runtime.replays.pop(session_id, None)
        await live_state._session_manager.close_session(session_id)
        if owned_remote is not None and owned_remote.remote_id in live_state._runtime.remotes:
            remote_session._set_context_remote_live(owned_remote.remote_id, remote_records._remote_url(owned_remote.host, owned_remote.port))
        context_records._clear_context_runtime(session_id)
        return envelope.success()

    return envelope.failure(f"Unsupported capture action: {action}", code="runtime_error")
