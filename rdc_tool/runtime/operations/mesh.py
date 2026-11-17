"""rd.mesh.* operations."""

from __future__ import annotations

import struct
from typing import Any, Dict

from rdc_tool.runtime import coerce, envelope, live_state, renderdoc_api, replay_access, texture_export
from rdc_tool.runtime.operations import buffer as buffer_ops


@replay_access._guard_rejection
async def dispatch(action: str, args: Dict[str, Any]) -> envelope.Outcome:
    if action == "get_drawcall_mesh_config":
        coerce._require(args, "session_id")
        session_id = str(args["session_id"])
        event_id = await replay_access._ensure_event(session_id, coerce._as_int(args["event_id"]) if args.get("event_id") is not None else None)
        snap = await live_state._pipeline_service.snapshot_pipeline(session_id, event_id, live_state._session_manager)
        from rdc_tool.core.mesh_data import vertex_input
        controller = await replay_access._get_controller(session_id)
        try:
            inputs = await renderdoc_api._offload(vertex_input, controller, renderdoc_api._get_rd(), event_id, coerce._as_int(args.get("instance"), 0), coerce._as_int(args.get("max_vertices"), 128))
        except ValueError as exc:
            return envelope.failure(str(exc), code="mesh_input_failed")
        return envelope.success(mesh_config={"event_id": event_id, "topology": snap.topology, "bindings": [b.model_dump(mode="json") for b in snap.bindings], "vertex_input": inputs})
    if action == "get_post_transform_data":
        stage = str(args.get("stage", "")).lower()
        from rdc_tool.core.mesh_data import read_post_transform_window, validate_post_transform_window
        window_requested = args.get("index_count") is not None or args.get("first_index") is not None
        if window_requested:
            try:
                if stage != "vs":
                    raise ValueError("Index windows currently require VS output")
                validate_post_transform_window(args.get("first_index", 0), args.get("index_count"), args.get("max_vertices", 0))
            except ValueError as exc:
                return envelope.failure(str(exc), code="validation_error", category="validation",
                            details={"session_id": str(args.get("session_id", "")), "failure_stage": "validate_mesh_window",
                                     "effects_attempted": False, "context_preserved": True})
        if stage not in {"vs", "gs"}:
            return envelope.failure("stage must be vs or gs", code="validation_error", category="validation")
        coerce._require(args, "session_id")
        session_id = str(args["session_id"])
        controller = await replay_access._get_controller(session_id)
        event_id = await replay_access._ensure_event(
            session_id,
            coerce._as_int(args.get("event_id"), 0) if args.get("event_id") is not None else None,
        )
        rd = renderdoc_api._get_rd()
        rd_stage = rd.MeshDataStage.VSOut if stage == "vs" else rd.MeshDataStage.GSOut
        instance = coerce._as_int(args.get("instance"), 0)
        view_index = coerce._as_int(args.get("view_index", 0), 0)
        max_vertices = coerce._as_int(args.get("max_vertices"), 0)
        try:
            mesh = await renderdoc_api._offload(controller.GetPostVSData, instance, view_index, rd_stage)
        except Exception as exc:
            return envelope.failure(
                f"Failed to fetch post-transform mesh data: {exc}",
                code="mesh_post_transform_failed",
                category="runtime",
                details={"session_id": session_id, "resolved_event_id": int(event_id), "stage": str(stage)},
            )
        vertex_resource_id = getattr(mesh, "vertexResourceId", None)
        if renderdoc_api._is_null_resource_id(vertex_resource_id):
            mesh_format = texture_export._mesh_format_payload(mesh)
            if stage == "gs":
                if not hasattr(controller, "GetPipelineState"):
                    gs_shader_id = None
                else:
                    pipeline_state = await renderdoc_api._offload(controller.GetPipelineState)
                    gs_shader_id = await renderdoc_api._offload(pipeline_state.GetShader, renderdoc_api._rd_stage("gs"))
                if renderdoc_api._is_null_resource_id(gs_shader_id):
                    return envelope.success(
                        mesh_data={
                            "mesh_format": mesh_format,
                            "vertex_rows": [],
                            "vertex_count": 0,
                            "truncated": False,
                            "stage": "GS",
                            "stage_bound": False,
                            "availability_reason": f"No shader bound at stage GS for event {int(event_id)}",
                        },
                        resolved_event_id=int(event_id),
                    )
            return envelope.failure(
                "Post-transform mesh data is unavailable for the requested draw",
                code="mesh_post_transform_unavailable",
                category="runtime",
                details={
                    "session_id": session_id,
                    "resolved_event_id": int(event_id),
                    "stage": str(stage),
                    "stage_name": "GS" if stage == "gs" else "VS",
                    "mesh_format": mesh_format,
                },
            )
        vertex_offset = int(getattr(mesh, "vertexByteOffset", 0) or 0)
        vertex_size = int(getattr(mesh, "vertexByteSize", 0) or 0)
        vertex_stride = int(getattr(mesh, "vertexByteStride", 0) or 0)
        if vertex_stride <= 0 or vertex_size < 0:
            return envelope.failure("Invalid post-transform vertex layout", code="mesh_post_transform_unavailable")
        unbounded = vertex_size == (1 << 64) - 1
        read_size = (max_vertices * vertex_stride if max_vertices > 0 else 0) if unbounded else (min(vertex_size, max_vertices * vertex_stride) if max_vertices > 0 and vertex_size > 0 else vertex_size)
        window_data = None
        if window_requested:
            try:
                window_data = await renderdoc_api._offload(read_post_transform_window, controller, mesh,
                    first_index=args.get("first_index", 0), index_count=args["index_count"],
                    max_vertices=max_vertices, indexed=not renderdoc_api._is_null_resource_id(getattr(mesh, "indexResourceId", None)))
                raw = window_data["raw"]
            except (ValueError, TypeError, AttributeError) as exc:
                return envelope.failure(str(exc), code="mesh_post_transform_window_failed", category="runtime",
                            details={"session_id": session_id, "resolved_event_id": int(event_id),
                                     "failure_stage": "read_mesh_window", "effects_attempted": True})
        else:
            raw = await renderdoc_api._offload(controller.GetBufferData, vertex_resource_id, vertex_offset, read_size)
            if read_size > 0 and not unbounded and len(raw) != read_size:
                return envelope.failure("Incomplete post-transform vertex readback", code="mesh_post_transform_failed")
        mesh_format = texture_export._mesh_format_payload(mesh)
        rows = texture_export._mesh_vertex_rows(raw, stride=vertex_stride, max_vertices=max_vertices)
        from rdc_tool.core.replay_facts import mesh_attributes, post_transform_outputs
        attributes = mesh_attributes(rd, mesh, raw, vertex_stride, rows)
        outputs = {"status": "unsupported", "reason": "No shader reflection available"}
        if hasattr(controller, "GetPipelineState"):
            pipe = await renderdoc_api._offload(controller.GetPipelineState)
            reflection = await renderdoc_api._offload(pipe.GetShaderReflection, renderdoc_api._rd_stage(stage))
            api = await renderdoc_api._offload(controller.GetAPIProperties)
            outputs = post_transform_outputs(reflection, "D3D11" if api.pipelineType == rd.GraphicsAPI.D3D11 else "D3D12" if api.pipelineType == rd.GraphicsAPI.D3D12 else "Vulkan" if stage == "vs" and api.pipelineType == rd.GraphicsAPI.Vulkan else "unverified", vertex_stride, raw, rows)
        if window_data is not None:
            for row, vertex, offset in zip(rows, window_data["vertex_indices"], window_data["vertex_byte_offsets"]):
                row["vertex_index"] = vertex
                row["source_byte_offset"] = offset
        truncated = (None if unbounded and max_vertices > 0 and len(rows) == max_vertices else bool(max_vertices > 0 and not unbounded and vertex_size // vertex_stride > len(rows)))
        if window_data is not None:
            window = window_data["window"]
            truncated = window["first_index"] > 0 or window["first_index"] + window["index_count"] < window["total_indices"] or not window["vertex_mapping_complete"]
        return envelope.success(
            mesh_data={
                "mesh_format": mesh_format,
                "vertex_rows": rows,
                **({"index_window": window_data["window"]} if window_data is not None else {}),
                "attributes": attributes, "outputs": outputs, "source": "post_transform",
                "vertex_count": len(rows),
                "truncated": truncated,
                "stage": stage.upper(), "stage_bound": True, "view_index": view_index,
            },
            resolved_event_id=int(event_id),
        )
    if action == "decode_index_data":
        coerce._require(args, "session_id", "index_buffer_id")
        format_name = str(args.get("format", "u32")).lower()
        if format_name not in {"u16", "u32"}:
            return envelope.failure("Index format must be u16 or u32", code="validation_error")
        fmt = "<I" if format_name == "u32" else "<H"
        size = 4 if fmt == "<I" else 2
        count = coerce._as_int(args.get("index_count"), 128)
        data_result = await buffer_ops.dispatch(
            "get_data",
            {
                "session_id": args["session_id"],
                "buffer_id": args["index_buffer_id"],
                "offset": args.get("index_offset", 0),
                "size": count * size,
                "as_base64": True,
            },
        )
        if not data_result.ok:
            return data_result
        import base64

        raw = base64.b64decode(data_result.data.get("base64", ""))
        indices = []
        for i in range(0, len(raw), size):
            if i + size > len(raw):
                break
            indices.append(struct.unpack(fmt, raw[i : i + size])[0])
        return envelope.success(indices=indices)
    return envelope.failure(f"Unsupported mesh action: {action}", code="runtime_error")
