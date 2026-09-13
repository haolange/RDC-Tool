"""Temporary replay reads with recorded initial-data provenance and restoration."""

from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable


class InitialContentsUnavailable(ValueError):
    pass


class ReplayRestoreError(RuntimeError):
    pass


def initial_provenance(controller: Any, resource_id: Any, subresource: dict[str, Any] | None = None) -> dict[str, Any]:
    descriptions = {str(item.resourceId): item for item in controller.GetResources()}
    resource = descriptions.get(str(resource_id))
    if resource is None:
        raise InitialContentsUnavailable("Resource description is not recorded")
    structured = controller.GetStructuredFile()
    if structured is None:
        raise InitialContentsUnavailable("Capture initial-data provenance is unavailable")
    events = []
    pending = list(controller.GetRootActions())
    while pending:
        action = pending.pop()
        events.extend(int(event.chunkIndex) for event in action.events)
        pending.extend(action.children)
    if not events:
        raise InitialContentsUnavailable("Capture frame boundary is unavailable")
    frame_start = min(events)
    creation_chunks = list(resource.initialisationChunks)
    if not creation_chunks or min(creation_chunks) >= frame_start:
        raise InitialContentsUnavailable("Resource did not exist before captured frame commands")
    candidates = [resource]
    # Vulkan buffers hold initial bytes in their bound memory allocation. Device
    # and other parents cannot qualify without a matching recorded contents blob.
    if getattr(resource.type, "name", str(resource.type)) == "Buffer":
        candidates.extend(descriptions[str(parent)] for parent in resource.parentResources
                          if str(parent) in descriptions)
    for candidate in candidates:
        for index in candidate.initialisationChunks:
            if index < 0 or index >= len(structured.chunks):
                raise InitialContentsUnavailable("Initialization chunk reference is invalid")
            chunk = structured.chunks[index]
            if str(chunk.name) != "Internal::Initial Contents":
                continue
            identity = chunk.FindChild("id")
            size = chunk.FindChild("ContentsSize")
            contents = chunk.FindChild("Contents")
            sparse = chunk.FindChild("IsSparse")
            if (identity is not None and identity.AsResourceId() == candidate.resourceId
                    and size is not None and size.AsInt() > 0 and contents is not None
                    and (sparse is None or not sparse.AsBool())):
                return {"source_resource_id": str(candidate.resourceId), "chunk_indices": [int(index)],
                        "scope": "recorded_capture_initial_contents"}
            # D3D12 serializes resource bytes and an explicit subresource coverage
            # set. A whole-resource request needs the all-subresources sentinel;
            # a selected texture read may prove just its required subresources.
            length = chunk.FindChild("ContentsLength")
            resource_contents = chunk.FindChild("ResourceContents")
            included = chunk.FindChild("subresourcesIncluded")
            coverage = ([included.GetChild(i).AsInt() for i in range(included.NumChildren())]
                        if included is not None else [])
            complete = coverage == [0xFFFFFFFF]
            if not complete and subresource is not None and getattr(candidate.type, "name", str(candidate.type)) == "Texture":
                texture = next((item for item in controller.GetTextures()
                                if item.resourceId == candidate.resourceId), None)
                if texture is not None:
                    mip, layer = int(subresource.get("mip", 0)), int(subresource.get("slice", 0))
                    mips, layers = int(texture.mips), int(texture.arraysize)
                    # D3D12 indexes mip + array*mips + plane*mips*arraysize.
                    # A 3D depth slice is part of one mip subresource. Packed
                    # depth/stencil readback needs both native planes restored.
                    dimension = int(texture.dimension)
                    array_layer = 0 if dimension == 3 else layer
                    plane_type = getattr(texture.format.type, "name", str(texture.format.type))
                    planes = (int(texture.format.YUVPlaneCount()) if plane_type.startswith("YUV")
                              else 2 if plane_type in {"D16S8", "D24S8", "D32S8"} else 1)
                    required = [mip + array_layer*mips + plane*mips*layers for plane in range(planes)]
                    valid_slice = (0 <= layer < max(1, int(texture.depth) >> mip)
                                   if dimension == 3 and mip >= 0 else 0 <= layer < layers)
                    complete = (planes > 0 and 0 <= mip < mips and valid_slice
                                and all(item in coverage for item in required))
            if (length is not None and resource_contents is not None
                    and getattr(candidate.type, "name", str(candidate.type)) == "Buffer"):
                buffer = next((item for item in controller.GetBuffers()
                               if item.resourceId == candidate.resourceId), None)
                # D3D12's buffer apply path copies the whole allocation and does
                # not consult the texture-only subresourcesIncluded array.
                complete = (buffer is not None and length is not None
                            and length.AsInt() >= int(buffer.length) > 0)
            if (identity is not None and identity.AsResourceId() == candidate.resourceId
                    and length is not None and length.AsInt() > 0 and resource_contents is not None
                    and complete):
                return {"source_resource_id": str(candidate.resourceId), "chunk_indices": [int(index)],
                        "scope": "recorded_capture_initial_contents"}
    raise InitialContentsUnavailable("Capture has no proven complete initial contents for this resource")


async def preserving_event(controller: Any, original_event: int, operation: Callable[[], Awaitable[Any]]) -> Any:
    """Drain in-flight native work before restoring, including on cancellation."""
    async def run() -> Any:
        read_error: BaseException | None = None
        try:
            return await operation()
        except BaseException as exc:
            read_error = exc
            raise
        finally:
            try:
                await asyncio.to_thread(controller.SetFrameEvent, original_event, True)
            except Exception as exc:
                message = f"Could not restore replay event {original_event}: {exc}"
                if read_error is not None:
                    message += f"; original read failed: {type(read_error).__name__}: {read_error}"
                raise ReplayRestoreError(message) from exc

    task = asyncio.create_task(run())
    cancelled = False
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            cancelled = True
    result = task.result()
    if cancelled:
        raise asyncio.CancelledError
    return result
