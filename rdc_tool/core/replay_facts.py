"""Native replay fact projections; no dependency or cross-capture conclusions."""
from __future__ import annotations
import hashlib
import math
import struct
from typing import Any


def shader_content_hash(reflection: Any) -> str | None:
    raw = getattr(reflection, "rawBytes", None)
    return hashlib.sha256(bytes(raw)).hexdigest() if raw else None


def usage_access(rd: Any, usage: Any) -> dict[str, Any]:
    # Native enum identity, never substring classification or a resource-id guess.
    read = {"VertexBuffer", "IndexBuffer", "Indirect", "InputTarget", "CopySrc", "ResolveSrc"}
    read.update(f"{stage}_{kind}" for stage in ("VS", "HS", "DS", "GS", "PS", "CS", "TS", "MS", "All") for kind in ("Constants", "Resource"))
    rw = {f"{stage}_RWResource" for stage in ("VS", "HS", "DS", "GS", "PS", "CS", "TS", "MS", "All")} | {"GenMips", "Copy", "Resolve"}
    write = {"StreamOut", "Clear", "CopyDst", "ResolveDst", "CPUWrite"}
    table = {**{name: (True, False) for name in read}, **{name: (True, True) for name in rw}, **{name: (False, True) for name in write},
             "ColorTarget": (None, True), "DepthStencilTarget": (None, True), "Unused": (False, False), "Barrier": (None, None), "Discard": (False, None)}
    for name, (reads, writes) in table.items():
        native = getattr(rd.ResourceUsage, name, None)
        if native is not None and usage == native:
            return {"usage_name": name, "is_read": reads, "is_write": writes, "binding_only_observable": False}
    return {"usage_name": None, "is_read": None, "is_write": None, "binding_only_observable": False}


def mesh_attributes(rd: Any, mesh: Any, raw: bytes, stride: int, rows: list[dict[str, Any]]) -> dict[str, Any]:
    fmt = getattr(mesh, "format", None)
    count = int(getattr(fmt, "compCount", 0))
    position_supported = (getattr(fmt, "compType", None) is not None and getattr(fmt, "compType", None) == getattr(getattr(rd, "CompType", None), "Float", None)
                          and int(getattr(fmt, "compByteWidth", 0)) == 4 and 1 <= count <= 4 and stride >= count * 4)
    for row in rows:
        values = list(struct.unpack_from("<" + "f" * count, raw, row["vertex_index"] * stride)) if position_supported else None
        row["position"] = values if values is not None and all(math.isfinite(v) for v in values) else None
    return {"position": {"status": "present" if position_supported and all(row["position"] is not None for row in rows) else "unsupported", "components": count if position_supported else None},
            "normal": {"status": "unsupported", "reason": "No proven post-transform attribute layout"},
            "uv": {"status": "unsupported", "reason": "No proven post-transform attribute layout"}}


def post_transform_outputs(reflection: Any, api: Any, stride: int, raw: bytes, rows: list[dict[str, Any]]) -> dict[str, Any]:
    """D3D11/12 stream-out packs signature fields, moving SV_Position first."""
    if str(api) == "Vulkan":
        return _vulkan_vs_outputs(reflection, stride, raw, rows)
    if str(api) not in {"D3D11", "D3D12"}:
        return {"status": "unsupported", "reason": "Post-transform signature packing is not established for this API"}
    sig = list(getattr(reflection, "outputSignature", []))
    if not sig or any(int(s.stream) != 0 or getattr(s.varType, "name", str(s.varType)) != "Float" for s in sig):
        return {"status": "unsupported", "reason": "Only stream-zero float signatures have a proven layout"}
    positions = [s for s in sig if getattr(s.systemValue, "name", str(s.systemValue)) == "Position"]
    if len(positions) != 1:
        return {"status": "unsupported", "reason": "No unique position signature"}
    sig = positions + [s for s in sig if s not in positions]
    sizes = [4 if getattr(s.systemValue, "name", str(s.systemValue)) == "Position" else int(s.compCount) for s in sig]
    if any(n < 1 or n > 4 for n in sizes) or sum(sizes)*4 != stride:
        return {"status": "unsupported", "reason": "Signature layout does not match native vertex stride"}
    layout, offset = [], 0
    for s, count in zip(sig, sizes):
        name = str(s.semanticIdxName)
        layout.append({"semantic": name, "byte_offset": offset, "components": count})
        for row in rows:
            values = list(struct.unpack_from("<"+"f"*count, raw, row["vertex_index"]*stride+offset))
            row.setdefault("outputs", {})[name] = values if all(math.isfinite(v) for v in values) else None
        offset += count*4
    return {"status": "present", "source": "post_transform", "layout": layout}


def _vulkan_vs_outputs(reflection: Any, stride: int, raw: bytes, rows: list[dict[str, Any]]) -> dict[str, Any]:
    # RenderDoc Vulkan ConvertToMeshOutputCompute writes reflection-order fields
    # with std430 vector alignment and a 16-byte final stride (vk_postvs.cpp).
    # This layout is VS-only; GS/XFB and other APIs must not enter this decoder.
    sig = list(getattr(reflection, "outputSignature", []))
    names = [getattr(s.systemValue, "name", str(s.systemValue)) for s in sig]
    if not sig or names[0] != "Position" or names.count("Position") != 1 or int(sig[0].compCount) != 4:
        return {"status": "unsupported", "reason": "Vulkan VS requires one leading float4 Position signature"}
    if any(int(s.stream) != 0 or getattr(s.varType, "name", str(s.varType)) != "Float"
           or getattr(s, "perPrimitiveRate", False) for s in sig):
        return {"status": "unsupported", "reason": "Only per-vertex stream-zero float32 Vulkan VS outputs have a proven decoder"}
    layout, offset, keys = [], 0, set()
    for field, builtin in zip(sig, names):
        count = int(field.compCount)
        if not 1 <= count <= 4:
            return {"status": "unsupported", "reason": "Invalid Vulkan VS signature component count"}
        location = getattr(field, "regIndex", None) if builtin == "Undefined" else None
        if builtin == "Undefined" and (not isinstance(location, int) or not 0 <= location < 0xffffffff):
            return {"status": "unsupported", "reason": "Vulkan VS varying has no explicit native location"}
        key = f"location:{location}" if builtin == "Undefined" else f"builtin:{builtin}"
        if not builtin or key in keys:
            return {"status": "unsupported", "reason": "Vulkan VS output identities are ambiguous"}
        keys.add(key)
        alignment = 16 if count >= 3 else count * 4
        offset = (offset + alignment - 1) // alignment * alignment
        layout.append({"key": key, "location": location, "system_value": builtin,
                       "variable_name": str(getattr(field, "varName", "")) or None,
                       "component_mask": getattr(field, "regChannelMask", None),
                       "scalar_type": "float32", "byte_offset": offset, "components": count})
        offset += count * 4
    if (offset + 15) // 16 * 16 != stride:
        return {"status": "unsupported", "reason": "Vulkan VS std430 signature layout does not match native vertex stride"}
    if len(raw) % stride or any(not isinstance(row.get("vertex_index"), int)
                                or row["vertex_index"] < 0 or (row["vertex_index"] + 1) * stride > len(raw)
                                for row in rows):
        raise ValueError("Incomplete post-transform vertex readback for Vulkan VS signature")
    for row in rows:
        values = {}
        for field in layout:
            data = list(struct.unpack_from("<" + "f" * field["components"], raw,
                                           row["vertex_index"] * stride + field["byte_offset"]))
            values[field["key"]] = data if all(math.isfinite(v) for v in data) else None
        row["outputs"] = values
    return {"status": "present", "source": "post_transform", "api": "Vulkan", "stage": "VS", "packing": "vulkan-vs-std430", "layout": layout}
