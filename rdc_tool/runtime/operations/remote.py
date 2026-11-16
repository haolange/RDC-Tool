"""rd.remote.* operations."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Dict

from rdc_tool import remote_bootstrap
from rdc_tool.context_snapshot import normalize_context_id
from rdc_tool.core.errors import CoreError
from rdc_tool.core.renderdoc_status import build_renderdoc_error_details
from rdc_tool.models import _new_id
from rdc_tool.remote_bootstrap import AndroidRemoteBootstrapError
from rdc_tool.runtime import (
    coerce,
    envelope,
    live_state,
    oplog,
    remote_records,
    remote_session,
    remote_target,
    renderdoc_api,
)
from rdc_tool.timeout_policy import remote_connect_timeout_ms


async def dispatch(action: str, args: Dict[str, Any]) -> envelope.Outcome:
    if action == "inspect_installation":
        if live_state._runtime_context_id() == "default":
            return envelope.failure("Installation inspection requires an owning daemon context", code="remote_context_required", category="validation")
        if not live_state._runtime.enable_remote:
            return envelope.capability_failure("remote_disabled", "Remote tools disabled by config", capability="remote",
                reason="Remote tools are disabled by config.", source="runtime_config", optional=True)
        try:
            facts = await renderdoc_api._offload(remote_bootstrap.inspect_android_installation, str(args.get("device_serial") or ""))
            return envelope.success(context_id=live_state._runtime_context_id(), **facts)
        except AndroidRemoteBootstrapError as error:
            return envelope.failure(error.message, code=error.code, category="runtime", details=error.details)

    if action == "connect":
        options = coerce._as_dict(args.get("options"), default={})
        transport = str(options.get("transport") or "renderdoc").strip().lower() or "renderdoc"
        host = str(args.get("host") or "").strip()
        if transport != "adb_android" and not host:
            coerce._require(args, "host")
        if not host:
            host = "127.0.0.1"
        port = coerce._as_int(args.get("port"), 38920)
        timeout_ms = remote_connect_timeout_ms(args)
        if not live_state._runtime.enable_remote:
            return envelope.capability_failure(
                "remote_disabled",
                "Remote tools disabled by config",
                capability="remote",
                reason="Remote tools are disabled by config.",
                source="runtime_config",
                optional=True,
            )
        if transport not in {"renderdoc", "adb_android"}:
            return envelope.failure(
                f"Unsupported remote transport: {transport}",
                code="remote_transport_unsupported",
                category="runtime",
                details={"transport": transport},
            )

        endpoint_host = host
        endpoint_port = port
        bootstrap_detail: Dict[str, Any] = {}
        bootstrap_result = None

        try:
            if transport == "adb_android" and host not in {"", "127.0.0.1", "localhost"}:
                return envelope.failure("Android adb transport requires host=127.0.0.1 or localhost", code="android_remote_host_invalid", category="runtime")
            bootstrap_result, remote_server, server_info = await remote_target._connect_remote_endpoint(host, port, transport, options, timeout_ms)
            if bootstrap_result is not None:
                bootstrap_detail = remote_bootstrap.describe_android_remote(bootstrap_result)
                endpoint_host, endpoint_port = bootstrap_result.host, bootstrap_result.port
        except AndroidRemoteBootstrapError as exc:
            details = dict(exc.details)
            details.setdefault("remote", {"stage": "checking", "code": exc.code, "device_serial": str(options.get("device_serial") or "")})
            return envelope.failure(exc.message, code=exc.code, category="runtime", details=details)
        except CoreError as exc:
            if bootstrap_result is not None:
                try:
                    await renderdoc_api._offload(remote_bootstrap.cleanup_android_remote, bootstrap_result)
                except Exception:
                    pass
            details = dict(exc.details)
            remote_facts = details.setdefault("remote", {"stage": "verifying", "code": exc.code})
            remote_facts.setdefault("device_serial", str(options.get("device_serial") or ""))
            details.setdefault("transport", transport)
            details.setdefault("host", endpoint_host)
            details.setdefault("port", endpoint_port)
            details.setdefault("requested_host", host)
            details.setdefault("requested_port", port)
            return envelope.failure(exc.message, code=exc.code, category=exc.category, details=details)
        except Exception as exc:
            if bootstrap_result is not None:
                try:
                    await renderdoc_api._offload(remote_bootstrap.cleanup_android_remote, bootstrap_result)
                except Exception:
                    pass
            return envelope.failure(
                str(exc),
                code="remote_connect_failed",
                category="runtime",
                details={
                    "transport": transport,
                    "host": endpoint_host,
                    "port": endpoint_port,
                    "requested_host": host,
                    "requested_port": port,
                    "source_layer": "runtime",
                    "operation": "rd.remote.connect",
                    "backend_type": "remote",
                    "capture_context": {
                        "endpoint": remote_records._remote_url(endpoint_host, endpoint_port),
                        "remote_id": "",
                    },
                    "classification": "remote_endpoint",
                    "fix_hint": "Repair the remote endpoint or Android bootstrap path before retrying rd.remote.connect.",
                },
            )

        remote_id = _new_id("remote")
        detail = {
            "connected": True,
            "requires_remote_device": transport == "adb_android",
            "transport": transport,
            "endpoint": remote_records._remote_url(endpoint_host, endpoint_port),
        }
        live_state._runtime.remotes[remote_id] = live_state.RemoteHandle(
            remote_id=remote_id,
            host=endpoint_host,
            port=endpoint_port,
            connected=True,
            origin_context_id=normalize_context_id(live_state._runtime_context_id()),
            context_locality="strict",
            reuse_policy="must_reconnect",
            transport=transport,
            remote_server=remote_server,
            server_info=server_info,
            bootstrap=bootstrap_detail,
            bootstrap_result=bootstrap_result,
            requested_host=host,
            requested_port=port,
            device_serial=str(options.get("device_serial") or ""),
            detail=detail,
        )
        remote_session._set_context_remote_live(remote_id, detail["endpoint"])
        oplog._progress("context_synced", "Remote handle synchronized to context", progress_pct=1.0, details={"remote_id": remote_id, "endpoint": detail["endpoint"]})
        return envelope.success(context_id=live_state._runtime_context_id(), remote_id=remote_id, server_info=server_info, detail=detail)

    if action == "disconnect":
        coerce._require(args, "remote_id")
        remote_id = str(args["remote_id"])
        consumed = remote_session._remote_consumed_payload(remote_id)
        if consumed is not None:
            return consumed
        handle = live_state._runtime.remotes.get(remote_id)
        if handle is None:
            handle = await remote_session._rehydrate_remote_handle_from_snapshot(remote_id)
        if handle is None:
            return remote_session._remote_handle_missing_payload(remote_id)
        try:
            remote_session._assert_remote_handle_context(handle)
        except CoreError as exc:
            return envelope.failure(exc.message, code=exc.code, category=exc.category, details=dict(exc.details))
        active_session_ids = remote_records._remote_active_session_ids(handle)
        if active_session_ids:
            return envelope.failure(
                f"Remote handle {remote_id} is still leased by active session(s): {', '.join(active_session_ids)}",
                code="remote_handle_in_use",
                category="runtime",
                details={
                    "remote_id": remote_id,
                    "active_session_ids": active_session_ids,
                },
            )
        errors = await remote_target._offload_target_operation(remote_target._disconnect_remote_handle_sync, handle)
        if errors:
            return envelope.failure("Remote disconnect cleanup failed", code="remote_disconnect_failed", category="runtime",
                        details={"remote_id": remote_id, "cleanup_errors": errors})
        live_state._runtime.remotes.pop(remote_id, None)
        remote_session._clear_context_remote_live(remote_id)
        return envelope.success(detail={"connected": False})

    if action == "ping":
        coerce._require(args, "remote_id")
        remote_id = str(args["remote_id"])
        consumed = remote_session._remote_consumed_payload(remote_id)
        if consumed is not None:
            return consumed
        handle = live_state._runtime.remotes.get(remote_id)
        if handle is None:
            handle = await remote_session._rehydrate_remote_handle_from_snapshot(remote_id)
        if handle is None:
            return remote_session._remote_handle_missing_payload(remote_id)
        try:
            remote_session._assert_remote_handle_context(handle)
        except CoreError as exc:
            return envelope.failure(exc.message, code=exc.code, category=exc.category, details=dict(exc.details))
        if not handle.connected or handle.remote_server is None:
            return envelope.failure(
                f"Remote handle {remote_id} is not connected",
                code="remote_not_connected",
                category="runtime",
                details={"remote_id": remote_id},
            )
        started = time.perf_counter()
        try:
            status = await renderdoc_api._offload(handle.remote_server.Ping)
        except Exception as exc:
            handle.connected = False
            return envelope.failure(
                f"RemoteServer.Ping({remote_records._remote_url(handle.host, handle.port)}) failed: {exc}",
                code="remote_ping_failed",
                category="runtime",
                details={
                    "remote_id": remote_id,
                    "source_layer": "runtime",
                    "operation": "rd.remote.ping",
                    "backend_type": "remote",
                    "capture_context": {"remote_id": remote_id, "endpoint": remote_records._remote_url(handle.host, handle.port)},
                    "classification": "remote_endpoint",
                    "fix_hint": "Reconnect to the remote endpoint before issuing more remote tools.",
                },
            )
        latency_ms = round((time.perf_counter() - started) * 1000.0, 3)
        if not renderdoc_api._status_ok(status):
            handle.connected = False
            details = build_renderdoc_error_details(
                status,
                operation=f"RemoteServer.Ping({remote_records._remote_url(handle.host, handle.port)})",
                source_layer="renderdoc_status",
                backend_type="remote",
                capture_context={"remote_id": remote_id, "endpoint": remote_records._remote_url(handle.host, handle.port), "latency_ms": latency_ms},
                classification="remote_endpoint",
                fix_hint="Reconnect to the remote endpoint before issuing more remote tools.",
            )
            return envelope.failure(
                f"RemoteServer.Ping({remote_records._remote_url(handle.host, handle.port)}) failed: {details['renderdoc_status']['status_text']}",
                code="remote_ping_failed",
                category="runtime",
                details=details,
            )
        handle.detail["connected"] = True
        return envelope.success(
            latency_ms=latency_ms,
            server_info=handle.server_info,
            detail={
                "connected": True,
                "remote_id": remote_id,
                "transport": handle.transport,
                "endpoint": remote_records._remote_url(handle.host, handle.port),
                "active_session_ids": remote_records._remote_active_session_ids(handle),
            },
        )

    if action in {
        "list_targets",
        "launch_app",
        "set_capture_options",
        "trigger_capture",
        "queue_capture",
        "list_captures",
        "copy_capture",
        "delete_capture",
    }:
        coerce._require(args, "remote_id")
        remote_id = str(args["remote_id"])
        consumed = remote_session._remote_consumed_payload(remote_id)
        if consumed is not None:
            return consumed
        handle = live_state._runtime.remotes.get(remote_id)
        if handle is None:
            return envelope.failure(f"Unknown remote_id: {remote_id}", code="remote_not_found", category="runtime")
        try:
            remote_session._assert_remote_handle_context(handle)
        except CoreError as exc:
            return envelope.failure(exc.message, code=exc.code, category=exc.category, details=dict(exc.details))
        if not handle.connected or handle.remote_server is None:
            return envelope.failure(
                f"Remote handle {remote_id} is not connected",
                code="remote_not_connected",
                category="runtime",
                details={"remote_id": remote_id, "endpoint": remote_records._remote_url(handle.host, handle.port)},
            )
        if action == "list_targets":
            try:
                targets = await remote_target._offload_target_operation(remote_target._remote_list_targets_sync, handle)
            except Exception as exc:
                return envelope.failure(
                    f"Failed to enumerate remote targets: {exc}",
                    code="remote_target_enumeration_failed",
                    category="runtime",
                    details={"remote_id": remote_id, "endpoint": remote_records._remote_url(handle.host, handle.port)},
                )
            return envelope.success(targets=targets, detail={"remote_id": remote_id, "target_count": len(targets)})
        if action == "launch_app":
            coerce._require(args, "exe_path")
            try:
                target = await remote_target._offload_target_operation(
                    remote_target._launch_remote_app_sync,
                    handle,
                    exe_path=str(args.get("exe_path") or ""),
                    working_dir=str(args.get("working_dir") or ""),
                    cmdline=str(args.get("cmdline") or ""),
                    env=coerce._as_dict(args.get("env"), default={}),
                    capture_options=coerce._as_dict(args.get("capture_options"), default={}),
                )
            except Exception as exc:
                return envelope.failure(
                    f"Failed to launch remote app: {exc}",
                    code="remote_launch_failed",
                    category="runtime",
                    details={"remote_id": remote_id, "endpoint": remote_records._remote_url(handle.host, handle.port)},
                )
            return envelope.success(
                target_id=str(target.get("target_id") or ""),
                pid=int(target.get("pid") or 0),
                target=target,
            )
        if action == "set_capture_options":
            options = coerce._as_dict(args.get("options"), default={})
            _, applied_options = await renderdoc_api._offload(remote_target._capture_options_from_dict, options)
            handle.default_capture_options = {**dict(handle.default_capture_options or {}), **applied_options}
            return envelope.success(applied=applied_options, default_capture_options=dict(handle.default_capture_options))
        if action in {"trigger_capture", "queue_capture"}:
            try:
                result = await remote_target._offload_target_operation(
                    remote_target._trigger_remote_capture_sync,
                    handle,
                    target_id=str(args.get("target_id") or ""),
                    num_frames=coerce._as_int(args.get("num_frames"), 1),
                    capture_delay_ms=coerce._as_int(args.get("capture_delay_ms"), 0),
                    queued=action == "queue_capture",
                )
            except Exception as exc:
                return envelope.failure(
                    f"Failed to {action}: {exc}",
                    code=f"remote_{action}_failed",
                    category="runtime",
                    details={"remote_id": remote_id, "endpoint": remote_records._remote_url(handle.host, handle.port)},
                )
            if action == "trigger_capture":
                return envelope.success(captures=result.get("captures", []), target=result.get("target", {}))
            return envelope.success(queue_status=result.get("queue_status", {}), captures=result.get("captures", []), target=result.get("target", {}))
        if action == "list_captures":
            try:
                target_id = str(args.get("target_id") or "")
                if target_id:
                    captures = await remote_target._offload_target_operation(remote_target._poll_captures_for_target_sync, handle, target_id=target_id, deadline_s=1.0, max_messages=12)
                else:
                    targets = await remote_target._offload_target_operation(remote_target._remote_list_targets_sync, handle)
                    captures = remote_target._capture_records_for_target(handle)
                    for item in targets:
                        tid = str(item.get("target_id") or "")
                        if not tid:
                            continue
                        captures = await remote_target._offload_target_operation(remote_target._poll_captures_for_target_sync, handle, target_id=tid, deadline_s=0.5, max_messages=8)
                    captures = remote_target._capture_records_for_target(handle)
            except Exception as exc:
                return envelope.failure(
                    f"Failed to list remote captures: {exc}",
                    code="remote_list_captures_failed",
                    category="runtime",
                    details={"remote_id": remote_id, "endpoint": remote_records._remote_url(handle.host, handle.port)},
                )
            return envelope.success(captures=captures)
        if action == "copy_capture":
            coerce._require(args, "capture_id", "local_path")
            capture_id = str(args.get("capture_id") or "").strip()
            record = dict(handle.known_captures.get(capture_id) or {})
            target_id = str(record.get("target_id") or "")
            if not target_id:
                targets = await remote_target._offload_target_operation(remote_target._remote_list_targets_sync, handle)
                if len(targets) == 1:
                    target_id = str(targets[0].get("target_id") or "")
            ident = remote_target._remote_target_ident(target_id)
            if ident <= 0:
                return envelope.failure(
                    f"Unable to resolve target for capture_id: {capture_id}",
                    code="remote_capture_target_unknown",
                    category="runtime",
                    details={"remote_id": remote_id, "capture_id": capture_id},
                )
            local_path = Path(str(args.get("local_path") or "")).resolve()
            local_path.parent.mkdir(parents=True, exist_ok=True)
            try:
                await remote_target._offload_target_operation(remote_target._copy_remote_capture_sync, handle, ident, coerce._as_int(capture_id, 0), local_path)
            except Exception as exc:
                return envelope.failure(
                    f"Failed to copy remote capture: {exc}",
                    code="remote_copy_capture_failed",
                    category="runtime",
                    details={"remote_id": remote_id, "capture_id": capture_id, "local_path": str(local_path)},
                )
            return envelope.success(saved_path=str(local_path), capture=dict(handle.known_captures.get(capture_id) or record))
        if action == "delete_capture":
            coerce._require(args, "capture_id")
            capture_id = str(args.get("capture_id") or "").strip()
            record = dict(handle.known_captures.get(capture_id) or {})
            target_id = str(record.get("target_id") or "")
            if not target_id:
                targets = await remote_target._offload_target_operation(remote_target._remote_list_targets_sync, handle)
                if len(targets) == 1:
                    target_id = str(targets[0].get("target_id") or "")
            ident = remote_target._remote_target_ident(target_id)
            if ident <= 0:
                return envelope.failure(
                    f"Unable to resolve target for capture_id: {capture_id}",
                    code="remote_capture_target_unknown",
                    category="runtime",
                    details={"remote_id": remote_id, "capture_id": capture_id},
                )
            try:
                await remote_target._offload_target_operation(remote_target._delete_remote_capture_sync, handle, ident, coerce._as_int(capture_id, 0))
            except Exception as exc:
                return envelope.failure(
                    f"Failed to delete remote capture: {exc}",
                    code="remote_delete_capture_failed",
                    category="runtime",
                    details={"remote_id": remote_id, "capture_id": capture_id},
                )
            handle.known_captures.pop(capture_id, None)
            return envelope.success(detail={"deleted_capture_id": capture_id})
    return envelope.failure(f"Unsupported remote action: {action}", code="runtime_error")
