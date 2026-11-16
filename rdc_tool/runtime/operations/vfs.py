"""rd.vfs.* operations."""

from __future__ import annotations

from typing import Any, Dict

from rdc_tool.runtime import coerce, envelope, vfs_tree


async def dispatch(action: str, args: Dict[str, Any]) -> envelope.Outcome:
    path = vfs_tree._vfs_normalize_path(args.get("path"))
    if args.get("projection") is not None and action != "ls":
        return envelope.failure(
            f"rd.vfs.{action} does not support tabular projection",
            code="projection_not_supported",
            category="validation",
            details={"tool_name": f"rd.vfs.{action}", "supported_projection": "tabular", "supported_actions": ["ls"]},
        )
    if action == "ls":
        node = await vfs_tree._vfs_resolve_node(path, args)
        entries = list(node.get("entries") or [])
        projection = envelope._projection_request(args, "rd.vfs.ls")
        if projection:
            return envelope.success(
                path=path,
                node=node,
                entries=entries,
                projections=envelope._vfs_entries_projection(
                    entries,
                    include_tsv_text=bool(projection.get("include_tsv_text", False)),
                ),
            )
        return envelope.success(path=path, node=node, entries=entries)
    if action == "cat":
        node = await vfs_tree._vfs_resolve_node(path, args)
        return envelope.success(path=path, node=node)
    if action == "resolve":
        node = await vfs_tree._vfs_resolve_node(path, args)
        return envelope.success(path=path, node=node)
    if action == "tree":
        depth = max(0, coerce._as_int(args.get("depth"), 2))
        budget = {"max_nodes": max(1, coerce._as_int(args.get("max_nodes"), 2000)), "emitted_nodes": 0, "truncated": False}
        tree = await vfs_tree._vfs_build_tree(path, args, depth, budget)
        truncation_reason = "max_nodes_exceeded" if budget.get("truncated") else "upstream_pagination_truncated" if budget.get("upstream_truncated") else ""
        return envelope.success(path=path, tree=tree, max_nodes=budget["max_nodes"], emitted_nodes=budget["emitted_nodes"], truncated=bool(truncation_reason), truncation_reason=truncation_reason)
    return envelope.failure(f"Unsupported vfs action: {action}", code="runtime_error")
