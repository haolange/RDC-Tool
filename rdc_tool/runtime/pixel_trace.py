"""Pixel history reads and their payloads."""

from __future__ import annotations

import asyncio
import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

from rdc_tool import timeout_policy
from rdc_tool.core import replay_facts
from rdc_tool.core.errors import CoreError
from rdc_tool.core.texture_view import bound_texture_view_format
from rdc_tool.runtime import context_records, envelope, live_state, renderdoc_api, replay_access, truth_matrix


def _subresource_to_dict(sub: Any) -> Dict[str, int]:
    return {
        "mip": int(getattr(sub, "mip", 0)),
        "slice": int(getattr(sub, "slice", 0)),
        "sample": int(getattr(sub, "sample", 0)),
    }


async def _refresh_pixel_context(session_id: str, x: int, y: int) -> None:
    output = await replay_access._get_output(session_id)
    try:
        await renderdoc_api._offload(output.SetPixelContextLocation, x, y)
    except Exception:
        pass
    try:
        await renderdoc_api._offload(output.Display)
    except Exception:
        pass


async def _pixel_history_raw(controller: Any, resource_id: Any, x: int, y: int, subresource: Any,
                             type_cast: Any = None) -> List[Any]:
    rd = renderdoc_api._get_rd()
    if type_cast is not None:
        return list(await renderdoc_api._offload(controller.PixelHistory, resource_id, x, y, subresource, type_cast) or [])
    try:
        history_raw = await renderdoc_api._offload(
            controller.PixelHistory,
            resource_id,
            x,
            y,
            subresource,
            rd.CompType.Typeless,
        )
    except Exception:
        history_raw = await renderdoc_api._offload(
            controller.PixelHistory,
            resource_id,
            x,
            y,
            subresource,
        )
    return list(history_raw or [])


def _pixel_history_timeout_message(timeout_s: float) -> str:
    return f"PixelHistory timed out after {timeout_s:.1f}s"


class PixelHistoryInputAttachmentConflict(Exception):
    def __init__(self, usage_event_id: int, image_usage_flags: int) -> None:
        self.usage_event_id = usage_event_id
        self.image_usage_flags = image_usage_flags
        super().__init__("Vulkan image lacks input-attachment usage")


async def _pixel_history_conflict_error(session_id: str, original_event: int,
                                        conflict: PixelHistoryInputAttachmentConflict) -> envelope.Outcome:
    details = {"context_id": live_state._runtime_context_id(), "session_id": session_id,
               "failure_stage": "validate_input_attachment", "usage_event_id": conflict.usage_event_id,
               "image_usage_flags": conflict.image_usage_flags}
    try:
        if original_event <= 0 or await replay_access._ensure_event(session_id, original_event) != original_event \
                or replay_access._active_event(session_id) != original_event:
            raise RuntimeError("Original replay event was not restored")
    except Exception as exc:
        return envelope.failure(f"Pixel History unavailable; replay restoration failed: {exc}",
                    code="pixel_history_unavailable_restore_failed", category="runtime",
                    details={**details, "replay_state_restored": False})
    return envelope.failure(
        "Pixel History unavailable: a Vulkan image is used as both input and output attachment "
        "without VK_IMAGE_USAGE_INPUT_ATTACHMENT_BIT. Read the region before and after candidate "
        "events and confirm it with draw coverage instead.",
        code="pixel_history_unsupported_input_attachment", category="capability",
        details={**details, "replay_state_restored": True, "restored_event_id": original_event},
    )


async def _pixel_history_raw_with_timeout(
    controller: Any,
    resource_id: Any,
    x: int,
    y: int,
    subresource: Any,
    *,
    timeout_s: Optional[float] = None,
    type_cast: Any = None,
) -> List[Any]:
    conflict = await renderdoc_api._offload(replay_facts.pixel_history_input_attachment_conflict, renderdoc_api._get_rd(), controller, resource_id)
    if conflict is not None:
        raise PixelHistoryInputAttachmentConflict(*conflict)
    effective_timeout = float(timeout_policy.PIXEL_HISTORY_TIMEOUT_S if timeout_s is None else timeout_s)
    return await asyncio.wait_for(
        (_pixel_history_raw(controller, resource_id, x, y, subresource, type_cast) if type_cast is not None
         else _pixel_history_raw(controller, resource_id, x, y, subresource)),
        timeout=effective_timeout,
    )


async def _pixel_history_view(controller: Any, resource_id: Any, texture_desc: Any) -> Tuple[Any, bool]:
    fmt = getattr(texture_desc, "format", None)
    name = getattr(fmt, "Name", None)
    if not callable(name) or "TYPELESS" not in str(name()).upper():
        return None, False
    view = await renderdoc_api._offload(bound_texture_view_format, controller, resource_id, renderdoc_api._get_rd())
    return view, view is None


def _pixel_history_color_type(texture_desc: Any) -> str:
    component = getattr(getattr(texture_desc, "format", None), "compType", None)
    comp_types = getattr(renderdoc_api._get_rd(), "CompType", None)
    if component is None or comp_types is None:
        return "unknown"
    for name, value_type in (
        ("Float", "float"), ("UNorm", "float"), ("SNorm", "float"),
        ("UScaled", "float"), ("SScaled", "float"), ("Depth", "float"),
        ("UNormSRGB", "float"), ("UInt", "uint"), ("SInt", "int"),
    ):
        if component == getattr(comp_types, name, None):
            return value_type
    return "unknown"


def _pixel_history_modification_payload(value: Any, color_type: str) -> Dict[str, Any]:
    if value is None:
        return {"valid": False, "unavailable_reason": "native_value_missing"}
    if not callable(getattr(value, "IsValid", None)) or not value.IsValid():
        return {"valid": False, "unavailable_reason": "native_value_invalid"}

    color = getattr(value, "col", None)
    channel = {"float": "floatValue", "uint": "uintValue", "int": "intValue"}.get(color_type)
    rgba = None
    non_finite_channels: List[int] = []
    if color is not None and channel is not None:
        raw = getattr(color, channel, None)
        if raw is not None:
            rgba = []
            for index in range(4):
                number = float(raw[index]) if color_type == "float" else int(raw[index])
                if color_type == "float" and not math.isfinite(number):
                    non_finite_channels.append(index)
                    rgba.append(None)
                else:
                    rgba.append(number)

    depth = float(getattr(value, "depth", -1.0))
    stencil = int(getattr(value, "stencil", -1))
    return {
        "valid": True,
        "color_type": color_type,
        "color_rgba": rgba,
        "non_finite_channels": non_finite_channels,
        "depth": depth if math.isfinite(depth) and depth != -1.0 else None,
        "stencil": stencil if stencil >= 0 else None,
        "stencil_status": "available" if stencil >= 0 else (
            "undetermined" if stencil == -2 else "not_in_use"
        ),
    }


def _pixel_history_item_payload(item: Any, color_type: str = "unknown") -> Dict[str, Any]:
    passed = bool(item.Passed()) if hasattr(item, "Passed") else False
    flags: List[str] = []
    if passed:
        flags.append("passed")
    if bool(getattr(item, "depthTestFailed", False)):
        flags.append("depth_test_failed")
    if bool(getattr(item, "stencilTestFailed", False)):
        flags.append("stencil_test_failed")
    if bool(getattr(item, "shaderDiscarded", False)):
        flags.append("shader_discarded")
    if bool(getattr(item, "unboundPS", False)):
        flags.append("unbound_ps")
    if bool(getattr(item, "sampleMasked", False)):
        flags.append("sample_masked")
    if bool(getattr(item, "scissorClipped", False)):
        flags.append("scissor_clipped")
    if bool(getattr(item, "viewClipped", False)):
        flags.append("view_clipped")
    if bool(getattr(item, "backfaceCulled", False)):
        flags.append("backface_culled")
    if bool(getattr(item, "directShaderWrite", False)):
        flags.append("direct_shader_write")
    frag_index = int(getattr(item, "fragIndex", -1))
    pre_mod = _pixel_history_modification_payload(getattr(item, "preMod", None), color_type)
    if frag_index > 0:
        pre_mod = {"valid": False, "unavailable_reason": "non_first_fragment"}
    return {
        "event_id": int(getattr(item, "eventId", 0)),
        "primitive_id": int(getattr(item, "primitiveID", -1)),
        "frag_index": frag_index,
        "pre_mod": pre_mod,
        "shader_out": _pixel_history_modification_payload(getattr(item, "shaderOut", None), color_type),
        "post_mod": _pixel_history_modification_payload(getattr(item, "postMod", None), color_type),
        "passed": passed,
        "depth_test_failed": bool(getattr(item, "depthTestFailed", False)),
        "stencil_test_failed": bool(getattr(item, "stencilTestFailed", False)),
        "shader_discarded": bool(getattr(item, "shaderDiscarded", False)),
        "unbound_ps": bool(getattr(item, "unboundPS", False)),
        "sample_masked": bool(getattr(item, "sampleMasked", False)),
        "scissor_clipped": bool(getattr(item, "scissorClipped", False)),
        "view_clipped": bool(getattr(item, "viewClipped", False)),
        "backface_culled": bool(getattr(item, "backfaceCulled", False)),
        "direct_shader_write": bool(getattr(item, "directShaderWrite", False)),
        "flags": ",".join(flags) if flags else "unknown",
    }


async def _pixel_history_writer_bindings(
    session_id: str, event_id: int, history: Sequence[Dict[str, Any]], controller: Any,
) -> List[Dict[str, Any]]:
    """Read binding evidence at history events, then restore the requested event."""
    from rdc_tool.core.replay_read import ReplayRestoreError, preserving_event

    writer_events = list(dict.fromkeys(int(item["event_id"]) for item in history))
    if not writer_events:
        return []

    async def inspect() -> List[Dict[str, Any]]:
        bindings: List[Dict[str, Any]] = []
        for writer_event in writer_events:
            try:
                if writer_event <= 0:
                    raise ValueError("Pixel history did not provide a valid writer event")
                if live_state._pipeline_service is None:
                    raise RuntimeError("Pipeline service is unavailable")
                snapshot = await live_state._pipeline_service.snapshot_pipeline(
                    session_id=session_id, event_id=writer_event, session_manager=live_state._session_manager,
                    sections=["shaders", "output_targets"],
                )
                state = snapshot.model_dump(mode="json")
                truth = truth_matrix._pipeline_truth_metadata(session_id, state)
                bindings.append({
                    "event_id": writer_event,
                    "shaders": state["shaders"],
                    "render_targets": state["render_targets"],
                    "binding_truth_level": truth["binding_truth_level"],
                    "summary_degraded_reasons": truth["summary_degraded_reasons"],
                })
            except Exception as exc:
                bindings.append({
                    "event_id": writer_event,
                    "binding_truth_level": "binding_degraded",
                    "error": {"code": "history_event_binding_unavailable", "message": str(exc)},
                })
        return bindings

    try:
        return await preserving_event(controller, event_id, inspect)
    except ReplayRestoreError as exc:
        context_records._update_context_session_record(session_id, recovery_status="requires_restart", last_error=str(exc))
        raise CoreError(code="replay_restore_failed", message=str(exc), category="runtime",
                        details={"session_id": session_id, "restored": False}) from exc


def _pixel_history_summary(items: Sequence[Dict[str, Any]], event_id: int) -> Dict[str, Any]:
    matched = [item for item in items if int(item.get("event_id") or 0) == int(event_id)]
    passed = [item for item in matched if bool(item.get("passed"))]
    viable = [
        item
        for item in passed
        if not bool(item.get("shader_discarded")) and not bool(item.get("unbound_ps"))
    ]
    primitive_ids = [
        int(item.get("primitive_id"))
        for item in viable
        if isinstance(item.get("primitive_id"), int) and int(item.get("primitive_id")) >= 0
    ]
    return {
        "hit_count": len(items),
        "matched_event_hit_count": len(matched),
        "passed_hit_count": len(passed),
        "viable_hit_count": len(viable),
        "primitive_ids": primitive_ids,
    }
