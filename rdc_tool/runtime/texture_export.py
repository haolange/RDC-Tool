"""Texture, buffer and mesh export and capture-state reads."""

from __future__ import annotations

import math
import shutil
import struct
from pathlib import Path
from typing import Any, Dict, List, Tuple

import numpy as np

from rdc_tool.core.errors import CoreError
from rdc_tool.runtime import (
    artifact_payloads,
    coerce,
    context_records,
    envelope,
    live_state,
    renderdoc_api,
    replay_access,
    texture_naming,
)


def _texture_export_channels(channels_value: Any) -> Dict[str, bool]:
    if isinstance(channels_value, str):
        selected = {token for token in channels_value.lower() if token in {"r", "g", "b", "a"}}
        if not selected:
            selected = {"r", "g", "b", "a"}
        return {token: token in selected for token in ("r", "g", "b", "a")}
    if isinstance(channels_value, dict):
        return {
            "r": coerce._as_bool(channels_value.get("r"), True),
            "g": coerce._as_bool(channels_value.get("g"), True),
            "b": coerce._as_bool(channels_value.get("b"), True),
            "a": coerce._as_bool(channels_value.get("a"), True),
        }
    return {"r": True, "g": True, "b": True, "a": True}


def _texture_export_view_config(args: Dict[str, Any], *, subresource: Dict[str, int]) -> Dict[str, Any]:
    remap = coerce._as_dict(args.get("remap"), default={})
    view_config: Dict[str, Any] = {
        "channels": _texture_export_channels(args.get("channels")),
        "flip_y": coerce._as_bool(args.get("flip_y"), False),
        "subresource": dict(subresource),
    }
    if remap.get("black_point") is not None:
        view_config["range_min"] = coerce._as_float(remap.get("black_point"), 0.0)
    if remap.get("white_point") is not None:
        view_config["range_max"] = coerce._as_float(remap.get("white_point"), 1.0)
    if remap.get("hdr_multiplier") is not None:
        view_config["hdr_multiplier"] = coerce._as_float(remap.get("hdr_multiplier"), 4.0)
    if remap.get("hdr_clamp") is not None:
        view_config["hdr"] = coerce._as_bool(remap.get("hdr_clamp"), False)
    return view_config


def _texture_export_uses_display_controls(args: Dict[str, Any]) -> bool:
    remap = coerce._as_dict(args.get("remap"), default={})
    return args.get("channels") is not None or args.get("flip_y") is not None or bool(remap)


async def _render_texture_export(
    *,
    session_id: str,
    event_id: int,
    texture_id: Any,
    output_path: str,
    file_format: str,
    subresource: Dict[str, int],
    view_config: Dict[str, Any],
) -> Dict[str, Any]:
    assert live_state._render_service is not None
    artifact_ref, meta = await live_state._render_service.render_event(
        session_id=session_id,
        event_id=event_id,
        session_manager=live_state._session_manager,
        artifact_store=live_state._artifact_store,
        source_config={"source": "texture", "texture_id": texture_id, "subresource": dict(subresource)},
        view_config={**view_config, "overlay": "none"},
        output_format=file_format,
    )
    artifact_path = artifact_payloads._artifact_path(artifact_ref)
    export_meta = dict(meta)
    export_meta["requested_remap"] = dict(coerce._as_dict(view_config.get("requested_remap"), default={}))
    actual_format = texture_naming._normalize_export_format(export_meta.get("format") or file_format)
    requested_format = texture_naming._normalize_export_format(file_format)
    if actual_format != requested_format:
        return {
            "format_error": {
                "requested_format": requested_format,
                "actual_format": actual_format,
                "artifact_path": artifact_path,
                "reason": "encoder_fell_back_to_different_format",
            },
            "artifact_path": artifact_path,
            "saved_path": "",
            "meta": export_meta,
        }
    out_path = Path(str(output_path))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(artifact_path, out_path)
    return {
        "artifact_path": artifact_path,
        "saved_path": str(out_path),
        "meta": export_meta,
    }


async def _save_texture_export(
    *,
    session_id: str,
    event_id: int,
    texture_id: Any,
    output_path: str,
    file_format: str,
    subresource: Dict[str, int],
) -> Dict[str, Any]:
    assert live_state._render_service is not None
    artifact_ref, meta, saved_path = await live_state._render_service.save_texture_file(
        session_id=session_id,
        event_id=event_id,
        texture_id=texture_id,
        session_manager=live_state._session_manager,
        artifact_store=live_state._artifact_store,
        output_format=file_format,
        output_path=output_path,
        subresource=subresource,
    )
    artifact_path = artifact_payloads._artifact_path(artifact_ref)
    requested_format = texture_naming._normalize_export_format(file_format)
    actual_format = texture_naming._normalize_export_format((meta or {}).get("format") or file_format)
    if actual_format != requested_format:
        return {
            "format_error": {
                "requested_format": requested_format,
                "actual_format": actual_format,
                "artifact_path": artifact_path,
                "reason": "encoder_fell_back_to_different_format",
            },
            "artifact_path": artifact_path,
            "saved_path": "",
            "meta": meta,
        }
    return {
        "artifact_path": artifact_path,
        "saved_path": saved_path or str(output_path),
        "meta": meta,
    }


async def _export_texture_file(args: Dict[str, Any]) -> envelope.Outcome:
    coerce._require(args, "session_id", "texture_id", "output_path")
    session_id = str(args["session_id"])
    requested_formats = texture_naming._parse_requested_formats(args.get("file_format", "png"))
    uses_display_controls = _texture_export_uses_display_controls(args)
    if uses_display_controls and any(fmt not in {"png", "jpg", "exr", "hdr", "auto", "smart", "all", "*"}
                                     for fmt in requested_formats):
        return envelope.failure("Display-mapped texture export only supports png, jpg, exr, hdr when channels/remap/flip_y are requested",
                                code="texture_export_format_unsupported", category="validation",
                                details={"session_id": session_id, "failure_stage": "validate_format",
                                         "effects_attempted": False, "context_preserved": True})
    event_id = coerce._as_int(args.get("event_id"), replay_access._active_event(session_id))
    if event_id <= 0:
        event_id = await replay_access._ensure_event(session_id, None)
    texture_id, texture_desc = await replay_access._get_texture_descriptor(
        session_id,
        args.get("texture_id"),
        event_id=event_id,
    )
    binding_index = await replay_access._binding_name_index_for_event(session_id, event_id)
    name_info = texture_naming._compose_texture_name_info(
        texture_id,
        resource_name=str(getattr(texture_desc, "name", "")) if texture_desc is not None else "",
        binding_names=binding_index.get(str(texture_id), []),
        alias_name=live_state._runtime.aliases.get(str(texture_id), ""),
    )
    recommended_formats = texture_naming._recommend_formats_for_texture(texture_desc, name_info=name_info, for_screenshot=False)
    requested_format_value = args.get("file_format")
    if requested_format_value is None:
        requested_format_value = "png"
    requested_formats = texture_naming._parse_requested_formats(requested_format_value)
    selected_formats = texture_naming._select_export_formats(
        requested_formats,
        recommended_formats=recommended_formats,
    )
    subresource = coerce._as_dict(args.get("subresource"), default={})
    normalized_subresource = {
        "mip": coerce._as_int(subresource.get("mip"), 0),
        "slice": coerce._as_int(subresource.get("slice"), 0),
        "sample": coerce._as_int(subresource.get("sample"), 0),
    }
    width = int(getattr(texture_desc, "width", 0)) if texture_desc is not None else 0
    height = int(getattr(texture_desc, "height", 0)) if texture_desc is not None else 0
    dim_token = f"_{width}x{height}" if width > 0 and height > 0 else ""
    base_name_stem = texture_naming._safe_name_token(f"ev{event_id}_{name_info['name_stem']}{dim_token}")
    base_output_path = str(args["output_path"])
    multi_export = len(selected_formats) > 1
    view_config = _texture_export_view_config(args, subresource=normalized_subresource)
    view_config["requested_remap"] = coerce._as_dict(args.get("remap"), default={})
    exports: List[Dict[str, Any]] = []
    for export_format in selected_formats:
        resolved_output_path = texture_naming._resolve_export_output_path(
            base_output_path,
            name_stem=base_name_stem,
            file_format=export_format,
            multi=multi_export,
        )
        if uses_display_controls:
            if export_format not in {"png", "jpg", "exr", "hdr"}:
                return envelope.failure(
                    "Display-mapped texture export only supports png, jpg, exr, hdr when channels/remap/flip_y are requested", code="runtime_error",
                )
            export_item = await _render_texture_export(
                session_id=session_id,
                event_id=event_id,
                texture_id=texture_id,
                output_path=resolved_output_path,
                file_format=export_format,
                subresource=normalized_subresource,
                view_config=view_config,
            )
            if export_item.get("format_error"):
                details = dict(export_item.get("format_error") or {})
                details.update(
                    {
                        "requested_formats": requested_formats,
                        "selected_formats": selected_formats,
                        "supported_formats": sorted({"png", "jpg", "exr", "hdr"}),
                        "recommended_formats": recommended_formats,
                        "downgrade_allowed": False,
                    }
                )
                return envelope.failure(
                    f"Requested texture format '{details.get('requested_format')}' was encoded as '{details.get('actual_format')}'",
                    code="format_encoder_unavailable",
                    category="runtime",
                    details=details,
                )
            exports.append(export_item)
            continue
        export_item = await _save_texture_export(
            session_id=session_id,
            event_id=event_id,
            texture_id=texture_id,
            output_path=resolved_output_path,
            file_format=export_format,
            subresource=normalized_subresource,
        )
        if export_item.get("format_error"):
            details = dict(export_item.get("format_error") or {})
            details.update(
                {
                    "requested_formats": requested_formats,
                    "selected_formats": selected_formats,
                    "supported_formats": sorted({"png", "jpg", "exr", "hdr", "dds"}),
                    "recommended_formats": recommended_formats,
                    "downgrade_allowed": False,
                }
            )
            return envelope.failure(
                f"Requested texture format '{details.get('requested_format')}' was encoded as '{details.get('actual_format')}'",
                code="format_encoder_unavailable",
                category="runtime",
                details=details,
            )
        exports.append(export_item)
    if not multi_export:
        single = exports[0]
        return envelope.success(
            artifact_path=single["artifact_path"],
            saved_path=single["saved_path"],
            meta=single["meta"],
            selected_formats=selected_formats,
            requested_formats=requested_formats,
            recommended_formats=recommended_formats,
            name_info=name_info,
            texture_format=texture_naming._texture_format_name(texture_desc),
        )
    return envelope.success(
        exports=exports,
        saved_paths=[item["saved_path"] for item in exports],
        selected_formats=selected_formats,
        requested_formats=requested_formats,
        recommended_formats=recommended_formats,
        name_info=name_info,
        texture_format=texture_naming._texture_format_name(texture_desc),
    )


async def _export_buffer_file(args: Dict[str, Any]) -> envelope.Outcome:
    coerce._require(args, "session_id", "buffer_id", "output_path")
    session_id = str(args["session_id"])
    controller = await replay_access._get_controller(session_id)
    rid = await replay_access._resolve_resource_id(session_id, args["buffer_id"])
    offset = coerce._as_int(args.get("offset"), 0)
    size = args.get("size")
    if size is None:
        size = 0
    data = await renderdoc_api._offload(controller.GetBufferData, rid, offset, coerce._as_int(size, 0))
    out = Path(str(args["output_path"]))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(data)
    return envelope.success(saved_path=str(out), byte_size=len(data))


async def _export_mesh_file(args: Dict[str, Any]) -> envelope.Outcome:
    coerce._require(args, "session_id", "output_path")
    space = args.get("space", "postvs")
    include_attributes = coerce._as_bool(args.get("include_attributes"), False)
    if args.get("format", "obj") != "obj" or space not in {"postvs", "vs_input"} or (space == "postvs" and include_attributes):
        return envelope.failure("Post-VS OBJ supports positions only; attributes require explicit VS input space", code="mesh_export_unsupported")
    session_id = str(args["session_id"])
    event_id = await replay_access._ensure_event(session_id, coerce._as_int(args["event_id"]) if args.get("event_id") is not None else None)
    controller = await replay_access._get_controller(session_id)
    if space == "vs_input":
        from rdc_tool.core.mesh_data import MeshReadError, input_obj, vertex_input
        try:
            data = await renderdoc_api._offload(vertex_input, controller, renderdoc_api._get_rd(), event_id, 0, 0)
            content, primitive_count = input_obj(data, include_attributes)
        except MeshReadError as exc:
            return envelope.failure(str(exc), code="mesh_input_failed")
        except ValueError as exc:
            return envelope.failure(str(exc), code="mesh_export_unsupported")
        out = Path(str(args["output_path"]))
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(content, encoding="utf-8")
        return envelope.success(saved_path=str(out), export_format="obj", space=space, include_attributes=include_attributes,
                   resolved_event_id=event_id, vertex_count=data["vertex_count"], primitive_count=primitive_count,
                   attributes={key: ("present" if key == "position" or include_attributes else "not_requested") for key in ("position", "normal", "uv")})
    mesh = await renderdoc_api._offload(controller.GetPostVSData, 0, 0, renderdoc_api._get_rd().MeshDataStage.VSOut)
    if renderdoc_api._is_null_resource_id(mesh.vertexResourceId):
        return envelope.failure("No post-transform vertex data", code="mesh_post_transform_unavailable")
    fmt = mesh.format
    if int(fmt.compByteWidth) != 4 or int(fmt.compCount) < 3 or int(fmt.compType) != int(renderdoc_api._get_rd().CompType.Float):
        return envelope.failure("OBJ export requires 32-bit float post-transform positions", code="mesh_export_unsupported")
    stride = int(mesh.vertexByteStride)
    if stride < int(fmt.compCount) * 4:
        return envelope.failure("Invalid post-transform vertex stride", code="mesh_post_transform_unavailable")
    raw = await renderdoc_api._offload(controller.GetBufferData, mesh.vertexResourceId, int(mesh.vertexByteOffset), int(mesh.vertexByteSize))
    if not raw or len(raw) % stride:
        return envelope.failure("Incomplete post-transform vertex readback", code="mesh_post_transform_failed")
    positions = [struct.unpack_from("<fff", raw, offset) for offset in range(0, len(raw), stride)]
    if any(not math.isfinite(component) for position in positions for component in position):
        return envelope.failure("Post-transform positions contain non-finite values", code="mesh_export_unsupported")
    if not renderdoc_api._is_null_resource_id(mesh.indexResourceId):
        index_stride = int(mesh.indexByteStride)
        if index_stride not in {2, 4}:
            return envelope.failure("Unsupported mesh index width", code="mesh_export_unsupported")
        index_raw = await renderdoc_api._offload(controller.GetBufferData, mesh.indexResourceId, int(mesh.indexByteOffset), int(mesh.numIndices) * index_stride)
        if len(index_raw) != int(mesh.numIndices) * index_stride:
            return envelope.failure("Incomplete post-transform index readback", code="mesh_post_transform_failed")
        indices = [item[0] + int(getattr(mesh, "baseVertex", 0)) for item in struct.iter_unpack("<H" if index_stride == 2 else "<I", index_raw)]
    else:
        indices = list(range(len(positions)))
    if any(index < 0 or index >= len(positions) for index in indices):
        return envelope.failure("Post-transform index outside vertex data", code="mesh_post_transform_failed")
    topology = int(mesh.topology)
    rd_topology = renderdoc_api._get_rd().Topology
    if topology == int(rd_topology.TriangleList):
        primitives = [("f", indices[i:i+3]) for i in range(0, len(indices)-2, 3)]
    elif topology == int(rd_topology.TriangleStrip):
        primitives = [("f", [indices[i+(i%2)], indices[i+1-(i%2)], indices[i+2]]) for i in range(len(indices)-2)]
    elif topology == int(rd_topology.LineList):
        primitives = [("l", indices[i:i+2]) for i in range(0, len(indices)-1, 2)]
    elif topology == int(rd_topology.PointList):
        primitives = [("p", [index]) for index in indices]
    else:
        return envelope.failure(f"Unsupported OBJ topology: {mesh.topology}", code="mesh_export_unsupported")
    lines = [f"# RDC-Tool post-VS positions, event {event_id}"]
    lines.extend("v " + " ".join(format(value, ".9g") for value in position) for position in positions)
    lines.extend(kind + " " + " ".join(str(index+1) for index in primitive) for kind, primitive in primitives)
    out = Path(str(args["output_path"]))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return envelope.success(saved_path=str(out), export_format="obj", space="postvs", include_attributes=False,
               resolved_event_id=event_id, vertex_count=len(positions), primitive_count=len(primitives),
               attributes={"position": "present", "normal": "unsupported", "uv": "unsupported"})


async def _read_at_capture_state(session_id: str, resource_id: Any, args: Dict[str, Any], reader: Any) -> Tuple[Any, Dict[str, Any]]:
    from rdc_tool.core.replay_read import (
        InitialContentsUnavailable,
        ReplayRestoreError,
        initial_provenance,
        preserving_event,
    )
    controller = await replay_access._get_controller(session_id)
    original_event = replay_access._active_event(session_id)
    state = args.get("state", "current")
    if state not in {"current", "capture_initial"} or (state == "capture_initial" and args.get("event_id") is not None):
        raise CoreError(code="validation_error", message="capture_initial and event_id are mutually exclusive", category="validation")
    requested = int(args.get("event_id", original_event)) if state == "current" else 0
    if args.get("event_id") is not None:
        _, _, events = await replay_access._load_action_index(session_id, controller=controller)
        replay_access._require_action_event(session_id, requested, events)
    provenance = None
    if state == "capture_initial":
        try:
            provenance = await renderdoc_api._offload(initial_provenance, controller, resource_id,
                                        args.get("subresource", {}) if "texture_id" in args else None)
        except InitialContentsUnavailable as exc:
            raise CoreError(code="initial_contents_unavailable", message=str(exc), category="runtime") from exc
    async def read():
        await renderdoc_api._offload(controller.SetFrameEvent, requested, True)
        return await reader(requested)
    try:
        result = await preserving_event(controller, original_event, read)
    except ReplayRestoreError as exc:
        context_records._update_context_session_record(session_id, recovery_status="requires_restart", last_error=str(exc))
        raise CoreError(code="replay_restore_failed", message=str(exc), category="runtime",
                        details={"session_id": session_id, "restored": False}) from exc
    return result, {"state": state, "resolved_event_id": requested, "restored_event_id": original_event,
                    "replay_state_restored": True, "initial_provenance": provenance}


def _resource_format_payload(fmt: Any) -> Dict[str, Any]:
    if fmt is None:
        return {}
    payload: Dict[str, Any] = {}
    for attr in ("type", "compCount", "compByteWidth", "compType", "special", "bgraOrder", "srgbCorrected"):
        if not hasattr(fmt, attr):
            continue
        value = getattr(fmt, attr)
        if isinstance(value, bool):
            payload[attr] = bool(value)
        else:
            try:
                payload[attr] = int(value)
            except Exception:
                payload[attr] = str(value)
    payload["repr"] = str(fmt)
    return payload


def _mesh_format_payload(mesh: Any) -> Dict[str, Any]:
    return {
        "vertex_resource_id": str(getattr(mesh, "vertexResourceId", "") or ""),
        "vertex_byte_offset": int(getattr(mesh, "vertexByteOffset", 0) or 0),
        "vertex_byte_size": int(getattr(mesh, "vertexByteSize", 0) or 0),
        "vertex_byte_stride": int(getattr(mesh, "vertexByteStride", 0) or 0),
        "index_resource_id": str(getattr(mesh, "indexResourceId", "") or ""),
        "index_byte_offset": int(getattr(mesh, "indexByteOffset", 0) or 0),
        "index_byte_size": int(getattr(mesh, "indexByteSize", 0) or 0),
        "index_byte_stride": int(getattr(mesh, "indexByteStride", 0) or 0),
        "num_indices": int(getattr(mesh, "numIndices", 0) or 0),
        "topology": str(getattr(mesh, "topology", "") or ""),
        "topology_name": getattr(getattr(mesh, "topology", None), "name", None),
        "base_vertex": int(mesh.baseVertex) if hasattr(mesh, "baseVertex") else None,
        "allow_restart": getattr(mesh, "allowRestart", None),
        "restart_index": getattr(mesh, "restartIndex", None),
        "status": str(getattr(mesh, "status", "") or ""),
        "format": _resource_format_payload(getattr(mesh, "format", None)),
    }


def _mesh_vertex_rows(raw: bytes, *, stride: int, max_vertices: int) -> List[Dict[str, Any]]:
    if stride <= 0:
        return []
    rows: List[Dict[str, Any]] = []
    total_vertices = len(raw) // stride
    count = total_vertices if max_vertices <= 0 else min(total_vertices, max_vertices)
    for vertex_index in range(count):
        start = vertex_index * stride
        end = start + stride
        chunk = raw[start:end]
        rows.append(
            {
                "vertex_index": vertex_index,
                "bytes_hex": chunk.hex(),
            }
        )
    return rows


def _sampled_texture_stats(arr: Any, source_stats: Dict[str, Any], stride: int) -> Dict[str, Any]:
    finite = arr[np.isfinite(arr)]
    stats = {
        **source_stats, "shape": list(arr.shape), "dtype": str(arr.dtype), "stride": stride,
        "nan_count": int(np.isnan(arr).sum()), "inf_count": int(np.isinf(arr).sum()),
        "min": float(finite.min()) if finite.size else None,
        "max": float(finite.max()) if finite.size else None,
        "mean": float(finite.mean()) if finite.size else None,
        "channels": {},
    }
    if arr.ndim == 3:
        for index, name in enumerate("rgba"[:arr.shape[2]]):
            channel = arr[..., index]
            valid = channel[np.isfinite(channel)]
            stats["channels"][name] = {
                "min": float(valid.min()) if valid.size else None,
                "max": float(valid.max()) if valid.size else None,
                "mean": float(valid.mean()) if valid.size else None,
                "nan_count": int(np.isnan(channel).sum()), "inf_count": int(np.isinf(channel).sum()),
            }
    return stats
