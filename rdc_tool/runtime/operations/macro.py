"""rd.macro.* operations."""

from __future__ import annotations

import asyncio
from typing import Any, Dict

from rdc_tool.runtime import coerce, envelope, live_state, replay_access


async def dispatch(action: str, args: Dict[str, Any]) -> envelope.Outcome:
    coerce._require(args, "session_id")
    session_id = str(args["session_id"])
    if action == "find_state_change_point":
        coerce._require(args, "event_range", "state_path", "target_value")
        event_range = coerce._as_dict(args["event_range"])
        start_evt = coerce._as_int(event_range.get("start_event_id"), 0)
        end_evt = coerce._as_int(event_range.get("end_event_id"), 0)
        path = str(args["state_path"])
        target_value = args["target_value"]
        found = None
        budget = coerce._as_int(args.get("max_events"), 2000)
        if start_evt < 0 or end_evt < start_evt or budget < 1 or not path:
            return envelope.failure("Invalid event range, state path or event budget", code="validation_error")
        section_by_field = {"shaders": "shaders", "render_targets": "output_targets", "depth_target": "output_targets",
                            "topology": "topology", "viewport": "viewports_scissors", "scissor": "viewports_scissors",
                            "blend_states": "blend", "depth_stencil": "depth_stencil", "bindings": "bindings", "api": None}
        root_field = path.split(".")[0]
        if root_field not in section_by_field:
            return envelope.failure(f"Unknown pipeline state path: {path}", code="validation_error")
        section = section_by_field[root_field]
        _, flat, _ = await replay_access._load_action_index(session_id)
        events = sorted({int(a.eventId) for a in flat if start_evt <= int(a.eventId) <= end_evt})
        examined = 0
        for evt in events[:budget]:
            await asyncio.sleep(0)
            examined += 1
            snapshot = await live_state._pipeline_service.snapshot_pipeline(session_id, evt, live_state._session_manager, sections=[section] if section else [])
            replay_access._store_active_event(session_id, evt)
            payload = snapshot.model_dump(mode="json")
            cursor: Any = payload
            ok = True
            for token in path.split("."):
                if isinstance(cursor, dict) and token in cursor:
                    cursor = cursor[token]
                elif isinstance(cursor, list) and token.isdigit() and int(token) < len(cursor):
                    cursor = cursor[int(token)]
                else:
                    ok = False
                    break
            if not ok:
                return envelope.failure(f"Unknown pipeline state path: {path}", code="validation_error")
            if cursor == target_value:
                found = evt
                break
        return envelope.success(found_event_id=found, examined_events=examined, complete=found is not None or examined == len(events),
                   range_exhausted=found is None and examined == len(events), budget_exhausted=found is None and examined < len(events))


    return envelope.failure(f"Unsupported macro action: {action}", code="runtime_error")
