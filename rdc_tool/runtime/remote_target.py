"""Remote server connections and target control (launch, capture, copy)."""

from __future__ import annotations

import asyncio
import contextvars
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from rdc_tool import remote_bootstrap
from rdc_tool.core.errors import CoreError, RuntimeToolError
from rdc_tool.core.renderdoc_status import build_renderdoc_error_details, status_code_name
from rdc_tool.remote_bootstrap import (
    AndroidBootstrapOptions,
    AndroidRemoteBootstrapError,
    ConnectionBudget,
    _connection_budget,
)
from rdc_tool.runtime import coerce, live_state, oplog, remote_records, renderdoc_api, settings


def _wait_for_remote_endpoint(url: str, timeout_ms: int) -> None:
    rd = renderdoc_api._get_rd()
    timeout_s = max(int(timeout_ms or 0), 1) / 1000.0
    deadline = time.perf_counter() + timeout_s
    last_status: Any = None
    last_progress_ts = 0.0
    while True:
        budget = _connection_budget.get()
        if budget:
            budget.remaining()
        status = rd.CheckRemoteServerConnection(url)
        if renderdoc_api._status_ok(status):
            return
        last_status = status
        now = time.perf_counter()
        if (now - last_progress_ts) >= 2.0:
            last_progress_ts = now
            oplog._progress(
                "waiting_endpoint",
                "Remote endpoint is still unavailable, retrying",
                progress_pct=0.35,
                details={"endpoint": url},
            )
        native_code = status_code_name(getattr(status, "code", status)).lower()
        status_name = renderdoc_api._status_text(status).lower()
        # Native enum names drive repair; text is diagnostic and only preserves
        # terminal handling for status objects without an exposed enum.
        busy = "busy" in native_code
        mismatch = "incompatible" in native_code or "versionmismatch" in native_code
        terminal = busy or mismatch or "busy" in status_name or "incompatible" in status_name or "versionmismatch" in status_name
        if terminal or time.perf_counter() >= deadline:
            details = build_renderdoc_error_details(
                status if last_status is None else last_status,
                operation=f"CheckRemoteServerConnection({url})",
                source_layer="renderdoc_status",
                backend_type="remote",
                capture_context={"endpoint": url},
                classification="remote_endpoint",
                fix_hint="Verify the remote endpoint is reachable before opening a remote replay session.",
            )
            code = "remote_busy" if busy else "remote_version_mismatch" if mismatch else "remote_connect_timeout"
            details["remote"] = {"stage": "verifying", "code": code}
            raise CoreError(code, f"CheckRemoteServerConnection({url}) failed: {details['renderdoc_status']['status_text']}", "runtime", details)
        time.sleep(min(0.25, max(deadline - time.perf_counter(), 0.05)))


def _create_remote_server_connection(url: str) -> Any:
    rd = renderdoc_api._get_rd()
    status, remote = rd.CreateRemoteServerConnection(url)
    if not renderdoc_api._status_ok(status) or remote is None:
        details = build_renderdoc_error_details(
            status,
            operation=f"CreateRemoteServerConnection({url})",
            source_layer="renderdoc_status",
            backend_type="remote",
            capture_context={"endpoint": url},
            classification="remote_endpoint",
            fix_hint="Reconnect to the remote endpoint and confirm it still exposes a RenderDoc server.",
        )
        raise RuntimeToolError(
            f"CreateRemoteServerConnection({url}) failed: {details['renderdoc_status']['status_text']}",
            details=details,
        )
    return remote


def _collect_remote_server_info(
    remote_server: Any,
    *,
    host: str,
    port: int,
    transport: str,
    bootstrap: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    info: Dict[str, Any] = {
        "version": renderdoc_api._renderdoc_version_value(),
        "name": str(host),
        "platform": "android" if transport == "adb_android" else "unknown",
        "transport": str(transport),
        "endpoint": remote_records._remote_url(host, port),
    }
    try:
        info["driver_name"] = str(remote_server.DriverName() or "")
    except Exception:
        info["driver_name"] = ""
    try:
        replays = remote_server.RemoteSupportedReplays()
        info["capabilities"] = {
            "supported_replays": [str(item) for item in list(replays or [])],
        }
    except Exception:
        info.setdefault("capabilities", {})
    if bootstrap:
        info["bootstrap"] = dict(bootstrap)
        if transport == "adb_android":
            info["platform"] = "android"
    return info


async def _connect_remote_endpoint(host: str, port: int, transport: str, options: Dict[str, Any], timeout_ms: int) -> tuple[Any, Any, Dict[str, Any]]:
    """Join cancellation before publishing a connection; roll back only acquired resources."""
    budget = ConnectionBudget(timeout_ms)
    def connect() -> tuple[Any, Any, Dict[str, Any]]:
        token = _connection_budget.set(budget)
        bootstrap = None
        remote = None
        try:
            endpoint_host, endpoint_port = host, port
            if transport == "adb_android":
                oplog._progress("bootstrap_start", "Preparing Android remote connection", progress_pct=0.05)
                android_options = AndroidBootstrapOptions(
                    device_serial=str(options.get("device_serial") or ""),
                    local_port=coerce._as_int(options.get("local_port"), 0),
                    expected_version=renderdoc_api._renderdoc_version_value(),
                    progress=lambda stage: oplog._progress(stage, f"Android service: {stage}"),
                    push_config=coerce._as_bool(options.get("push_config"), True))
                bootstrap = remote_bootstrap.bootstrap_android_remote(remote_port=port, options=android_options)
                endpoint_host, endpoint_port = bootstrap.host, bootstrap.port
            detail = remote_bootstrap.describe_android_remote(bootstrap) if bootstrap else {}
            url = remote_records._remote_url(endpoint_host, endpoint_port)
            oplog._progress("verifying", "Checking remote service compatibility")
            try:
                _wait_for_remote_endpoint(url, max(1, int(budget.remaining() * 1000)))
            except CoreError as error:
                if bootstrap is None or error.code != "remote_version_mismatch":
                    raise
                remote_bootstrap.repair_incompatible_android_helper(bootstrap, android_options)
                bootstrap = remote_bootstrap._prepare_android_service(bootstrap, android_options, False, f"{bootstrap.package_name}/.Loader")
                detail = remote_bootstrap.describe_android_remote(bootstrap)
                url = remote_records._remote_url(bootstrap.host, bootstrap.port)
                oplog._progress("verifying", "Verifying repaired Android remote service")
                _wait_for_remote_endpoint(url, max(1, int(budget.remaining() * 1000)))
            remote = _create_remote_server_connection(url)
            budget.remaining()
            ping = remote.Ping()
            if not renderdoc_api._status_ok(ping):
                renderdoc_api._check_status(ping, "RemoteServer.Ping", backend_type="remote", capture_context={"endpoint": url})
            info = _collect_remote_server_info(remote, host=endpoint_host, port=endpoint_port, transport=transport, bootstrap=detail)
            budget.remaining()
            return bootstrap, remote, info
        except BaseException as exc:
            # Cleanup is separately bounded; the expired/cancelled connection budget must not suppress it.
            _connection_budget.reset(token)
            token = _connection_budget.set(None)
            errors = []
            if remote is not None:
                try:
                    remote.ShutdownConnection()
                except Exception as cleanup_error:
                    errors.append(str(cleanup_error))
            if bootstrap is not None:
                errors.extend(remote_bootstrap.cleanup_android_remote(bootstrap))
            if errors:
                if isinstance(exc, AndroidRemoteBootstrapError):
                    exc.details.setdefault("cleanup_errors", []).extend(errors)
                elif isinstance(exc, CoreError):
                    exc.details.setdefault("cleanup_errors", []).extend(errors)
                else:
                    raise RuntimeToolError(str(exc), details={"cleanup_errors": errors}) from exc
            raise
        finally:
            _connection_budget.reset(token)
    ctx = contextvars.copy_context()
    future = asyncio.get_running_loop().run_in_executor(None, ctx.run, connect)
    try:
        return await asyncio.shield(future)
    except asyncio.CancelledError:
        budget.cancelled.set()
        receipt: Dict[str, Any] = {"remote": {"stage": "cancelled", "code": "remote_connect_cancelled",
            "device_serial": str(options.get("device_serial") or "")}}
        try:
            bootstrap, remote, _ = await asyncio.shield(future)
        except Exception as error:
            # The joined worker has released its resources. PackageManager may
            # already have committed; retain its facts rather than imply rollback.
            if isinstance(error, (AndroidRemoteBootstrapError, CoreError)):
                receipt.update(error.details)
        else:
            # Cancellation can race with a completed worker, before handle publication.
            try:
                await renderdoc_api._offload(remote.ShutdownConnection)
            finally:
                if bootstrap is not None:
                    cleanup_errors = await renderdoc_api._offload(remote_bootstrap.cleanup_android_remote, bootstrap)
                    receipt["installation"] = {"installed_apk": bootstrap.installed_apk,
                        "uninstalled_existing": bootstrap.uninstalled_existing, "install_mode": bootstrap.install_mode}
                    if cleanup_errors:
                        receipt["cleanup_errors"] = cleanup_errors
        oplog._progress("cancelled", "Remote connection cancelled after native actions settled", details=receipt)
        raise


def _disconnect_remote_handle_sync(handle: live_state.RemoteHandle) -> List[str]:
    errors: List[str] = []
    for lease in list(handle.target_control_leases):
        errors.extend(_close_target_control_sync(handle, lease))
    if errors:
        return errors
    if handle.remote_server is not None:
        try:
            handle.remote_server.ShutdownConnection()
            handle.remote_server = None
            handle.connected = False
        except Exception as exc:
            errors.append(f"remote shutdown failed: {exc}")
    if handle.transport == "adb_android" and handle.bootstrap_result is not None:
        errors.extend(remote_bootstrap.cleanup_android_remote(handle.bootstrap_result))
    return errors


_CAPTURE_OPTION_ATTRS: Dict[str, str] = {
    "allow_vsync": "allowVSync",
    "allow_fullscreen": "allowFullscreen",
    "api_validation": "apiValidation",
    "capture_all_cmd_lists": "captureAllCmdLists",
    "capture_callstacks": "captureCallstacks",
    "capture_callstacks_only_actions": "captureCallstacksOnlyActions",
    "debug_output_mute": "debugOutputMute",
    "delay_for_debugger": "delayForDebugger",
    "hook_into_children": "hookIntoChildren",
    "ref_all_resources": "refAllResources",
    "soft_memory_limit": "softMemoryLimit",
    "verify_buffer_access": "verifyBufferAccess",
}


def _remote_target_message_type_name(value: Any) -> str:
    rd = renderdoc_api._get_rd()
    raw_value = int(value or 0)
    for name in dir(rd.TargetControlMessageType):
        if name.startswith("_"):
            continue
        try:
            if int(getattr(rd.TargetControlMessageType, name)) == raw_value:
                return name
        except Exception:
            continue
    return str(raw_value)


def _capture_options_from_dict(values: Dict[str, Any]) -> Tuple[Any, Dict[str, Any]]:
    rd = renderdoc_api._get_rd()
    options = rd.CaptureOptions()
    applied: Dict[str, Any] = {}
    for raw_key, raw_value in dict(values or {}).items():
        key = str(raw_key or "").strip()
        attr = _CAPTURE_OPTION_ATTRS.get(key, key)
        if not attr or not hasattr(options, attr):
            continue
        current_value = getattr(options, attr)
        if isinstance(current_value, bool):
            coerced = coerce._as_bool(raw_value, current_value)
        elif isinstance(current_value, int):
            coerced = coerce._as_int(raw_value, int(current_value))
        else:
            coerced = raw_value
        setattr(options, attr, coerced)
        applied[key] = coerced
    return options, applied


def _environment_modifications_from_dict(values: Dict[str, Any]) -> List[Any]:
    rd = renderdoc_api._get_rd()
    modifications: List[Any] = []
    for name, value in dict(values or {}).items():
        item = rd.EnvironmentModification()
        item.name = str(name or "")
        item.value = str(value or "")
        if hasattr(item, "sep"):
            item.sep = ";"
        if hasattr(item, "mod"):
            try:
                item.mod = 0
            except Exception:
                pass
        modifications.append(item)
    return modifications


def _remote_target_control_client_name(handle: live_state.RemoteHandle) -> str:
    remote_id = str(handle.remote_id or "remote").strip() or "remote"
    return f"rdc-tool-{remote_id}"[:64]


def _remote_target_ident(target_id: Any) -> int:
    text = str(target_id or "").strip()
    try:
        return int(text)
    except Exception:
        return 0


def _close_target_control_sync(handle: live_state.RemoteHandle, lease: Dict[str, Any]) -> List[str]:
    control = lease.get("control")
    if control is not None:
        try:
            control.Shutdown()
        except Exception as exc:
            return [f"target control shutdown failed: {exc}"]
        lease["control"] = None
    bridge = lease.get("bridge")
    if bridge is not None:
        errors = remote_bootstrap.cleanup_android_remote(bridge)
        if errors:
            return errors
    handle.target_control_leases[:] = [item for item in handle.target_control_leases if item is not lease]
    return []


@contextmanager
def _target_control_scope_sync(handle: live_state.RemoteHandle, ident: int):
    if handle.target_control_leases:
        raise RuntimeToolError("Unreleased target control resources require remote disconnect cleanup")
    lease: Dict[str, Any] = {"control": None, "bridge": None}
    handle.target_control_leases.append(lease)
    try:
        host, native_ident = _target_control_host(handle.host), int(ident)
        if handle.transport == "adb_android":
            serial = str(handle.device_serial or getattr(handle.bootstrap_result, "device_serial", "") or "").strip()
            if not serial:
                raise RuntimeToolError("Android target control requires the connected device serial")
            bridge = remote_bootstrap.forward_android_target(remote_bootstrap.resolve_adb_path(), serial, int(ident))
            lease["bridge"] = bridge
            host, native_ident = bridge.host, bridge.port
        # Target-control APIs take a hostname and a separate ident/port. Unlike
        # the replay-server API, host:port is not a supported endpoint here.
        control = renderdoc_api._get_rd().CreateTargetControl(
            host, native_ident, _remote_target_control_client_name(handle), False,
        )
        lease["control"] = control
        if control is None:
            raise RuntimeToolError("Native target control connection returned no handle")
        yield control
    finally:
        errors = _close_target_control_sync(handle, lease)
        if errors:
            raise RuntimeToolError("Target control cleanup failed", details={"cleanup_errors": errors})


def _target_control_host(host: str) -> str:
    host = str(host or "").strip()
    if not host or ":" in host or "/" in host:
        raise RuntimeToolError("Native target discovery requires a supported hostname without a port or protocol")
    return host


def _require_available_target_control(control: Any) -> None:
    busy_client = str(control.GetBusyClient() or "")
    if busy_client:
        raise RuntimeToolError("Remote target is busy", details={"busy_client": busy_client})
    if not control.Connected():
        raise RuntimeToolError("Remote target control is disconnected")


async def _offload_target_operation(fn: Any, *args: Any, **kwargs: Any) -> Any:
    future = asyncio.create_task(renderdoc_api._offload(fn, *args, **kwargs))
    try:
        return await asyncio.shield(future)
    except asyncio.CancelledError:
        # The worker owns the control and any temporary forward until the
        # complete synchronous operation, including Shutdown, has settled.
        try:
            await asyncio.shield(future)
        finally:
            raise


def _copy_remote_capture_sync(handle: live_state.RemoteHandle, ident: int, capture_id: int, local_path: Path) -> None:
    with _target_control_scope_sync(handle, ident) as control:
        _require_available_target_control(control)
        control.CopyCapture(capture_id, str(local_path))
        deadline = time.perf_counter() + 30.0
        while time.perf_counter() < deadline:
            events = _drain_target_control_messages_sync(
                handle, control, target_id=str(ident), max_messages=6, deadline_s=0.2,
            )
            if any(event.get("type") == "CaptureCopied"
                   and str((event.get("capture") or {}).get("capture_id")) == str(capture_id)
                   for event in events) and local_path.is_file():
                return
            time.sleep(0.1)
        raise RuntimeToolError("Remote capture copy did not confirm completion before timeout")


def _delete_remote_capture_sync(handle: live_state.RemoteHandle, ident: int, capture_id: int) -> None:
    with _target_control_scope_sync(handle, ident) as control:
        _require_available_target_control(control)
        control.DeleteCapture(capture_id)


def _target_summary_from_control(handle: live_state.RemoteHandle, ident: int, control: Any) -> Dict[str, Any]:
    target_id = str(int(ident))
    target = dict(handle.known_targets.get(target_id) or {})
    target.update(
        {
            "target_id": target_id,
            "ident": int(ident),
            "name": str(control.GetTarget() or ""),
            "api": str(control.GetAPI() or ""),
            "pid": int(control.GetPID() or 0),
            "connected": bool(control.Connected()) if hasattr(control, "Connected") else True,
        }
    )
    target.pop("busy_client", None)
    busy_client = str(control.GetBusyClient() or "") if hasattr(control, "GetBusyClient") else ""
    if busy_client:
        target["busy_client"] = busy_client
    handle.known_targets[target_id] = target
    return target


def _update_remote_capture_registry_from_message(
    handle: live_state.RemoteHandle,
    *,
    target_id: str,
    message_type: str,
    message: Any,
) -> Optional[Dict[str, Any]]:
    capture = getattr(message, "newCapture", None)
    capture_id = getattr(capture, "captureId", None)
    if not isinstance(capture_id, int) or isinstance(capture_id, bool) or capture_id < 0:
        return None
    capture_key = str(capture_id)
    record = dict(handle.known_captures.get(capture_key) or {})
    record.update(
        {
            "capture_id": capture_key,
            "target_id": str(target_id or ""),
            "path": str(getattr(capture, "path", "") or ""),
            "title": str(getattr(capture, "title", "") or ""),
            "api": str(getattr(capture, "api", "") or ""),
            "frame_number": int(getattr(capture, "frameNumber", 0) or 0),
            "size_bytes": int(getattr(capture, "byteSize", 0) or 0),
            "timestamp": int(getattr(capture, "timestamp", 0) or 0),
            "local": bool(getattr(capture, "local", False)),
            "thumb_width": int(getattr(capture, "thumbWidth", 0) or 0),
            "thumb_height": int(getattr(capture, "thumbHeight", 0) or 0),
            "message_type": message_type,
            "updated_at_ms": settings._now_ms(),
        }
    )
    handle.known_captures[capture_key] = record
    return record


def _drain_target_control_messages_sync(
    handle: live_state.RemoteHandle,
    control: Any,
    *,
    target_id: str,
    max_messages: int = 16,
    deadline_s: float = 0.0,
) -> List[Dict[str, Any]]:
    events: List[Dict[str, Any]] = []
    deadline = time.perf_counter() + max(float(deadline_s or 0.0), 0.0)
    remaining_messages = max(1, int(max_messages or 1))
    while remaining_messages > 0:
        message = control.ReceiveMessage(None)
        message_type = _remote_target_message_type_name(getattr(message, "type", 0))
        event: Dict[str, Any] = {"type": message_type}
        if message_type == "Noop":
            if deadline_s > 0.0 and time.perf_counter() < deadline:
                time.sleep(0.1)
                remaining_messages -= 1
                continue
            break
        if message_type == "Disconnected":
            events.append(event)
            break
        if message_type in {"NewCapture", "CaptureCopied"}:
            capture_record = _update_remote_capture_registry_from_message(
                handle,
                target_id=target_id,
                message_type=message_type,
                message=message,
            )
            if capture_record is not None:
                event["capture"] = capture_record
        elif message_type == "NewChild":
            child = getattr(message, "newChild", None)
            child_ident = int(getattr(child, "ident", 0) or 0)
            if child_ident > 0:
                child_target_id = str(child_ident)
                handle.known_targets.setdefault(
                    child_target_id,
                    {
                        "target_id": child_target_id,
                        "ident": child_ident,
                        "pid": int(getattr(child, "processId", 0) or 0),
                    },
                )
                event["target"] = dict(handle.known_targets[child_target_id])
        elif message_type == "RegisterAPI":
            api_use = getattr(message, "apiUse", None)
            target = dict(handle.known_targets.get(str(target_id or "")) or {})
            target["api"] = str(getattr(api_use, "name", "") or target.get("api") or "")
            target["supported"] = bool(getattr(api_use, "supported", True))
            support_message = str(getattr(api_use, "supportMessage", "") or "")
            if support_message:
                target["support_message"] = support_message
            target["presenting"] = bool(getattr(api_use, "presenting", False))
            handle.known_targets[str(target_id or "")] = target
            event["target"] = target
        elif message_type == "Busy":
            busy = getattr(message, "busy", None)
            target = dict(handle.known_targets.get(str(target_id or "")) or {})
            target["busy_client"] = str(getattr(busy, "clientName", "") or "")
            handle.known_targets[str(target_id or "")] = target
            event["target"] = target
        elif message_type == "CapturableWindowCount":
            target = dict(handle.known_targets.get(str(target_id or "")) or {})
            target["capturable_window_count"] = int(getattr(message, "capturableWindowCount", 0) or 0)
            handle.known_targets[str(target_id or "")] = target
            event["target"] = target
        elif message_type == "CaptureProgress":
            event["progress"] = float(getattr(message, "capProgress", 0.0) or 0.0)
        events.append(event)
        remaining_messages -= 1
    return events


def _remote_list_targets_sync(handle: live_state.RemoteHandle) -> List[Dict[str, Any]]:
    if handle.transport == "adb_android":
        serial = str(handle.device_serial or getattr(handle.bootstrap_result, "device_serial", "") or "").strip()
        if not serial:
            raise RuntimeToolError("Android target discovery requires the connected device serial")
        idents = remote_bootstrap.list_android_target_idents(remote_bootstrap.resolve_adb_path(), serial)
    else:
        host = _target_control_host(handle.host)
        idents = []
        next_ident = 0
        for _ in range(64):
            ident = int(renderdoc_api._get_rd().EnumerateRemoteTargets(host, next_ident) or 0)
            if ident == 0:
                break
            if ident < 0 or ident in idents:
                raise RuntimeToolError("Native target enumeration returned an invalid or repeated ident")
            idents.append(ident)
            next_ident = ident
        else:
            raise RuntimeToolError("Native target enumeration exceeded the scan limit")
    discovered: List[Dict[str, Any]] = []
    for ident in idents:
        target_id = str(ident)
        try:
            with _target_control_scope_sync(handle, ident) as control:
                summary = _target_summary_from_control(handle, ident, control)
                if not summary.get("busy_client") and summary.get("connected"):
                    _drain_target_control_messages_sync(handle, control, target_id=target_id, max_messages=4, deadline_s=0.0)
                discovered.append(dict(handle.known_targets.get(target_id) or summary))
        except Exception as exc:
            if handle.target_control_leases:
                raise
            errored = {"target_id": target_id, "ident": ident, "connected": False, "error": str(exc)}
            handle.known_targets[target_id] = errored
            discovered.append(errored)
    handle.known_targets = {str(item["target_id"]): item for item in discovered}
    handle.last_target_scan_ms = settings._now_ms()
    return sorted(discovered, key=lambda item: int(item.get("ident") or 0))


def _resolve_remote_target_ident_sync(handle: live_state.RemoteHandle, target_id: str = "") -> Tuple[int, Dict[str, Any]]:
    requested_ident = _remote_target_ident(target_id)
    if requested_ident > 0:
        summary = dict(handle.known_targets.get(str(requested_ident)) or {})
        if not summary:
            _remote_list_targets_sync(handle)
            summary = dict(handle.known_targets.get(str(requested_ident)) or {})
        if not summary:
            raise RuntimeToolError(
                f"Unknown target_id: {target_id}",
                details={"remote_id": handle.remote_id, "target_id": target_id},
            )
        return requested_ident, summary

    targets = _remote_list_targets_sync(handle)
    if len(targets) == 1:
        summary = dict(targets[0])
        return int(summary.get("ident") or 0), summary
    if not targets:
        raise RuntimeToolError(
            "No remote targets are currently available",
            details={"remote_id": handle.remote_id, "endpoint": remote_records._remote_url(handle.host, handle.port)},
        )
    raise RuntimeToolError(
        "target_id is required when multiple remote targets are available",
        details={
            "remote_id": handle.remote_id,
            "available_target_ids": [str(item.get("target_id") or "") for item in targets],
        },
    )


def _capture_records_for_target(handle: live_state.RemoteHandle, target_id: str = "") -> List[Dict[str, Any]]:
    records = [dict(item) for item in handle.known_captures.values()]
    if target_id:
        records = [item for item in records if str(item.get("target_id") or "") == str(target_id or "")]
    return sorted(
        records,
        key=lambda item: (int(item.get("timestamp") or 0), int(item.get("capture_id") or 0)),
        reverse=True,
    )


def _poll_captures_for_target_sync(
    handle: live_state.RemoteHandle,
    *,
    target_id: str,
    deadline_s: float = 3.0,
    max_messages: int = 24,
) -> List[Dict[str, Any]]:
    ident = _remote_target_ident(target_id)
    if ident <= 0:
        return []
    with _target_control_scope_sync(handle, ident) as control:
        _require_available_target_control(control)
        _drain_target_control_messages_sync(
            handle, control, target_id=str(target_id or ""),
            max_messages=max_messages, deadline_s=deadline_s,
        )
    return _capture_records_for_target(handle, target_id=str(target_id or ""))


def _launch_remote_app_sync(
    handle: live_state.RemoteHandle,
    *,
    exe_path: str,
    working_dir: str,
    cmdline: str,
    env: Dict[str, Any],
    capture_options: Dict[str, Any],
) -> Dict[str, Any]:
    merged_capture_options = {**dict(handle.default_capture_options or {}), **dict(capture_options or {})}
    capture_options_obj, applied_capture_options = _capture_options_from_dict(merged_capture_options)
    env_modifications = _environment_modifications_from_dict(env)
    execute_result = handle.remote_server.ExecuteAndInject(
        str(exe_path or ""),
        str(working_dir or ""),
        str(cmdline or ""),
        env_modifications,
        capture_options_obj,
    )
    status = getattr(execute_result, "result", None)
    status_ok = False
    if status is not None:
        ok_method = getattr(status, "OK", None)
        if callable(ok_method):
            try:
                status_ok = bool(ok_method())
            except Exception:
                status_ok = renderdoc_api._status_ok(status)
        else:
            status_ok = renderdoc_api._status_ok(status)
    if status is not None and not status_ok:
        raise RuntimeToolError(
            f"ExecuteAndInject({exe_path}) failed: {renderdoc_api._status_text(status)}",
            details=build_renderdoc_error_details(
                status,
                operation=f"ExecuteAndInject({exe_path})",
                source_layer="renderdoc_status",
                backend_type="remote",
                capture_context={"remote_id": handle.remote_id, "endpoint": remote_records._remote_url(handle.host, handle.port)},
                classification="remote_endpoint",
                fix_hint="Verify the remote endpoint can launch and inject the target application.",
            ),
        )
    ident = int(getattr(execute_result, "ident", 0) or 0)
    if ident <= 0:
        raise RuntimeToolError(
            (
                f"ExecuteAndInject({exe_path}) did not return a target ident"
                + (f": {renderdoc_api._status_text(status)}" if status is not None else "")
            ),
            details={
                "remote_id": handle.remote_id,
                "endpoint": remote_records._remote_url(handle.host, handle.port),
                "renderdoc_status": {
                    "status_text": renderdoc_api._status_text(status) if status is not None else "",
                    "status_ok": status_ok,
                },
            },
        )
    with _target_control_scope_sync(handle, ident) as control:
        target = _target_summary_from_control(handle, ident, control)
        _require_available_target_control(control)
        _drain_target_control_messages_sync(handle, control, target_id=str(ident), max_messages=8, deadline_s=0.5)
        target = dict(handle.known_targets.get(str(ident)) or target)
    target["capture_options"] = applied_capture_options
    return target


def _trigger_remote_capture_sync(
    handle: live_state.RemoteHandle,
    *,
    target_id: str,
    num_frames: int,
    capture_delay_ms: int = 0,
    queued: bool = False,
) -> Dict[str, Any]:
    ident, target = _resolve_remote_target_ident_sync(handle, target_id)
    with _target_control_scope_sync(handle, ident) as control:
        _require_available_target_control(control)
        if capture_delay_ms > 0:
            time.sleep(max(0.0, float(capture_delay_ms) / 1000.0))
        if queued:
            control.QueueCapture(0, max(1, int(num_frames or 1)))
        else:
            control.TriggerCapture(max(1, int(num_frames or 1)))
        _drain_target_control_messages_sync(
            handle, control, target_id=str(ident),
            deadline_s=5.0 if not queued else 2.0, max_messages=32,
        )
        captures = _capture_records_for_target(handle, target_id=str(ident))
    return {
        "target": dict(handle.known_targets.get(str(ident)) or target),
        "captures": captures,
        "queue_status": {
            "queued": bool(queued),
            "target_id": str(ident),
            "num_frames": max(1, int(num_frames or 1)),
        },
    }
