"""Remote session records: endpoints, lease scopes and snapshot payloads shared by context and remote code."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from rdc_tool.context_snapshot import normalize_context_id
from rdc_tool.runtime import coerce, live_state


def _remote_url(host: str, port: int) -> str:
    return f"{host}:{port}" if int(port or 0) > 0 else str(host)


def _remote_active_session_ids(handle: Optional[live_state.RemoteHandle]) -> List[str]:
    if handle is None:
        return []
    session_ids = [str(item or "").strip() for item in list(handle.leased_session_ids or [])]
    session_ids = [item for item in session_ids if item]
    leased_session_id = str(handle.leased_session_id or "").strip()
    if leased_session_id and leased_session_id not in session_ids:
        session_ids.append(leased_session_id)
    return session_ids


def _remote_context_scope(
    remote_id: str,
    *,
    origin_context_id: str = "",
    context_id: Optional[str] = None,
) -> Dict[str, str]:
    current_context_id = normalize_context_id(context_id or live_state._runtime_context_id())
    resolved_origin = normalize_context_id(origin_context_id or current_context_id)
    return {
        "remote_id": str(remote_id or "").strip(),
        "origin_context_id": resolved_origin,
        "current_context_id": current_context_id,
        "context_locality": "strict",
        "reuse_policy": "must_reconnect",
    }


def _remote_snapshot_payload_from_handle(handle: live_state.RemoteHandle) -> Dict[str, Any]:
    active_session_ids = _remote_active_session_ids(handle)
    scope = _remote_context_scope(
        str(handle.remote_id or ""),
        origin_context_id=str(handle.origin_context_id or ""),
    )
    bootstrap = dict(handle.bootstrap or {})
    requested = {
        "host": str(handle.requested_host or handle.host or "127.0.0.1"),
        "port": int(handle.requested_port or coerce._as_int(bootstrap.get("remote_port"), handle.port or 38920)),
    }
    options = {
        "device_serial": str(handle.device_serial or bootstrap.get("device_serial") or "").strip(),
        "local_port": coerce._as_int(bootstrap.get("port"), 0),
        "remote_port": coerce._as_int(bootstrap.get("remote_port"), requested["port"]),

        "push_config": True,
    }
    return {
        "state": "live_handle",
        "remote_id": str(handle.remote_id or ""),
        "origin_remote_id": str(handle.remote_id or ""),
        "endpoint": _remote_url(handle.host, handle.port),
        "consumed_by_session_id": active_session_ids[0] if active_session_ids else "",
        "active_session_ids": active_session_ids,
        "origin_context_id": scope["origin_context_id"],
        "context_locality": scope["context_locality"],
        "reuse_policy": scope["reuse_policy"],
        "transport": str(handle.transport or "renderdoc"),
        "requested": requested,
        "options": options,
        "bootstrap": bootstrap,
        "device_serial": options["device_serial"],
    }


def _remote_snapshot_payload_expired(remote_payload: Dict[str, Any], *, context_id: Optional[str] = None) -> Dict[str, Any]:
    remote_id = str(remote_payload.get("remote_id") or remote_payload.get("origin_remote_id") or "").strip()
    scope = _remote_context_scope(
        remote_id,
        origin_context_id=str(remote_payload.get("origin_context_id") or ""),
        context_id=context_id,
    )
    return {
        "state": "expired",
        "remote_id": "",
        "origin_remote_id": remote_id,
        "endpoint": str(remote_payload.get("endpoint") or "").strip(),
        "consumed_by_session_id": str(remote_payload.get("consumed_by_session_id") or "").strip(),
        "active_session_ids": [
            str(item).strip()
            for item in list(remote_payload.get("active_session_ids") or [])
            if str(item).strip()
        ],
        "origin_context_id": scope["origin_context_id"],
        "context_locality": scope["context_locality"],
        "reuse_policy": scope["reuse_policy"],
        "transport": str(remote_payload.get("transport") or "renderdoc").strip() or "renderdoc",
        "requested": dict(remote_payload.get("requested") or {}) if isinstance(remote_payload.get("requested"), dict) else {},
        "options": dict(remote_payload.get("options") or {}) if isinstance(remote_payload.get("options"), dict) else {},
        "bootstrap": dict(remote_payload.get("bootstrap") or {}) if isinstance(remote_payload.get("bootstrap"), dict) else {},
        "device_serial": str(remote_payload.get("device_serial") or "").strip(),
    }


def _remote_session_metadata(
    handle: live_state.RemoteHandle,
    *,
    remote_id: str,
    endpoint: str,
) -> Dict[str, Any]:
    requested_host = str(handle.requested_host or handle.host or "").strip()
    requested_port = int(handle.requested_port or handle.port or 0)
    bootstrap = dict(handle.bootstrap or {})
    origin_context_id = normalize_context_id(
        str(handle.origin_context_id or live_state._runtime_context_id()).strip() or live_state._runtime_context_id()
    )
    return {
        "transport": str(handle.transport or "renderdoc"),
        "host": str(handle.host or "").strip(),
        "port": int(handle.port or 0),
        "endpoint": str(endpoint or _remote_url(handle.host, handle.port)),
        "origin_remote_id": str(remote_id or handle.remote_id or "").strip(),
        "origin_context_id": origin_context_id,
        "context_locality": str(handle.context_locality or "strict").strip() or "strict",
        "reuse_policy": str(handle.reuse_policy or "must_reconnect").strip() or "must_reconnect",
        "ownership_state": "session_owned",
        "device_serial": str(
            handle.device_serial
            or bootstrap.get("device_serial")
            or ""
        ).strip(),
        "requested": {
            "host": requested_host,
            "port": requested_port,
        },
        "options": {

            "push_config": coerce._as_bool(bootstrap.get("pushed_config"), True),
            "device_serial": str(handle.device_serial or bootstrap.get("device_serial") or "").strip(),
            "local_port": int(handle.port or 0),
            "remote_port": coerce._as_int(bootstrap.get("remote_port"), requested_port),
        },
        "bootstrap": {
            "package_name": str(bootstrap.get("package_name") or "").strip(),
            "activity_name": str(bootstrap.get("activity_name") or "").strip(),
            "abi": str(bootstrap.get("abi") or "").strip(),
            "device_serial": str(bootstrap.get("device_serial") or "").strip(),
            "port": coerce._as_int(bootstrap.get("port"), int(handle.port or 0)),
            "remote_port": coerce._as_int(bootstrap.get("remote_port"), requested_port),
            "forward_spec": str(bootstrap.get("forward_spec") or "").strip(),
            "created_forward": bool(bootstrap.get("created_forward")),
            "started_activity": bool(bootstrap.get("started_activity")),
            "owned_pids": list(bootstrap.get("owned_pids") or []),
            "config_remote_path": str(bootstrap.get("config_remote_path") or "").strip(),
        },
    }


def _session_record_remote_metadata(session_record: Dict[str, Any]) -> Dict[str, Any]:
    remote = session_record.get("remote")
    return dict(remote or {}) if isinstance(remote, dict) else {}
