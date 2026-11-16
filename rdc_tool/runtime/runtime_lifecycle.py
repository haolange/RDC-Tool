"""Runtime startup and shutdown."""

from __future__ import annotations

from pathlib import Path

from rdc_tool.config import RdcToolConfig
from rdc_tool.context_snapshot import normalize_context_id
from rdc_tool.core.event_graph import EventGraphService
from rdc_tool.core.patch_engine import PatchEngine
from rdc_tool.core.perf_service import PerfService
from rdc_tool.core.pipeline_service import PipelineService
from rdc_tool.core.render_service import RenderService
from rdc_tool.core.session_manager import SessionManager
from rdc_tool.runtime import context_records, live_state, oplog, preview_sync, remote_target, renderdoc_api, settings
from rdc_tool.runtime_bootstrap import bootstrap_renderdoc_runtime
from rdc_tool.runtime_paths import binding_module_name, ensure_runtime_dirs
from rdc_tool.utils.artifact_store import ArtifactStore


async def runtime_startup() -> None:
    if live_state._runtime_bootstrapped:
        return

    ensure_runtime_dirs()
    bootstrap = bootstrap_renderdoc_runtime(probe_import=False)
    renderdoc_dir = bootstrap.pymodules_dir
    binding_path = renderdoc_dir / binding_module_name()
    if not binding_path.is_file():
        oplog._record_log("warning", f"renderdoc runtime missing: {binding_path}")
    for item in bootstrap.loader_errors:
        oplog._record_log("warning", f"renderdoc bootstrap warning: {item}")

    live_state._config = RdcToolConfig.from_env()
    artifact_root = Path(live_state._config.artifact.store_path).resolve()
    artifact_root.mkdir(parents=True, exist_ok=True)
    live_state._config.artifact.store_path = artifact_root
    live_state._artifact_store = ArtifactStore(root=artifact_root)

    live_state._session_manager = SessionManager()
    live_state._event_graph_service = EventGraphService()
    live_state._render_service = RenderService()
    live_state._pipeline_service = PipelineService()
    live_state._perf_service = PerfService()
    live_state._patch_engine = PatchEngine()

    live_state._runtime.config = settings._serialize_runtime_config()
    live_state._runtime.initialized = False
    live_state._runtime.logs.clear()
    live_state._runtime.context_states.clear()
    live_state._runtime.hydrated_contexts.clear()
    live_state._runtime_bootstrapped = True
    oplog._record_log("info", "RDC-Tool runtime initialized")


async def runtime_shutdown(*, clear_context_state: bool = True) -> None:
    if not live_state._runtime_bootstrapped:
        return
    context_ids = sorted(
        {normalize_context_id(item) for item in list(live_state._runtime.context_states.keys())}
        | {normalize_context_id(item) for item in list(live_state._runtime.context_snapshots.keys())}
        | {normalize_context_id(item) for item in list(live_state._runtime.previews.keys())}
        | {normalize_context_id(live_state._runtime_context_id())}
    )
    for context_id in context_ids:
        preview = preview_sync._preview_state_value(context_id)
        await preview_sync._close_preview_binding(context_id)
        if not clear_context_state and preview.get("enabled"):
            preview_sync._store_preview_state(
                context_id,
                preview_sync._preview_update_payload(
                    context_id,
                    preview,
                    enabled=True,
                    state_name="stale",
                    last_error="",
                ),
            )
    for debug_id in list(live_state._runtime.shader_debugs.keys()):
        handle = live_state._runtime.shader_debugs.pop(debug_id, None)
        if handle is not None:
            try:
                controller = live_state._session_manager.get_controller(handle.session_id)
                controller.FreeTrace(handle.trace)
            except Exception:
                pass
    if live_state._session_manager is not None:
        if live_state._patch_engine is not None:
            for session_id in list(live_state._runtime.replays.keys()):
                try:
                    await live_state._patch_engine.revert_all(session_id, live_state._session_manager)
                except Exception:
                    pass
        live_state._runtime.shader_replacements.clear()
        live_state._runtime.restored_shader_sessions.clear()
        for info in list(live_state._session_manager.list_sessions()):
            try:
                await live_state._session_manager.close_session(info.session_id)
            except Exception:
                pass
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
    if clear_context_state:
        context_records._reset_context_snapshot()
    live_state._runtime_bootstrapped = False
    oplog._record_log("info", "RDC-Tool runtime shutdown complete")
