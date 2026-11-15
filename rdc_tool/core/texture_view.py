"""Resolve the typed view of a resource at the current replay event."""

from __future__ import annotations

from typing import Any


def bound_texture_view_format(controller: Any, resource_id: Any, rd: Any) -> Any | None:
    """Return a unique bound typed format; ambiguous or absent bindings stay unknown."""
    pipe = controller.GetPipelineState()
    descriptors = list(pipe.GetOutputTargets())
    for name in ("Vertex", "Hull", "Domain", "Geometry", "Pixel", "Compute"):
        stage = getattr(rd.ShaderStage, name)
        for item in (*pipe.GetReadOnlyResources(stage), *pipe.GetReadWriteResources(stage)):
            descriptors.append(item.descriptor)
    formats = {}
    for descriptor in descriptors:
        if str(getattr(descriptor, "resource", "")) != str(resource_id):
            continue
        fmt = getattr(descriptor, "format", None)
        if fmt is None:
            continue
        name = str(fmt.Name()).upper()
        if name and "TYPELESS" not in name and name != "UNKNOWN":
            formats[name] = fmt
    return next(iter(formats.values())) if len(formats) == 1 else None
