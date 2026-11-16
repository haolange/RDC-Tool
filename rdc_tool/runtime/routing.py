"""Route an rd.* operation to its namespace module after argument and prerequisite checks."""

from __future__ import annotations

from types import MappingProxyType, ModuleType
from typing import Any, Dict, Mapping

from rdc_tool.core.errors import NotFoundError
from rdc_tool.runtime import context_records, envelope, live_state, replay_access
from rdc_tool.runtime.operations import (
    buffer,
    capture,
    core,
    debug,
    diag,
    event,
    export,
    macro,
    mesh,
    perf,
    pipeline,
    remote,
    replay,
    resource,
    session,
    shader,
    texture,
    util,
    vfs,
)
from rdc_tool.runtime_catalog import OPERATION_INDEX, validate_operation_arguments

OPERATION_MODULES: Mapping[str, ModuleType] = MappingProxyType({
    module.__name__.rsplit(".", 1)[1]: module
    for module in (buffer, capture, core, debug, diag, event, export, macro, mesh, perf, pipeline, remote, replay,
                   resource, session, shader, texture, util, vfs)
})


def _prerequisite_error(tool_name: str, requirement: str, via_tools: list[str], reason: str) -> envelope.Failure:
    return envelope.failure(
        f"{tool_name} requires {requirement} before execution",
        code=f"missing_prerequisite_{requirement.replace('.', '_')}",
        details={"prerequisite": requirement, "via_tools": list(via_tools), "reason": reason, "tool_name": tool_name},
    )


def _when_applies(args: Dict[str, Any], when: str) -> bool:
    if not when:
        return True
    if when == "options.remote_id_present":
        options = args.get("options")
        return isinstance(options, dict) and str(options.get("remote_id") or "").strip() != ""
    return False


def _has_prerequisite(requirement: str, args: Dict[str, Any]) -> bool:
    snapshot = context_records._context_snapshot()
    runtime_state = snapshot.get("runtime", {}) if isinstance(snapshot, dict) else {}
    remote_state = snapshot.get("remote", {}) if isinstance(snapshot, dict) else {}
    if requirement == "capture_file_id":
        return bool(str(args.get("capture_file_id") or runtime_state.get("capture_file_id") or "").strip())
    if requirement == "session_id":
        return bool(str(args.get("session_id") or runtime_state.get("session_id") or "").strip())
    if requirement == "remote_id":
        if str(args.get("remote_id") or "").strip():
            return True
        options = args.get("options")
        if isinstance(options, dict) and str(options.get("remote_id") or "").strip():
            return True
        return bool(str(remote_state.get("remote_id") or "").strip())
    if requirement == "active_event_id":
        return int(args.get("event_id") or runtime_state.get("active_event_id") or 0) > 0
    if requirement == "capability.remote":
        return bool(live_state._runtime.enable_remote)
    return True


def _unmet_prerequisite(tool_name: str, args: Dict[str, Any]) -> envelope.Failure | None:
    for item in OPERATION_INDEX[tool_name].get("prerequisites", []):
        requirement = str(item.get("requires") or "").strip()
        if not requirement or not _when_applies(args, str(item.get("when") or "").strip()) or _has_prerequisite(requirement, args):
            continue
        via_tools = [str(name).strip() for name in item.get("via_tools", []) if str(name).strip()]
        return _prerequisite_error(tool_name, requirement, via_tools, str(item.get("reason") or "").strip())
    return None


async def route(operation: str, args: Dict[str, Any]) -> envelope.Outcome:
    definition = OPERATION_INDEX.get(operation)
    if definition is None:
        raise NotFoundError(f"Unsupported operation: {operation}")
    _, namespace, action = operation.split(".")
    module = OPERATION_MODULES[namespace]
    try:
        validate_operation_arguments(operation, args)
    except ValueError as exc:
        return envelope.failure(str(exc), code="validation_error", category="validation")
    unmet = _unmet_prerequisite(operation, args)
    if unmet is not None:
        return unmet
    if "lifecycle" in (definition.get("effects") or ()):
        return await module.dispatch(action, dict(args))
    async with replay_access._replay_operation_health(operation):
        return await module.dispatch(action, dict(args))
