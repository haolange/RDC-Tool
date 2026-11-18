"""Shader debug handles and state payloads."""

from __future__ import annotations

from typing import Any, Dict, Optional

from rdc_tool.core.errors import CoreError
from rdc_tool.runtime import live_state, shader_values


def _coarse_pixel_debug_qualification(rasterizer: Any) -> Optional[Dict[str, Any]]:
    rate = [int(component) for component in rasterizer.baseShadingRate]
    if max(rate) <= 1:
        return None
    return {
        "status": "unverified",
        "requested_base_shading_rate": rate,
        "effective_shading_rate": None,
        "reason": (
            "D3D12 requests coarse shading. Native pixel-debug inputs can be pixel-centred and "
            "the debug output can differ from the fragment recorded by Pixel History. "
            "The effective rate and actual invocation position are not established; compare "
            "the completed debug output with Pixel History before attributing trace values."
        ),
    }


def _require_shader_debug_handle(session_id: str, debug_id: str) -> live_state.ShaderDebugHandle:
    handle = live_state._runtime.shader_debugs.get(debug_id)
    reason = "unknown_handle" if handle is None else "session_mismatch" if handle.session_id != session_id else ""
    if reason:
        raise CoreError(
            code="shader_debug_handle_invalid", category="validation",
            message="Shader debugger handle is unavailable for the owning replay session; historical handles cannot be reused after replay recovery.",
            details={"session_id": session_id, "failure_stage": "validate_debug_handle",
                     "failure_reason": reason, "effects_attempted": False, "context_preserved": True},
        )
    return handle


def _bounded_debug_variable(variable: Dict[str, Any], depth: int) -> Dict[str, Any]:
    result = dict(variable)
    members = variable.get("members") or []
    result["members"] = [_bounded_debug_variable(member, depth - 1) for member in members] if depth > 0 else []
    if members and depth == 0:
        result["members_truncated"] = True
    return result


def _shader_debug_state_payload(handle: live_state.ShaderDebugHandle, detail_level: str = "summary") -> Dict[str, Any]:
    state = handle.current_state
    instruction = getattr(state, "nextInstruction", None) if state is not None else None
    payload = {"pc": int(state.stepIndex) if state is not None else 0,
               "has_native_state": state is not None,
               "next_instruction": int(instruction) if instruction is not None else None,
               "source_location": None}
    # Native instInfo is a sparse sorted interval map, not an instruction-indexed array.
    infos = getattr(handle.trace, "instInfo", None) or []
    if instruction is not None:
        low, high = 0, len(infos)
        while low < high:
            middle = (low + high) // 2
            if int(infos[middle].instruction) <= int(instruction):
                low = middle + 1
            else:
                high = middle
        if low:
            info = infos[low - 1]
            line = info.lineInfo
            file_index = int(getattr(line, "fileIndex", -1))
            def positive(name: str) -> Optional[int]:
                value = int(getattr(line, name, 0))
                return value if value > 0 else None
            payload["source_location"] = {
                "mapping_instruction": int(info.instruction),
                "mapping_end_instruction_exclusive": int(infos[low].instruction) if low < len(infos) else None,
                "disassembly_line": positive("disassemblyLine"),
                "disassembly_source": "renderdoc_native_debug_disassembly",
                "file_index": file_index if file_index >= 0 else None,
                "line_start": positive("lineStart") if file_index >= 0 else None,
                "line_end": positive("lineEnd") if file_index >= 0 else None,
                "column_start": positive("colStart") if file_index >= 0 else None,
                "column_end": positive("colEnd") if file_index >= 0 else None,
            }
    if detail_level == "full":
        variables = list(_shader_debug_variable_snapshot(handle).values())
        stack = list(getattr(state, "callstack", None) or []) if state is not None else []
        payload.update(variables=[_bounded_debug_variable(value, 2) for value in variables[:64]],
                       variable_count=len(variables), variables_truncated=len(variables) > 64,
                       variable_member_depth=2,
                       callstack=[str(name) for name in stack[:64]],
                       callstack_count=len(stack), callstack_truncated=len(stack) > 64)
    return payload


def _shader_debug_variable_snapshot(handle: live_state.ShaderDebugHandle) -> Dict[str, Dict[str, Any]]:
    """Merge the immutable native trace inputs with the current mutable variables."""
    inputs = {str(variable.name): {**shader_values._shader_variable_payload(variable), "variable_origin": "trace_input"}
              for variable in handle.trace.inputs if variable.name}
    return {**inputs, **handle.variables}
