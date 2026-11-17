"""rd.pipeline.* operations."""

from __future__ import annotations

from typing import Any, Dict

from rdc_tool.core.errors import CoreError
from rdc_tool.models import ShaderStage
from rdc_tool.runtime import (
    coerce,
    envelope,
    live_state,
    renderdoc_api,
    replay_access,
    shader_values,
    truth_matrix,
    visual_target,
)


@replay_access._guard_rejection
async def dispatch(action: str, args: Dict[str, Any]) -> envelope.Outcome:
    coerce._require(args, "session_id")
    session_id = str(args["session_id"])
    stage = renderdoc_api._parse_stage(args.get("stage"))
    if action in {"get_stage_state", "get_shader", "get_resource_bindings", "get_constant_buffers"}:
        try:
            renderdoc_api._rd_stage(stage)
        except CoreError as exc:
            return envelope.failure(str(exc), code=exc.code, category=exc.category,
                        details={**exc.details, "effects_attempted": False, "context_preserved": True})
    detail = args.get("detail", "full")
    sections = args.get("sections")
    from rdc_tool.core.pipeline_service import PIPELINE_SECTIONS
    fields = PIPELINE_SECTIONS
    if action == "get_state" and (detail not in {"summary", "full"} or (sections is not None and
            (not isinstance(sections, list) or any(not isinstance(k, str) or k not in fields for k in sections)))):
        return envelope.failure("Invalid pipeline detail or sections", code="validation_error", category="validation",
            details={"session_id": session_id, "failure_stage": "validate_pipeline_selection",
                     "effects_attempted": False, "context_preserved": True})
    resolved_event_id = await replay_access._ensure_event(session_id, coerce._as_int(args["event_id"]) if args.get("event_id") is not None else None)
    assert live_state._pipeline_service is not None
    snapshot_dict: Dict[str, Any] = {}
    truth_meta: Dict[str, Any] = {}
    visual_target_payload: Dict[str, Any] = {}
    if action == "get_state":
        selected = sections if sections is not None else (list(fields) if detail == "full" else
            ["shaders", "output_targets", "topology", "viewports_scissors"])
        snapshot = await live_state._pipeline_service.snapshot_pipeline(
            session_id=session_id, event_id=resolved_event_id, session_manager=live_state._session_manager, sections=selected)
        keys = {k for section in selected for k in fields[section]}
        snapshot_dict = {
            k: v for k, v in snapshot.model_dump(mode="json").items() if k in keys or k == "api"
        }
        # Model defaults for uncollected sections are not failed native reads.
        # Qualify only the requested facts that will actually be returned.
        truth_meta = truth_matrix._pipeline_truth_metadata(session_id, snapshot_dict)
        if "output_targets" in selected:
            try:
                _, _, visual_target_payload, truth_meta = await visual_target._resolve_visual_target_for_event(
                    session_id, resolved_event_id, target={"semantic": "event_output"})
            except Exception as exc:
                visual_target_payload = {"unavailable_reason": str(exc)}

        snapshot_dict.update(truth_meta)
        if "output_targets" in selected:
            snapshot_dict.update(selected_visual_target=visual_target_payload,
                                 export_target_available=bool(visual_target_payload.get("texture_id")))
        return envelope.success(resolved_event_id=int(resolved_event_id), pipeline_state=snapshot_dict)
    controller = await replay_access._get_controller(session_id)
    if resolved_event_id > 0:
        await renderdoc_api._offload(controller.SetFrameEvent, resolved_event_id, True)
    pipe = await renderdoc_api._offload(controller.GetPipelineState)
    def _pipeline_ok(**fields: Any) -> envelope.Outcome:
        return envelope.success(resolved_event_id=int(resolved_event_id), **fields)

    if action == "get_stage_state":
        rd_stage = renderdoc_api._rd_stage(stage)
        shader_id = await renderdoc_api._offload(pipe.GetShader, rd_stage)
        reflection = await renderdoc_api._offload(pipe.GetShaderReflection, rd_stage)
        resources = []
        samplers = []
        if reflection is not None:
            for ro in getattr(reflection, "readOnlyResources", []) or []:
                resources.append({"name": str(getattr(ro, "name", "")), "bindpoint": int(getattr(ro, "bindPoint", 0)), "type": "SRV"})
            for rw in getattr(reflection, "readWriteResources", []) or []:
                resources.append({"name": str(getattr(rw, "name", "")), "bindpoint": int(getattr(rw, "bindPoint", 0)), "type": "UAV"})
            for sampler in getattr(reflection, "samplers", []) or []:
                samplers.append({"name": str(getattr(sampler, "name", "")), "bindpoint": int(getattr(sampler, "bindPoint", 0)), "type": "sampler"})
        constant_blocks = await shader_values._collect_constant_buffers(
            controller,
            pipe,
            reflection,
            stage,
            shader_id,
            include_contents=False,
            max_bytes=coerce._as_int(args.get("max_bytes"), 1048576),
            flatten=False,
        )
        truth_meta = truth_matrix._pipeline_truth_metadata(session_id, {"shaders": [] if renderdoc_api._is_null_resource_id(shader_id) else [{"resource_id": str(shader_id)}]})
        if reflection is None or any(item.get("unavailable_reason") for item in constant_blocks):
            truth_meta["binding_truth_level"] = "binding_degraded"
            if not truth_meta.get("summary_degraded_reasons"):
                truth_meta["summary_degraded_reasons"] = ["reflection_partial"]
        degraded_reasons = list(truth_meta.get("summary_degraded_reasons") or [])
        unavailable_reason = "binding_degraded" if truth_meta.get("binding_truth_level") == "binding_degraded" else ""
        state = {
            "stage": stage.upper(),
            "shader_id": str(shader_id),
            "entry": str(getattr(reflection, "entryPoint", "")) if reflection else "",
            "resources": resources,
            "samplers": samplers,
            "constant_blocks": constant_blocks,
            "binding_truth_level": truth_meta.get("binding_truth_level"),
            "summary_degraded": bool(degraded_reasons),
            "summary_degraded_reasons": degraded_reasons,
            "stage_binding_quality": "degraded" if degraded_reasons else "available",
            "recommended_next_tools": ["rd.pipeline.get_constant_buffers", "rd.shader.get_bindpoint_mapping"] if degraded_reasons else [],
        }
        if unavailable_reason:
            state["unavailable_reason"] = unavailable_reason
        return _pipeline_ok(stage_state=state)
    if action == "get_vertex_buffers":
        vbs = []
        try:
            raw = await renderdoc_api._offload(pipe.GetVBuffers)
            for idx, vb in enumerate(raw):
                vbs.append(
                    {
                        "slot": idx,
                        "resource_id": str(getattr(vb, "resourceId", "")),
                        "offset": int(getattr(vb, "byteOffset", 0)),
                        "stride": int(getattr(vb, "byteStride", 0)),
                    },
                )
        except Exception as exc:
            return envelope.failure(f"Vertex buffer read failed: {exc}", code="pipeline_read_failed")
        return _pipeline_ok(vertex_buffers=vbs)
    if action == "get_index_buffer":
        index_buffer = {}
        try:
            ib = await renderdoc_api._offload(pipe.GetIBuffer)
            index_buffer = {
                "resource_id": str(getattr(ib, "resourceId", "")),
                "offset": int(getattr(ib, "byteOffset", 0)),
                "format": str(getattr(ib, "byteStride", "")),
            }
        except Exception as exc:
            return envelope.failure(f"Index buffer read failed: {exc}", code="pipeline_read_failed")
        return _pipeline_ok(index_buffer=index_buffer)
    if action == "get_resource_bindings":
        bindings = await live_state._pipeline_service.get_resource_bindings(
            session_id, resolved_event_id, live_state._session_manager,
            stage=ShaderStage(str(args["stage"]).lower()) if args.get("stage") else None)
        binding_type = args.get("type")
        if binding_type is not None and binding_type not in {"SRV", "UAV", "CBV", "Sampler"}:
            return envelope.failure("Invalid binding type", code="validation_error")
        return _pipeline_ok(bindings=[b.model_dump(mode="json") for b in bindings if binding_type is None or b.type.upper() == str(binding_type).upper()])
    if action == "get_constant_buffers":
        rd_stage = renderdoc_api._rd_stage(stage)
        shader_id = await renderdoc_api._offload(pipe.GetShader, rd_stage)
        reflection = await renderdoc_api._offload(pipe.GetShaderReflection, rd_stage)
        constant_buffers = await shader_values._collect_constant_buffers(
            controller,
            pipe,
            reflection,
            stage,
            shader_id,
            slot=coerce._as_int(args.get("slot"), 0) if args.get("slot") is not None else None,
            array_index=coerce._as_int(args.get("array_index"), 0),
            include_contents=coerce._as_bool(args.get("include_contents"), False),
            max_bytes=coerce._as_int(args.get("max_bytes"), 1048576),
            flatten=coerce._as_bool(args.get("flatten"), True),
        )
        return _pipeline_ok(constant_buffers=constant_buffers)
    if action == "get_shader":
        rd_stage = renderdoc_api._rd_stage(stage)
        shader_id = await renderdoc_api._offload(pipe.GetShader, rd_stage)
        if renderdoc_api._is_null_resource_id(shader_id):
            return envelope.failure(
                f"No shader bound at stage {stage.upper()} for event {int(resolved_event_id)}",
                code="shader_not_bound",
                category="runtime",
                details={"session_id": session_id, "resolved_event_id": int(resolved_event_id), "stage": stage.upper()},
            )
        reflection = await renderdoc_api._offload(pipe.GetShaderReflection, rd_stage)
        shader = {
            "stage": stage.upper(),
            "shader_id": str(shader_id),
            "entry": str(getattr(reflection, "entryPoint", "")) if reflection else "",
            "encoding": str(getattr(reflection, "encoding", "")) if reflection else "",
        }
        return _pipeline_ok(shader=shader)
    return envelope.failure(f"Unsupported pipeline action: {action}", code="runtime_error")
