"""Read capture metadata and structured calls without replay-side mutations."""

from __future__ import annotations

from typing import Any


def read_thumbnail(rd: Any, path: str, image_format: str, max_size: int) -> bytes:
    capture = rd.OpenCaptureFile()
    try:
        status = capture.OpenFile(path, "", None)
        if status != rd.ResultCode.Succeeded:
            raise RuntimeError(f"OpenFile: {status}")
        requested = getattr(rd.FileType, image_format.upper())
        thumbnail = capture.GetThumbnail(requested, max_size)
        data = bytes(thumbnail.data)
        if data and (thumbnail.type != requested or thumbnail.width <= 0 or thumbnail.height <= 0
                     or max(thumbnail.width, thumbnail.height) > max_size):
            raise RuntimeError("Embedded thumbnail result violates requested format or dimensions")
        return data
    finally:
        capture.Shutdown()


def structured_object(rd: Any, obj: Any, budget: list[int], *, depth: int = 0,
                      path: tuple[int, ...] = (), child_offset: int = 0,
                      value_offset: int = 0) -> dict[str, Any]:
    """A typed bounded projection; omitted children carry an explicit count."""
    if budget[0] <= 0:
        raise ValueError("Structured node budget exhausted")
    budget[0] -= 1
    base = obj.type.basetype
    result: dict[str, Any] = {"name": str(obj.name), "type": str(obj.type.name),
                              "base_type": getattr(base, "name", str(base)), "byte_size": int(obj.type.byteSize),
                              "object_path": list(path)}
    if base in (rd.SDBasic.Chunk, rd.SDBasic.Struct, rd.SDBasic.Array):
        count = obj.NumChildren()
        if child_offset > count:
            raise ValueError("Child offset outside structured object")
        children = []
        while child_offset + len(children) < count and budget[0] > 0 and depth < 12:
            index = child_offset + len(children)
            children.append(structured_object(rd, obj.GetChild(index), budget, depth=depth + 1,
                                              path=(*path, index)))
        next_child = child_offset + len(children)
        result.update(children=children, child_count=count, child_offset=child_offset,
                      omitted_children=count-next_child, next_child_offset=next_child if next_child < count else None)
    elif base == rd.SDBasic.Resource:
        result["value"] = str(obj.AsResourceId())
    elif base == rd.SDBasic.Boolean:
        result["value"] = obj.AsBool()
    elif base == rd.SDBasic.Float:
        result["value"] = obj.AsFloat()
    elif base == rd.SDBasic.String:
        value = obj.AsString()
        if value_offset > len(value):
            raise ValueError("Value offset outside structured string")
        end = min(len(value), value_offset + 4096)
        result.update(value=value[value_offset:end], value_offset=value_offset,
                      omitted_characters=len(value)-end, next_value_offset=end if end < len(value) else None)
    elif base == rd.SDBasic.Character:
        result["value"] = chr(obj.AsInt() & 0xff)
    elif base == rd.SDBasic.Buffer:
        # SD buffers are indexed out-of-line; their length is not their contents.
        result.update(buffer_index=int(obj.AsInt()), contents_status="not_inlined")
    elif base == rd.SDBasic.Null:
        result["value"] = None
    else:
        result["value"] = obj.AsInt()
    return result


def query_calls(rd: Any, controller: Any, *, event_id: int | None, chunk_indices: list[int] | None,
                offset: int, limit: int, max_nodes: int, object_path: list[int] | None = None,
                child_offset: int = 0, value_offset: int = 0) -> dict[str, Any]:
    structured = controller.GetStructuredFile()
    if structured is None:
        raise RuntimeError("Structured capture data unavailable")
    associations: list[tuple[int, int | None]] = []
    if chunk_indices is not None:
        associations = [(index, None) for index in chunk_indices]
    else:
        pending = list(reversed(controller.GetRootActions()))
        while pending:
            action = pending.pop()
            pending.extend(reversed(action.children))
            if int(action.eventId) == event_id:
                associations = [(int(event.chunkIndex), int(event.eventId)) for event in action.events]
                break
            matching = [event for event in action.events if int(event.eventId) == event_id]
            if matching:
                associations = [(int(event.chunkIndex), int(event.eventId)) for event in matching]
                break
        else:
            raise ValueError(f"Event not found: {event_id}")
    if any(index < 0 or index >= len(structured.chunks) for index, _ in associations):
        raise ValueError("Chunk index outside the captured structured file")
    path = tuple(object_path or ())
    if (path or child_offset or value_offset) and len(associations) != 1:
        raise ValueError("Structured object continuation requires exactly one chunk")
    budget = [max_nodes]
    rows = []
    for index, associated_event in associations[offset:offset+limit]:
        if budget[0] <= 0:
            break
        obj = structured.chunks[index]
        for child in path:
            if child < 0 or child >= obj.NumChildren():
                raise ValueError("Object path outside structured chunk")
            obj = obj.GetChild(child)
        rows.append({"chunk_index": index, "event_id": associated_event,
                     "call": structured_object(rd, obj, budget, path=path,
                                               child_offset=child_offset, value_offset=value_offset)})
    next_offset = offset + len(rows)
    return {"calls": rows, "total": len(associations), "offset": offset,
            "next_offset": next_offset if next_offset < len(associations) else None,
            "node_budget_exhausted": budget[0] == 0,
            "scope": "captured_api_calls"}
