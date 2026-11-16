"""Operation results and their tabular projections."""

from __future__ import annotations

from typing import Any, Dict, List, Sequence

from rdc_tool.core.contracts import TSV_FORMAT_VERSION
from rdc_tool.core.tsv_projection import project_rows, to_tsv_string
from rdc_tool.io_utils import safe_json_text
from rdc_tool.runtime import coerce


def _json_default(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if hasattr(value, "__dict__"):
        return value.__dict__
    return str(value)


def _ok(**fields: Any) -> str:
    payload: Dict[str, Any] = {"success": True}
    payload.update(fields)
    return safe_json_text(payload, default=_json_default)


def _err(message: str, **fields: Any) -> str:
    payload: Dict[str, Any] = {"success": False, "error_message": str(message)}
    payload.update(fields)
    return safe_json_text(payload, default=_json_default)


def _projection_request(args: Dict[str, Any], tool_name: str) -> Dict[str, Any]:
    projection = args.get("projection")
    if projection is None:
        return {}
    if not isinstance(projection, dict):
        raise ValueError(f"{tool_name} projection must be an object")
    kind = str(projection.get("kind") or "").strip().lower()
    if kind and kind != "tabular":
        raise ValueError(f"{tool_name} only supports projection.kind='tabular'")
    return {
        "kind": "tabular",
        "include_tsv_text": coerce._as_bool(projection.get("include_tsv_text"), False),
    }


def _tabular_projection(
    rows: Sequence[Dict[str, Any]],
    *,
    columns: Sequence[str],
    include_tsv_text: bool,
    details_json_path: str = "",
    details_json_url: str = "",
) -> Dict[str, Any]:
    normalized_rows = [
        {
            **dict(row),
            "details_json_path": str(row.get("details_json_path") or details_json_path),
            "details_json_url": str(row.get("details_json_url") or details_json_url),
        }
        for row in rows
    ]
    header, body = project_rows(normalized_rows, columns=columns, format_version=TSV_FORMAT_VERSION)
    tabular: Dict[str, Any] = {
        "format_version": TSV_FORMAT_VERSION,
        "columns": header,
        "rows": body,
        "row_count": len(body),
    }
    if details_json_path:
        tabular["details_json_path"] = str(details_json_path)
    if details_json_url:
        tabular["details_json_url"] = str(details_json_url)
    if include_tsv_text:
        tabular["tsv_text"] = to_tsv_string(normalized_rows, columns=columns, format_version=TSV_FORMAT_VERSION)
    return {"tabular": tabular}


def _vfs_entries_projection(entries: Sequence[Dict[str, Any]], *, include_tsv_text: bool) -> Dict[str, Any]:
    rows = [
        {
            "name": str(entry.get("name") or ""),
            "path": str(entry.get("path") or ""),
            "kind": str(entry.get("kind") or ""),
            "title": str(entry.get("title") or ""),
            "summary": str(entry.get("summary") or ""),
            "requires_session": bool(entry.get("requires_session", False)),
            "exists": bool(entry.get("exists", True)),
        }
        for entry in entries
        if isinstance(entry, dict)
    ]
    return _tabular_projection(
        rows,
        columns=["name", "path", "kind", "title", "summary", "requires_session", "exists"],
        include_tsv_text=include_tsv_text,
    )


def _artifact_rows_projection(artifacts: Sequence[Dict[str, Any]], *, include_tsv_text: bool) -> Dict[str, Any]:
    rows = [
        {
            "artifact_id": str(item.get("artifact_id") or ""),
            "type": str(item.get("type") or ""),
            "path": str(item.get("path") or ""),
            "url": str(item.get("url") or ""),
            "mime": str(item.get("mime") or ""),
            "size_bytes": int(item.get("size_bytes") or 0),
            "storage_backend": str(item.get("storage_backend") or ""),
        }
        for item in artifacts
        if isinstance(item, dict)
    ]
    return _tabular_projection(
        rows,
        columns=["artifact_id", "type", "path", "url", "mime", "size_bytes", "storage_backend"],
        include_tsv_text=include_tsv_text,
    )


def _event_actions_projection(actions: Sequence[Dict[str, Any]], *, include_tsv_text: bool) -> Dict[str, Any]:
    rows: List[Dict[str, Any]] = []

    def visit(item: Dict[str, Any]) -> None:
        flags = coerce._as_dict(item.get("flags"), default={})
        outputs = item.get("outputs")
        rows.append(
            {
                "event_id": int(item.get("event_id") or 0),
                "name": str(item.get("name") or ""),
                "depth": int(item.get("depth") or 0),
                "is_draw": bool(flags.get("is_draw", False)),
                "is_dispatch": bool(flags.get("is_dispatch", False)),
                "is_marker": bool(flags.get("is_marker", False)),
                "is_pass_boundary": bool(flags.get("is_pass_boundary", False)),
                "num_indices": int(item.get("num_indices") or 0),
                "num_vertices": int(item.get("num_vertices") or 0),
                "outputs": ",".join(str(value) for value in outputs) if isinstance(outputs, list) else "",
            },
        )
        for child in item.get("children") or []:
            if isinstance(child, dict):
                visit(child)

    for action in actions:
        if isinstance(action, dict):
            visit(action)
    return _tabular_projection(
        rows,
        columns=[
            "event_id",
            "name",
            "depth",
            "is_draw",
            "is_dispatch",
            "is_marker",
            "is_pass_boundary",
            "num_indices",
            "num_vertices",
            "outputs",
        ],
        include_tsv_text=include_tsv_text,
    )


def _resource_rows_projection(resources: Sequence[Dict[str, Any]], *, include_tsv_text: bool) -> Dict[str, Any]:
    rows = []
    for resource in resources:
        if not isinstance(resource, dict):
            continue
        kind = "texture" if resource.get("texture_id") else "buffer" if resource.get("buffer_id") else "resource"
        rows.append(
            {
                "resource_id": str(resource.get("resource_id") or ""),
                "kind": kind,
                "name": str(resource.get("name") or ""),
                "width": int(resource.get("width") or 0),
                "height": int(resource.get("height") or 0),
                "depth": int(resource.get("depth") or 0),
                "format": str(resource.get("format") or ""),
                "byte_size": int(resource.get("byte_size") or 0),
            },
        )
    return _tabular_projection(
        rows,
        columns=["resource_id", "kind", "name", "width", "height", "depth", "format", "byte_size"],
        include_tsv_text=include_tsv_text,
    )

def _capability_entry(
    available: bool,
    *,
    reason: str,
    optional: bool,
    source: str,
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "available": bool(available),
        "reason": str(reason or ""),
        "optional": bool(optional),
        "source": str(source),
    }
    payload.update(extra)
    return payload


def _capability_error(
    code: str,
    message: str,
    *,
    capability: str,
    reason: str,
    source: str,
    optional: bool = True,
    **details: Any,
) -> str:
    return _err(
        message,
        code=code,
        category="capability",
        details={
            "capability": capability,
            "reason": reason,
            "optional": bool(optional),
            "source": source,
            **details,
        },
    )
