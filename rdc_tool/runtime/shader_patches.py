"""Shader source inputs, edit plans and replacement bookkeeping."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from rdc_tool.context_snapshot import normalize_context_id
from rdc_tool.core.errors import RuntimeToolError
from rdc_tool.core.patch_engine import PatchEngine
from rdc_tool.models import PatchSpec, ShaderStage
from rdc_tool.runtime import (
    coerce,
    context_records,
    envelope,
    live_state,
    remote_records,
    renderdoc_api,
    replay_access,
    settings,
)


def _shader_encoding_name(value: Any) -> str:
    rd = renderdoc_api._get_rd()
    try:
        raw_value = int(value)
    except Exception:
        raw_value = None
    if raw_value is not None:
        for name in dir(rd.ShaderEncoding):
            if name.startswith("_"):
                continue
            try:
                if int(getattr(rd.ShaderEncoding, name)) != raw_value:
                    continue
            except Exception:
                continue
            mapping = {
                "SPIRVAsm": "spirvasm",
                "SPIRV": "spirv",
                "DXBC": "dxbc",
                "DXIL": "dxil",
                "HLSL": "hlsl",
                "GLSL": "glsl",
                "Slang": "slang",
            }
            return mapping.get(name, str(name).strip().lower())
    text = str(value or "").strip()
    if "." in text:
        text = text.rsplit(".", 1)[-1]
    return text.lower()


def _shader_binary_suffix(container: str) -> str:
    normalized = str(container or "").strip().lower()
    mapping = {
        "dxbc": ".dxbc",
        "dxil": ".dxil",
        "spirv": ".spv",
        "spirvasm": ".spvasm",
        "spirv_asm": ".spvasm",
        "glsl": ".glsl",
        "hlsl": ".hlslbin",
    }
    return mapping.get(normalized, ".bin")


def _normalize_shader_source_input(args: Dict[str, Any]) -> Dict[str, Any]:
    source_text = str(args.get("source_text") or "")
    source_path = str(args.get("source_path") or "").strip()
    if args.get("source") is not None:
        raise ValueError("Unknown shader source parameter; use source_text or source_path")
    if source_text and source_path:
        raise ValueError("Use only one shader source input: source_text or source_path")
    include_dirs = [str(item).strip() for item in coerce._as_list(args.get("include_dirs"), default=[]) if str(item).strip()]
    if source_path:
        path = Path(source_path).expanduser()
        if not path.is_file():
            raise FileNotFoundError(f"Shader source file not found: {source_path}")
        resolved = path.resolve()
        resolved_path = str(resolved)
        source = resolved.read_text(encoding="utf-8-sig")
        include_dirs = [str(resolved.parent), *include_dirs]
        source_kind = "source_path"
    else:
        source = source_text
        resolved_path = ""
        source_kind = "source_text"
    normalized_include_dirs: List[str] = []
    for item in include_dirs:
        if item and item not in normalized_include_dirs:
            normalized_include_dirs.append(item)
    if not source:
        raise ValueError("Missing required shader source input: source_text or source_path")
    return {
        "source": source,
        "source_kind": source_kind,
        "resolved_source_path": resolved_path,
        "include_dirs": normalized_include_dirs,
    }


def _shader_raw_bytes(reflection: Any) -> bytes:
    raw_bytes = getattr(reflection, "rawBytes", None)
    if raw_bytes is None:
        return b""
    try:
        return bytes(raw_bytes)
    except Exception:
        pass
    try:
        return raw_bytes.tobytes()
    except Exception:
        return b""


def _shader_edit_plan(
    *,
    source_encoding: str = "",
    disassembly_target: str = "",
    source: str = "",
    source_available: bool = True,
) -> Dict[str, Any]:
    plan = PatchEngine._edit_plan_for_source(
        encoding_name=str(source_encoding or ""),
        disassembly_target=str(disassembly_target or ""),
        source=str(source or ""),
    )
    if source_available:
        return plan
    plan.update({
        "can_edit_text": False, "can_build": False, "can_replace": False,
        "allowed_edit_inputs": [], "allowed_ops": [], "build_input_kind": "unsupported", "requires_toolchain": [],
    })
    encoding_key = str(source_encoding or "").strip().lower().replace("_", "")
    if encoding_key == "dxil":
        plan["input_kind"] = "source_unavailable"
        plan["recommended_next_tool"] = "rd.shader.get_disassembly"
        plan["fallback_tools"] = ["rd.shader.get_disassembly", "rd.shader.extract_binary"]
        plan["blocked_reason"] = (
            "DXIL debug source is unavailable. Request target='DXIL ASM' from "
            "rd.shader.get_disassembly and inspect its edit_plan before replacement."
        )
        return plan
    if encoding_key == "dxbc":
        plan["input_kind"] = "renderdoc_disassembly"
        plan["recommended_next_tool"] = "rd.shader.get_disassembly"
        plan["fallback_tools"] = ["rd.shader.get_disassembly", "rd.shader.extract_binary"]
        plan["blocked_reason"] = (
            f"{encoding_key.upper()} debug source is unavailable. "
            "Use rd.shader.get_disassembly for read-only inspection and "
            "rd.shader.extract_binary for the raw container; do not pass DXIL/DXBC "
            "disassembly text to rd.shader.edit_and_replace."
        )
        return plan
    if encoding_key in {"spirv", "spirvasm", "openglspirv", "openglspirvasm"}:
        plan["input_kind"] = "source_unavailable"
        plan["recommended_next_tool"] = "rd.shader.get_disassembly"
        plan["fallback_tools"] = ["rd.shader.get_disassembly"]
        plan["blocked_reason"] = (
            "Original shader source is unavailable. Request target='SPIR-V ASM' from "
            "rd.shader.get_disassembly and inspect that result's edit_plan before replacement."
        )
        return plan
    plan["input_kind"] = "unsupported"
    plan["recommended_next_tool"] = "rd.shader.get_disassembly"
    plan["fallback_tools"] = ["rd.shader.get_disassembly", "rd.shader.extract_binary"]
    return plan


def _shader_source_fallback_args(
    *,
    session_id: str,
    event_id: int,
    stage: str,
    shader_id: str,
    source_encoding: str,
) -> Dict[str, Any]:
    encoding_key = str(source_encoding or "").strip().lower().replace("_", "")
    args: Dict[str, Any] = {
        "session_id": session_id,
        "event_id": int(event_id),
        "stage": stage.upper(),
        "shader_id": shader_id,
        "target": "auto",
    }
    if encoding_key in {"spirv", "spirvasm", "openglspirv", "openglspirvasm"}:
        args["target"] = "SPIR-V ASM"
        args["source_encoding"] = "spirvasm"
    elif encoding_key == "dxil":
        args["target"] = "DXIL ASM"
        args["source_encoding"] = "dxilasm"
    return args


def _replacement_from_spec(spec: Any) -> Dict[str, Any]:
    stage = getattr(getattr(spec, "target_stage", None), "value", getattr(spec, "target_stage", ""))
    return {
        "replacement_id": str(getattr(spec, "patch_id", "") or ""),
        "stage": str(stage or "").upper(),
        "resolved_event_id": int(getattr(spec, "target_event_id", 0) or 0),
        "original_shader_id": str(getattr(spec, "target_shader_id", "") or ""),
        "status": "applied",
        "messages": [],
    }


def _patch_spec_payload_from_spec(spec: PatchSpec) -> Dict[str, Any]:
    if hasattr(spec, "model_dump"):
        return dict(spec.model_dump(mode="json"))
    return json.loads(json.dumps(spec, default=envelope._json_default))


def _patch_spec_payload_from_args(
    patch_spec: PatchSpec,
    *,
    ops_payload: Sequence[Any],
    source_text: str,
    diff_text: str,
    source_target: str,
    source_encoding: str,
    expected_source_hash: str,
    max_diff_ops: int,
    preserve_outputs: bool,
) -> Dict[str, Any]:
    payload = _patch_spec_payload_from_spec(patch_spec)
    payload.update(
        {
            "ops": list(ops_payload or []),
            "source_text": str(source_text or ""),
            "diff_text": str(diff_text or ""),
            "source_target": str(source_target or ""),
            "source_encoding": str(source_encoding or ""),
            "expected_source_hash": str(expected_source_hash or ""),
            "max_diff_ops": int(max_diff_ops or 0),
            "preserve_outputs": bool(preserve_outputs),
        }
    )
    return payload


def _replacement_patch_spec_payload(replacement: Dict[str, Any]) -> Dict[str, Any]:
    patch_spec = replacement.get("patch_spec")
    if isinstance(patch_spec, dict):
        return dict(patch_spec)
    return {}


def _sync_context_session_replacements(
    session_id: str,
    replacements: Optional[Sequence[Dict[str, Any]]] = None,
    *,
    context_id: Optional[str] = None,
) -> None:
    ctx = normalize_context_id(context_id or live_state._runtime_context_id())
    state = context_records._context_state(ctx)
    sessions = state.setdefault("sessions", {})
    record = dict(sessions.get(str(session_id)) or {})
    if not record:
        return
    entries = [
        dict(item)
        for item in (replacements if replacements is not None else context_records._replacement_metadata_entries(str(session_id)))
        if isinstance(item, dict) and str(item.get("replacement_id") or "").strip()
    ]
    record["shader_replacements"] = entries
    record["updated_at_ms"] = settings._now_ms()
    sessions[str(session_id)] = record
    state["sessions"] = sessions
    context_records._store_context_state(state, ctx)
    context_records._sync_context_snapshot_from_state(ctx)


async def _reapply_session_replacements_from_record(
    session_id: str,
    session_record: Dict[str, Any],
) -> List[Dict[str, Any]]:
    if live_state._patch_engine is None:
        return []
    persisted = session_record.get("shader_replacements")
    if not isinstance(persisted, list) or not persisted:
        return []
    reapplied: List[Dict[str, Any]] = []
    for item in persisted:
        replacement = dict(item or {}) if isinstance(item, dict) else {}
        if str(replacement.get("status") or "") != "applied":
            continue
        spec_payload = _replacement_patch_spec_payload(replacement)
        if not spec_payload:
            raise RuntimeToolError(
                "Persisted shader replacement is missing patch_spec",
                details={
                    "session_id": str(session_id),
                    "replacement_id": str(replacement.get("replacement_id") or ""),
                },
            )
        patch_spec = PatchSpec.model_validate(spec_payload)
        event_id = int(spec_payload.get("target_event_id") or replacement.get("resolved_event_id") or 0)
        stage = ShaderStage(str(spec_payload.get("target_stage") or replacement.get("stage") or "").lower())
        patch_result = await live_state._patch_engine.apply_patch(
            session_id=str(session_id),
            event_id=event_id,
            stage=stage,
            session_manager=live_state._session_manager,
            patch_spec=patch_spec,
        )
        if not patch_result.success:
            raise RuntimeToolError(
                patch_result.error_message or "Persisted shader replacement reapply failed",
                details={
                    "session_id": str(session_id),
                    "replacement_id": patch_spec.patch_id,
                    "code": patch_result.error_code or "shader_replace_reapply_failed",
                    "category": patch_result.error_category or "runtime",
                    "details": dict(patch_result.error_details or {}),
                },
            )
        updated = {
            **replacement,
            "replacement_id": patch_spec.patch_id,
            "stage": str(getattr(patch_spec.target_stage, "value", patch_spec.target_stage)).upper(),
            "resolved_event_id": int(event_id or 0),
            "original_shader_id": str(patch_spec.target_shader_id),
            "status": "applied",
            "messages": list(patch_result.messages or replacement.get("messages") or []),
            "applied_to_shader_hash": patch_result.applied_to_shader_hash,
            "original_shader_hash": patch_result.original_shader_hash,
            "compile": {
                "encoding": str(patch_result.encoding or dict(replacement.get("compile") or {}).get("encoding") or ""),
                "disassembly_target": str(patch_result.disassembly_target or dict(replacement.get("compile") or {}).get("disassembly_target") or ""),
                "entry_point": str(patch_result.entry_point or dict(replacement.get("compile") or {}).get("entry_point") or ""),
                "compile_flags": list(patch_result.compile_flags or dict(replacement.get("compile") or {}).get("compile_flags") or []),
            },
            "patch_spec": spec_payload,
            "reapplied_at_ms": settings._now_ms(),
        }
        reapplied.append(updated)
    if reapplied:
        live_state._runtime.shader_replacements[str(session_id)] = reapplied
    return reapplied


def _active_replacement_specs(session_id: str) -> Optional[List[Any]]:
    if live_state._patch_engine is None or not hasattr(live_state._patch_engine, "list_patches"):
        return None
    try:
        specs = list(live_state._patch_engine.list_patches(session_id))
    except Exception:
        return None
    return specs


def _list_replacement_payloads(session_id: str) -> List[Dict[str, Any]]:
    metadata_entries = context_records._replacement_metadata_entries(session_id)
    specs = _active_replacement_specs(session_id)
    if specs is None:
        return metadata_entries

    metadata_by_id = {str(item.get("replacement_id") or ""): item for item in metadata_entries}
    ordered: List[Dict[str, Any]] = []
    for spec in specs:
        replacement_id = str(getattr(spec, "patch_id", "") or "")
        if not replacement_id:
            continue
        ordered.append(dict(metadata_by_id.get(replacement_id) or _replacement_from_spec(spec)))
    live_state._runtime.shader_replacements[session_id] = [dict(item) for item in ordered]
    return ordered


def _store_replacement_payload(session_id: str, replacement: Dict[str, Any]) -> None:
    replacement_id = str(replacement.get("replacement_id") or "")
    entries = [
        dict(item)
        for item in context_records._replacement_metadata_entries(session_id)
        if str(item.get("replacement_id") or "") != replacement_id
    ]
    entries.append(dict(replacement))
    live_state._runtime.shader_replacements[session_id] = entries
    _sync_context_session_replacements(session_id, entries)


async def _validate_remote_replacement_persistence(
    session_id: str,
    replacement: Dict[str, Any],
) -> None:
    patch_spec = _replacement_patch_spec_payload(replacement)
    if not coerce._as_bool(patch_spec.get("preserve_outputs"), True):
        return
    replay = live_state._runtime.replays.get(str(session_id))
    if replay is None:
        return
    ctx = live_state._runtime_context_id()
    state = context_records._context_state(ctx)
    session_record = dict((state.get("sessions") or {}).get(str(session_id)) or {})
    if str(session_record.get("backend_type") or "local") != "remote":
        return
    if not remote_records._session_record_remote_metadata(session_record):
        return
    event_id = int(patch_spec.get("target_event_id") or replacement.get("resolved_event_id") or 0)
    if event_id <= 0:
        return

    try:
        controller = await replay_access._get_controller(str(session_id))
        await renderdoc_api._offload(controller.SetFrameEvent, int(event_id), True)
        outputs = await replay_access._output_target_resource_ids(str(session_id), event_id)
    except Exception as exc:
        raise RuntimeToolError(
            "Remote shader replacement could not validate live framebuffer output targets",
            details={
                "session_id": str(session_id),
                "replacement_id": str(replacement.get("replacement_id") or ""),
                "event_id": int(event_id),
                "code": "shader_replace_preserve_outputs_failed",
                "category": "runtime",
                "failure_stage": "validate_live_remote_outputs",
                "failure_reason": "live_output_target_probe_failed",
                "replacement_attempted": True,
                "cleanup_attempted": False,
                "context_preserved": True,
                "exception_type": type(exc).__name__,
            },
        ) from exc
    if not outputs:
        raise RuntimeToolError(
            "Remote shader replacement did not preserve framebuffer output targets in the live replay session",
            details={
                "session_id": str(session_id),
                "replacement_id": str(replacement.get("replacement_id") or ""),
                "event_id": int(event_id),
                "code": "shader_replace_preserve_outputs_failed",
                "category": "runtime",
                "failure_stage": "validate_live_remote_outputs",
                "failure_reason": "event_output_targets_missing_after_replacement",
                "replacement_attempted": True,
                "cleanup_attempted": False,
                "context_preserved": True,
            },
        )
