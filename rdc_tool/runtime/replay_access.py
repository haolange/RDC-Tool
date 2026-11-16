"""Live replay access: sessions, controllers, events, resources and output targets."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional, Sequence, Tuple

from rdc_tool.core.errors import CoreError
from rdc_tool.core.renderdoc_status import status_text as _rd_status_text
from rdc_tool.core.session_manager import SessionError
from rdc_tool.runtime import (
    action_index,
    coerce,
    context_records,
    live_state,
    renderdoc_api,
    session_recovery,
    texture_naming,
)


async def _ensure_live_session(session_id: str) -> live_state.ReplayHandle:
    assert live_state._session_manager is not None
    record = (context_records._context_state(live_state._runtime_context_id()).get("sessions") or {}).get(str(session_id), {})
    if (record.get("recovery") or {}).get("status") == "requires_restart":
        raise CoreError(code="session_requires_restart", message="Replay requires controlled recovery; close and reopen the capture",
                        category="runtime", details={"session_id": session_id, "last_error": record.get("last_error")})
    replay = live_state._runtime.replays.get(str(session_id))
    if replay is not None:
        try:
            live_state._session_manager.get_controller(str(session_id))
            live_state._session_manager.get_output(str(session_id))
            return replay
        except SessionError:
            pass
    await session_recovery._recover_single_session_from_state(live_state._runtime_context_id(), str(session_id))
    replay = live_state._runtime.replays.get(str(session_id))
    if replay is None:
        raise CoreError(
            code="session_resume_failed",
            message=f"Session could not be resumed: {session_id}",
            category="runtime",
            details={"session_id": str(session_id)},
        )
    return replay


async def _get_controller(session_id: str) -> Any:
    assert live_state._session_manager is not None
    await _ensure_live_session(session_id)
    controller = live_state._session_manager.get_controller(session_id)
    health_scope = live_state._CURRENT_REPLAY_HEALTH_SCOPE.get()
    if health_scope is not None:
        await _check_replay_operation_health(controller, session_id, health_scope["operation"], "before_native_access")
        health_scope["controllers"][session_id] = controller
    return controller


@asynccontextmanager
async def _replay_operation_health(operation: str):
    """Check controllers actually accessed, without preceding semantic argument validation."""
    scope = {"operation": operation, "controllers": {}}
    token = live_state._CURRENT_REPLAY_HEALTH_SCOPE.set(scope)
    try:
        yield
    finally:
        try:
            for session_id, controller in tuple(scope["controllers"].items()):
                await _check_replay_operation_health(controller, session_id, operation, "after_operation")
        finally:
            live_state._CURRENT_REPLAY_HEALTH_SCOPE.reset(token)


async def _check_replay_operation_health(controller: Any, session_id: str, operation: str, stage: str) -> None:
    """Reject native default/null results after a fatal replay error, before publication."""
    from rdc_tool.core.renderdoc_status import status_code_name, status_code_raw

    def probe():
        getter = getattr(controller, "GetFatalErrorStatus", None)
        if not callable(getter):
            raise RuntimeError("Replay controller does not expose GetFatalErrorStatus")
        status = getter()
        if status is None or not callable(getattr(status, "OK", None)):
            raise RuntimeError("Replay fatal-status probe returned no valid ResultDetails")
        return status, bool(status.OK())

    details = {"session_id": session_id, "operation": operation, "failure_stage": stage,
               "source_layer": "renderdoc", "recovery_required": True}
    try:
        status, healthy = await renderdoc_api._offload(probe)
    except Exception as exc:
        message = f"Cannot establish native replay health: {exc}"
        code = "replay_health_unavailable"
        details["probe_error"] = str(exc)
    else:
        if healthy:
            return
        native_code = status.code
        details["renderdoc_status"] = {
            "result_code_name": status_code_name(native_code),
            "result_code_raw": status_code_raw(native_code),
            "status_text": _rd_status_text(status),
        }
        message = f"Native replay fatal error: {details['renderdoc_status']['status_text']}"
        code = "replay_fatal_error"
    context_records._update_context_session_record(session_id, recovery_status="requires_restart", last_error=message)
    raise CoreError(code=code, message=message, category="runtime", details=details)

async def _get_output(session_id: str) -> Any:
    assert live_state._session_manager is not None
    await _ensure_live_session(session_id)
    return live_state._session_manager.get_output(session_id)


def _get_replay_handle(session_id: str) -> live_state.ReplayHandle:
    replay = live_state._runtime.replays.get(session_id)
    if replay is None:
        raise ValueError(f"Unknown replay session_id: {session_id}")
    return replay


def _active_event(session_id: str) -> int:
    replay = live_state._runtime.replays.get(session_id)
    if replay is None:
        return 0
    return replay.active_event_id


def _raise_event_not_found(session_id: str, event_id: int) -> None:
    raise CoreError(
        code="event_not_found",
        message=f"Event not found: {int(event_id)}",
        category="not_found",
        details={
            "session_id": str(session_id or ""),
            "event_id": int(event_id),
        },
    )


def _require_action_event(session_id: str, event_id: int, by_event: Dict[int, Any]) -> int:
    resolved = int(event_id)
    if resolved <= 0 or resolved not in by_event:
        _raise_event_not_found(session_id, resolved)
    return resolved


def _store_active_event(session_id: str, event_id: int, *, context_id: Optional[str] = None) -> None:
    resolved = int(event_id or 0)
    if session_id in live_state._runtime.replays:
        live_state._runtime.replays[session_id].active_event_id = resolved
    context_records._set_context_active_event(session_id, resolved, context_id=context_id)


def _capture_dependent_session_ids(capture_file_id: str) -> List[str]:
    wanted = str(capture_file_id or "")
    dependent = [
        str(session_id)
        for session_id, handle in live_state._runtime.replays.items()
        if str(handle.capture_file_id or "") == wanted
    ]
    dependent.sort()
    return dependent


async def _ensure_event(session_id: str, event_id: Optional[int]) -> int:
    controller = await _get_controller(session_id)
    roots, _, by_event = await _load_action_index(session_id, controller=controller)
    should_repair_state = False
    if event_id is None:
        active_event = _active_event(session_id)
        if active_event > 0 and active_event in by_event:
            resolved_event = active_event
        else:
            resolved_event = action_index._pick_default_event_id(roots)
            should_repair_state = active_event != resolved_event
    else:
        resolved_event = _require_action_event(session_id, int(event_id), by_event)
    if resolved_event > 0:
        await renderdoc_api._offload(controller.SetFrameEvent, resolved_event, True)
        _store_active_event(session_id, resolved_event)
    elif should_repair_state:
        _store_active_event(session_id, resolved_event)
    return resolved_event


class ResourceLookupMiss(ValueError):
    """A completed read-only inventory lookup found no matching resource."""


async def _resolve_resource_id(session_id: str, resource_id: Any) -> Any:
    controller = await _get_controller(session_id)
    wanted = str(resource_id)
    textures = await renderdoc_api._offload(controller.GetTextures)
    buffers = await renderdoc_api._offload(controller.GetBuffers)
    resources = await renderdoc_api._offload(controller.GetResources)
    for collection in (textures, buffers, resources):
        for obj in collection:
            rid = getattr(obj, "resourceId", None)
            if rid is None:
                continue
            if wanted in texture_naming._resource_id_tokens(rid):
                return rid
    raise ResourceLookupMiss(f"Resource not found: {resource_id}")


async def _resolve_texture_id(session_id: str, texture_id: Optional[Any], *, event_id: Optional[int] = None) -> Any:
    controller = await _get_controller(session_id)
    if texture_id:
        return await _resolve_resource_id(session_id, texture_id)
    target_event = await _ensure_event(session_id, event_id)
    if target_event <= 0:
        raise ValueError("No active event to infer texture target")
    pipe = await renderdoc_api._offload(controller.GetPipelineState)
    rd = renderdoc_api._get_rd()
    null_id = rd.ResourceId()
    outputs = await renderdoc_api._offload(pipe.GetOutputTargets)
    for out in reversed(outputs):
        rid = getattr(out, "resourceId", null_id)
        if rid != null_id:
            return rid
    textures = await renderdoc_api._offload(controller.GetTextures)
    if not textures:
        raise ValueError("No textures available in capture")
    return textures[0].resourceId


async def _binding_name_index_for_event(session_id: str, event_id: Optional[int]) -> Dict[str, List[str]]:
    if live_state._pipeline_service is None:
        return {}
    evt = coerce._as_int(event_id, 0)
    if evt <= 0:
        try:
            evt = await _ensure_event(session_id, None)
        except Exception:
            evt = 0
    if evt <= 0:
        return {}
    try:
        bindings = await live_state._pipeline_service.get_resource_bindings(session_id, evt, live_state._session_manager)
    except Exception:
        return {}
    index: Dict[str, List[str]] = {}
    for binding in bindings:
        rid = str(getattr(binding, "resource_id", "")).strip()
        if not rid:
            continue
        label = str(getattr(binding, "resource_name", "")).strip()
        if not label:
            label = f"{str(getattr(binding, 'type', 'res')).lower()}{int(getattr(binding, 'binding', 0))}"
        for key in texture_naming._resource_id_tokens(rid):
            bucket = index.setdefault(key, [])
            if label not in bucket:
                bucket.append(label)
    return index


async def _binding_texture_candidates_for_event(
    session_id: str,
    event_id: Optional[int],
) -> List[Tuple[Any, Any, str, str, int]]:
    if live_state._pipeline_service is None:
        return []
    evt = coerce._as_int(event_id, 0)
    if evt <= 0:
        try:
            evt = await _ensure_event(session_id, None)
        except Exception:
            evt = 0
    if evt <= 0:
        return []
    try:
        bindings = await live_state._pipeline_service.get_resource_bindings(session_id, evt, live_state._session_manager)
    except Exception:
        return []
    controller = await _get_controller(session_id)
    textures = await renderdoc_api._offload(controller.GetTextures)
    by_resource_key: Dict[str, Any] = {}
    for texture in textures:
        rid = getattr(texture, "resourceId", None)
        if rid is None:
            continue
        for key in texture_naming._resource_id_tokens(rid):
            by_resource_key[key] = texture

    candidates_by_key: Dict[str, Tuple[Any, Any, str, str, int]] = {}
    for binding in bindings:
        rid_text = str(getattr(binding, "resource_id", "")).strip()
        if not rid_text:
            continue
        binding_type = str(getattr(binding, "type", "")).strip().upper()
        if binding_type not in {"UAV", "SRV"}:
            continue
        texture_desc = None
        for key in texture_naming._resource_id_tokens(rid_text):
            texture_desc = by_resource_key.get(key)
            if texture_desc is not None:
                break
        if texture_desc is None:
            continue
        resolved_rid = getattr(texture_desc, "resourceId", None)
        if resolved_rid is None:
            continue
        binding_name = str(getattr(binding, "resource_name", "")).strip()
        binding_index = coerce._as_int(getattr(binding, "binding", 0), 0)
        existing = candidates_by_key.get(str(resolved_rid))
        if existing is not None and existing[2] == "UAV":
            continue
        candidates_by_key[str(resolved_rid)] = (
            resolved_rid,
            texture_desc,
            binding_type,
            binding_name,
            binding_index,
        )
    return list(candidates_by_key.values())


async def _get_texture_descriptor(
    session_id: str,
    texture_id: Any,
    *,
    event_id: Optional[int] = None,
) -> Tuple[Any, Optional[Any]]:
    controller = await _get_controller(session_id)
    resolved = await _resolve_texture_id(session_id, texture_id, event_id=event_id)
    textures = await renderdoc_api._offload(controller.GetTextures)
    for texture in textures:
        rid = getattr(texture, "resourceId", None)
        if rid is not None and texture_naming._resource_id_matches(rid, resolved):
            return resolved, texture
    return resolved, None


def _extract_descriptor_resource_id(descriptor: Any) -> Any:
    rid = getattr(descriptor, "resourceId", None)
    if rid is not None:
        return rid
    resource = getattr(descriptor, "resource", None)
    if resource is None:
        return None
    return getattr(resource, "resourceId", resource)


async def _output_target_resource_ids(session_id: str, event_id: Optional[int]) -> List[Tuple[Any, int]]:
    controller = await _get_controller(session_id)
    evt = await _ensure_event(session_id, event_id)
    if evt <= 0:
        return []
    pipe = await renderdoc_api._offload(controller.GetPipelineState)
    outputs = await renderdoc_api._offload(pipe.GetOutputTargets)
    rd = renderdoc_api._get_rd()
    null_id = rd.ResourceId()
    out: List[Tuple[Any, int]] = []
    for idx, desc in enumerate(outputs):
        rid = _extract_descriptor_resource_id(desc)
        if rid is None:
            continue
        if rid == null_id:
            continue
        out.append((rid, idx))
    return out


async def _resolve_target_texture_for_event(
    session_id: str,
    target: Optional[Dict[str, Any]],
    *,
    event_id: Optional[int] = None,
) -> Tuple[Any, Optional[Any]]:
    parsed = target or {}
    explicit_texture = parsed.get("texture_id") or parsed.get("textureId")
    if explicit_texture is not None and str(explicit_texture).strip():
        return await _get_texture_descriptor(
            session_id,
            explicit_texture,
            event_id=event_id,
        )

    raw_rt_index = parsed.get("rt_index")
    if raw_rt_index is not None:
        outputs = await _output_target_resource_ids(session_id, event_id)
        rt_index = coerce._as_int(raw_rt_index, -1)
        if 0 <= rt_index < len(outputs):
            rid, _ = outputs[rt_index]
            return await _get_texture_descriptor(
                session_id,
                rid,
                event_id=event_id,
            )
        raise ValueError(f"Render target index out of range: {raw_rt_index}")

    return await _get_texture_descriptor(session_id, None, event_id=event_id)


async def _configure_texture_output_for_target(
    session_id: str,
    target: Optional[Dict[str, Any]],
    *,
    event_id: Optional[int] = None,
    sample_override: Optional[int] = None,
) -> Tuple[Any, Optional[Any], Any]:
    assert live_state._session_manager is not None
    rd = renderdoc_api._get_rd()
    parsed = target or {}
    rid, texture_desc = await _resolve_target_texture_for_event(
        session_id,
        parsed,
        event_id=event_id,
    )

    sub_dict = coerce._as_dict(parsed.get("subresource"), default={})
    raw_sample = sub_dict.get("sample", parsed.get("sample"))
    sample_value = sample_override if sample_override is not None else (
        coerce._as_int(raw_sample, 0) if raw_sample is not None else 0
    )

    sub = rd.Subresource()
    sub.mip = coerce._as_int(sub_dict.get("mip", parsed.get("mip")), 0)
    sub.slice = coerce._as_int(sub_dict.get("slice", parsed.get("slice")), 0)
    sub.sample = int(sample_value)

    display = rd.TextureDisplay()
    display.resourceId = rid
    display.subresource = sub
    display.typeCast = rd.CompType.Typeless
    display.overlay = rd.DebugOverlay.NoOverlay

    output = await _get_output(session_id)
    await renderdoc_api._offload(output.SetTextureDisplay, display)
    try:
        await renderdoc_api._offload(output.Display)
    except Exception:
        pass
    return rid, texture_desc, sub


async def _load_action_index(session_id: str, *, controller: Optional[Any] = None) -> Tuple[Sequence[Any], List[Any], Dict[int, Any]]:
    if controller is None:
        controller = await _get_controller(session_id)
    roots = await renderdoc_api._offload(controller.GetRootActions)
    flat, by_event = action_index._build_action_index(roots)
    return roots, flat, by_event
