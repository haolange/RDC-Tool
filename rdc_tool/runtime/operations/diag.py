"""rd.diag.* operations."""

from __future__ import annotations

from typing import Any, Dict, List

from rdc_tool.runtime import coerce, envelope, replay_access
from rdc_tool.runtime.operations import pipeline as pipeline_ops


@replay_access._guard_rejection
async def dispatch(action: str, args: Dict[str, Any]) -> envelope.Outcome:
    coerce._require(args, "session_id")
    session_id = str(args["session_id"])
    state_result = await pipeline_ops.dispatch("get_state", {"session_id": session_id})
    if not state_result.ok:
        return state_result
    summary = state_result.data.get("pipeline_state", {})
    issues: List[Dict[str, Any]] = []

    if action == "scan_common_issues":
        rt_count = len(summary.get("render_targets", []))
        if rt_count == 0:
            issues.append({"severity": "error", "check": "render_targets", "message": "No render targets bound."})
        if not summary.get("shaders"):
            issues.append({"severity": "warn", "check": "shaders", "message": "No shader is bound at active event."})
        if not summary.get("topology"):
            issues.append({"severity": "warn", "check": "topology", "message": "Primitive topology is empty."})
        severity = str(args.get("severity_min", "info"))
        levels = {"info": 0, "warn": 1, "warning": 1, "error": 2}
        if severity not in levels:
            return envelope.failure("Unknown severity_min", code="validation_error")
        issues = [issue for issue in issues if levels[issue["severity"]] >= levels[severity]]
        return envelope.success(issues=issues, suggestions=["Check active event", "Verify drawcall context"] if coerce._as_bool(args.get("include_suggestions"), True) else [])


    return envelope.failure(f"Unsupported diag action: {action}", code="runtime_error")
