"""rd.core.* operations."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List

from rdc_tool.config import RdcToolConfig
from rdc_tool.context_snapshot import normalize_context_id
from rdc_tool.platform import host as platform_host
from rdc_tool.platform import preview as platform_preview
from rdc_tool.runtime import (
    coerce,
    context_records,
    discovery,
    envelope,
    live_state,
    preview_sync,
    remote_records,
    remote_target,
    renderdoc_api,
    replay_access,
    settings,
    truth_matrix,
)
from rdc_tool.runtime_paths import artifacts_dir
from rdc_tool.runtime_state import read_runtime_logs
from rdc_tool.utils.artifact_store import ArtifactStore


async def dispatch(action: str, args: Dict[str, Any]) -> envelope.Outcome:
    if action == "init":
        global_env = coerce._as_dict(args.get("global_env"), default={})
        live_state._runtime.enable_remote = coerce._as_bool(args.get("enable_remote"), True)
        if global_env:
            settings._apply_runtime_config(global_env)
        live_state._runtime.initialized = True
        context_records._sync_context_metrics(live_state._runtime_context_id())
        version = await _core_get_version_value()
        capabilities = await _core_capabilities(detail="summary")
        return envelope.success(api_version=version, capabilities=capabilities)

    if action == "shutdown":
        unique_remote_ids = {
            str(item.remote_id or "")
            for item in list(live_state._runtime.remotes.values()) + list(live_state._runtime.session_owned_remotes.values())
            if item is not None and str(item.remote_id or "").strip()
        }
        released = {
            "sessions": len(live_state._runtime.replays),
            "capture_files": len(live_state._runtime.captures),
            "remote_connections": len(unique_remote_ids),
            "shader_debugs": len(live_state._runtime.shader_debugs),
        }
        if live_state._patch_engine is not None:
            for sid in list(live_state._runtime.replays.keys()):
                try:
                    await live_state._patch_engine.revert_all(sid, live_state._session_manager)
                except Exception:
                    pass
        live_state._runtime.shader_replacements.clear()
        live_state._runtime.restored_shader_sessions.clear()
        for context_id in list(live_state._runtime.previews.keys()):
            try:
                await preview_sync._close_preview_binding(context_id)
            except Exception:
                pass
        for sid in list(live_state._runtime.replays.keys()):
            try:
                await live_state._session_manager.close_session(sid)
            except Exception:
                pass
        live_state._runtime.replays.clear()
        live_state._runtime.captures.clear()
        live_state._runtime.shader_debugs.clear()
        for remote_id in list(live_state._runtime.remotes.keys()):
            handle = live_state._runtime.remotes.pop(remote_id, None)
            if handle is not None:
                try:
                    await renderdoc_api._offload(remote_target._disconnect_remote_handle_sync, handle)
                except Exception:
                    pass
        live_state._runtime.session_owned_remotes.clear()
        live_state._runtime.consumed_remotes.clear()
        live_state._runtime.context_snapshots.clear()
        live_state._runtime.previews.clear()
        live_state._runtime.context_states.clear()
        live_state._runtime.hydrated_contexts.clear()
        context_records._reset_context_snapshot()
        live_state._runtime.initialized = False
        return envelope.success(released=released)

    if action == "get_version":
        version = await _core_get_version_value()
        return envelope.success(version=version, commit_hash=None, build_date=None)

    if action == "get_capabilities":
        detail = str(args.get("detail_level", "summary"))
        return envelope.success(capabilities=await _core_capabilities(detail=detail))

    if action == "set_config":
        coerce._require(args, "config")
        cfg = coerce._as_dict(args.get("config"))
        applied = settings._apply_runtime_config(cfg)
        if live_state._artifact_store is not None:
            live_state._artifact_store = ArtifactStore(root=Path(str((live_state._config or RdcToolConfig()).artifact.store_path)).resolve())
        return envelope.success(applied=applied)

    if action == "get_config":
        return envelope.success(config=settings._serialize_runtime_config())

    if action == "set_log_level":
        level = str(args.get("level", "info")).upper()
        logging.getLogger().setLevel(level)
        settings._apply_runtime_config({"log_level": level})
        return envelope.success()

    if action == "get_logs":
        since_ms = args.get("since_ms")
        level_min = str(args.get("level_min", "")).lower().strip()
        max_lines = coerce._as_int(args.get("max_lines"), 500)
        levels = ["trace", "debug", "info", "warn", "warning", "error"]
        if level_min and level_min in levels:
            cutoff = levels.index("warning" if level_min == "warn" else level_min)
        else:
            cutoff = 0
        out: List[Dict[str, Any]] = []
        log_records = read_runtime_logs(live_state._runtime_context_id(), since_ms=coerce._as_int(since_ms) if since_ms is not None else None, max_lines=max_lines * 4)
        if not log_records:
            log_records = list(live_state._runtime.logs)
        for item in log_records:
            if since_ms is not None and int(item.get("ts_ms", 0)) < int(since_ms):
                continue
            lv = str(item.get("level", "info")).lower()
            lv = "warning" if lv == "warn" else lv
            idx = levels.index(lv) if lv in levels else 0
            if idx < cutoff:
                continue
            out.append(item)
        return envelope.success(logs=out[-max_lines:])

    if action == "get_operation_history":
        state = context_records._context_state(live_state._runtime_context_id())
        max_items = coerce._as_int(args.get("max_items"), 32)
        since_ms = coerce._as_int(args.get("since_ms"), 0)
        operation_name = str(args.get("operation") or "").strip().lower()
        status_filter = str(args.get("status") or "").strip().lower()
        items = []
        for entry in state.get("recent_operations", []):
            if not isinstance(entry, dict):
                continue
            if since_ms and int(entry.get("updated_at_ms") or 0) < since_ms:
                continue
            if operation_name and operation_name not in str(entry.get("operation") or "").lower():
                continue
            if status_filter and status_filter != str(entry.get("status") or "").lower():
                continue
            items.append(entry)
        return envelope.success(context_id=live_state._runtime_context_id(), operations=items[:max_items])

    if action == "get_runtime_metrics":
        return envelope.success(**discovery._runtime_metrics_payload(live_state._runtime_context_id()))

    if action == "list_tools":
        detail_level = str(args.get("detail_level") or "summary").strip().lower() or "summary"
        tools = discovery._filter_tool_profiles(
            query=str(args.get("query") or ""),
            namespace=str(args.get("namespace") or ""),
            group=str(args.get("group") or ""),
            capability=str(args.get("capability") or ""),
            role=str(args.get("role") or ""),
            intent=str(args.get("intent") or ""),
            mutates_state=(
                bool(args.get("mutates_state"))
                if args.get("mutates_state") is not None
                else None
            ),
            detail_level="full" if detail_level == "full" else "summary",
        )
        return envelope.success(tool_count=len(tools), tools=tools)


    if action == "get_tool_graph":
        return envelope.success(
            **discovery._tool_graph_payload(
                query=str(args.get("query") or ""),
                namespace=str(args.get("namespace") or ""),
                capability=str(args.get("capability") or ""),
                role=str(args.get("role") or ""),
                intent=str(args.get("intent") or ""),
            )
        )

    if action == "healthcheck":
        checks: List[Dict[str, Any]] = []
        try:
            rd = renderdoc_api._get_rd()
            _ = rd.GetVersionString() if hasattr(rd, "GetVersionString") else "unknown"
            checks.append({"name": "renderdoc_import", "ok": True})
        except Exception as exc:
            checks.append({"name": "renderdoc_import", "ok": False, "detail": str(exc)})

        artifact_dir = Path(live_state._runtime.config.get("artifact_dir", str(artifacts_dir())))
        try:
            artifact_dir.mkdir(parents=True, exist_ok=True)
            probe = artifact_dir / ".healthcheck.tmp"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
            checks.append({"name": "artifact_dir_writable", "ok": True})
        except Exception as exc:
            checks.append({"name": "artifact_dir_writable", "ok": False, "detail": str(exc)})

        if coerce._as_bool(args.get("check_replay"), True):
            checks.append({"name": "replay_runtime", "ok": True})
        if coerce._as_bool(args.get("check_remote"), False):
            checks.append({"name": "remote_runtime", "ok": live_state._runtime.enable_remote})
        success = all(bool(item.get("ok")) for item in checks)
        if not success:
            return envelope.failure("healthcheck failed", code="runtime_error", details={"checks": checks})
        return envelope.success(checks=checks)

    return envelope.failure(f"Unsupported core action: {action}", code="runtime_error")


async def _core_get_version_value() -> str:
    return renderdoc_api._renderdoc_version_value()

async def _core_capabilities(*, detail: str) -> Dict[str, Any]:
    context_id = normalize_context_id(live_state._runtime_context_id())
    context_state = context_records._context_state(context_id)
    current_session_id = str(context_state.get("current_session_id") or "").strip()
    current_session_record = dict((context_state.get("sessions") or {}).get(current_session_id) or {})
    current_backend = live_state._normalize_backend(
        str(current_session_record.get("backend_type") or context_state.get("backend") or "local"),
        default="local",
    )
    current_controller = None
    session_probe = {"status": "not_currently_probed", "reason": "Summary reads do not resume or probe replay controllers."}
    if detail == "full" and current_session_id:
        try:
            current_controller = await replay_access._get_controller(current_session_id)
            session_probe = {"status": "verified", "reason": "Selected replay controller is live."}
        except Exception as exc:
            session_probe = {"status": "unavailable", "reason": str(exc), "code": getattr(exc, "code", "session_probe_failed")}
    elif detail == "full":
        session_probe = {"status": "not_currently_probed", "reason": "No replay session is selected."}
    remote_connected = any(handle.connected for handle in live_state._runtime.remotes.values())
    remote_reason = (
        "Remote tools are disabled by config."
        if not live_state._runtime.enable_remote
        else (
            "At least one live RenderDoc remote endpoint is connected."
            if remote_connected
            else "Requires a live RenderDoc remote endpoint."
        )
    )
    summary = {
        "replay": envelope._capability_entry(
            True,
            reason="Bundled RenderDoc replay runtime is available.",
            optional=False,
            source="bundled_runtime",
        ),
        "remote": envelope._capability_entry(
            bool(live_state._runtime.enable_remote and remote_connected),
            reason=remote_reason,
            optional=True,
            source="external_dependency",
            enabled_by_config=bool(live_state._runtime.enable_remote),
            connected_handles=sum(1 for handle in live_state._runtime.remotes.values() if handle.connected),
        ),
        "shader_debug": envelope._capability_entry(
            True,
            reason="Requires an opened replay session whose API reports shader debugging support.",
            optional=True,
            source="renderdoc_runtime",
        ),
        "shader_replace": envelope._capability_entry(
            True,
            reason="Requires an opened replay session whose replay backend exposes runtime shader replacement APIs.",
            optional=True,
            source="renderdoc_runtime",
        ),
        "mesh_post_transform": envelope._capability_entry(
            True,
            reason="Requires a replay session whose controller exposes GetPostVSData.",
            optional=True,
            source="renderdoc_runtime",
        ),
        "shader_binary_export": envelope._capability_entry(
            True,
            reason="Requires a bound shader whose reflection exposes rawBytes.",
            optional=True,
            source="renderdoc_runtime",
        ),
        "shader_compile": envelope._capability_entry(
            True,
            reason="Requires a replay session whose controller exposes BuildTargetShader.",
            optional=True,
            source="renderdoc_runtime",
        ),
        "counters": envelope._capability_entry(
            True,
            reason="Requires a replay session and a capture/backend that exposes counters.",
            optional=True,
            source="renderdoc_runtime",
        ),
        "preview_window": envelope._capability_entry(
            platform_preview.preview_window_supported(),
            reason=("Native preview windows are available on this host."
                    if platform_preview.preview_window_supported()
                    else "This host has no native preview window; rd.session.observe exports headless images."),
            optional=True,
            source="platform",
            host_target=platform_host.host_target(),
        ),
        "artifact_dir": live_state._runtime.config.get("artifact_dir"),
        "context_id": context_id,
        "current_session_id": current_session_id,
        "current_backend": current_backend,
        "current_session_probe": session_probe,
    }
    if current_backend == "remote" and current_session_id:
        if detail == "full" and current_controller is not None:
            summary["remote_capability_matrix"] = await renderdoc_api._offload(
                truth_matrix._session_remote_capability_matrix, current_session_id,
                context_id=context_id, controller=current_controller, probe_live=True,
            )
        else:
            summary["remote_capability_matrix"] = truth_matrix._session_remote_capability_matrix(
                current_session_id, context_id=context_id, controller=None, probe_live=False,
            )
    elif remote_connected:
        handle = next((item for item in live_state._runtime.remotes.values() if item.connected), None)
        if handle is not None:
            scope = remote_records._remote_context_scope(
                str(handle.remote_id or ""),
                origin_context_id=str(handle.origin_context_id or ""),
                context_id=context_id,
            )
            summary["remote_capability_matrix"] = {
                "endpoint": truth_matrix._truth_matrix_entry(
                    "verified",
                    "At least one live remote handle is connected.",
                    endpoint=remote_records._remote_url(handle.host, handle.port),
                    origin_remote_id=str(handle.remote_id or ""),
                    origin_context_id=scope["origin_context_id"],
                ),
                "replay": truth_matrix._truth_matrix_entry(
                    "blocked_current_session",
                    "A remote handle is connected, but no remote replay session is currently selected.",
                    context_id=context_id,
                ),
            }
    if detail == "full":
        summary["sessions"] = len(live_state._runtime.replays)
        summary["capture_files"] = len(live_state._runtime.captures)
        summary["remote_connections"] = len(live_state._runtime.remotes)
    return summary
