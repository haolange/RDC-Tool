"""Tool discovery, capability summaries and runtime metrics."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from rdc_tool.context_snapshot import normalize_context_id
from rdc_tool.operation_definitions import OPERATIONS
from rdc_tool.platform import host as platform_host
from rdc_tool.platform import process as platform_process
from rdc_tool.runtime import coerce, context_records, live_state
from rdc_tool.runtime_catalog import OPERATION_INDEX
from rdc_tool.runtime_state import list_context_ids, summarize_operation_durations

_MACRO_GUIDE: Dict[str, Dict[str, Any]] = {
    "rd.macro.find_state_change_point": {
        "canonical_tools": ["rd.pipeline.get_state", "rd.event.diff_pipeline_state"],
        "guidance": "Search real events within a bounded state-transition window.",
    },
}


def _tool_namespace(tool_name: str) -> str:
    parts = str(tool_name or "").split(".")
    if len(parts) < 2:
        return "rd"
    return ".".join(parts[:2])


_PRIMARY_DISCOVERY_NAMESPACE_RANKS = {
    "rd.capture": 100,
    "rd.replay": 110,
    "rd.event": 120,
    "rd.pipeline": 130,
    "rd.resource": 140,
    "rd.texture": 150,
    "rd.buffer": 160,
    "rd.mesh": 170,
    "rd.shader": 180,
    "rd.debug": 190,
    "rd.export": 200,
    "rd.remote": 210,
    "rd.diag": 220,
    "rd.perf": 230,
    "rd.util": 240,
}
_MACRO_DISCOVERY_RANK = 300
_META_DISCOVERY_RANK = 400
_NAVIGATION_DISCOVERY_RANK = 500
_NAVIGATION_QUERY_TERMS = {
    "browse",
    "path",
    "tree",
    "ls",
    "navigate",
    "vfs",
}
_TABULAR_QUERY_TERMS = {
    "table",
    "tabular",
    "tsv",
    "spreadsheet",
}
_QUERY_TOKEN_RE = re.compile(r"[a-z0-9_]+|[\u4e00-\u9fff]+")


def _tool_role(tool_name: str) -> str:
    if tool_name.startswith("rd.macro."):
        return "macro"
    if tool_name.startswith("rd.vfs."):
        return "navigation"
    return "canonical"


def _tool_mutates_state(tool_name: str) -> bool:
    definition = OPERATION_INDEX.get(tool_name)
    return bool(definition and definition.get("effects"))


def _tool_capabilities(tool: Dict[str, Any]) -> List[str]:
    name = str(tool.get("name") or "")
    capabilities: set[str] = set()
    for prereq in tool.get("prerequisites", []):
        if not isinstance(prereq, dict):
            continue
        requires = str(prereq.get("requires") or "").strip()
        if requires.startswith("capability."):
            capabilities.add(requires.split(".", 1)[1])
    if name.startswith("rd.remote."):
        capabilities.add("remote")
    if name.startswith("rd.debug.") or name.startswith("rd.shader."):
        capabilities.add("shader_debug")
    if name.startswith("rd.perf."):
        capabilities.add("counters")
    return sorted(capabilities)


def _tool_intents(tool: Dict[str, Any]) -> List[str]:
    name = str(tool.get("name") or "")
    group = str(tool.get("group") or "").lower()
    intents: set[str] = set()
    if name.startswith("rd.session.") or name.startswith("rd.capture.") or name.startswith("rd.replay."):
        intents.add("session")
    if name.startswith("rd.vfs.") or name.startswith("rd.core.list_tools"):
        intents.add("discovery")
    if name.startswith("rd.remote."):
        intents.add("remote")
    if (
        name.startswith("rd.macro.")
        or name in {"rd.diag.scan_common_issues", "rd.event.get_action_details", "rd.texture.get_pixel_history", "rd.texture.get_histogram", "rd.texture.compute_stats"}
    ):
        intents.add("analysis")
    if "artifact_write" in tool.get("effects", []):
        intents.add("export")
    if name.startswith("rd.debug.") or name.startswith("rd.shader."):
        intents.add("debug")
    if "analysis" in group and not name.startswith("rd.analysis."):
        intents.add("analysis")
    if not intents:
        intents.add("inspection")
    return sorted(intents)


def _tool_discovery_rank(tool: Dict[str, Any] | str) -> int:
    if isinstance(tool, dict):
        name = str(tool.get("name") or "")
    else:
        name = str(tool or "")
    if name.startswith("rd.vfs."):
        return _NAVIGATION_DISCOVERY_RANK
    if name.startswith("rd.macro."):
        return _MACRO_DISCOVERY_RANK
    if name.startswith("rd.session.") or name.startswith("rd.core."):
        return _META_DISCOVERY_RANK
    return _PRIMARY_DISCOVERY_NAMESPACE_RANKS.get(_tool_namespace(name), 250)


def _tool_recommended_for(tool_name: str) -> List[str]:
    if tool_name.startswith("rd.vfs."):
        return ["browse_only"]
    return []


def _tool_not_primary_for(tool_name: str) -> List[str]:
    if tool_name.startswith("rd.vfs."):
        return ["precise_debug", "export", "state_mutation", "automation"]
    return []


def _query_contains_term(query_text: str, terms: set[str]) -> bool:
    return any(term in query_text for term in terms)


def _query_tokens(query_text: str) -> List[str]:
    if not query_text:
        return []
    tokens = _QUERY_TOKEN_RE.findall(query_text)
    if tokens:
        return tokens
    return [query_text]


def _tool_supports_tabular_projection(entry: Dict[str, Any]) -> bool:
    supports_projection = entry.get("supports_projection")
    if not isinstance(supports_projection, dict):
        return False
    return bool(supports_projection.get("tabular"))


def _tool_search_haystack(entry: Dict[str, Any]) -> str:
    parts = [
        str(entry.get("name") or ""),
        str(entry.get("namespace") or ""),
        str(entry.get("group") or ""),
        str(entry.get("description") or ""),
        " ".join(str(item) for item in entry.get("capabilities", [])),
        " ".join(str(item) for item in entry.get("intents", [])),
    ]
    if _tool_supports_tabular_projection(entry):
        parts.append("tabular tsv projection table spreadsheet")
    if str(entry.get("role") or "") == "navigation":
        parts.append("browse path tree navigate vfs")
    return " ".join(parts).lower()


def _tool_matches_query(entry: Dict[str, Any], query_text: str) -> bool:
    if not query_text:
        return True
    haystack = _tool_search_haystack(entry)
    if query_text in haystack:
        return True
    tokens = _query_tokens(query_text)
    if tokens and all(token in haystack for token in tokens):
        return True
    if _query_contains_term(query_text, _NAVIGATION_QUERY_TERMS) and str(entry.get("role") or "") == "navigation":
        return True
    if _query_contains_term(query_text, _TABULAR_QUERY_TERMS) and _tool_supports_tabular_projection(entry):
        return True
    return False


def _tool_query_rank_adjustment(entry: Dict[str, Any], query_text: str) -> int:
    if not query_text:
        return 0
    adjustment = 0
    if _query_contains_term(query_text, _NAVIGATION_QUERY_TERMS) and str(entry.get("role") or "") == "navigation":
        adjustment -= 450
    if _query_contains_term(query_text, _TABULAR_QUERY_TERMS) and _tool_supports_tabular_projection(entry):
        adjustment -= 275
        if str(entry.get("role") or "") == "navigation":
            adjustment -= 450
    return adjustment


def _tool_sort_key(entry: Dict[str, Any], *, query_text: str = "") -> Tuple[int, str]:
    rank = int(entry.get("discovery_rank") or _tool_discovery_rank(entry))
    rank += _tool_query_rank_adjustment(entry, query_text)
    return (rank, str(entry.get("name") or ""))


def _tool_profile(tool: Dict[str, Any], *, detail_level: str = "summary") -> Dict[str, Any]:
    name = str(tool.get("name") or "")
    payload = {
        "name": name,
        "namespace": _tool_namespace(name),
        "group": str(tool.get("group") or ""),
        "description": str(tool.get("description") or ""),
        "role": _tool_role(name),
        "discovery_rank": _tool_discovery_rank(tool),
        "mutates_state": _tool_mutates_state(name),
        "capabilities": _tool_capabilities(tool),
        "intents": _tool_intents(tool),
        "prerequisites": list(tool.get("prerequisites") or []),
        "param_names": list(tool.get("param_names") or []),
    }
    recommended_for = _tool_recommended_for(name)
    if recommended_for:
        payload["recommended_for"] = recommended_for
    not_primary_for = _tool_not_primary_for(name)
    if not_primary_for:
        payload["not_primary_for"] = not_primary_for
    if tool.get("supports_projection") is not None:
        payload["supports_projection"] = dict(tool.get("supports_projection") or {})
    if name in _MACRO_GUIDE:
        payload["canonical_tools"] = list(_MACRO_GUIDE[name]["canonical_tools"])
        payload["guidance"] = str(_MACRO_GUIDE[name]["guidance"])
    if detail_level == "full":
        payload["parameter_raw"] = str(tool.get("parameter_raw") or "")
        payload["returns_raw"] = str(tool.get("returns_raw") or "")
    return payload


def _filter_tool_profiles(
    *,
    query: str = "",
    namespace: str = "",
    group: str = "",
    capability: str = "",
    role: str = "",
    intent: str = "",
    mutates_state: Optional[bool] = None,
    detail_level: str = "summary",
) -> List[Dict[str, Any]]:
    query_text = str(query or "").strip().lower()
    namespace_text = str(namespace or "").strip().lower()
    group_text = str(group or "").strip().lower()
    capability_text = str(capability or "").strip().lower()
    role_text = str(role or "").strip().lower()
    intent_text = str(intent or "").strip().lower()
    out: List[Dict[str, Any]] = []
    for tool in OPERATIONS:
        entry = _tool_profile(tool, detail_level=detail_level)
        if namespace_text and str(entry.get("namespace") or "").lower() != namespace_text:
            continue
        if group_text and group_text not in str(entry.get("group") or "").lower():
            continue
        if capability_text and capability_text not in [str(item).lower() for item in entry.get("capabilities", [])]:
            continue
        if role_text and str(entry.get("role") or "").lower() != role_text:
            continue
        if intent_text and intent_text not in [str(item).lower() for item in entry.get("intents", [])]:
            continue
        if mutates_state is not None and bool(entry.get("mutates_state")) != bool(mutates_state):
            continue
        if query_text and not _tool_matches_query(entry, query_text):
            continue
        out.append(entry)
    out.sort(key=lambda item: _tool_sort_key(item, query_text=query_text))
    return out


def _tool_graph_payload(*, query: str = "", namespace: str = "", intent: str = "", capability: str = "", role: str = "") -> Dict[str, Any]:
    tools = _filter_tool_profiles(
        query=query,
        namespace=namespace,
        intent=intent,
        capability=capability,
        role=role,
        detail_level="summary",
    )
    selected = {str(item.get("name") or "") for item in tools}
    edges: List[Dict[str, Any]] = []
    for tool in tools:
        name = str(tool.get("name") or "")
        for prereq in tool.get("prerequisites", []):
            if not isinstance(prereq, dict):
                continue
            for via_tool in prereq.get("via_tools", []):
                via_name = str(via_tool or "").strip()
                if via_name and via_name in selected:
                    edges.append(
                        {
                            "from": via_name,
                            "to": name,
                            "type": "prerequisite",
                            "requires": str(prereq.get("requires") or ""),
                        }
                    )
        for canonical in tool.get("canonical_tools", []):
            canonical_name = str(canonical or "").strip()
            if canonical_name and canonical_name in selected:
                edges.append({"from": name, "to": canonical_name, "type": "macro_expands_to"})
    return {"tools": tools, "edges": edges}


def _runtime_metrics_payload(context_id: Optional[str] = None) -> Dict[str, Any]:
    ctx = normalize_context_id(context_id or live_state._runtime_context_id())
    state = context_records._sync_context_metrics(ctx)
    metrics = dict(state.get("metrics") or {})
    metrics["operation_duration_summary"] = summarize_operation_durations(metrics.get("recent_operation_duration_ms") or [])
    memory = platform_process.memory_bytes()
    metrics["process_memory_bytes"] = memory
    if memory is None:
        metrics["process_memory_unavailable_reason"] = f"host {platform_host.host_target()} does not report process memory"
    metrics["live_runtime_session_count"] = len(live_state._runtime.replays)
    metrics["live_runtime_capture_count"] = len(live_state._runtime.captures)
    metrics["live_remote_count"] = len(live_state._runtime.remotes)
    known = {normalize_context_id(item) for item in list_context_ids()} | {ctx}
    metrics["known_context_count"] = len(known)
    metrics["occupying_context_count"] = len(context_records._occupying_context_ids())
    metrics["current_session_id"] = str(state.get("current_session_id") or "")
    metrics["current_capture_file_id"] = str(state.get("current_capture_file_id") or "")
    return {
        "context_id": ctx,
        "limits": dict(state.get("limits") or {}),
        "metrics": metrics,
        "recovery": dict(state.get("recovery") or {}),
        "recent_operations": list(state.get("recent_operations") or []),
    }


def _session_locator_projection(snapshot: Dict[str, Any], state: Dict[str, Any]) -> Dict[str, Any]:
    runtime = dict(snapshot.get("runtime") or {})
    sessions = state.get("sessions") if isinstance(state.get("sessions"), dict) else {}
    captures = state.get("captures") if isinstance(state.get("captures"), dict) else {}
    current_session_id = str(state.get("current_session_id") or runtime.get("session_id") or "").strip()
    session = dict(sessions.get(current_session_id) or {}) if isinstance(sessions, dict) else {}
    current_capture_file_id = str(
        state.get("current_capture_file_id")
        or session.get("capture_file_id")
        or runtime.get("capture_file_id")
        or ""
    ).strip()
    capture = dict(captures.get(current_capture_file_id) or {}) if isinstance(captures, dict) else {}
    return {
        "rdc_path": str(session.get("rdc_path") or capture.get("file_path") or capture.get("rdc_path") or "").strip(),
        "session_id": current_session_id,
        "frame_index": coerce._as_int(runtime.get("frame_index"), coerce._as_int(session.get("frame_index"), 0)),
        "active_event_id": coerce._as_int(runtime.get("active_event_id"), coerce._as_int(session.get("active_event_id"), 0)),
    }


def _context_summary(context_id: str) -> Dict[str, Any]:
    ctx = normalize_context_id(context_id)
    snapshot = context_records._context_snapshot(ctx)
    state = context_records._context_state(ctx)
    return {
        "context_id": ctx,
        "backend": str(snapshot.get("backend") or "local"),
        "session_locator": _session_locator_projection(snapshot, state),
        "current_session_id": str(state.get("current_session_id") or ""),
        "current_capture_file_id": str(state.get("current_capture_file_id") or ""),
        "session_count": len(state.get("sessions") or {}),
        "capture_count": len(state.get("captures") or {}),
        "updated_at_ms": int(snapshot.get("updated_at_ms") or 0),
    }
