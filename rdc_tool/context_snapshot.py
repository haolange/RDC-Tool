"""Context-scoped snapshot helpers shared by runtime and daemon-facing tools."""

from __future__ import annotations

import json
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

import msvcrt

from rdc_tool.io_utils import atomic_write_json
from rdc_tool.runtime_paths import cli_runtime_dir

USER_CONTEXT_KEYS = {
    "focus_pixel",
    "focus_resource_id",
    "focus_shader_id",
    "notes",
}
RUNTIME_OWNED_KEYS = {
    "session_id",
    "capture_file_id",
    "frame_index",
    "active_event_id",
    "backend_type",
    "remote_id",
    "origin_remote_id",
    "last_artifacts",
    "preview",
}
_CONTEXT_MUTEXES: dict[str, threading.Lock] = {}
_CONTEXT_MUTEXES_LOCK = threading.Lock()


@dataclass(frozen=True)
class SnapshotRetentionPolicy:
    total_limit: int = 32
    per_type_limit: int = 8


def _now_ms() -> int:
    return int(time.time() * 1000)


def _normalize_rect(value: Any) -> Dict[str, int] | None:
    if not isinstance(value, dict):
        return None
    try:
        x = int(round(float(value.get("x", 0))))
        y = int(round(float(value.get("y", 0))))
        width = int(round(float(value.get("width", 0))))
        height = int(round(float(value.get("height", 0))))
    except (TypeError, ValueError):
        return None
    if width <= 0 or height <= 0:
        return None
    return {
        "x": x,
        "y": y,
        "width": width,
        "height": height,
    }


def _normalize_extent(value: Any) -> Dict[str, int]:
    if not isinstance(value, dict):
        return {"width": 0, "height": 0}
    try:
        width = max(0, int(round(float(value.get("width", 0)))))
        height = max(0, int(round(float(value.get("height", 0)))))
    except (TypeError, ValueError):
        return {"width": 0, "height": 0}
    return {
        "width": width,
        "height": height,
    }


def default_preview_display_state() -> Dict[str, Any]:
    return {
        "output_slot": None,
        "texture_id": "",
        "texture_format": "",
        "framebuffer_extent": {"width": 0, "height": 0},
        "viewport_rect": None,
        "scissor_rect": None,
        "effective_region_rect": None,
        "region_marker_mode": "none",
        "window_rect": {"width": 0, "height": 0},
        "fit_mode": "fit_with_screen_cap",
        "screen_cap_ratio": 0.5,
    }


def normalize_preview_display_state(value: Any) -> Dict[str, Any]:
    payload = default_preview_display_state()
    if not isinstance(value, dict):
        return payload
    output_slot = value.get("output_slot")
    if output_slot is None or output_slot == "":
        normalized_output_slot = None
    else:
        normalized_output_slot = _normalize_int(output_slot)
    try:
        screen_cap_ratio = float(value.get("screen_cap_ratio") or 0.5)
    except (TypeError, ValueError):
        screen_cap_ratio = 0.5
    payload.update(
        {
            "output_slot": normalized_output_slot,
            "texture_id": str(value.get("texture_id") or "").strip(),
            "texture_format": str(value.get("texture_format") or "").strip(),
            "framebuffer_extent": _normalize_extent(value.get("framebuffer_extent")),
            "viewport_rect": _normalize_rect(value.get("viewport_rect")),
            "scissor_rect": _normalize_rect(value.get("scissor_rect")),
            "effective_region_rect": _normalize_rect(value.get("effective_region_rect")),
            "region_marker_mode": str(value.get("region_marker_mode") or "none").strip() or "none",
            "window_rect": _normalize_extent(value.get("window_rect")),
            "fit_mode": str(value.get("fit_mode") or "fit_with_screen_cap").strip() or "fit_with_screen_cap",
            "screen_cap_ratio": screen_cap_ratio,
        }
    )
    return payload


def default_preview_state(*, backend: str = "local", enabled: bool = False) -> Dict[str, Any]:
    return {
        "enabled": bool(enabled),
        "state": "disabled" if not enabled else "starting",
        "view_mode": "active_event",
        "bound_session_id": "",
        "bound_capture_file_id": "",
        "bound_event_id": 0,
        "backend": str(backend or "local").strip() or "local",
        "recovered_from_session_id": "",
        "rebind_count": 0,
        "last_error": "",
        "display": default_preview_display_state(),
        "updated_at_ms": _now_ms(),
    }


def normalize_preview_state(value: Any, *, backend: str = "local") -> Dict[str, Any]:
    payload = default_preview_state(backend=backend)
    if not isinstance(value, dict):
        return payload
    enabled = bool(value.get("enabled", payload["enabled"]))
    state = str(value.get("state") or payload["state"]).strip() or payload["state"]
    if not enabled:
        state = "disabled"
    payload.update(
        {
            "enabled": enabled,
            "state": state,
            "view_mode": "active_event",
            "bound_session_id": str(value.get("bound_session_id") or "").strip(),
            "bound_capture_file_id": str(value.get("bound_capture_file_id") or "").strip(),
            "bound_event_id": _normalize_int(value.get("bound_event_id")),
            "backend": str(value.get("backend") or backend or "local").strip() or "local",
            "recovered_from_session_id": str(value.get("recovered_from_session_id") or "").strip(),
            "rebind_count": max(0, _normalize_int(value.get("rebind_count"))),
            "last_error": str(value.get("last_error") or "").strip(),
            "display": normalize_preview_display_state(value.get("display")),
            "updated_at_ms": _normalize_int(value.get("updated_at_ms"), _now_ms()),
        }
    )
    return payload


def _context_mutex(context: Optional[str]) -> threading.Lock:
    ctx = normalize_context_id(context)
    with _CONTEXT_MUTEXES_LOCK:
        lock = _CONTEXT_MUTEXES.get(ctx)
        if lock is None:
            lock = threading.Lock()
            _CONTEXT_MUTEXES[ctx] = lock
        return lock


def normalize_context_id(context: Optional[str]) -> str:
    text = str(context or "").strip()
    if not text or text.lower() == "default":
        return "default"
    return text


def _sanitize_context(context: Optional[str]) -> str:
    ctx = normalize_context_id(context)
    return "".join(ch if ch.isalnum() or ch in ("-", "_", ".") else "_" for ch in ctx)


def _coerce_retention_policy(retention: Any = None) -> SnapshotRetentionPolicy:
    if isinstance(retention, SnapshotRetentionPolicy):
        return retention
    if isinstance(retention, dict):
        total_limit = int(retention.get("total_limit") or SnapshotRetentionPolicy.total_limit)
        per_type_limit = int(retention.get("per_type_limit") or SnapshotRetentionPolicy.per_type_limit)
        return SnapshotRetentionPolicy(
            total_limit=max(total_limit, 1),
            per_type_limit=max(per_type_limit, 1),
        )
    total_limit = int(getattr(retention, "total_limit", SnapshotRetentionPolicy.total_limit) or SnapshotRetentionPolicy.total_limit)
    per_type_limit = int(getattr(retention, "per_type_limit", SnapshotRetentionPolicy.per_type_limit) or SnapshotRetentionPolicy.per_type_limit)
    return SnapshotRetentionPolicy(
        total_limit=max(total_limit, 1),
        per_type_limit=max(per_type_limit, 1),
    )


def context_snapshot_path(context: Optional[str] = "default") -> Path:
    state_dir = cli_runtime_dir()
    state_dir.mkdir(parents=True, exist_ok=True)
    ctx = normalize_context_id(context)
    if ctx == "default":
        return state_dir / "context_snapshot.json"
    return state_dir / f"context_snapshot_{_sanitize_context(ctx)}.json"


def _context_snapshot_lock_path(context: Optional[str] = "default") -> Path:
    return context_snapshot_path(context).with_suffix(".lock")


@contextmanager
def _locked_snapshot_file(context: Optional[str] = "default"):
    lock_path = _context_snapshot_lock_path(context)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with _context_mutex(context):
        with open(lock_path, "a+b") as handle:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)


def default_context_snapshot(context: Optional[str] = "default") -> Dict[str, Any]:
    ctx = normalize_context_id(context)
    return {
        "context_id": ctx,
        "backend": "local",
        "runtime": {
            "session_id": "",
            "capture_file_id": "",
            "frame_index": 0,
            "active_event_id": 0,
            "backend_type": "none",
        },
        "remote": {
            "state": "none",
            "remote_id": "",
            "origin_remote_id": "",
            "endpoint": "",
            "consumed_by_session_id": "",
            "active_session_ids": [],
            "origin_context_id": "",
            "context_locality": "strict",
            "reuse_policy": "must_reconnect",
            "transport": "",
            "requested": {},
            "options": {},
            "bootstrap": {},
            "device_serial": "",
        },
        "focus": {
            "pixel": None,
            "resource_id": "",
            "shader_id": "",
        },
        "notes": "",
        "last_artifacts": [],
        "preview": default_preview_state(),
        "updated_at_ms": _now_ms(),
    }


def _normalize_int(value: Any, default: int = 0) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return int(default)
    return parsed


def normalize_pixel(value: Any) -> Dict[str, Any] | None:
    if value is None or value == "":
        return None
    if isinstance(value, str):
        parts = [part.strip() for part in value.split(",")]
        if len(parts) >= 2:
            try:
                return {"x": int(parts[0]), "y": int(parts[1])}
            except ValueError:
                return None
        return None
    if isinstance(value, dict):
        if "x" not in value or "y" not in value:
            return None
        try:
            payload: Dict[str, Any] = {
                "x": int(value.get("x")),
                "y": int(value.get("y")),
            }
        except (TypeError, ValueError):
            return None
        for key in ("sample", "view", "primitive"):
            if key in value and value.get(key) is not None:
                payload[key] = _normalize_int(value.get(key))
        target = value.get("target")
        if isinstance(target, dict):
            payload["target"] = dict(target)
        return payload
    return None


def _normalize_artifact_entry(value: Any) -> Dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    path = str(value.get("path") or "").strip()
    if not path:
        return None
    return {
        "path": path,
        "type": str(value.get("type") or "file").strip() or "file",
        "source_tool": str(value.get("source_tool") or "").strip(),
        "ts_ms": _normalize_int(value.get("ts_ms"), _now_ms()),
    }


def _trim_artifacts(entries: Iterable[Dict[str, Any]], *, retention: SnapshotRetentionPolicy) -> list[Dict[str, Any]]:
    deduped: list[Dict[str, Any]] = []
    seen_paths: set[str] = set()
    for item in sorted(
        (
            entry
            for entry in entries
            if isinstance(entry, dict) and str(entry.get("path") or "").strip()
        ),
        key=lambda entry: int(entry.get("ts_ms") or 0),
        reverse=True,
    ):
        path = str(item.get("path") or "").strip()
        if path in seen_paths:
            continue
        deduped.append(item)
        seen_paths.add(path)

    kept: list[Dict[str, Any]] = []
    per_type_counts: dict[str, int] = {}
    for entry in deduped:
        artifact_type = str(entry.get("type") or "file").strip() or "file"
        count = per_type_counts.get(artifact_type, 0)
        if count >= retention.per_type_limit:
            continue
        per_type_counts[artifact_type] = count + 1
        kept.append(entry)
        if len(kept) >= retention.total_limit:
            break
    return kept


def normalize_context_snapshot(
    payload: Dict[str, Any] | None,
    context: Optional[str] = "default",
    *,
    retention: Any = None,
) -> Dict[str, Any]:
    retention_policy = _coerce_retention_policy(retention)
    snapshot = default_context_snapshot(context)
    if not isinstance(payload, dict):
        return snapshot

    snapshot["context_id"] = normalize_context_id(payload.get("context_id") or context)
    snapshot["backend"] = str(payload.get("backend") or "local").strip() or "local"

    runtime_payload = payload.get("runtime")
    if isinstance(runtime_payload, dict):
        snapshot["runtime"]["session_id"] = str(runtime_payload.get("session_id") or "").strip()
        snapshot["runtime"]["capture_file_id"] = str(runtime_payload.get("capture_file_id") or "").strip()
        snapshot["runtime"]["frame_index"] = _normalize_int(runtime_payload.get("frame_index"))
        snapshot["runtime"]["active_event_id"] = _normalize_int(runtime_payload.get("active_event_id"))
        snapshot["runtime"]["backend_type"] = str(runtime_payload.get("backend_type") or "none").strip() or "none"

    remote_payload = payload.get("remote")
    if isinstance(remote_payload, dict):
        snapshot["remote"]["state"] = str(remote_payload.get("state") or "none").strip() or "none"
        snapshot["remote"]["remote_id"] = str(remote_payload.get("remote_id") or "").strip()
        snapshot["remote"]["origin_remote_id"] = str(remote_payload.get("origin_remote_id") or "").strip()
        snapshot["remote"]["endpoint"] = str(remote_payload.get("endpoint") or "").strip()
        snapshot["remote"]["consumed_by_session_id"] = str(
            remote_payload.get("consumed_by_session_id") or ""
        ).strip()
        snapshot["remote"]["active_session_ids"] = [
            str(item).strip()
            for item in list(remote_payload.get("active_session_ids") or [])
            if str(item).strip()
        ]
        snapshot["remote"]["origin_context_id"] = str(
            remote_payload.get("origin_context_id") or ""
        ).strip()
        snapshot["remote"]["context_locality"] = str(
            remote_payload.get("context_locality") or "strict"
        ).strip() or "strict"
        snapshot["remote"]["reuse_policy"] = str(
            remote_payload.get("reuse_policy") or "must_reconnect"
        ).strip() or "must_reconnect"
        snapshot["remote"]["transport"] = str(
            remote_payload.get("transport") or ""
        ).strip()
        for key in ("requested", "options", "bootstrap"):
            value = remote_payload.get(key)
            snapshot["remote"][key] = dict(value) if isinstance(value, dict) else {}
        snapshot["remote"]["device_serial"] = str(
            remote_payload.get("device_serial") or ""
        ).strip()

    focus_payload = payload.get("focus")
    if isinstance(focus_payload, dict):
        snapshot["focus"]["pixel"] = normalize_pixel(focus_payload.get("pixel"))
        snapshot["focus"]["resource_id"] = str(focus_payload.get("resource_id") or "").strip()
        snapshot["focus"]["shader_id"] = str(focus_payload.get("shader_id") or "").strip()

    snapshot["notes"] = str(payload.get("notes") or "").strip()

    artifacts = payload.get("last_artifacts")
    if isinstance(artifacts, list):
        normalized = []
        for item in artifacts:
            entry = _normalize_artifact_entry(item)
            if entry is not None:
                normalized.append(entry)
        snapshot["last_artifacts"] = _trim_artifacts(normalized, retention=retention_policy)

    snapshot["preview"] = normalize_preview_state(
        payload.get("preview"),
        backend=str(snapshot.get("backend") or "local"),
    )
    snapshot["updated_at_ms"] = _normalize_int(payload.get("updated_at_ms"), _now_ms())
    return snapshot


def load_context_snapshot(
    context: Optional[str] = "default",
    *,
    retention: Any = None,
) -> Dict[str, Any]:
    path = context_snapshot_path(context)
    if not path.is_file():
        return default_context_snapshot(context)
    with _locked_snapshot_file(context):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return default_context_snapshot(context)
    return normalize_context_snapshot(payload, context, retention=retention)


def save_context_snapshot(
    payload: Dict[str, Any],
    context: Optional[str] = "default",
    *,
    retention: Any = None,
) -> Dict[str, Any]:
    snapshot = normalize_context_snapshot(payload, context, retention=retention)
    snapshot["updated_at_ms"] = _now_ms()
    path = context_snapshot_path(context)
    path.parent.mkdir(parents=True, exist_ok=True)
    with _locked_snapshot_file(context):
        atomic_write_json(path, snapshot)
    return snapshot


def clear_context_snapshot(context: Optional[str] = "default") -> None:
    with _locked_snapshot_file(context):
        try:
            context_snapshot_path(context).unlink(missing_ok=True)
        except Exception:
            pass


def update_user_context(
    snapshot: Dict[str, Any],
    key: str,
    value: Any,
    *,
    retention: Any = None,
) -> Dict[str, Any]:
    if key not in USER_CONTEXT_KEYS:
        if key in RUNTIME_OWNED_KEYS:
            raise ValueError(f"Context key '{key}' is runtime-owned and cannot be updated manually")
        raise ValueError(f"Unsupported context key: {key}")

    updated = normalize_context_snapshot(snapshot, snapshot.get("context_id"), retention=retention)
    if key == "focus_pixel":
        updated["focus"]["pixel"] = normalize_pixel(value)
    elif key == "focus_resource_id":
        updated["focus"]["resource_id"] = str(value or "").strip()
    elif key == "focus_shader_id":
        updated["focus"]["shader_id"] = str(value or "").strip()
    elif key == "notes":
        updated["notes"] = str(value or "").strip()
    updated["updated_at_ms"] = _now_ms()
    return updated


def merge_recent_artifacts(
    snapshot: Dict[str, Any],
    artifacts: Iterable[Dict[str, Any]],
    *,
    source_tool: str,
    retention: Any = None,
) -> Dict[str, Any]:
    retention_policy = _coerce_retention_policy(retention)
    updated = normalize_context_snapshot(snapshot, snapshot.get("context_id"), retention=retention_policy)
    current = [
        entry
        for entry in (updated.get("last_artifacts") or [])
        if isinstance(entry, dict) and str(entry.get("path") or "").strip()
    ]
    ts_ms = _now_ms()
    for artifact in artifacts:
        path = str(artifact.get("path") or "").strip()
        if not path:
            continue
        entry = {
            "path": path,
            "type": str(artifact.get("type") or "file").strip() or "file",
            "source_tool": source_tool,
            "ts_ms": ts_ms,
        }
        current = [item for item in current if str(item.get("path") or "").strip() != path]
        current.insert(0, entry)
    updated["last_artifacts"] = _trim_artifacts(current, retention=retention_policy)
    updated["updated_at_ms"] = _now_ms()
    return updated
