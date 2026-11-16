"""rd.event.* operations."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Sequence

from rdc_tool.runtime import (
    action_index,
    coerce,
    envelope,
    live_state,
    preview_sync,
    renderdoc_api,
    replay_access,
    session_recovery,
)


async def dispatch(action: str, args: Dict[str, Any]) -> str:
    if action == "get_api_calls":
        from rdc_tool.core.capture_queries import query_calls
        coerce._require(args, "session_id")
        if (args.get("event_id") is None) == (args.get("chunk_indices") is None):
            return envelope._err("Specify exactly one of event_id and chunk_indices", code="validation_error")
        controller = await replay_access._get_controller(str(args["session_id"]))
        return envelope._ok(**(await renderdoc_api._offload(query_calls, renderdoc_api._get_rd(), controller,
            event_id=args.get("event_id"), chunk_indices=args.get("chunk_indices"),
            offset=int(args.get("offset", 0)), limit=int(args.get("limit", 50)),
            max_nodes=int(args.get("max_nodes", 4096)), object_path=args.get("object_path"),
            child_offset=int(args.get("child_offset", 0)), value_offset=int(args.get("value_offset", 0)))))
    coerce._require(args, "session_id")
    session_id = str(args["session_id"])
    flag_filters: Dict[str, List[Any]] = {}
    if action == "search_actions":
        query = coerce._parse_query_like(args.get("query"))
        validation_details = {"session_id": session_id, "failure_stage": "validate_query",
                              "effects_attempted": False, "context_preserved": True}
        action_flags = renderdoc_api._get_rd().ActionFlags
        for filter_name in ("flags_include", "flags_exclude"):
            requested = query.get(filter_name, [])
            if not isinstance(requested, list) or any(not isinstance(name, str) or not name for name in requested):
                return envelope._err(f"{filter_name} must be an array of ActionFlags names", code="validation_error", category="validation", details=validation_details)
            members = []
            for name in requested:
                member = getattr(action_flags, name, None)
                if member is None:
                    return envelope._err(f"Unknown ActionFlags name in {filter_name}: {name}", code="validation_error", category="validation", details=validation_details)
                members.append(member)
            flag_filters[filter_name] = members
    controller = await replay_access._get_controller(session_id)

    roots, flat, by_event = await replay_access._load_action_index(session_id, controller=controller)

    def _parent_chain(event_id: int) -> List[Any]:
        chain: List[Any] = []

        def walk(nodes: Sequence[Any], stack: List[Any]) -> bool:
            for node in nodes:
                stack.append(node)
                if int(getattr(node, "eventId", 0)) == event_id:
                    chain.extend(stack)
                    return True
                children = getattr(node, "children", None) or []
                if walk(children, stack):
                    return True
                stack.pop()
            return False

        walk(roots, [])
        return chain

    if action == "set_active":
        coerce._require(args, "event_id")
        event_id = coerce._as_int(args["event_id"])
        resolved_event = replay_access._require_action_event(session_id, event_id, by_event)
        await renderdoc_api._offload(controller.SetFrameEvent, resolved_event, True)
        replay_access._store_active_event(session_id, resolved_event)
        await preview_sync._auto_sync_preview_if_enabled(live_state._runtime_context_id())
        return envelope._ok(active_event_id=resolved_event)

    if action == "get_active":
        return envelope._ok(active_event_id=replay_access._active_event(session_id))


    if action == "get_action_tree":
        offset = max(0, coerce._as_int(args.get("offset"), 0))
        limit = max(1, coerce._as_int(args.get("limit"), 256))
        max_nodes = max(1, coerce._as_int(args.get("max_nodes"), 2000))
        max_depth = args.get("max_depth")
        requested = args.get("event_id")
        source = list(roots)
        if requested is not None:
            node = by_event.get(int(requested))
            if node is None:
                return envelope._err(f"Event not found: {requested}", code="event_not_found")
            source = [node]
        include_markers = coerce._as_bool(args.get("include_markers"), True)
        include_drawcalls = coerce._as_bool(args.get("include_drawcalls"), True)
        name_filter = str(coerce._as_dict(args.get("filter"), default={}).get("name_contains", "")).lower()
        visited = 0
        truncated = offset > 0 or offset + limit < len(source)
        def trim(node: Any, depth: int) -> list[Dict[str, Any]]:
            nonlocal visited, truncated
            if visited >= max_nodes or (max_depth is not None and depth > int(max_depth)):
                truncated = True
                return []
            item = action_index._action_to_dict(node, include_children=False, depth=depth)
            flags = item.get("flags", {})
            keep = (include_markers or not flags.get("is_marker")) and (include_drawcalls or not flags.get("is_draw"))
            matches = not name_filter or name_filter in str(item.get("name", "")).lower()
            visited += 1
            children = []
            for child in getattr(node, "children", None) or []:
                children.extend(trim(child, depth + 1))
            item["children"] = children
            if not keep:
                return children
            return [item] if matches or children else []
        children = []
        for node in source[offset:offset + limit]:
            children.extend(trim(node, 1))
        def count_nodes(nodes: list[Dict[str, Any]]) -> int:
            return sum(1 + count_nodes(node.get("children", [])) for node in nodes)
        emitted = count_nodes(children)
        result = {"root": {"event_id": 0, "name": "root", "flags": {}, "children": children},
                  "pagination": {"offset": offset, "limit": limit, "max_nodes": max_nodes,
                    "emitted_nodes": emitted, "visited_nodes": visited, "returned_root_count": len(children), "total_root_count": len(source),
                    "truncated": truncated}}
        projection = envelope._projection_request(args, "rd.event.get_action_tree")
        if projection:
            result["projections"] = envelope._event_actions_projection(children, include_tsv_text=bool(projection.get("include_tsv_text", False)))
        return envelope._ok(**result)

    if action == "get_action_details":
        coerce._require(args, "event_id")
        event_id = coerce._as_int(args["event_id"])
        action_obj = by_event.get(event_id)
        if action_obj is None:
            return envelope._err(f"Event not found: {event_id}")
        payload = action_index._action_to_dict(action_obj, include_children=True)
        payload["parent_chain"] = [{"event_id": int(item.eventId), "name": action_index._action_name(item)} for item in _parent_chain(event_id)[:-1]]
        payload["marker_path"] = [str(item.customName) for item in _parent_chain(event_id) if getattr(item, "customName", "") and action_index._map_action_flags(item.flags).get("is_marker")] or None
        payload["depth_output"] = None if renderdoc_api._is_null_resource_id(getattr(action_obj, "depthOut", None)) else str(action_obj.depthOut)
        payload["children_event_ids"] = [int(c.eventId) for c in getattr(action_obj, "children", None) or []]
        return envelope._ok(action=payload)


    if action == "get_parent_chain":
        coerce._require(args, "event_id")
        event_id = coerce._as_int(args["event_id"])
        chain = _parent_chain(event_id)
        out = [
            {
                "event_id": int(getattr(item, "eventId", 0)),
                "name": action_index._action_name(item),
                "flags": action_index._map_action_flags(getattr(item, "flags", 0)),
            }
            for item in chain
        ]
        return envelope._ok(parent_chain=out)

    if action == "search_actions":
        max_results = coerce._as_int(args.get("max_results"), 200)
        name_regex = query.get("name_regex")
        pattern = re.compile(str(name_regex)) if name_regex else None
        name_contains = str(query.get("name_contains", "")).lower().strip()
        event_id_min = query.get("event_id_min")
        event_id_max = query.get("event_id_max")
        matches = []
        for action_obj in flat:
            eid = int(getattr(action_obj, "eventId", 0))
            name = action_index._action_name(action_obj)
            flags = getattr(action_obj, "flags", 0)
            if any(not bool(flags & member) for member in flag_filters["flags_include"]):
                continue
            if any(bool(flags & member) for member in flag_filters["flags_exclude"]):
                continue
            if event_id_min is not None and eid < int(event_id_min):
                continue
            if event_id_max is not None and eid > int(event_id_max):
                continue
            if name_contains and name_contains not in name.lower():
                continue
            if pattern and not pattern.search(name):
                continue
            chain = _parent_chain(eid)
            matches.append(
                {
                    "event_id": eid,
                    "name": name,
                    "flags": action_index._map_action_flags(getattr(action_obj, "flags", 0)),
                    "path": [action_index._action_name(item) for item in chain],
                },
            )
            if len(matches) >= max_results:
                break
        return envelope._ok(matches=matches)

    if action == "list_passes":
        tree = live_state._event_graph_service.build_event_tree(session_id, live_state._session_manager)
        tree = live_state._event_graph_service.infer_passes(tree, session_id, live_state._session_manager)
        pass_map: Dict[str, Dict[str, Any]] = {}

        def walk(nodes: List[Any]) -> None:
            for node in nodes:
                if node.inferred_pass:
                    slot = pass_map.setdefault(
                        node.inferred_pass,
                        {
                            "name": node.inferred_pass,
                            "begin_event_id": node.event_id,
                            "end_event_id": node.event_id,
                            "drawcall_count": 0,
                        },
                    )
                    slot["begin_event_id"] = min(slot["begin_event_id"], node.event_id)
                    slot["end_event_id"] = max(slot["end_event_id"], node.event_id)
                    if node.flags.is_draw:
                        slot["drawcall_count"] += 1
                walk(node.children)

        walk(tree)
        passes = list(pass_map.values())
        passes.sort(key=lambda p: p["begin_event_id"])
        return envelope._ok(passes=passes)


    if action == "get_callstack":
        coerce._require(args, "event_id")
        event_id = coerce._as_int(args["event_id"])
        action_obj = by_event.get(event_id)
        if action_obj is None:
            return envelope._err(f"Event not found: {event_id}")
        callstack = []
        raw = getattr(action_obj, "callstack", None) or []
        for frame in raw:
            callstack.append(
                {
                    "module": str(getattr(frame, "module", "")),
                    "function": str(getattr(frame, "function", "")),
                    "file": str(getattr(frame, "file", "")),
                    "line": int(getattr(frame, "line", 0)),
                    "address": str(getattr(frame, "address", "")),
                },
            )
        return envelope._ok(callstack=callstack)

    if action == "diff_pipeline_state":
        coerce._require(args, "event_a", "event_b")
        event_a = coerce._as_int(args["event_a"])
        event_b = coerce._as_int(args["event_b"])
        snap_a = await live_state._pipeline_service.snapshot_pipeline(session_id, event_a, live_state._session_manager)
        snap_b = await live_state._pipeline_service.snapshot_pipeline(session_id, event_b, live_state._session_manager)
        a = snap_a.model_dump(mode="json")
        b = snap_b.model_dump(mode="json")
        diff: List[Dict[str, Any]] = []

        def walk(path: str, va: Any, vb: Any) -> None:
            if isinstance(va, dict) and isinstance(vb, dict):
                keys = set(va.keys()) | set(vb.keys())
                for k in sorted(keys):
                    walk(f"{path}.{k}" if path else k, va.get(k), vb.get(k))
                return
            if isinstance(va, list) and isinstance(vb, list):
                max_len = max(len(va), len(vb))
                for i in range(max_len):
                    walk(f"{path}[{i}]", va[i] if i < len(va) else None, vb[i] if i < len(vb) else None)
                return
            if va != vb:
                diff.append({"path": path, "before": va, "after": vb})

        walk("", a, b)
        return envelope._ok(diff=diff)

    if action == "get_resource_usage":
        event_id = args.get("event_id")
        snap = await session_recovery._pipeline_snapshot(session_id, event_id=coerce._as_int(event_id) if event_id is not None else None)
        usage = {
            "render_targets": [rt.model_dump(mode="json") for rt in snap.render_targets],
            "depth_target": snap.depth_target.model_dump(mode="json") if snap.depth_target else None,
            "bindings": [b.model_dump(mode="json") for b in snap.bindings],
        }
        return envelope._ok(usage=usage)

    return envelope._err(f"Unsupported event action: {action}")
