"""Shader variables and constant buffer values."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from rdc_tool.core.errors import CoreError
from rdc_tool.runtime import coerce, renderdoc_api


def _shader_value_payload(value: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    if value is None:
        return payload
    for field_name in ("f16v", "f32v", "f64v", "s8v", "s16v", "s32v", "s64v", "u8v", "u16v", "u32v", "u64v"):
        if not hasattr(value, field_name):
            continue
        try:
            items = [item for item in list(getattr(value, field_name) or [])]
        except Exception:
            continue
        if items:
            payload[field_name] = items
    return payload


def _shader_variable_type_name(variable: Any) -> str:
    type_obj = getattr(variable, "type", None)
    descriptor = getattr(type_obj, "descriptor", None)
    for attr_name in ("name", "type", "baseType"):
        candidate = getattr(descriptor, attr_name, None) if descriptor is not None else getattr(type_obj, attr_name, None)
        if candidate is not None and str(candidate):
            return str(candidate)
    if descriptor is not None:
        return str(descriptor)
    if type_obj is not None:
        return str(type_obj)
    return ""


def _shader_variable_layout_payload(variable: Any) -> Dict[str, Any]:
    return {
        "name": str(getattr(variable, "name", "") or ""),
        "type": _shader_variable_type_name(variable),
        "rows": int(getattr(variable, "rows", 0) or 0),
        "columns": int(getattr(variable, "columns", 0) or 0),
        "members": [
            _shader_variable_layout_payload(member)
            for member in (getattr(variable, "members", None) or [])
        ],
    }


def _simplify_shader_value(payload: Dict[str, Any]) -> Any:
    for field_name in ("f32v", "f64v", "s32v", "u32v", "s16v", "u16v", "s8v", "u8v", "s64v", "u64v", "f16v"):
        values = payload.get(field_name)
        if isinstance(values, list) and values:
            return values[0] if len(values) == 1 else values
    return payload


def _shader_variable_payload(variable: Any) -> Dict[str, Any]:
    payload = _shader_variable_layout_payload(variable)
    value_payload = _shader_value_payload(getattr(variable, "value", None))
    if value_payload:
        payload["value"] = value_payload
    if payload.get("members"):
        payload["members"] = [
            _shader_variable_payload(member)
            for member in (getattr(variable, "members", None) or [])
        ]
    return payload


def _flatten_shader_variable_values(variable: Any, prefix: str, output: Dict[str, Any]) -> None:
    current_name = str(getattr(variable, "name", "") or "")
    current_path = current_name if not prefix else (f"{prefix}.{current_name}" if current_name else prefix)
    members = list(getattr(variable, "members", None) or [])
    if members:
        for member in members:
            _flatten_shader_variable_values(member, current_path, output)
        return
    value_payload = _shader_value_payload(getattr(variable, "value", None))
    if current_path and value_payload:
        output[current_path] = _simplify_shader_value(value_payload)


def _pipeline_object_for_cbuffer(pipe: Any, stage_name: str) -> Any:
    rd = renderdoc_api._get_rd()
    if str(stage_name or "").lower() == "cs" and hasattr(pipe, "GetComputePipelineObject"):
        try:
            return pipe.GetComputePipelineObject()
        except Exception:
            pass
    if hasattr(pipe, "GetGraphicsPipelineObject"):
        try:
            return pipe.GetGraphicsPipelineObject()
        except Exception:
            pass
    if hasattr(pipe, "GetComputePipelineObject"):
        try:
            return pipe.GetComputePipelineObject()
        except Exception:
            pass
    return rd.ResourceId()


def _constant_buffer_binding_info(bound_block: Any, block: Any, block_index: int) -> Dict[str, Any]:
    descriptor = getattr(bound_block, "descriptor", None)
    resource = getattr(descriptor, "resource", None)
    return {
        "resource": resource,
        "resource_id": str(resource) if resource is not None and not renderdoc_api._is_null_resource_id(resource) else "",
        "offset": coerce._as_int(getattr(descriptor, "byteOffset", 0), 0),
        "size": coerce._as_int(getattr(descriptor, "byteSize", 0), 0),
        "slot": int(block_index),
        "set_or_space": coerce._as_int(getattr(block, "fixedBindSetOrSpace", 0), 0),
    }


def _constant_buffer_byte_window(block_bytes: int, binding_bytes: int, max_bytes: int) -> Dict[str, Any]:
    if max_bytes < 0:
        raise CoreError(code="invalid_max_bytes", category="validation", message="max_bytes must be non-negative; zero means no per-block byte cap")
    block_bytes = max(0, int(block_bytes))
    binding_bytes = max(0, int(binding_bytes))
    required = block_bytes or binding_bytes
    available = binding_bytes or required
    permitted = min(available, max_bytes) if max_bytes > 0 else available
    status = "unknown_extent" if required <= 0 else "binding_limited" if available < required else "budget_limited" if permitted < required else "complete_range_permitted"
    return {"required_bytes": required, "required_source": "reflection" if block_bytes else "binding" if binding_bytes else "unknown",
            "binding_bytes": binding_bytes, "byte_budget": int(max_bytes), "permitted_bytes": permitted,
            "complete_range_permitted": status == "complete_range_permitted", "status": status}


async def _collect_constant_buffers(
    controller: Any,
    pipe: Any,
    reflection: Any,
    stage_name: str,
    shader_id: Any,
    *,
    slot: Optional[int] = None,
    array_index: int = 0,
    include_contents: bool = False,
    max_bytes: int = 1048576,
    flatten: bool = True,
) -> List[Dict[str, Any]]:
    if reflection is None:
        return []
    block_defs = list(getattr(reflection, "constantBlocks", None) or [])
    if not block_defs:
        return []

    rd = renderdoc_api._get_rd()
    rd_stage = renderdoc_api._rd_stage(stage_name)
    entry_point = str(getattr(reflection, "entryPoint", "") or "main")
    pipeline_obj = _pipeline_object_for_cbuffer(pipe, stage_name)
    requested_slot = None if slot is None else int(slot)
    results: List[Dict[str, Any]] = []

    for block_index, block in enumerate(block_defs):
        block_slot = int(block_index)
        if requested_slot is not None and int(block_slot) != requested_slot:
            continue

        bound_block = None
        if hasattr(pipe, "GetConstantBlock"):
            try:
                bound_block = await renderdoc_api._offload(pipe.GetConstantBlock, rd_stage, int(block_index), int(array_index))
            except Exception:
                bound_block = None

        binding = _constant_buffer_binding_info(bound_block, block, block_index)
        vars_layout = [
            _shader_variable_layout_payload(variable)
            for variable in (getattr(block, "variables", None) or [])
        ]
        entry: Dict[str, Any] = {
            "stage": str(stage_name or "").upper(),
            "slot": int(binding.get("slot", block_slot) or 0),
            "array_index": int(array_index),
            "set_or_space": int(binding.get("set_or_space", 0) or 0),
            "resource_id": str(binding.get("resource_id") or ""),
            "offset": int(binding.get("offset", 0) or 0),
            "size": int(binding.get("size", 0) or 0),
            "block_index": int(block_index),
            "block_name": str(getattr(block, "name", "") or ""),
            "byte_size": int(getattr(block, "byteSize", 0) or 0),
            "vars": vars_layout,
        }

        if include_contents:
            coverage = _constant_buffer_byte_window(entry["byte_size"], entry["size"], int(max_bytes))
            entry.update(input_coverage=coverage, decode_input_bytes=0, decode_status="unavailable",
                         contents=[], flattened_contents={} if flatten else None)
            if not coverage["complete_range_permitted"]:
                entry["decode_error"] = "Complete reflected input range is unavailable: " + coverage["status"]
            elif getattr(block, "bufferBacked", None) is True and not entry["resource_id"]:
                entry["decode_error"] = "Buffer-backed constant block has no bound resource"
            elif not hasattr(controller, "GetCBufferVariableContents"):
                entry["decode_error"] = "Native constant buffer decoding is unavailable"
            else:
                resource = binding.get("resource")
                if resource is None:
                    resource = rd.ResourceId()
                requested_length = int(coverage["permitted_bytes"])
                entry["decode_input_bytes"] = requested_length
                try:
                    raw_contents = list(await renderdoc_api._offload(
                        controller.GetCBufferVariableContents, pipeline_obj, shader_id, rd_stage, entry_point,
                        int(block_index), resource, int(binding.get("offset", 0) or 0), requested_length,
                    ) or [])
                    serialized_contents = [_shader_variable_payload(variable) for variable in raw_contents]
                    if not serialized_contents:
                        raise ValueError("Native constant buffer decoder returned no variables")
                    if flatten:
                        flattened: Dict[str, Any] = {}
                        for variable in raw_contents:
                            _flatten_shader_variable_values(variable, "", flattened)
                        entry["flattened_contents"] = flattened
                    entry["contents"] = serialized_contents
                    entry["decode_status"] = "decoded"
                except Exception as exc:
                    entry["contents"] = []
                    entry["flattened_contents"] = {} if flatten else None
                    entry["decode_error"] = str(exc)

        results.append(entry)

    return results
