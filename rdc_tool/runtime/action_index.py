"""Flattening and indexing the action tree."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

from rdc_tool.runtime import renderdoc_api


def _flatten_actions(actions: Sequence[Any], out: Optional[List[Any]] = None) -> List[Any]:
    if out is None:
        out = []
    for action in actions:
        out.append(action)
        children = getattr(action, "children", None) or []
        _flatten_actions(children, out)
    return out


def _build_action_index(actions: Sequence[Any]) -> Tuple[List[Any], Dict[int, Any]]:
    flat = _flatten_actions(actions)
    by_event: Dict[int, Any] = {}
    for action in flat:
        event_id = int(getattr(action, "eventId", 0))
        if event_id > 0 and event_id not in by_event:
            by_event[event_id] = action
    return flat, by_event


def _pick_default_event_id(actions: Sequence[Any]) -> int:
    flat, _ = _build_action_index(actions)
    for action in flat:
        flags = _map_action_flags(getattr(action, "flags", 0))
        if flags.get("is_draw") or flags.get("is_dispatch"):
            return int(getattr(action, "eventId", 0))
    return int(getattr(flat[0], "eventId", 0)) if flat else 0


def _action_name(action: Any) -> str:
    return str(getattr(action, "customName", "") or getattr(action, "name", "") or "")


def _map_action_flags(flags: Any) -> Dict[str, bool]:
    try:
        rd = renderdoc_api._get_rd()
        af = rd.ActionFlags
    except Exception:
        return {}

    def _hf(name: str) -> bool:
        member = getattr(af, name, None)
        if member is None:
            return False
        try:
            return bool(flags & member)
        except Exception:
            return False

    return {
        "is_draw": _hf("Drawcall") or _hf("Draw"),
        "is_dispatch": _hf("Dispatch") or _hf("MeshDispatch") or _hf("DispatchRay"),
        "is_marker": _hf("SetMarker") or _hf("PushMarker") or _hf("PopMarker"),
        "is_copy": _hf("Copy"),
        "is_resolve": _hf("Resolve"),
        "is_clear": _hf("Clear"),
        "is_pass_boundary": _hf("Present") or _hf("PassBoundary"),
    }


def _action_to_dict(action: Any, *, include_children: bool = True, depth: int = 0) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "event_id": int(getattr(action, "eventId", 0)),
        "name": _action_name(action),
        "flags": _map_action_flags(getattr(action, "flags", 0)),
        "num_indices": int(getattr(action, "numIndices", 0)),
        "num_instances": int(getattr(action, "numInstances", 0)),
        "num_vertices": int(getattr(action, "numIndices", 0)),
        "depth": depth,
    }
    outputs = getattr(action, "outputs", None) or []
    if outputs:
        payload["outputs"] = [str(o) for o in outputs]
    if include_children:
        children = getattr(action, "children", None) or []
        payload["children"] = [_action_to_dict(c, include_children=True, depth=depth + 1) for c in children]
    return payload
