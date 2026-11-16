"""Access to the RenderDoc binding: import, status checks and shader stages."""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

from rdc_tool.core.errors import CoreError, RuntimeToolError
from rdc_tool.core.renderdoc_status import (
    build_renderdoc_error_details,
)
from rdc_tool.core.renderdoc_status import status_ok as _rd_status_ok
from rdc_tool.core.renderdoc_status import status_text as _rd_status_text
from rdc_tool.runtime_bootstrap import bootstrap_renderdoc_runtime


async def _offload(fn: Any, *args: Any, **kwargs: Any) -> Any:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: fn(*args, **kwargs))


def _get_rd() -> Any:
    bootstrap_renderdoc_runtime(probe_import=False)
    import renderdoc as rd
    return rd


def _status_ok(status: Any) -> bool:
    return _rd_status_ok(status, _get_rd())


def _status_text(status: Any) -> str:
    return _rd_status_text(status)


def _check_status(
    status: Any,
    operation: str,
    *,
    backend_type: str = "local",
    capture_context: Optional[Dict[str, Any]] = None,
    classification: str = "renderdoc_status",
    fix_hint: str = "Inspect the RenderDoc status and capture context before retrying.",
) -> None:
    if not _status_ok(status):
        details = build_renderdoc_error_details(
            status,
            operation=operation,
            source_layer="renderdoc_status",
            backend_type=backend_type,
            capture_context=capture_context,
            classification=classification,
            fix_hint=fix_hint,
        )
        raise RuntimeToolError(
            f"{operation} failed with status: {details['renderdoc_status']['status_text']}",
            details=details,
        )


def _renderdoc_version_value() -> str:
    try:
        rd = _get_rd()
        if hasattr(rd, "GetVersionString"):
            return str(rd.GetVersionString())
    except Exception:
        pass
    return "unknown"


def _is_null_resource_id(resource_id: Any) -> bool:
    if resource_id is None:
        return True
    text = str(resource_id or "").strip()
    if text in {"", "0", "ResourceId::0"}:
        return True
    rd = _get_rd()
    try:
        return resource_id == rd.ResourceId()
    except Exception:
        return False


def _parse_stage(stage: Optional[str]) -> str:
    if stage is None:
        return "ps"
    return str(stage).strip().lower()


def _rd_stage(stage: str) -> Any:
    name = str(stage).strip().lower()
    details = {"requested_stage": stage, "allowed_stages": _stage_candidates(),
               "failure_stage": "validate_stage"}
    if name == "rt":
        raise CoreError(code="shader_stage_unsupported", category="capability",
                        message="Ray-tracing stage inspection is not supported", details=details)
    if name not in _stage_candidates():
        raise CoreError(code="invalid_shader_stage", category="validation",
                        message=f"Invalid shader stage: {stage}", details=details)
    mapping = {
        "vs": "Vertex", "hs": "Hull", "ds": "Domain", "gs": "Geometry",
        "ps": "Pixel", "cs": "Compute", "ms": "Mesh", "as": "Amplification",
    }
    native_stage = getattr(_get_rd().ShaderStage, mapping[name], None)
    if native_stage is None:
        raise CoreError(code="shader_stage_unsupported", category="capability",
                        message=f"Native runtime does not expose shader stage: {stage}", details=details)
    return native_stage


def _stage_candidates() -> List[str]:
    return ["vs", "hs", "ds", "gs", "ps", "cs", "ms", "as"]
