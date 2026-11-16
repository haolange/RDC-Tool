"""rd.replay.* operations."""

from __future__ import annotations

from typing import Any, Dict

from rdc_tool.runtime import (
    action_index,
    coerce,
    context_records,
    envelope,
    live_state,
    preview_sync,
    renderdoc_api,
    replay_access,
    visual_target,
)


async def dispatch(action: str, args: Dict[str, Any]) -> str:
    coerce._require(args, "session_id")
    session_id = str(args["session_id"])
    await replay_access._ensure_live_session(session_id)
    replay = replay_access._get_replay_handle(session_id)
    controller = await replay_access._get_controller(session_id)

    if action == "set_frame":
        replay.frame_index = coerce._as_int(args.get("frame_index"), 0)
        roots = await renderdoc_api._offload(controller.GetRootActions)
        active_event_id = await visual_target._pick_previewable_default_event_id(
            session_id,
            roots,
            fallback_event_id=action_index._pick_default_event_id(roots),
        )
        replay.active_event_id = active_event_id
        context_records._set_context_frame(session_id, replay.frame_index, active_event_id)
        await preview_sync._auto_sync_preview_if_enabled(live_state._runtime_context_id())
        return envelope._ok(active_event_id=active_event_id)

    if action == "get_frame_info":
        roots = await renderdoc_api._offload(controller.GetRootActions)
        flat = action_index._flatten_actions(roots)
        drawcalls = 0
        markers = 0
        for action_obj in flat:
            flags = action_index._map_action_flags(getattr(action_obj, "flags", 0))
            if flags.get("is_draw"):
                drawcalls += 1
            if flags.get("is_marker"):
                markers += 1
        frame_info = {
            "frame_index": replay.frame_index,
            "event_range": {
                "start": int(getattr(flat[0], "eventId", 0)) if flat else 0,
                "end": int(getattr(flat[-1], "eventId", 0)) if flat else 0,
            },
            "drawcall_count": drawcalls,
            "marker_count": markers,
        }
        return envelope._ok(frame_info=frame_info)

    if action == "get_api_properties":
        props = await renderdoc_api._offload(controller.GetAPIProperties)
        api_properties = {
            "pipeline_type": str(getattr(props, "pipelineType", "")),
            "local_renderer": str(getattr(props, "localRenderer", "")),
            "shader_debugging": bool(getattr(props, "shaderDebugging", False)),
        }
        return envelope._ok(api_properties=api_properties)

    if action == "get_driver_info":
        props = await renderdoc_api._offload(controller.GetAPIProperties)
        info = {
            "vendor": str(getattr(props, "vendor", "")),
            "device": str(getattr(props, "localRenderer", "")),
            "driver_version": str(getattr(props, "driverVersion", "")),
            "driver_name": str(getattr(props, "localRenderer", "")),
            "replay_api": str(getattr(props, "pipelineType", "")),
        }
        return envelope._ok(driver_info=coerce._sanitize_dict(info))

    return envelope._err(f"Unsupported replay action: {action}")
