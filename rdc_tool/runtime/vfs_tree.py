"""The virtual filesystem view over a replay."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from rdc_tool.core.errors import CoreError
from rdc_tool.runtime import coerce, context_records, live_state


def _vfs_normalize_path(raw: Any) -> str:
    text = str(raw or "/").strip().replace("\\", "/")
    if not text:
        return "/"
    if not text.startswith("/"):
        text = "/" + text
    parts = [part for part in text.split("/") if part]
    return "/" + "/".join(parts) if parts else "/"


def _vfs_parts(path: str) -> List[str]:
    normalized = _vfs_normalize_path(path)
    if normalized == "/":
        return []
    return [part for part in normalized.split("/") if part]


def _vfs_entry(
    name: str,
    path: str,
    *,
    kind: str = "directory",
    title: str = "",
    summary: str = "",
    requires_session: bool = False,
    canonical_tools: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    return {
        "name": str(name),
        "path": _vfs_normalize_path(path),
        "kind": kind,
        "title": str(title or ""),
        "summary": str(summary or title or ""),
        "exists": True,
        "requires_session": bool(requires_session),
        "canonical_tools": list(canonical_tools or []),
    }


def _vfs_node(
    path: str,
    *,
    kind: str,
    title: str,
    summary: str = "",
    requires_session: bool = False,
    canonical_tools: Optional[Sequence[str]] = None,
    data: Any = None,
    entries: Optional[Sequence[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    normalized = _vfs_normalize_path(path)
    parts = _vfs_parts(normalized)
    name = "/" if not parts else parts[-1]
    payload: Dict[str, Any] = {
        "path": normalized,
        "name": name,
        "kind": kind,
        "title": title,
        "summary": str(summary or title or ""),
        "exists": True,
        "requires_session": bool(requires_session),
        "canonical_tools": list(canonical_tools or []),
    }
    if data is not None:
        payload["data"] = data
    if entries is not None:
        payload["entries"] = list(entries)
    return payload


async def _vfs_call(tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
    # VFS reads re-enter the full operation pipeline (catalog checks, prerequisites, envelope).
    from rdc_tool.runtime import dispatch

    payload = await dispatch.dispatch_operation(
        tool_name,
        dict(args or {}),
        transport="vfs",
        remote=tool_name.startswith("rd.remote."),
        context_id=live_state._runtime_context_id(),
    )
    if not payload.get("ok"):
        error = payload.get("error", {}) if isinstance(payload.get("error"), dict) else {}
        raise CoreError(
            code=str(error.get("code") or "vfs_tool_failed"),
            category=str(error.get("category") or "runtime"),
            message=str(error.get("message") or f"{tool_name} failed"),
            details=dict(error.get("details") or {}),
        )
    return dict(payload.get("data") or {})


def _vfs_unavailable_shader_node(path: str, *, stage: str, title: str, exc: CoreError) -> Dict[str, Any]:
    return _vfs_node(
        path,
        kind="object",
        title=title,
        summary=str(exc.message),
        requires_session=True,
        canonical_tools=["rd.pipeline.get_shader"],
        data={
            "available": False,
            "stage": str(stage or "").lower(),
            "error": {
                "code": exc.code,
                "category": exc.category,
                "message": exc.message,
                "details": dict(exc.details or {}),
            },
        },
    )


def _vfs_default_session_id() -> str:
    snapshot = context_records._context_snapshot(live_state._runtime_context_id())
    runtime_payload = snapshot.get("runtime", {})
    return str(runtime_payload.get("session_id") or "").strip()


def _vfs_require_session_id(path: str, args: Dict[str, Any]) -> str:
    session_id = str(args.get("session_id") or "").strip()
    if session_id:
        return session_id
    session_id = _vfs_default_session_id()
    if session_id:
        return session_id
    context_id = live_state._runtime_context_id()
    normalized_path = _vfs_normalize_path(path)
    raise CoreError(
        code="session_required",
        category="validation",
        message=f"{normalized_path} requires session_id or an active context session",
        details={
            "context_id": context_id,
            "path": normalized_path,
            "requires_session": True,
            "recovery_hint": "Open a capture with `rdc-tool capture open --file <rdc>` or pass --session-id.",
        },
    )


def _vfs_parse_index(segment: str, *, path: str) -> int:
    try:
        return int(segment)
    except ValueError as exc:
        raise ValueError(f"{_vfs_normalize_path(path)} expects a numeric index segment") from exc


async def _vfs_root_node() -> Dict[str, Any]:
    entries = [
        _vfs_entry("context", "/context", kind="object", title="Current context snapshot", canonical_tools=["rd.session.get_context"]),
        _vfs_entry("artifacts", "/artifacts", title="Recent artifacts and exports", canonical_tools=["rd.util.list_artifacts"]),
        _vfs_entry("draws", "/draws", title="Action tree and draw hierarchy", requires_session=True, canonical_tools=["rd.event.get_action_tree", "rd.event.get_action_details"]),
        _vfs_entry("passes", "/passes", title="Inferred render passes", requires_session=True, canonical_tools=["rd.event.list_passes", "rd.event.search_actions"]),
        _vfs_entry("resources", "/resources", title="All textures and buffers", requires_session=True, canonical_tools=["rd.resource.list_all", "rd.resource.get_details"]),
        _vfs_entry("textures", "/textures", title="Texture inventory", requires_session=True, canonical_tools=["rd.resource.list_all", "rd.texture.get_data"]),
        _vfs_entry("buffers", "/buffers", title="Buffer inventory", requires_session=True, canonical_tools=["rd.resource.list_all", "rd.buffer.get_data"]),
        _vfs_entry("pipeline", "/pipeline", title="Current pipeline snapshot", requires_session=True, canonical_tools=["rd.pipeline.get_state", "rd.pipeline.get_state"]),
        _vfs_entry("shaders", "/shaders", title="Current bound shaders", requires_session=True, canonical_tools=["rd.pipeline.get_state", "rd.pipeline.get_shader"]),
        _vfs_entry("debug", "/debug", title="Debug focus and entry hints", canonical_tools=["rd.session.get_context", "rd.texture.get_pixel_history", "rd.texture.get_pixel_history"]),
    ]
    return _vfs_node("/", kind="directory", title="RDC-Tool VFS root", entries=entries)


async def _vfs_draws_node(parts: List[str], path: str, args: Dict[str, Any]) -> Dict[str, Any]:
    session_id = _vfs_require_session_id(path, args)
    if len(parts) == 1:
        payload = await _vfs_call("rd.event.get_action_tree", {"session_id": session_id, "max_depth": args.get("max_depth") or 2, "max_nodes": max(1, coerce._as_int(args.get("max_nodes"), 2000))})
        root = payload.get("root", {})
        children = list(root.get("children") or []) if isinstance(root, dict) else []
        entries = [
            _vfs_entry(
                str(child.get("event_id", "")),
                f"/draws/{child.get('event_id', '')}",
                kind="object",
                title=str(child.get("name", "")),
                requires_session=True,
                canonical_tools=["rd.event.get_action_details"],
            )
            for child in children
            if child.get("event_id") is not None
        ]
        node = _vfs_node("/draws", kind="directory", title="Action tree roots", requires_session=True, canonical_tools=["rd.event.get_action_tree"], data=root, entries=entries)
        node["pagination"] = dict(payload.get("pagination") or {})
        return node

    event_id = coerce._as_int(parts[1])
    if len(parts) == 2:
        if coerce._as_bool(args.get("_vfs_tree_mode"), False):
            return _vfs_node(
                path,
                kind="object",
                title=f"draw {event_id}",
                requires_session=True,
                canonical_tools=["rd.event.get_action_details"],
                data={
                    "event_id": event_id,
                    "detail_deferred": True,
                    "recommended_next_tool": "rd.event.get_action_details",
                    "unavailable_reason": "vfs_tree_summary_mode",
                },
                entries=[],
            )
        payload = await _vfs_call("rd.event.get_action_details", {"session_id": session_id, "event_id": event_id})
        action = payload.get("action", {})
        entries = [
            _vfs_entry("children", f"/draws/{event_id}/children", title="Immediate child actions", requires_session=True, canonical_tools=["rd.event.get_action_details", "rd.event.get_action_details"]),
            _vfs_entry("pipeline", f"/draws/{event_id}/pipeline", kind="object", title="Pipeline snapshot at this event", requires_session=True, canonical_tools=["rd.pipeline.get_state"]),
            _vfs_entry("shaders", f"/draws/{event_id}/shaders", title="Bound shaders at this event", requires_session=True, canonical_tools=["rd.pipeline.get_state", "rd.pipeline.get_shader"]),
        ]
        return _vfs_node(path, kind="object", title=str(action.get("name", f"draw {event_id}")), requires_session=True, canonical_tools=["rd.event.get_action_details"], data=action, entries=entries)

    tail = parts[2]
    if tail == "children":
        payload = await _vfs_call("rd.event.get_action_details", {"session_id": session_id, "event_id": event_id})
        action = payload.get("action", {})
        children = list(action.get("children") or []) if isinstance(action, dict) else []
        entries = [
            _vfs_entry(
                str(child.get("event_id", "")),
                f"/draws/{child.get('event_id', '')}",
                kind="object",
                title=str(child.get("name", "")),
                requires_session=True,
                canonical_tools=["rd.event.get_action_details"],
            )
            for child in children
            if child.get("event_id") is not None
        ]
        return _vfs_node(path, kind="directory", title=f"Children of draw {event_id}", requires_session=True, canonical_tools=["rd.event.get_action_details"], data={"parent_event_id": event_id, "children": children}, entries=entries)
    if tail == "pipeline":
        if len(parts) == 3:
            payload = await _vfs_call("rd.pipeline.get_state", {"session_id": session_id, "event_id": event_id})
            state = payload.get("pipeline_state", {})
            entries = [
                _vfs_entry("summary", f"/draws/{event_id}/pipeline/summary", kind="object", title="Pipeline summary", requires_session=True, canonical_tools=["rd.pipeline.get_state"]),
                _vfs_entry("shaders", f"/draws/{event_id}/pipeline/shaders", title="Bound shaders", requires_session=True, canonical_tools=["rd.pipeline.get_state", "rd.pipeline.get_shader"]),
            ]
            return _vfs_node(path, kind="object", title=f"Pipeline at draw {event_id}", requires_session=True, canonical_tools=["rd.pipeline.get_state"], data=state, entries=entries)
        if len(parts) >= 4 and parts[3] == "summary":
            payload = await _vfs_call("rd.pipeline.get_state", {"session_id": session_id, "event_id": event_id})
            return _vfs_node(path, kind="object", title=f"Pipeline summary at draw {event_id}", requires_session=True, canonical_tools=["rd.pipeline.get_state"], data=payload.get("pipeline_state", {}))
        if len(parts) >= 4 and parts[3] == "shaders":
            payload = await _vfs_call("rd.pipeline.get_state", {"session_id": session_id, "event_id": event_id})
            shaders = list(payload.get("pipeline_state", {}).get("shaders", []) or [])
            if len(parts) == 4:
                entries = [
                    _vfs_entry(
                        str(shader.get("stage", "")).lower(),
                        f"/draws/{event_id}/pipeline/shaders/{str(shader.get('stage', '')).lower()}",
                        kind="object",
                        title=str(shader.get("entry", "") or shader.get("stage", "")),
                        requires_session=True,
                        canonical_tools=["rd.pipeline.get_shader"],
                    )
                    for shader in shaders
                    if shader.get("stage")
                ]
                return _vfs_node(path, kind="directory", title=f"Pipeline shaders at draw {event_id}", requires_session=True, canonical_tools=["rd.pipeline.get_state", "rd.pipeline.get_shader"], data={"shaders": shaders}, entries=entries)
            stage = str(parts[4]).lower()
            try:
                payload = await _vfs_call("rd.pipeline.get_shader", {"session_id": session_id, "event_id": event_id, "stage": stage})
            except CoreError as exc:
                if exc.code == "shader_not_bound":
                    return _vfs_unavailable_shader_node(path, stage=stage, title=f"{stage.upper()} shader at draw {event_id}", exc=exc)
                raise
            return _vfs_node(path, kind="object", title=f"{stage.upper()} shader at draw {event_id}", requires_session=True, canonical_tools=["rd.pipeline.get_shader"], data=payload.get("shader", {}))
    if tail == "shaders":
        payload = await _vfs_call("rd.pipeline.get_state", {"session_id": session_id, "event_id": event_id})
        shaders = list(payload.get("pipeline_state", {}).get("shaders", []) or [])
        if len(parts) == 3:
            entries = [
                _vfs_entry(
                    str(shader.get("stage", "")).lower(),
                    f"/draws/{event_id}/shaders/{str(shader.get('stage', '')).lower()}",
                    kind="object",
                    title=str(shader.get("entry", "") or shader.get("stage", "")),
                    requires_session=True,
                    canonical_tools=["rd.pipeline.get_shader"],
                )
                for shader in shaders
                if shader.get("stage")
            ]
            return _vfs_node(path, kind="directory", title=f"Bound shaders at draw {event_id}", requires_session=True, canonical_tools=["rd.pipeline.get_state", "rd.pipeline.get_shader"], data={"shaders": shaders}, entries=entries)
        stage = str(parts[3]).lower()
        try:
            payload = await _vfs_call("rd.pipeline.get_shader", {"session_id": session_id, "event_id": event_id, "stage": stage})
        except CoreError as exc:
            if exc.code == "shader_not_bound":
                return _vfs_unavailable_shader_node(path, stage=stage, title=f"{stage.upper()} shader at draw {event_id}", exc=exc)
            raise
        return _vfs_node(path, kind="object", title=f"{stage.upper()} shader at draw {event_id}", requires_session=True, canonical_tools=["rd.pipeline.get_shader"], data=payload.get("shader", {}))

    raise ValueError(f"Unsupported VFS path: {_vfs_normalize_path(path)}")


async def _vfs_passes_node(parts: List[str], path: str, args: Dict[str, Any]) -> Dict[str, Any]:
    session_id = _vfs_require_session_id(path, args)
    payload = await _vfs_call("rd.event.list_passes", {"session_id": session_id, "marker_policy": args.get("marker_policy", "both")})
    passes = list(payload.get("passes", []) or [])
    if len(parts) == 1:
        entries = [
            _vfs_entry(str(index), f"/passes/{index}", kind="object", title=str(item.get("name", "")), requires_session=True, canonical_tools=["rd.event.list_passes", "rd.event.search_actions"])
            for index, item in enumerate(passes)
        ]
        return _vfs_node("/passes", kind="directory", title="Pass list", requires_session=True, canonical_tools=["rd.event.list_passes"], data={"passes": passes}, entries=entries)

    index = _vfs_parse_index(parts[1], path=path)
    if index < 0 or index >= len(passes):
        raise ValueError(f"Pass index out of range: {index}")
    selected = passes[index]
    if len(parts) == 2:
        entries = [
            _vfs_entry("draws", f"/passes/{index}/draws", title="Draws inside this pass", requires_session=True, canonical_tools=["rd.event.search_actions"]),
        ]
        return _vfs_node(path, kind="object", title=str(selected.get("name", f"pass {index}")), requires_session=True, canonical_tools=["rd.event.list_passes"], data=selected, entries=entries)
    if parts[2] == "draws":
        query = {
            "event_id_min": int(selected.get("begin_event_id") or 0),
            "event_id_max": int(selected.get("end_event_id") or 0),
            "flags_include": ["Drawcall"],
        }
        matches_payload = await _vfs_call("rd.event.search_actions", {"session_id": session_id, "query": query, "max_results": args.get("max_results") or 500})
        matches = [
            item
            for item in list(matches_payload.get("matches", []) or [])
            if isinstance(item, dict) and bool((item.get("flags") or {}).get("is_draw"))
        ]
        entries = [
            _vfs_entry(str(item.get("event_id", "")), f"/draws/{item.get('event_id', '')}", kind="object", title=str(item.get("name", "")), requires_session=True, canonical_tools=["rd.event.get_action_details"])
            for item in matches
            if item.get("event_id") is not None
        ]
        return _vfs_node(path, kind="directory", title=f"Draws in pass {index}", requires_session=True, canonical_tools=["rd.event.search_actions"], data={"pass": selected, "draws": matches}, entries=entries)

    raise ValueError(f"Unsupported VFS path: {_vfs_normalize_path(path)}")


async def _vfs_resource_like_node(parts: List[str], path: str, args: Dict[str, Any], *, root_name: str) -> Dict[str, Any]:
    session_id = _vfs_require_session_id(path, args)
    list_tool = "rd.resource.list_all"
    key_name = "resources"
    kind = {"resources": "all", "textures": "texture", "buffers": "buffer"}[root_name]
    payload = await _vfs_call(list_tool, {"session_id": session_id, "kind": kind})
    items = list(payload.get(key_name, []) or [])
    if len(parts) == 1:
        entries = []
        for item in items:
            item_id = str(item.get("resource_id") or item.get("texture_id") or item.get("buffer_id") or "").strip()
            if not item_id:
                continue
            title = str(item.get("name", "") or item.get("resource_name", "") or item_id)
            entries.append(_vfs_entry(item_id, f"/{root_name}/{item_id}", kind="object", title=title, requires_session=True, canonical_tools=["rd.resource.get_details"]))
        return _vfs_node(path, kind="directory", title=f"{root_name} list", requires_session=True, canonical_tools=[list_tool], data={key_name: items}, entries=entries)

    item_id = str(parts[1]).strip()
    selected = next((item for item in items if str(item.get("resource_id") or item.get("texture_id") or item.get("buffer_id") or "").strip() == item_id), None)
    if selected is None:
        raise ValueError(f"{root_name[:-1]} not found: {item_id}")

    if len(parts) == 2:
        entries = []
        if selected.get("texture_id") is not None:
            entries.append(_vfs_entry("data", f"/{root_name}/{item_id}/data", kind="object", title="Texture readback container metadata", requires_session=True, canonical_tools=["rd.texture.get_data"]))
        if root_name in {"resources", "textures", "buffers"}:
            entries.append(_vfs_entry("usage", f"/{root_name}/{item_id}/usage", kind="object", title="Resource usage", requires_session=True, canonical_tools=["rd.resource.get_usage"]))
        if selected.get("buffer_id") is not None:
            entries.insert(0, _vfs_entry("data", f"/{root_name}/{item_id}/data", kind="object", title="Buffer data readback metadata", requires_session=True, canonical_tools=["rd.buffer.get_data"]))
        return _vfs_node(path, kind="object", title=str(selected.get("name", item_id)), requires_session=True, canonical_tools=["rd.resource.get_details"], data=selected, entries=entries)

    tail = parts[2]
    if tail == "usage":
        payload = await _vfs_call("rd.resource.get_usage", {"session_id": session_id, "resource_id": item_id})
        return _vfs_node(path, kind="object", title=f"Usage for {item_id}", requires_session=True, canonical_tools=["rd.resource.get_usage"], data={"resource_id": item_id, "usage": payload.get("usage", [])})
    if tail == "data" and selected.get("texture_id") is not None:
        payload = await _vfs_call("rd.texture.get_data", {"session_id": session_id, "texture_id": item_id, "subresource": {"mip": 0, "slice": 0, "sample": 0}})
        return _vfs_node(path, kind="object", title=f"Texture readback container for {item_id}", requires_session=True, canonical_tools=["rd.texture.get_data"], data=payload)
    if tail == "data" and selected.get("buffer_id") is not None:
        payload = await _vfs_call("rd.buffer.get_data", {"session_id": session_id, "buffer_id": item_id, "offset": 0, "size": 0})
        return _vfs_node(path, kind="object", title=f"Buffer data for {item_id}", requires_session=True, canonical_tools=["rd.buffer.get_data"], data=payload)

    raise ValueError(f"Unsupported VFS path: {_vfs_normalize_path(path)}")


async def _vfs_pipeline_like_node(parts: List[str], path: str, args: Dict[str, Any], *, event_id: Optional[int] = None) -> Dict[str, Any]:
    session_id = _vfs_require_session_id(path, args)
    call_args: Dict[str, Any] = {"session_id": session_id}
    if event_id is not None:
        call_args["event_id"] = int(event_id)
    state_payload = await _vfs_call("rd.pipeline.get_state", call_args)
    state = state_payload.get("pipeline_state", {})
    title_suffix = f" at event {event_id}" if event_id is not None else ""
    base_path = _vfs_normalize_path(path)

    if len(parts) == 1 or (event_id is not None and len(parts) == 3):
        entries = [
            _vfs_entry("summary", f"{base_path}/summary", kind="object", title="Pipeline summary", requires_session=True, canonical_tools=["rd.pipeline.get_state"]),
            _vfs_entry("shaders", f"{base_path}/shaders", title="Bound shaders", requires_session=True, canonical_tools=["rd.pipeline.get_state", "rd.pipeline.get_shader"]),
        ]
        return _vfs_node(base_path, kind="object", title=f"Pipeline{title_suffix}", requires_session=True, canonical_tools=["rd.pipeline.get_state"], data=state, entries=entries)

    tail_index = 1 if event_id is None else 3
    tail = parts[tail_index]
    if tail == "summary":
        summary_payload = await _vfs_call("rd.pipeline.get_state", call_args)
        return _vfs_node(path, kind="object", title=f"Pipeline summary{title_suffix}", requires_session=True, canonical_tools=["rd.pipeline.get_state"], data=summary_payload.get("pipeline_state", {}))
    if tail == "shaders":
        shaders = list(state.get("shaders", []) or []) if isinstance(state, dict) else []
        if len(parts) == tail_index + 1:
            entries = [
                _vfs_entry(
                    str(shader.get("stage", "")).lower(),
                    f"{base_path}/shaders/{str(shader.get('stage', '')).lower()}",
                    kind="object",
                    title=str(shader.get("entry", "") or shader.get("stage", "")),
                    requires_session=True,
                    canonical_tools=["rd.pipeline.get_shader"],
                )
                for shader in shaders
                if shader.get("stage")
            ]
            return _vfs_node(path, kind="directory", title=f"Pipeline shaders{title_suffix}", requires_session=True, canonical_tools=["rd.pipeline.get_state", "rd.pipeline.get_shader"], data={"shaders": shaders}, entries=entries)
        stage = str(parts[tail_index + 1]).lower()
        try:
            shader_payload = await _vfs_call("rd.pipeline.get_shader", {**call_args, "stage": stage})
        except CoreError as exc:
            if exc.code == "shader_not_bound":
                return _vfs_unavailable_shader_node(path, stage=stage, title=f"{stage.upper()} shader{title_suffix}", exc=exc)
            raise
        return _vfs_node(path, kind="object", title=f"{stage.upper()} shader{title_suffix}", requires_session=True, canonical_tools=["rd.pipeline.get_shader"], data=shader_payload.get("shader", {}))

    raise ValueError(f"Unsupported VFS path: {_vfs_normalize_path(path)}")


async def _vfs_context_node(path: str) -> Dict[str, Any]:
    payload = await _vfs_call("rd.session.get_context", {})
    entries = [
        _vfs_entry("runtime", "/context", kind="object", title="Runtime snapshot", canonical_tools=["rd.session.get_context"]),
    ]
    return _vfs_node(path, kind="object", title="Current context snapshot", canonical_tools=["rd.session.get_context"], data=payload, entries=entries)


async def _vfs_artifacts_node(parts: List[str], path: str, args: Dict[str, Any]) -> Dict[str, Any]:
    payload = await _vfs_call("rd.util.list_artifacts", {"session_id": args.get("session_id"), "prefix": args.get("prefix", "")})
    artifacts = list(payload.get("artifacts", []) or [])
    if len(parts) == 1:
        entries = [
            _vfs_entry(str(index), f"/artifacts/{index}", kind="object", title=str(item.get("path", "")), canonical_tools=["rd.util.list_artifacts"])
            for index, item in enumerate(artifacts)
        ]
        return _vfs_node(path, kind="directory", title="Artifacts", canonical_tools=["rd.util.list_artifacts"], data={"artifacts": artifacts}, entries=entries)
    index = _vfs_parse_index(parts[1], path=path)
    if index < 0 or index >= len(artifacts):
        raise ValueError(f"Artifact index out of range: {index}")
    return _vfs_node(path, kind="object", title=f"Artifact {index}", canonical_tools=["rd.util.list_artifacts"], data=artifacts[index])


async def _vfs_debug_node(parts: List[str], path: str) -> Dict[str, Any]:
    snapshot = context_records._context_snapshot(live_state._runtime_context_id())
    focus = snapshot.get("focus", {})
    entries = [
        _vfs_entry("focus", "/debug/focus", kind="object", title="Current focus hints", canonical_tools=["rd.session.get_context"]),
    ]
    if len(parts) == 1:
        return _vfs_node(path, kind="directory", title="Debug focus and hints", canonical_tools=["rd.session.get_context", "rd.texture.get_pixel_history", "rd.texture.get_pixel_history"], data={"focus": focus, "recommended_tools": ["rd.texture.get_pixel_history", "rd.texture.get_pixel_history"]}, entries=entries)
    if len(parts) == 2 and parts[1] == "focus":
        return _vfs_node(path, kind="object", title="Current focus", canonical_tools=["rd.session.get_context"], data=focus)
    raise ValueError(f"Unsupported VFS path: {_vfs_normalize_path(path)}")


async def _vfs_resolve_node(path: str, args: Dict[str, Any]) -> Dict[str, Any]:
    normalized = _vfs_normalize_path(path)
    parts = _vfs_parts(normalized)
    if not parts:
        return await _vfs_root_node()
    head = parts[0]
    if head == "context":
        return await _vfs_context_node(normalized)
    if head == "artifacts":
        return await _vfs_artifacts_node(parts, normalized, args)
    if head == "draws":
        return await _vfs_draws_node(parts, normalized, args)
    if head == "passes":
        return await _vfs_passes_node(parts, normalized, args)
    if head == "resources":
        return await _vfs_resource_like_node(parts, normalized, args, root_name="resources")
    if head == "textures":
        return await _vfs_resource_like_node(parts, normalized, args, root_name="textures")
    if head == "buffers":
        return await _vfs_resource_like_node(parts, normalized, args, root_name="buffers")
    if head == "pipeline":
        return await _vfs_pipeline_like_node(parts, normalized, args)
    if head == "shaders":
        session_id = _vfs_require_session_id(normalized, args)
        rewritten = ["pipeline", "shaders", *parts[1:]]
        return await _vfs_pipeline_like_node(rewritten, "/pipeline/shaders" if len(rewritten) == 2 else f"/pipeline/shaders/{'/'.join(rewritten[2:])}", {"session_id": session_id})
    if head == "debug":
        return await _vfs_debug_node(parts, normalized)
    raise ValueError(f"Unsupported VFS path: {normalized}")


async def _vfs_build_tree(path: str, args: Dict[str, Any], depth: int, budget: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if budget is None:
        budget = {"max_nodes": max(1, coerce._as_int(args.get("max_nodes"), 2000)), "emitted_nodes": 0, "truncated": False}
    if int(budget.get("emitted_nodes") or 0) >= int(budget.get("max_nodes") or 1):
        budget["truncated"] = True
        return _vfs_node(path, kind="unavailable", title="VFS tree node budget exhausted", data={"truncation_reason": "max_nodes_exceeded"})
    budget["emitted_nodes"] = int(budget.get("emitted_nodes") or 0) + 1
    resolve_args = {**dict(args), "_vfs_tree_mode": True}
    node = await _vfs_resolve_node(path, resolve_args)
    if node.get("pagination", {}).get("truncated"):
        budget["upstream_truncated"] = True
    if depth <= 0:
        return node
    entries = list(node.get("entries") or []) if isinstance(node, dict) else []
    if not entries:
        return node
    children = []
    for entry in entries:
        if int(budget.get("emitted_nodes") or 0) >= int(budget.get("max_nodes") or 1):
            budget["truncated"] = True
            break
        child_path = str(entry.get("path") or "").strip()
        if not child_path:
            continue
        children.append(await _vfs_build_tree(child_path, args, depth - 1, budget))
    enriched = dict(node)
    enriched["children"] = children
    return enriched
