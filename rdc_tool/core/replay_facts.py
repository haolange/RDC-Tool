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
