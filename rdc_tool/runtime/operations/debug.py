"""rd.debug.* operations."""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

from rdc_tool.core.errors import CoreError
from rdc_tool.runtime import (
    coerce,
    envelope,
    live_state,
    renderdoc_api,
    replay_access,
    settings,
    shader_debug,
    shader_values,
)


async def dispatch(action: str, args: Dict[str, Any]) -> envelope.Outcome:
    coerce._require(args, "session_id")
    session_id = str(args["session_id"])


    coerce._require(args, "shader_debug_id")
    debug_id = str(args["shader_debug_id"])
    try:
        handle = shader_debug._require_shader_debug_handle(session_id, debug_id)
    except CoreError as exc:
        return envelope.failure(exc.message, code=exc.code, category=exc.category, details=dict(exc.details))
    validation_details = {"session_id": session_id, "failure_stage": "validate_debug_request",
                          "effects_attempted": False, "context_preserved": True}
    if action == "step" and args.get("step_mode", "instruction") != "instruction":
        return envelope.failure("Only instruction stepping is supported", code="validation_error", category="validation", details=validation_details)
    if action == "run_to":
        target = args.get("target")
        if not isinstance(target, dict) or set(target) != {"pc"} or type(target["pc"]) is not int or target["pc"] < 0:
            return envelope.failure("run_to requires non-negative target.pc", code="validation_error", category="validation", details=validation_details)
        if handle.current_state is not None and target["pc"] < handle.current_state.stepIndex:
            return envelope.failure("run_to cannot move backwards", code="validation_error", category="validation", details=validation_details)
    if action == "set_breakpoints":
        requested = args.get("breakpoints")
        if not isinstance(requested, list) or any(not isinstance(bp, dict) or set(bp) != {"pc"}
                or type(bp["pc"]) is not int or bp["pc"] < 0 for bp in requested):
            return envelope.failure("Breakpoints require non-negative pc only", code="validation_error", category="validation", details=validation_details)
    if action == "get_variables" and (type(args.get("expand_depth", 2)) is not int or args.get("expand_depth", 2) < 0
            or type(args.get("max_variables", 2048)) is not int or args.get("max_variables", 2048) < 1):
        return envelope.failure("Variable depth must be non-negative and count positive", code="validation_error", category="validation", details=validation_details)
    replay_before = live_state._runtime.replays.get(session_id)
    event_before = replay_before.active_event_id if replay_before is not None else None
    controller = await replay_access._get_controller(session_id)

    async def continue_once() -> Optional[Any]:
        if not handle.pending_states:
            states = await renderdoc_api._offload(controller.ContinueDebug, handle.debugger)
            if not states:
                return None
            handle.pending_states.extend(states)
        state = handle.pending_states.popleft()
        for change in state.changes:
            before_name = str(change.before.name or "")
            after_name = str(change.after.name or "")
            if before_name and before_name != after_name:
                handle.variables.pop(before_name, None)
            if after_name:
                handle.variables[after_name] = shader_values._shader_variable_payload(change.after)
        handle.current_state = state
        return state

    if action == "step":
        state = await continue_once()
        if state is None:
            handle.stopped_reason = "finished"
            return envelope.success(state={}, stopped_reason="finished")
        return envelope.success(state=shader_debug._shader_debug_state_payload(handle))
    if action == "continue":
        timeout_ms = coerce._as_int(args.get("timeout_ms"), 10000)
        deadline = settings._now_ms() + timeout_ms
        state = None
        while settings._now_ms() < deadline:
            state = await continue_once()
            if state is None:
                handle.stopped_reason = "finished"
                return envelope.success(state={}, stopped_reason="finished")
            if handle.breakpoints:
                pc = int(getattr(state, "stepIndex", 0))
                if any(bp.get("pc") == pc for bp in handle.breakpoints):
                    handle.stopped_reason = "breakpoint"
                    return envelope.success(state=shader_debug._shader_debug_state_payload(handle), stopped_reason="breakpoint")
        handle.stopped_reason = "timeout"
        return envelope.success(state=shader_debug._shader_debug_state_payload(handle), stopped_reason="timeout")
    if action == "run_to":
        target = coerce._as_dict(args.get("target"), default={})
        target_pc = target.get("pc")
        if target_pc is None:
            return envelope.failure("run_to currently supports target.pc only", code="runtime_error")
        if handle.current_state is None and int(target_pc) == 0:
            return envelope.success(state=shader_debug._shader_debug_state_payload(handle))
        if handle.current_state is not None:
            current_pc = int(getattr(handle.current_state, "stepIndex", 0))
            if current_pc == int(target_pc):
                return envelope.success(state=shader_debug._shader_debug_state_payload(handle))
        timeout_ms = coerce._as_int(args.get("timeout_ms"), 10000)
        deadline = settings._now_ms() + timeout_ms
        while settings._now_ms() < deadline:
            state = await continue_once()
            if state is None:
                handle.stopped_reason = "finished"
                return envelope.success(state={}, stopped_reason="finished")
            pc = int(getattr(state, "stepIndex", 0))
            if pc == int(target_pc):
                return envelope.success(state=shader_debug._shader_debug_state_payload(handle))
        return envelope.failure("run_to timeout", code="runtime_error")
    if action == "set_breakpoints":
        bps = coerce._as_list(args.get("breakpoints"), default=[])
        handle.breakpoints = [coerce._as_dict(bp) for bp in bps]
        return envelope.success(active_breakpoints=handle.breakpoints)
    if action == "clear_breakpoints":
        handle.breakpoints = []
        return envelope.success()
    if action == "get_variables":
        name_filter = str(args.get("name_filter", ""))
        expand_depth = coerce._as_int(args.get("expand_depth"), 2)
        max_variables = coerce._as_int(args.get("max_variables"), 2048)

        variables = [shader_debug._bounded_debug_variable(variable, expand_depth)
                     for name, variable in shader_debug._shader_debug_variable_snapshot(handle).items() if name_filter in name]
        return envelope.success(variables=variables[:max_variables], truncated=len(variables) > max_variables)
    if action == "evaluate_expression":
        coerce._require(args, "expression")
        expr = str(args["expression"])
        variables_result = await dispatch("get_variables", {"session_id": session_id, "shader_debug_id": debug_id})
        if not variables_result.ok:
            return variables_result
        values = {var["name"]: var.get("value") for var in variables_result.data.get("variables", [])}
        if expr in values:
            return envelope.success(value=values[expr])
        try:
            literal = json.loads(expr)
        except Exception:
            literal = None
        else:
            return envelope.success(value=literal)
        preserved = (replay_before is not None and live_state._runtime.replays.get(session_id) is replay_before
                     and replay_before.active_event_id == event_before
                     and live_state._runtime.shader_debugs.get(debug_id) is handle)
        details = {"session_id": session_id, "shader_debug_id": debug_id}
        if preserved:
            details.update({"failure_stage": "evaluate_expression", "effects_attempted": False, "context_preserved": True})
        return envelope.failure(f"Unknown expression or variable: {expr}", code="expression_not_found",
                                category="validation" if preserved else "runtime", details=details)
    if action == "get_callstack":
        state = handle.current_state
        callstack = [] if state is None else [
            {"function": str(name), "file": None, "line": None, "pc": int(state.stepIndex)}
            for name in state.callstack
        ]
        return envelope.success(callstack=callstack)
    if action == "finish":
        if handle.trace is not None:
            await renderdoc_api._offload(controller.FreeTrace, handle.trace)
        live_state._runtime.shader_debugs.pop(debug_id, None)
        return envelope.success()

    return envelope.failure(f"Unsupported debug action: {action}", code="runtime_error")
