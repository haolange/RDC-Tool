"""Remote handle leases, snapshots and recovery metadata for remote sessions."""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from rdc_tool import context_snapshot, remote_bootstrap
from rdc_tool.context_snapshot import default_context_snapshot, normalize_context_id
from rdc_tool.core.errors import CoreError, RuntimeToolError
from rdc_tool.remote_bootstrap import AndroidBootstrapResult
from rdc_tool.runtime import (
    coerce,
    context_records,
    envelope,
    live_state,
    remote_records,
    remote_target,
    renderdoc_api,
    settings,
)
from rdc_tool.timeout_policy import remote_connect_timeout_ms


def _assert_remote_handle_context(
    handle: live_state.RemoteHandle,
    *,
    context_id: Optional[str] = None,
) -> None:
    scope = remote_records._remote_context_scope(
        str(handle.remote_id or ""),
        origin_context_id=str(handle.origin_context_id or ""),
        context_id=context_id,
    )
    if scope["origin_context_id"] != scope["current_context_id"]:
        raise CoreError(
            code="remote_handle_context_mismatch",
            message=(
                f"Remote handle {scope['remote_id']} belongs to context "
                f"{scope['origin_context_id']} and cannot be reused from context "
                f"{scope['current_context_id']}"
            ),
            category="runtime",
            details=scope,
        )


def _set_context_remote_live(remote_id: str, endpoint: str, *, context_id: Optional[str] = None) -> Dict[str, Any]:
    ctx = normalize_context_id(context_id or live_state._runtime_context_id())
    state = context_records._context_state(ctx)
    state["backend"] = "remote"
    context_records._store_context_state(state, ctx)
    snapshot = context_records._context_snapshot(ctx)
    handle = live_state._runtime.remotes.get(str(remote_id or "").strip())
    if handle is not None:
        payload = remote_records._remote_snapshot_payload_from_handle(handle)
        payload["endpoint"] = str(endpoint or payload.get("endpoint") or "")
        snapshot["remote"] = payload
    else:
        scope = remote_records._remote_context_scope(str(remote_id or ""), context_id=ctx)
        snapshot["remote"] = {
            "state": "live_handle",
            "remote_id": str(remote_id or ""),
            "origin_remote_id": str(remote_id or ""),
            "endpoint": str(endpoint or ""),
            "consumed_by_session_id": "",
            "active_session_ids": [],
            "origin_context_id": scope["origin_context_id"],
            "context_locality": scope["context_locality"],
            "reuse_policy": scope["reuse_policy"],
            "transport": "renderdoc",
            "requested": {},
            "options": {},
            "bootstrap": {},
            "device_serial": "",
        }
    return context_records._store_context_snapshot(snapshot, ctx)


def _set_context_remote_session_owned(
    remote_id: str,
    session_id: str,
    endpoint: str,
    *,
    context_id: Optional[str] = None,
) -> Dict[str, Any]:
    ctx = normalize_context_id(context_id or live_state._runtime_context_id())
    state = context_records._context_state(ctx)
    state["backend"] = "remote"
    context_records._store_context_state(state, ctx)
    snapshot = context_records._context_snapshot(ctx)
    snapshot["remote"] = {
        "state": "session_owned",
        "remote_id": "",
        "origin_remote_id": str(remote_id or ""),
        "endpoint": str(endpoint or ""),
        "consumed_by_session_id": str(session_id or ""),
        "active_session_ids": [str(session_id or "")] if str(session_id or "").strip() else [],
        **remote_records._remote_context_scope(str(remote_id or ""), context_id=ctx),
    }
    return context_records._store_context_snapshot(snapshot, ctx)


def _register_remote_session_lease(
    session_id: str,
    handle: live_state.RemoteHandle,
    *,
    context_id: Optional[str] = None,
) -> live_state.RemoteHandle:
    sid = str(session_id or "").strip()
    if not sid:
        return handle
    active_session_ids = remote_records._remote_active_session_ids(handle)
    if sid not in active_session_ids:
        active_session_ids.append(sid)
    handle.leased_session_ids = active_session_ids
    handle.leased_session_id = active_session_ids[0] if active_session_ids else ""
    live_state._runtime.session_owned_remotes[sid] = handle
    if handle.remote_id in live_state._runtime.remotes:
        _set_context_remote_live(handle.remote_id, remote_records._remote_url(handle.host, handle.port), context_id=context_id)
    else:
        _set_context_remote_session_owned(handle.remote_id, sid, remote_records._remote_url(handle.host, handle.port), context_id=context_id)
    return handle


def _release_remote_session_lease(session_id: str, *, context_id: Optional[str] = None) -> Optional[live_state.RemoteHandle]:
    sid = str(session_id or "").strip()
    handle = live_state._runtime.session_owned_remotes.pop(sid, None)
    if handle is None:
        return None
    active_session_ids = [item for item in remote_records._remote_active_session_ids(handle) if item != sid]
    handle.leased_session_ids = active_session_ids
    handle.leased_session_id = active_session_ids[0] if active_session_ids else ""
    if handle.remote_id in live_state._runtime.remotes:
        _set_context_remote_live(handle.remote_id, remote_records._remote_url(handle.host, handle.port), context_id=context_id)
    elif active_session_ids:
        _set_context_remote_session_owned(
            handle.remote_id,
            active_session_ids[0],
            remote_records._remote_url(handle.host, handle.port),
            context_id=context_id,
        )
    return handle


def _clear_context_remote_live(remote_id: str, *, context_id: Optional[str] = None) -> Dict[str, Any]:
    ctx = normalize_context_id(context_id or live_state._runtime_context_id())
    snapshot = context_records._context_snapshot(ctx)
    remote = snapshot.get("remote", {})
    if remote.get("state") == "live_handle" and remote.get("remote_id") == str(remote_id or ""):
        snapshot["remote"] = default_context_snapshot(context_id).get("remote", {})
        state = context_records._context_state(ctx)
        if str((snapshot.get("runtime") or {}).get("backend_type") or "none") != "remote":
            state["backend"] = "local"
            context_records._store_context_state(state, ctx)
        return context_records._store_context_snapshot(snapshot, ctx)
    return snapshot


def _remote_consumed_payload(remote_id: str) -> str | None:
    tombstone = live_state._runtime.consumed_remotes.get(str(remote_id or ""))
    if tombstone is None:
        return None
    scope = remote_records._remote_context_scope(
        str(tombstone.remote_id or remote_id or ""),
        origin_context_id=str(tombstone.origin_context_id or ""),
    )
    details = {
        "remote_id": tombstone.remote_id,
        "endpoint": tombstone.endpoint,
        "consumed_by_session_id": tombstone.consumed_by_session_id,
        "consumed_at_ms": tombstone.consumed_at_ms,
        "origin_context_id": scope["origin_context_id"],
        "context_locality": scope["context_locality"],
        "reuse_policy": scope["reuse_policy"],
        "source_layer": "runtime",
        "operation": "remote_handle_lifecycle",
        "backend_type": "remote",
        "capture_context": {
            "remote_id": tombstone.remote_id,
            "session_id": tombstone.consumed_by_session_id,
        },
        "classification": "tool_usage_conflict",
        "fix_hint": "Reconnect with rd.remote.connect to obtain a new live remote_id.",
    }
    return envelope.failure(
        f"Remote handle {tombstone.remote_id} has been consumed by session {tombstone.consumed_by_session_id}",
        code="remote_handle_consumed",
        category="runtime",
        details=details,
    )


async def _rehydrate_remote_handle_from_snapshot(remote_id: str) -> live_state.RemoteHandle | None:
    rid = str(remote_id or "").strip()
    if not rid:
        return None
    if rid in live_state._runtime.remotes:
        return live_state._runtime.remotes[rid]
    ctx = normalize_context_id(live_state._runtime_context_id())
    snapshot = context_snapshot.load_context_snapshot(ctx, retention=settings._snapshot_retention())
    remote_payload = dict(snapshot.get("remote") or {}) if isinstance(snapshot, dict) else {}
    remote_ids = {
        str(remote_payload.get("remote_id") or "").strip(),
        str(remote_payload.get("origin_remote_id") or "").strip(),
    }
    if rid not in remote_ids:
        return None
    endpoint = str(remote_payload.get("endpoint") or "").strip()
    host, port = _parse_remote_endpoint(endpoint)
    transport = str(remote_payload.get("transport") or "renderdoc").strip() or "renderdoc"
    bootstrap_detail = dict(remote_payload.get("bootstrap") or {}) if isinstance(remote_payload.get("bootstrap"), dict) else {}
    options = dict(remote_payload.get("options") or {}) if isinstance(remote_payload.get("options"), dict) else {}
    requested = dict(remote_payload.get("requested") or {}) if isinstance(remote_payload.get("requested"), dict) else {}
    requested_host = str(requested.get("host") or host or "127.0.0.1").strip() or "127.0.0.1"
    requested_port = coerce._as_int(
        requested.get("port"),
        coerce._as_int(options.get("remote_port"), coerce._as_int(bootstrap_detail.get("remote_port"), port or 38920)),
    )
    device_serial = str(
        remote_payload.get("device_serial")
        or options.get("device_serial")
        or bootstrap_detail.get("device_serial")
        or ""
    ).strip()
    if transport == "adb_android":
        requested_port = coerce._as_int(
            bootstrap_detail.get("remote_port"),
            coerce._as_int(options.get("remote_port"), requested_port),
        )
        options = {**options, "local_port": 0}
    prior_android = await renderdoc_api._offload(_retire_recovery_android_forward, remote_payload, ctx) if transport == "adb_android" else None
    try:
        bootstrap_result, remote_server, server_info = await remote_target._connect_remote_endpoint(
            "127.0.0.1" if transport == "adb_android" else host,
            requested_port if transport == "adb_android" else port,
            transport, {**options, "device_serial": device_serial}, remote_connect_timeout_ms({}))
        if bootstrap_result is not None:
            if prior_android is not None:
                await _retain_recovered_android_ownership(bootstrap_result, prior_android, remote_server)
            bootstrap_detail = remote_bootstrap.describe_android_remote(bootstrap_result)
            host, port = bootstrap_result.host, bootstrap_result.port
            requested_host, requested_port = "127.0.0.1", bootstrap_result.remote_port
    except Exception:
        return None
    url = remote_records._remote_url(host, port)
    scope = remote_records._remote_context_scope(rid, origin_context_id=str(remote_payload.get("origin_context_id") or ""), context_id=ctx)
    handle = live_state.RemoteHandle(
        remote_id=rid,
        host=host,
        port=port,
        connected=True,
        origin_context_id=scope["origin_context_id"],
        context_locality=scope["context_locality"],
        reuse_policy=scope["reuse_policy"],
        transport=transport,
        remote_server=remote_server,
        server_info=server_info,
        bootstrap=bootstrap_detail,
        bootstrap_result=bootstrap_result,
        requested_host=requested_host,
        requested_port=requested_port,
        device_serial=device_serial,
        detail={
            "connected": True,
            "transport": transport,
            "endpoint": url,
            "requires_remote_device": transport == "adb_android",
            "bootstrap": dict(bootstrap_detail) if bootstrap_detail else {},
            "rehydrated": True,
        },
    )
    live_state._runtime.remotes[rid] = handle
    _set_context_remote_live(rid, url, context_id=ctx)
    return handle


def _remote_handle_missing_payload(remote_id: str) -> envelope.Outcome:
    ctx = normalize_context_id(live_state._runtime_context_id())
    snapshot = context_snapshot.load_context_snapshot(ctx, retention=settings._snapshot_retention())
    remote_payload = dict(snapshot.get("remote") or {}) if isinstance(snapshot, dict) else {}
    endpoint = str(remote_payload.get("endpoint") or "").strip()
    details = {
        "remote_id": str(remote_id or "").strip(),
        "context_id": ctx,
        "endpoint": endpoint,
        "remote_state": str(remote_payload.get("state") or "none"),
        "origin_remote_id": str(remote_payload.get("origin_remote_id") or ""),
        "source_layer": "runtime",
        "operation": "remote_handle_lifecycle",
        "backend_type": "remote",
        "classification": "remote_endpoint",
        "fix_hint": "Reconnect with rd.remote.connect; the previous live remote handle expired before it could be rehydrated.",
    }
    code = "remote_handle_expired" if endpoint else "remote_not_found"
    message = (
        f"Remote handle {remote_id} expired and could not be rehydrated"
        if endpoint
        else f"Unknown remote_id: {remote_id}"
    )
    return envelope.failure(message, code=code, category="runtime", details=details)


def _parse_remote_endpoint(endpoint: str) -> Tuple[str, int]:
    text = str(endpoint or "").strip()
    if not text:
        return "", 0
    if ":" not in text:
        return text, 0
    host, raw_port = text.rsplit(":", 1)
    return host.strip(), coerce._as_int(raw_port, 0)


def _retire_recovery_android_forward(remote_record: Dict[str, Any], context_id: str) -> AndroidBootstrapResult | None:
    """Release the verified old forward before a recovered connection allocates a new one."""
    bootstrap = coerce._as_dict(remote_record.get("bootstrap"), default={})
    if bootstrap.get("created_forward") is not True:
        raise RuntimeToolError("Persisted Android forward ownership is missing")
    options = coerce._as_dict(remote_record.get("options"), default={})
    serial = str(remote_record.get("device_serial") or "").strip()
    port = coerce._as_int(bootstrap.get("port"), 0)
    remote_port = coerce._as_int(bootstrap.get("remote_port"), 0)
    pids = bootstrap.get("owned_pids")
    started = bool(bootstrap.get("started_activity"))
    if not (
        remote_record.get("transport") == "adb_android"
        and remote_record.get("origin_context_id") == context_id
        and serial
        and bootstrap.get("device_serial") == serial
        and (not options.get("device_serial") or options.get("device_serial") == serial)
        and port > 0
        and port == coerce._as_int(options.get("local_port"), 0)
        and remote_port > 0
        and remote_port == coerce._as_int(options.get("remote_port"), 0)
        and bootstrap.get("forward_spec") == f"tcp:{port}"
        and remote_record.get("endpoint") == f"127.0.0.1:{port}"
        and (not started or (
            bool(bootstrap.get("package_name"))
            and isinstance(pids, list)
            and bool(pids)
            and all(isinstance(pid, int) and not isinstance(pid, bool) and pid > 0 for pid in pids)
        ))
    ):
        raise RuntimeToolError("Persisted Android forward ownership is incomplete or inconsistent")
    prior = AndroidBootstrapResult(
        adb_path=remote_bootstrap.resolve_adb_path(),
        device_serial=serial,
        package_name=str(bootstrap.get("package_name") or ""),
        activity_name=str(bootstrap.get("activity_name") or ""),
        abi=str(bootstrap.get("abi") or ""),
        host="127.0.0.1",
        port=port,
        remote_port=remote_port,
        apk_path="",
        forward_spec=f"tcp:{port}",
        created_forward=True,
        started_activity=started,
        owned_pids=list(pids or []),
    )
    forward_only = AndroidBootstrapResult(
        adb_path=prior.adb_path,
        device_serial=serial,
        package_name=prior.package_name,
        activity_name=prior.activity_name,
        abi=prior.abi,
        host=prior.host,
        port=port,
        remote_port=remote_port,
        apk_path="",
        forward_spec=prior.forward_spec,
        created_forward=True,
    )
    errors = remote_bootstrap.cleanup_android_remote(forward_only)
    if errors:
        raise RuntimeToolError("Persisted Android forward cleanup failed", details={"cleanup_errors": errors})
    return prior


async def _retain_recovered_android_ownership(
    current: AndroidBootstrapResult, prior: AndroidBootstrapResult, remote_server: Any,
) -> None:
    try:
        await renderdoc_api._offload(remote_bootstrap.retain_android_helper_ownership, current, prior)
    except BaseException as exc:
        cleanup_errors = []
        try:
            await renderdoc_api._offload(remote_server.ShutdownConnection)
        except Exception as shutdown_error:
            cleanup_errors.append(f"remote shutdown failed: {shutdown_error}")
        try:
            cleanup_errors.extend(await renderdoc_api._offload(remote_bootstrap.cleanup_android_remote, current))
        except Exception as cleanup_error:
            cleanup_errors.append(str(cleanup_error))
        if cleanup_errors:
            raise RuntimeToolError(
                "Recovered Android connection cleanup failed",
                details={"cleanup_errors": cleanup_errors},
            ) from exc
        raise
