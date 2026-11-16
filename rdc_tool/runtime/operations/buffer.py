"""rd.buffer.* operations."""

from __future__ import annotations

import base64
import struct
from pathlib import Path
from typing import Any, Dict

from rdc_tool.runtime import (
    artifact_payloads,
    coerce,
    envelope,
    live_state,
    renderdoc_api,
    replay_access,
    texture_export,
)


async def dispatch(action: str, args: Dict[str, Any]) -> envelope.Outcome:
    coerce._require(args, "session_id", "buffer_id")
    session_id = str(args["session_id"])
    buffer_id = args["buffer_id"]
    controller = await replay_access._get_controller(session_id)
    try:
        rid = await replay_access._resolve_resource_id(session_id, buffer_id)
    except replay_access.ResourceLookupMiss as exc:
        return envelope.failure(str(exc), code="resource_not_found", category="validation",
                    details={"session_id": session_id, "failure_stage": "resolve_buffer",
                             "effects_attempted": False, "context_preserved": True})
    offset = coerce._as_int(args.get("offset"), 0)
    size = args.get("size")
    if size is None:
        size = 0
    size = coerce._as_int(size, 0)
    if action == "get_data":
        descriptions = await renderdoc_api._offload(controller.GetBuffers)
        descriptor = next((item for item in descriptions if item.resourceId == rid), None)
        if descriptor is None:
            return envelope.failure("Buffer not found", code="resource_not_found", category="validation",
                        details={"session_id": session_id, "failure_stage": "resolve_buffer",
                                 "effects_attempted": False, "context_preserved": True})
        expected = int(descriptor.length)-offset if size == 0 else size
        if offset < 0 or expected < 0 or offset+expected > int(descriptor.length):
            return envelope.failure("Buffer range exceeds resource", code="validation_error", category="validation",
                        details={"session_id": session_id, "failure_stage": "validate_buffer_range",
                                 "effects_attempted": False, "context_preserved": True})
        inline = coerce._as_bool(args.get("as_base64"), False)
        if inline and expected > 1048576:
            return envelope.failure("Inline buffer limit is 1 MiB; request a smaller range or export", code="output_budget_exceeded", category="validation",
                        details={"session_id": session_id, "failure_stage": "validate_buffer_read_budget",
                                 "effects_attempted": False, "context_preserved": True})
        async def read_buffer(event):
            data = await renderdoc_api._offload(controller.GetBufferData, rid, offset, expected) if expected else b""
            if len(data) != expected:
                raise RuntimeError(f"Incomplete buffer read: expected {expected}, received {len(data)}")
            return data
        data, metadata = await texture_export._read_at_capture_state(session_id, rid, args, read_buffer)
        result: Dict[str, Any] = {"byte_size": len(data), "buffer_id": str(rid), **metadata}
        if inline:
            result["base64"] = base64.b64encode(data).decode("ascii")
        if args.get("output_path"):
            out = Path(str(args["output_path"]))
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(data)
            result["artifact_path"] = str(out)
        elif not inline:
            assert live_state._artifact_store is not None
            artifact = await live_state._artifact_store.store(data, mime="application/octet-stream", suffix=".bin")
            result["artifact_path"] = artifact_payloads._artifact_path(artifact)
        return envelope.success(**result)

    data = await renderdoc_api._offload(controller.GetBufferData, rid, offset, size)

    if action == "search_pattern":
        pattern_value = args.get("pattern")
        if pattern_value is None:
            return envelope.failure("Missing required parameter(s): pattern", code="runtime_error")
        if isinstance(pattern_value, str):
            p = pattern_value.strip().replace(" ", "")
            if p.startswith("0x"):
                p = p[2:]
            pattern = bytes.fromhex(p)
        elif isinstance(pattern_value, list):
            pattern = bytes(int(v) & 0xFF for v in pattern_value)
        else:
            return envelope.failure("Unsupported pattern type", code="runtime_error")
        max_results = coerce._as_int(args.get("max_results"), 256)
        matches = []
        start = 0
        while True:
            idx = data.find(pattern, start)
            if idx < 0:
                break
            matches.append({"offset": offset + idx})
            if len(matches) >= max_results:
                break
            start = idx + 1
        return envelope.success(matches=matches)

    if action == "get_structured_data":
        layout = coerce._as_dict(args.get("layout"), default={})
        fields = coerce._as_list(layout.get("fields"), default=[])
        stride = coerce._as_int(layout.get("stride"), 0)
        if stride <= 0:
            return envelope.failure("Structured buffer layout requires positive stride", code="validation_error")
        offset_items = 0
        max_elements = coerce._as_int(args.get("max_elements"), 256)
        count = coerce._as_int(args.get("count"), max_elements)
        total = min(count, max_elements)
        type_map = {
            "u32": ("<I", 4),
            "i32": ("<i", 4),
            "f32": ("<f", 4),
            "u16": ("<H", 2),
            "i16": ("<h", 2),
            "u8": ("<B", 1),
            "i8": ("<b", 1),
        }
        elements = []
        for i in range(total):
            base = offset_items + i * stride
            if base + stride > len(data):
                break
            item: Dict[str, Any] = {"index": i}
            for field_def in fields:
                fd = coerce._as_dict(field_def)
                name = str(fd.get("name", "field"))
                ftype = str(fd.get("type", "u32")).lower()
                if ftype not in type_map:
                    return envelope.failure(f"Unsupported structured field type: {ftype}", code="validation_error")
                fmt, size_bytes = type_map[ftype]
                field_offset = coerce._as_int(fd.get("offset"), 0)
                field_count = coerce._as_int(fd.get("count"), 1)
                if field_offset < 0 or field_count < 1 or field_offset + size_bytes * field_count > stride:
                    return envelope.failure("Structured field exceeds stride", code="validation_error")
                start = base + field_offset
                values = [struct.unpack_from(fmt, data, start + j * size_bytes)[0] for j in range(field_count)]
                item[name] = values[0] if field_count == 1 else values
            elements.append(item)
        return envelope.success(elements=elements)

    return envelope.failure(f"Unsupported buffer action: {action}", code="runtime_error")
