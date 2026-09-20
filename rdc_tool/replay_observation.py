"""Window-free, context-owned replay observations for embedded consumers.

The daemon's context worker serializes the whole operation with all CLI calls.
No window preview lifecycle is entered here. Device presentation is independent.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from rdc_tool import server_runtime as runtime

_revisions: dict[tuple[str, str], int] = {}


async def _final_target(session_id: str, flat: list[Any]) -> tuple[int, Any, Any]:
    """Require an actual Present action and a uniquely evidenced resource."""
    rd = runtime._get_rd()
    flag = getattr(rd.ActionFlags, "Present", None)
    presents = [a for a in flat if flag is not None and bool(a.flags & flag)]
    if not presents:
        raise ValueError("Capture has no explicit Present action")
    present = max(presents, key=lambda a: int(a.eventId))
    event_id = int(present.eventId)
    controller = await runtime._get_controller(session_id)
    # RenderDoc encodes the presented swap buffer in Present.copyDestination.
    # ResourceUsage has no Present enum in the bundled binding. Never infer the
    # target from area, its name, generic pass boundaries or the first RT.
    destination = getattr(present, "copyDestination", None)
    swap_flag = getattr(rd.TextureCategory, "SwapBuffer", None)
    matches = [texture for texture in await runtime._offload(controller.GetTextures)
               if destination is not None and texture.resourceId == destination
               and swap_flag is not None and bool(texture.creationFlags & swap_flag)]
    if len(matches) != 1:
        raise ValueError("Final Present does not identify exactly one swap-buffer resource")
    return event_id, matches[0].resourceId, matches[0]



async def handle(action: str, args: dict[str, Any]) -> str:
    context_id = runtime._runtime_context_id()
    state = runtime._context_state(context_id)
    session_id = str(args.get("session_id") or state.get("current_session_id") or "")
    if not session_id:
        return runtime._err("Open a capture in this context first", code="replay_session_missing")
    if session_id != str(state.get("current_session_id") or "") and session_id not in state.get("sessions", {}):
        return runtime._err("Session does not belong to the selected context", code="replay_session_mismatch")
    await runtime._ensure_live_session(session_id)
    roots, flat, by_event = await runtime._load_action_index(session_id)
    ancestors = {}
    def visit(nodes, parents):
        for node in nodes:
            ancestors[int(node.eventId)] = parents
            visit(getattr(node, "children", []), parents + [node])
    visit(roots, [])
    def event_row(action):
        parents = ancestors.get(int(action.eventId), [])
        return {"event_id": int(action.eventId), "name": runtime._action_name(action),
                "parent_chain": [{"event_id": int(p.eventId), "name": runtime._action_name(p)} for p in parents],
                "marker_path": [str(p.customName) for p in parents if getattr(p, "customName", "") and runtime._map_action_flags(p.flags).get("is_marker")] or None}
    events = sorted({int(a.eventId): event_row(a)
                     for a in flat if int(a.eventId) > 0}.values(), key=lambda item: item["event_id"])
    if action == "get_replay_events":
        return runtime._ok(context_id=context_id, session_id=session_id, events=events, complete=True)

    out_path = Path(str(args.get("out_path") or ""))
    if not args.get("out_path") or not out_path.is_absolute() or out_path.suffix.lower() != ".png":
        return runtime._err("out_path must be an absolute PNG path", code="observation_path_invalid")
    # Refuse reuse: a failed export must never expose a previous image as new.
    if out_path.exists():
        return runtime._err("out_path already exists; use a new observation path", code="observation_path_exists")
    if args.get("final_output") and (args.get("event_id") is not None or args.get("target")):
        return runtime._err("final_output cannot be combined with event_id or target", code="observation_selection_conflict")
    event_id = args.get("event_id", runtime._active_event(session_id))
    if isinstance(event_id, bool) or not isinstance(event_id, int) or event_id not in by_event:
        return runtime._err("Event is not in this capture", code="observation_event_invalid")
    target = args.get("target") or {}
    if not isinstance(target, dict):
        return runtime._err("target must be an object", code="observation_target_invalid")
    texture_id = texture_desc = None
    final_error = None
    is_final = False
    if args.get("final_output"):
        try:
            event_id, texture_id, texture_desc = await _final_target(session_id, flat)
            is_final = True
        except Exception as exc:
            final_error = {"code": "final_output_unavailable", "message": str(exc)}
    if not args.get("final_output"):
        rd = runtime._get_rd()
        present_flag = getattr(rd.ActionFlags, "Present", None)
        presents = [a for a in flat if present_flag is not None and bool(getattr(a, "flags", 0) & present_flag)]
        selected_present = [a for a in presents if int(a.eventId) == event_id]
        if selected_present:
            try:
                present_event, present_texture, present_desc = await _final_target(session_id, selected_present)
                if not target or (target.get("texture_id") == str(present_texture) and "rt_index" not in target):
                    event_id, texture_id, texture_desc = present_event, present_texture, present_desc
                    is_final = event_id == max(int(a.eventId) for a in presents)
            except Exception as exc:
                final_error = {"code": "present_output_unavailable", "message": str(exc)}
    controller = await runtime._get_controller(session_id)
    await runtime._offload(controller.SetFrameEvent, event_id, True)
    runtime._store_active_event(session_id, event_id, context_id=context_id)
    key = (context_id, session_id)
    revision = _revisions.get(key, 0) + 1
    _revisions[key] = revision
    backend = str((state.get("sessions", {}).get(session_id) or {}).get("backend_type") or state.get("backend") or "local")
    result: dict[str, Any] = {
        "context_id": context_id, "session_id": session_id, "revision": revision,
        "event_id": event_id, "image_event_id": None, "image_path": None,
        "modification_state": "intervention" if runtime._replacement_metadata_entries(session_id) else "restored" if session_id in runtime._runtime.restored_shader_sessions else "baseline",
        "display_parameters": {"mip": 0, "slice": 0, "sample": 0, "range_min": 0.0, "range_max": 1.0},
        "is_final_output": is_final, "final_output_error": final_error,
        "target": None, "targets": [], "image_error": None,
        "remote_display": {"status": "unavailable" if backend == "remote" else "not_applicable",
                           "event_id": event_id, "texture_id": None, "sequence": None,
                           "reason": "No presentation requested" if backend == "remote" else None},
    }
    async def present(resource, unavailable_reason=None):
        if backend != "remote":
            return
        receipt = result["remote_display"]
        receipt.update(texture_id=str(resource) if resource is not None else None, sequence=None)
        try:
            sequence = await runtime._session_manager.present_remote(session_id, event_id, resource)
            receipt.update(status="unavailable" if unavailable_reason else "presented",
                           sequence=sequence, reason=unavailable_reason)
        except Exception as exc:
            receipt.update(status="unsupported" if getattr(exc, "code", "") == "remote_presentation_unsupported" else "unavailable",
                           reason=str(exc))

    try:
        outputs = await runtime._output_target_resource_ids(session_id, event_id)
        result["targets"] = [{"texture_id": str(rid), "output_slot": slot} for rid, slot in outputs]
        slot = None
        if texture_id is None:
            if "rt_index" in target:
                requested_slot = target["rt_index"]
                if isinstance(requested_slot, bool) or not isinstance(requested_slot, int):
                    raise ValueError("rt_index must be an integer color attachment slot")
                match = next(((rid, idx) for rid, idx in outputs if idx == requested_slot), None)
            elif target.get("texture_id"):
                match = next(((rid, idx) for rid, idx in outputs if str(rid) == str(target["texture_id"])), None)
            else:
                match = outputs[0] if outputs else None
            if match is None:
                result["image_error"] = {"code": "missing_target" if target else "no_color_output",
                                         "message": "Requested color target is unavailable" if target else "Selected event has no color output"}
                await present(None, result["image_error"]["code"])
                return runtime._ok(**result)
            texture_id, slot = match
            texture_id, texture_desc = await runtime._get_texture_descriptor(session_id, texture_id, event_id=event_id)
        result["target"] = {"texture_id": str(texture_id), "output_slot": slot,
                            "target_source": "swapchain_present" if is_final else "event_output"}
        if is_final and not any(t["texture_id"] == str(texture_id) for t in result["targets"]):
            result["targets"].append({"texture_id": str(texture_id), "output_slot": None})
        await present(texture_id)
        assert runtime._render_service is not None
        await runtime._render_service.save_texture_file(
            session_id=session_id, event_id=event_id, texture_id=texture_id,
            session_manager=runtime._session_manager, artifact_store=None,
            output_format="png", output_path=str(out_path),
            subresource={"mip": 0, "slice": 0, "sample": 0})
        if not out_path.is_file() or out_path.stat().st_size == 0:
            raise RuntimeError("PNG export did not produce a complete image")
        result.update(image_event_id=event_id, image_path=str(out_path),
                      width=int(getattr(texture_desc, "width", 0)), height=int(getattr(texture_desc, "height", 0)))
    except Exception as exc:
        result["image_error"] = {"code": "export_failure", "message": str(exc)}
        if out_path.is_file():
            out_path.unlink()
    return runtime._ok(**result)
