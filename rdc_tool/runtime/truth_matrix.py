"""Capability and truth metadata reported for sessions, pipelines and events."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from rdc_tool.context_snapshot import normalize_context_id
from rdc_tool.runtime import context_records, live_state, remote_records, renderdoc_api, replay_access, shader_patches


def _session_replace_capability(session_id: str, controller: Any) -> Tuple[bool, str]:
    try:
        state = live_state._session_manager.get_state(session_id)
    except Exception:
        state = None
    methods = ("BuildTargetShader", "ReplaceResource", "RemoveReplacement", "FreeTargetResource")
    missing = [name for name in methods if not hasattr(controller, name)]
    supported = not missing
    reason = (
        "Replay controller exposes runtime shader replacement APIs."
        if supported
        else f"Replay controller is missing runtime shader replacement APIs: {', '.join(missing)}"
    )
    if state is not None:
        state.capabilities.patch_supported = supported
    return supported, reason


def _truth_matrix_entry(status: str, reason: str, **details: Any) -> Dict[str, Any]:
    return {
        "status": str(status or "unsupported").strip() or "unsupported",
        "reason": str(reason or "").strip(),
        "details": dict(details or {}),
    }


def _supported_source_encoding_names(controller: Any) -> List[str]:
    if not hasattr(controller, "GetTargetShaderEncodings"):
        return []
    return [
        name
        for name in (shader_patches._shader_encoding_name(item) for item in list(controller.GetTargetShaderEncodings() or []))
        if str(name or "").strip()
    ]


def _session_remote_capability_matrix(
    session_id: str,
    *,
    context_id: Optional[str] = None,
    controller: Any | None = None,
    probe_live: bool = True,
) -> Dict[str, Any]:
    ctx = normalize_context_id(context_id or live_state._runtime_context_id())
    state = context_records._context_state(ctx)
    sessions = state.get("sessions") if isinstance(state.get("sessions"), dict) else {}
    session_record = dict(sessions.get(str(session_id)) or {}) if isinstance(sessions, dict) else {}
    backend_type = live_state._normalize_backend(str(session_record.get("backend_type") or state.get("backend") or "local"), default="local")
    if backend_type != "remote":
        return {}

    remote_meta = remote_records._session_record_remote_metadata(session_record)
    endpoint = str(remote_meta.get("endpoint") or "").strip()
    origin_remote_id = str(remote_meta.get("origin_remote_id") or "").strip()
    origin_context_id = normalize_context_id(
        str(remote_meta.get("origin_context_id") or ctx)
    )
    current_event_id = int(session_record.get("active_event_id") or 0)

    if probe_live and current_event_id <= 0:
        current_event_id = int(replay_access._active_event(session_id) or 0)

    if probe_live and controller is None:
        try:
            controller = live_state._session_manager.get_controller(str(session_id)) if live_state._session_manager is not None else None
        except Exception:
            controller = None

    replay_live = str(session_id or "").strip() in live_state._runtime.replays
    remote_handle = live_state._runtime.remotes.get(origin_remote_id)
    endpoint_live = bool(remote_handle is not None and remote_handle.connected)
    endpoint_status = "verified" if endpoint and origin_remote_id and (endpoint_live or (replay_live and controller is not None)) else "not_currently_probed"
    endpoint_reason = (
        "Recorded remote endpoint is backed by a live handle or selected replay controller."
        if endpoint_status == "verified"
        else "Recorded endpoint metadata alone does not verify a live connection."
    )
    replay_status = "verified" if replay_live else "not_currently_probed"
    replay_reason = (
        "Replay session is currently live in the selected context."
        if replay_live
        else "Registered replay is not loaded; deferred recovery is not evidence of unsupported replay."
    )

    if not probe_live or controller is None:
        not_probed_reason = (
            "Live remote shader capability probing is skipped for non-blocking context reads."
            if not probe_live else "No live controller was obtained; shader support has not been probed."
        )
        return {
            "endpoint": _truth_matrix_entry(
                endpoint_status,
                endpoint_reason,
                endpoint=endpoint,
                origin_remote_id=origin_remote_id,
                origin_context_id=origin_context_id,
            ),
            "replay": _truth_matrix_entry(
                replay_status,
                replay_reason,
                session_id=str(session_id or ""),
                context_id=ctx,
            ),
            "event_bound_inspection": _truth_matrix_entry(
                "not_currently_probed",
                not_probed_reason,
                active_event_id=current_event_id,
                has_bound_shader=False,
            ),
            "shader_debug": _truth_matrix_entry(
                "not_currently_probed",
                not_probed_reason,
                active_event_id=current_event_id,
            ),
            "shader_replace": _truth_matrix_entry(
                "not_currently_probed",
                not_probed_reason,
                active_event_id=current_event_id,
            ),
            "shader_compile": _truth_matrix_entry(
                "not_currently_probed",
                not_probed_reason,
                supported_source_encodings=[],
            ),
            "fix_verification": _truth_matrix_entry(
                "not_currently_probed",
                "Use direct shader/export tools or rd.core.get_capabilities(detail_level=full) for live remote capability verification.",
                blocked_capability_codes=["REMOTE_LIVE_CAPABILITY_NOT_PROBED_IN_CONTEXT"],
            ),
        }

    has_bound_shader = False
    inspection_status = "not_currently_probed"
    inspection_reason = "The active event has not established a bound shader for event-bound inspection."
    if controller is not None:
        try:
            pipe = controller.GetPipelineState()
            for stage_name in renderdoc_api._stage_candidates():
                rd_stage = renderdoc_api._rd_stage(stage_name)
                bound_shader = pipe.GetShader(rd_stage)
                if not renderdoc_api._is_null_resource_id(bound_shader):
                    has_bound_shader = True
                    break
            if has_bound_shader and current_event_id > 0:
                inspection_status = "verified"
                inspection_reason = "Current event exposes at least one bound shader for event-bound inspection."
            elif current_event_id > 0:
                inspection_status = "not_currently_probed"
                inspection_reason = "The active event has no bound shader; this does not establish visibility at a different target event."
        except Exception as exc:
            inspection_status = "unstable"
            inspection_reason = f"Unable to inspect event-bound shader visibility: {exc}"

    supported_encodings = []
    encoding_error = None
    try:
        supported_encodings = _supported_source_encoding_names(controller)
    except Exception as exc:
        encoding_error = str(exc)
    patch_supported = False
    patch_reason = "Replay controller unavailable."
    if controller is not None:
        patch_supported, patch_reason = _session_replace_capability(session_id, controller)
    replace_status = "verified" if patch_supported else "unsupported"
    compile_status = "unstable" if encoding_error is not None else ("verified" if supported_encodings else "unsupported")
    compile_reason = (
        "Replay controller exposes BuildTargetShader encodings."
        if supported_encodings
        else "Replay controller does not expose any compilable source encodings."
    )
    if encoding_error is not None:
        compile_reason = f"Unable to query shader compile encodings: {encoding_error}"
    debug_status = "degraded"
    debug_reason = "Remote shader debug remains dependent on replay backend support and target/event binding."
    if controller is None or not hasattr(controller, "DebugPixel"):
        debug_status = "unsupported"
        debug_reason = "Replay controller does not expose DebugPixel."
    elif inspection_status == "blocked_current_session":
        debug_status = "blocked_current_session"
        debug_reason = "Shader debug is blocked until a valid event-bound shader target is established."

    fix_status = "verified"
    fix_reason = "Remote session currently exposes enough surfaces for strict verification planning."
    blocked_codes: List[str] = []
    if inspection_status == "not_currently_probed":
        fix_status = "not_currently_probed"
        fix_reason = "Inspect the intended draw event and its shader edit_plan before deciding whether fix verification is possible."
    elif inspection_status != "verified":
        fix_status = "blocked_current_session"
        fix_reason = "Event-bound shader inspection is not currently stable enough for strict verification."
        blocked_codes.append("BLOCKED_REMOTE_SHADER_INTROSPECTION")
    if replace_status != "verified":
        fix_status = "blocked_current_session"
        fix_reason = "Runtime shader replacement is unavailable for the selected remote replay backend."
        blocked_codes.append("BLOCKED_REMOTE_SHADER_REPLACEMENT")
    if compile_status != "verified":
        fix_status = "blocked_current_session"
        fix_reason = "Shader compile is unavailable for the selected remote replay backend."
        blocked_codes.append("BLOCKED_REMOTE_SHADER_COMPILE_ENCODING")

    return {
        "endpoint": _truth_matrix_entry(
            endpoint_status,
            endpoint_reason,
            endpoint=endpoint,
            origin_remote_id=origin_remote_id,
            origin_context_id=origin_context_id,
        ),
        "replay": _truth_matrix_entry(
            replay_status,
            replay_reason,
            session_id=str(session_id or ""),
            context_id=ctx,
        ),
        "event_bound_inspection": _truth_matrix_entry(
            inspection_status,
            inspection_reason,
            active_event_id=current_event_id,
            has_bound_shader=bool(has_bound_shader),
        ),
        "shader_debug": _truth_matrix_entry(
            debug_status,
            debug_reason,
            active_event_id=current_event_id,
        ),
        "shader_replace": _truth_matrix_entry(
            replace_status,
            patch_reason,
            active_event_id=current_event_id,
        ),
        "shader_compile": _truth_matrix_entry(
            compile_status,
            compile_reason,
            supported_source_encodings=supported_encodings,
        ),
        "fix_verification": _truth_matrix_entry(
            fix_status,
            fix_reason,
            blocked_capability_codes=blocked_codes,
        ),
    }


def _session_backend_record(
    session_id: str,
    *,
    context_id: Optional[str] = None,
) -> Tuple[str, Dict[str, Any]]:
    ctx = normalize_context_id(context_id or live_state._runtime_context_id())
    state = context_records._context_state(ctx)
    sessions = state.get("sessions") if isinstance(state.get("sessions"), dict) else {}
    record = dict(sessions.get(str(session_id)) or {}) if isinstance(sessions, dict) else {}
    backend = live_state._normalize_backend(
        str(record.get("backend_type") or state.get("backend") or "local"),
        default="local",
    )
    return backend, record


def _pipeline_truth_metadata(
    session_id: str,
    snapshot_dict: Dict[str, Any],
    *,
    context_id: Optional[str] = None,
) -> Dict[str, Any]:
    backend, _ = _session_backend_record(session_id, context_id=context_id)
    shaders = list(snapshot_dict.get("shaders") or [])
    render_targets = list(snapshot_dict.get("render_targets") or [])
    api_name = str(snapshot_dict.get("api") or "").strip().upper()
    degraded_reasons: List[str] = []
    if "shaders" in snapshot_dict and not shaders:
        degraded_reasons.append("binding_unavailable")
    if "render_targets" in snapshot_dict and not render_targets:
        degraded_reasons.append("event_bound_pipeline_state_partial")
    if backend == "remote" and degraded_reasons:
        degraded_reasons.append("summary_degraded")
    if backend == "remote" and api_name in {"", "UNKNOWN", "D3D11"}:
        degraded_reasons.append("api_summary_untrusted")
    unique_reasons = list(dict.fromkeys(degraded_reasons))
    summary_status = "verified" if not unique_reasons else "degraded"
    return {
        "backend_type": backend,
        "summary_status": summary_status,
        "summary_degraded_reasons": unique_reasons,
        "binding_truth_level": "binding_verified" if not unique_reasons else "binding_degraded",
        "visual_truth_level": "not_applicable",
        "evidence_truth_level": "structured_evidence" if summary_status == "verified" else "partial_structured_evidence",
    }


async def _event_truth_metadata(
    session_id: str,
    event_id: int,
    *,
    context_id: Optional[str] = None,
) -> Dict[str, Any]:
    backend, _ = _session_backend_record(session_id, context_id=context_id)
    degraded = {
        "backend_type": backend,
        "summary_status": "degraded",
        "summary_degraded_reasons": ["summary_degraded"],
        "binding_truth_level": "binding_degraded",
        "visual_truth_level": "not_applicable",
        "evidence_truth_level": "partial_structured_evidence",
    }
    if live_state._pipeline_service is None:
        return degraded
    try:
        snapshot = await live_state._pipeline_service.snapshot_pipeline(
            session_id=session_id,
            event_id=int(event_id),
            session_manager=live_state._session_manager,
        )
    except Exception:
        return degraded
    snapshot_dict = snapshot.model_dump(mode="json")
    return _pipeline_truth_metadata(session_id, snapshot_dict, context_id=context_id)
