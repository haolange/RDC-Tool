"""rd.shader.* operations."""

from __future__ import annotations

import difflib
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Tuple

from rdc_tool.host_tools import HostToolUnavailableError
from rdc_tool.platform import dxc
from rdc_tool.core.errors import CoreError, RuntimeToolError
from rdc_tool.core.patch_engine import PatchEngine, _compiler_output_is_fatal, _shader_build_input_provenance
from rdc_tool.models import PatchSpec, ShaderStage, _new_id
from rdc_tool.runtime import (
    artifact_payloads,
    coerce,
    context_records,
    envelope,
    live_state,
    pixel_trace,
    renderdoc_api,
    replay_access,
    shader_debug,
    shader_patches,
    shader_values,
    texture_naming,
    truth_matrix,
)


async def _disassembly_target_metadata(controller: Any) -> Dict[str, Any]:
    result = {"available_targets": [], "available_targets_status": "unsupported", "available_targets_error": None}
    native_targets = getattr(controller, "GetDisassemblyTargets", None)
    if callable(native_targets):
        try:
            result["available_targets"] = [str(item) for item in await renderdoc_api._offload(native_targets, True)]
            result["available_targets_status"] = "complete"
        except Exception as exc:
            replay_access._event_effect_attempted()
            result["available_targets_status"] = "unavailable"
            result["available_targets_error"] = str(exc)
    return result


@replay_access._guard_rejection
async def dispatch(action: str, args: Dict[str, Any]) -> envelope.Outcome:
    if "stage" in args:
        requested_stage = str(args["stage"]).strip()
        if requested_stage not in renderdoc_api._stage_candidates():
            return envelope.failure(
                f"Invalid shader stage: {args['stage']}",
                code="invalid_shader_stage",
                category="validation",
                details={
                    "requested_stage": requested_stage,
                    "allowed_stages": renderdoc_api._stage_candidates(),
                    "failure_stage": "validate_stage",
                    "effects_attempted": False,
                    "context_preserved": True,
                },
            )
    if action == "debug_start":
        coerce._require(args, "params")
        mode = str(args.get("mode", "pixel")).lower()
        if mode != "pixel":
            return envelope.failure(
                f"Unsupported shader debug mode: {mode}", code="validation_error", category="validation",
                details={"failure_stage": "mode_validation", "failure_reason": "debug_mode_unsupported",
                         "requested_mode": mode, "supported_modes": ["pixel"],
                         "effects_attempted": False, "context_preserved": True})
        params = coerce._as_dict(args.get("params"))
        x = coerce._as_int(params.get("x"), 0)
        y = coerce._as_int(params.get("y"), 0)
        target = coerce._parse_target_like(params.get("target"))
        sample_raw = params.get("sample")
        view_raw = params.get("view")
        primitive_raw = params.get("primitive")
        sample_override = coerce._as_int(sample_raw, 0) if sample_raw is not None else None
        view_override = coerce._as_int(view_raw, 0) if view_raw is not None else None
        primitive_override = coerce._as_int(primitive_raw, -1) if primitive_raw is not None else None
        if primitive_override is not None and primitive_override < 0:
            primitive_override = None
    if action == "compile":
        session_id = str(args.get("session_id") or context_records._context_snapshot().get("runtime", {}).get("session_id") or "").strip()
        if not session_id:
            return envelope.failure(
                "rd.shader.compile requires session_id or a current context session",
                code="validation_error",
                category="validation",
            )
        if session_id not in live_state._runtime.replays:
            return envelope.failure(
                "rd.shader.compile requires session_id to reference a live replay session",
                code="validation_error",
                category="validation",
                details={"session_id": session_id},
            )
        if args.get("event_id") is not None:
            await replay_access._validate_action_events(session_id, [args["event_id"]])
        controller = await replay_access._get_controller(session_id)
        rd = renderdoc_api._get_rd()
        try:
            source_payload = shader_patches._normalize_shader_source_input(args)
        except (OSError, ValueError) as exc:
            return envelope.failure(
                str(exc),
                code="validation_error",
                category="validation",
                details={
                    "source_kind": "invalid",
                    "resolved_source_path": str(args.get("source_path") or ""),
                    "include_dirs": coerce._as_list(args.get("include_dirs"), default=[]),
                    "entry": str(args.get("entry") or "main"),
                    "target": str(args.get("target") or ""),
                    "failure_stage": "validate_compile_input",
                    "effects_attempted": False,
                    "context_preserved": True,
                },
            )
        source = str(source_payload["source"])
        stage = renderdoc_api._parse_stage(args.get("stage"))
        entry = str(args.get("entry") or "main").strip() or "main"
        requested_encoding_name = str(args.get("source_encoding") or "").strip().lower()
        target_hint = str(args.get("target") or "").strip().lower()
        if not requested_encoding_name:
            if "#version" in source.lower():
                requested_encoding_name = "glsl"
            elif target_hint.startswith("spirv") or source.lstrip().startswith("Op"):
                requested_encoding_name = "spirvasm"
            else:
                requested_encoding_name = "hlsl"
        supported_encodings = list(await renderdoc_api._offload(controller.GetTargetShaderEncodings) or [])
        supported_encoding_names = [shader_patches._shader_encoding_name(item) for item in supported_encodings]
        # Resolve the same native encoding and ASM-to-binary route as PatchEngine.
        build_encoding = PatchEngine._find_requested_encoding(supported_encodings, requested_encoding_name)
        if build_encoding is None and requested_encoding_name in {"spirvasm", "spirv_asm"}:
            build_encoding = PatchEngine._find_requested_encoding(supported_encodings, "spirv")
        if build_encoding is None and requested_encoding_name in {"dxilasm", "dxil_asm"}:
            build_encoding = PatchEngine._find_requested_encoding(supported_encodings, "dxil")
        replacement_supported, replacement_reason = truth_matrix._session_replace_capability(session_id, controller)
        edit_plan = shader_patches._shader_edit_plan(
            source_encoding=requested_encoding_name,
            source=source,
            source_available=True,
        )
        source_details = {
            "source_kind": str(source_payload.get("source_kind") or ""),
            "resolved_source_path": str(source_payload.get("resolved_source_path") or ""),
            "include_dirs": list(source_payload.get("include_dirs") or []),
            "entry": entry,
            "target": str(args.get("target") or ""),
        }
        prebuild_proof = {
            "failure_stage": "validate_compile_input",
            "effects_attempted": False,
            "context_preserved": True,
        }
        if build_encoding is None:
            return envelope.failure(
                f"Requested shader source encoding is unsupported for this session: {requested_encoding_name}",
                code="shader_compile_encoding_unsupported", category="validation",
                details={
                    "requested_source_encoding": requested_encoding_name,
                    "supported_source_encodings": supported_encoding_names,
                    "runtime_replacement_supported": bool(replacement_supported),
                    "runtime_replacement_reason": replacement_reason,
                    "edit_plan": edit_plan, **source_details, **prebuild_proof,
                },
            )
        if requested_encoding_name in {"dxil", "dxbc"}:
            return envelope.failure(
                f"{requested_encoding_name.upper()} compile requires a binary container input, not source text.",
                code="shader_compile_encoding_unsupported",
                category="validation",
                details={
                    "requested_source_encoding": requested_encoding_name,
                    "supported_source_encodings": supported_encoding_names,
                    "runtime_replacement_supported": bool(replacement_supported),
                    "runtime_replacement_reason": replacement_reason,
                    "edit_plan": edit_plan,
                    "failure_stage": "validate_compile_input",
                    "effects_attempted": False,
                    "context_preserved": True,
                    "failure_reason": "binary_container_text_input_unsupported",
                    "recommended_next_tool": "rd.shader.extract_binary",
                    **source_details,
                },
            )
        build_encoding_name = shader_patches._shader_encoding_name(build_encoding)
        try:
            build_bytes = await renderdoc_api._offload(
                PatchEngine._source_bytes_for_build, source, build_encoding_name,
                "DXIL ASM" if requested_encoding_name in {"dxilasm", "dxil_asm"} else "SPIR-V ASM"
            )
        except (HostToolUnavailableError, dxc.DxcError) as exc:
            missing = isinstance(exc, HostToolUnavailableError)
            stage_name = getattr(exc, "stage", "toolchain")
            return envelope.failure(
                str(exc), code="host_tool_unavailable" if missing else f"shader_{stage_name}_failed",
                category="capability" if missing else "validation",
                details={"requested_source_encoding": requested_encoding_name, **source_details, **prebuild_proof,
                         "failure_stage": stage_name, "diagnostics": getattr(exc, "diagnostics", str(exc)),
                         "line": getattr(exc, "line", None)},
            )
        except (OSError, ValueError, RuntimeError) as exc:
            return envelope.failure(
                str(exc), code="shader_compile_assembly_failed", category="validation",
                details={"requested_source_encoding": requested_encoding_name,
                         "build_encoding": build_encoding_name, **source_details,
                         **prebuild_proof, "failure_stage": "assemble_compile_input"},
            )
        compile_flags = rd.ShaderCompileFlags()
        shader_id, messages = await renderdoc_api._offload(
            controller.BuildTargetShader,
            entry,
            build_encoding,
            build_bytes,
            compile_flags,
            renderdoc_api._rd_stage(stage),
        )
        if not renderdoc_api._is_null_resource_id(shader_id) and _compiler_output_is_fatal(messages):
            await renderdoc_api._offload(controller.FreeTargetResource, shader_id)
            return envelope.failure(
                str(messages), code="shader_compile_failed", category="runtime",
                details={"session_id": session_id, "stage": stage.upper(),
                         "requested_source_encoding": requested_encoding_name,
                         "failure_stage": "native_build_diagnostics", **source_details},
            )
        if renderdoc_api._is_null_resource_id(shader_id):
            return envelope.failure(
                str(messages or "BuildTargetShader returned a null shader id"),
                code="shader_compile_failed",
                category="runtime",
                details={
                    "session_id": session_id,
                    "stage": stage.upper(),
                    "entry": entry,
                    "requested_source_encoding": requested_encoding_name,
                    "supported_source_encodings": supported_encoding_names,
                    "runtime_replacement_supported": bool(replacement_supported),
                    "runtime_replacement_reason": replacement_reason,
                    "edit_plan": edit_plan,
                    **source_details,
                },
            )
        result: Dict[str, Any] = {
            "session_id": session_id,
            "shader_id": str(shader_id),
            "entry": entry,
            "stage": stage.upper(),
            "source_encoding": requested_encoding_name,
            "build_encoding": build_encoding_name,
            "build_input": _shader_build_input_provenance(
                build_bytes, encoding=build_encoding_name,
                original_shader_id="", target_shader_id=shader_id,
            ),
            "supported_source_encodings": supported_encoding_names,
            "runtime_replacement_supported": bool(replacement_supported),
            "runtime_replacement_reason": replacement_reason,
            "messages": str(messages or ""),
            "compiler_messages": str(messages or ""),
            "edit_plan": edit_plan,
            **source_details,
        }
        assembled_input = (
            build_encoding_name in {"spirv", "openglspirv"}
            and PatchEngine._looks_like_raw_spirv_asm(source)
        )
        if build_encoding_name == "dxil" and requested_encoding_name in {"dxilasm", "dxil_asm"}:
            raw_bytes = build_bytes
            artifact_kind = "validated-dxil-build-input"
        elif assembled_input:
            # Publish the exact accepted module as build input, never inferred device code.
            raw_bytes = build_bytes
            artifact_kind = "assembled-spirv-build-input"
        else:
            artifact_kind = "native-shader-readback"
            try:
                entry_points = await renderdoc_api._offload(controller.GetShaderEntryPoints, shader_id)
                if entry_points:
                    reflection = await renderdoc_api._offload(controller.GetShader, rd.ResourceId(), shader_id, entry_points[0])
                    raw_bytes = shader_patches._shader_raw_bytes(reflection)
                else:
                    raw_bytes = b""
            except Exception:
                raw_bytes = b""
        if raw_bytes:
            result["artifact_kind"] = artifact_kind
            output_path = args.get("output_path")
            suffix = shader_patches._shader_binary_suffix(build_encoding_name)
            if output_path:
                out = Path(str(output_path))
                if out.suffix == "":
                    out = out.with_suffix(suffix)
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(raw_bytes)
                result["saved_path"] = str(out)
            else:
                assert live_state._artifact_store is not None
                artifact = await live_state._artifact_store.store(raw_bytes, mime="application/octet-stream", suffix=suffix)
                result["artifact_path"] = artifact_payloads._artifact_path(artifact)
            result["byte_size"] = len(raw_bytes)
        return envelope.success(**result)

    coerce._require(args, "session_id")
    session_id = str(args["session_id"])
    if action == "get_debug_state":
        try:
            shader_debug._require_shader_debug_handle(session_id, str(args.get("shader_debug_id", "")))
            if args.get("detail_level", "full") not in ("summary", "full"):
                return envelope.failure("detail_level must be summary or full", code="validation_error", category="validation",
                            details={"session_id": session_id, "effects_attempted": False, "context_preserved": True,
                                     "failure_stage": "validate_debug_request"})
        except CoreError as exc:
            return envelope.failure(exc.message, code=exc.code, category=exc.category, details=dict(exc.details))
    controller = await replay_access._get_controller(session_id)
    if action == "get_disassembly":
        requested_target = str(args.get("target", "auto")).strip()
        requested_encoding = str(args.get("source_encoding") or "")
        if (requested_target and requested_target.lower() != "auto"
                and not PatchEngine._is_raw_spirv_asm_request(requested_target, requested_encoding)
                and not PatchEngine._is_raw_dxil_asm_request(requested_target, requested_encoding)):
            target_discovery = await _disassembly_target_metadata(controller)
            if target_discovery["available_targets_status"] != "complete":
                return envelope.failure(
                    "Unable to discover native disassembly targets", code="shader_disassembly_unavailable", category="runtime",
                    details={"session_id": session_id, "requested_target": requested_target,
                             "failure_stage": "validate_target", "failure_reason": "target_discovery_failed",
                             "effects_attempted": False, "context_preserved": True, **target_discovery},
                )
            targets = target_discovery["available_targets"]
            if not PatchEngine._find_matching_target(targets, requested_target):
                return envelope.failure(
                    f"Requested disassembly target is unavailable: {requested_target}",
                    code="shader_disassembly_unavailable",
                    category="validation",
                    details={
                        "session_id": session_id,
                        "requested_target": requested_target,
                        "available_targets": targets,
                        "failure_stage": "validate_target",
                        "failure_reason": "target_unavailable",
                        "effects_attempted": False,
                        "context_preserved": True,
                    },
                )
    inspection_original_event = replay_access._active_event(session_id) if action in {"get_source", "get_disassembly", "get_constant_buffer_contents", "debug_start", "edit_and_replace"} else 0
    event_id = await replay_access._ensure_event(session_id, args.get("event_id"))
    pipe = await renderdoc_api._offload(controller.GetPipelineState)

    async def _resolve_shader_binding(
        *,
        shader_id: str = "",
        stage_name: Any = None,
        require_reflection: bool = False,
    ) -> Tuple[str, str, Any]:
        requested_shader_id = str(shader_id or "").strip()
        requested_stage = renderdoc_api._parse_stage(stage_name) if stage_name is not None and str(stage_name).strip() else ""
        if requested_shader_id:
            matches: List[Tuple[str, str, Any]] = []
            for candidate_stage in renderdoc_api._stage_candidates():
                rd_stage = renderdoc_api._rd_stage(candidate_stage)
                bound = await renderdoc_api._offload(pipe.GetShader, rd_stage)
                if renderdoc_api._is_null_resource_id(bound):
                    continue
                if requested_shader_id in texture_naming._resource_id_tokens(bound):
                    reflection = await renderdoc_api._offload(pipe.GetShaderReflection, rd_stage)
                    matches.append((candidate_stage, str(bound), reflection))
            if not matches:
                raise CoreError(
                    code="shader_binding_lookup_failed",
                    message=f"Shader not bound at current event: {requested_shader_id}",
                    category="runtime",
                    details={
                        "session_id": session_id,
                        "resolved_event_id": int(event_id),
                        "shader_id": requested_shader_id,
                        "failure_stage": "resolve_binding",
                        "failure_reason": "shader_id_not_bound",
                    },
                )
            resolved_stage, resolved_shader_id, reflection = matches[0]
            if requested_stage and resolved_stage != requested_stage:
                raise CoreError(
                    code="shader_stage_mismatch",
                    message=(
                        f"Shader stage mismatch for {requested_shader_id}: "
                        f"expected {requested_stage}, got {resolved_stage}"
                    ),
                    category="validation",
                    details={
                        "session_id": session_id,
                        "resolved_event_id": int(event_id),
                        "shader_id": requested_shader_id,
                        "expected_stage": requested_stage,
                        "bound_stage": resolved_stage,
                        "failure_stage": "resolve_binding",
                        "failure_reason": "stage_mismatch",
                    },
                )
        else:
            resolved_stage = requested_stage or "ps"
            rd_stage_explicit = renderdoc_api._rd_stage(resolved_stage)
            bound_shader = await renderdoc_api._offload(pipe.GetShader, rd_stage_explicit)
            if renderdoc_api._is_null_resource_id(bound_shader):
                raise CoreError(
                    code="shader_binding_lookup_failed",
                    message=f"No shader bound at stage {resolved_stage.upper()} for event {int(event_id)}",
                    category="runtime",
                    details={
                        "session_id": session_id,
                        "resolved_event_id": int(event_id),
                        "stage": resolved_stage.upper(),
                        "failure_stage": "resolve_binding",
                        "failure_reason": "stage_unbound",
                    },
                )
            resolved_shader_id = str(bound_shader)
            reflection = await renderdoc_api._offload(pipe.GetShaderReflection, rd_stage_explicit)
        if require_reflection and reflection is None:
            raise CoreError(
                code="shader_reflection_unavailable",
                message=f"Shader reflection unavailable at event {int(event_id)}",
                category="runtime",
                details={
                    "session_id": session_id,
                    "resolved_event_id": int(event_id),
                    "shader_id": resolved_shader_id,
                    "stage": resolved_stage.upper(),
                    "failure_stage": "resolve_binding",
                    "failure_reason": "reflection_unavailable",
                },
            )
        return resolved_stage, resolved_shader_id, reflection

    if action == "debug_start":
        rd = renderdoc_api._get_rd()
        remote_capability_matrix = await renderdoc_api._offload(
            truth_matrix._session_remote_capability_matrix, session_id, controller=controller, context_id=live_state._runtime_context_id(),
        )
        debug_capability = dict(remote_capability_matrix.get("shader_debug") or {})
        if debug_capability and str(debug_capability.get("status") or "") in {"unsupported", "blocked_current_session"}:
            capability_code = "shader_debug_backend_unsupported"
            capability_message = "Shader debug is unavailable for the selected remote replay backend"
            if str(debug_capability.get("status") or "") == "blocked_current_session":
                capability_code = "shader_debug_event_binding_unavailable"
                capability_message = "Shader debug is blocked until a valid remote event-bound target is established"
            return envelope.capability_failure(
                capability_code,
                capability_message,
                capability="shader_debug",
                reason=str(debug_capability.get("reason") or "Shader debug is unavailable."),
                source="renderdoc_runtime",
                action=action,
                session_id=session_id,
                resolved_event_id=int(event_id),
                remote_capability_matrix=remote_capability_matrix,
            )
        target_candidates: List[Tuple[str, Dict[str, Any]]] = []
        seen_target_candidates: set[str] = set()

        def add_target_candidate(source_label: str, target_value: Dict[str, Any]) -> None:
            normalized = dict(target_value or {})
            key = json.dumps(normalized, sort_keys=True, ensure_ascii=False)
            if key in seen_target_candidates:
                return
            seen_target_candidates.add(key)
            target_candidates.append((source_label, normalized))

        if target:
            add_target_candidate("user.target", target)
        else:
            try:
                for rid, rt_index in await replay_access._output_target_resource_ids(session_id, event_id):
                    add_target_candidate(
                        f"event.output[{rt_index}]",
                        {"rt_index": int(rt_index), "texture_id": str(rid)},
                    )
            except Exception:
                pass
            if not target_candidates:
                add_target_candidate("default_target", {})

        trace = None
        attempts_log: List[Dict[str, Any]] = []
        last_context: Dict[str, Any] = {
            "event_id": int(event_id),
            "x": int(x),
            "y": int(y),
            "target": dict(target or {}),
        }
        last_target_source = ""
        last_history_summary: Dict[str, Any] = {
            "hit_count": 0,
            "matched_event_hit_count": 0,
            "passed_hit_count": 0,
            "viable_hit_count": 0,
            "primitive_ids": [],
        }
        target_config_failures = 0
        configured_target_count = 0
        debug_attempt_count = 0
        debug_exception_count = 0
        invalid_trace_count = 0
        cross_event_rejections = 0
        debugger_missing_count = 0
        matched_event_hit_seen = False
        pixel_history_conflicts: List[pixel_trace.PixelHistoryInputAttachmentConflict] = []

        for target_source, target_candidate in target_candidates:
            try:
                target_rid, target_texture_desc, target_sub = await replay_access._configure_texture_output_for_target(
                    session_id,
                    target_candidate,
                    event_id=event_id,
                    sample_override=sample_override,
                )
                await pixel_trace._refresh_pixel_context(session_id, x, y)
            except Exception as exc:
                target_config_failures += 1
                attempts_log.append(
                    {
                        "target_source": target_source,
                        "stage": "configure_target",
                        "resolved_context": {
                            "event_id": int(event_id),
                            "x": int(x),
                            "y": int(y),
                            "target": dict(target_candidate),
                        },
                        "error": f"Failed to configure debug target: {exc}",
                        "exception_type": type(exc).__name__,
                    },
                )
                continue

            configured_target_count += 1
            resolved_target = {
                "texture_id": str(target_rid),
                "subresource": pixel_trace._subresource_to_dict(target_sub),
            }
            if "rt_index" in target_candidate:
                resolved_target["rt_index"] = coerce._as_int(target_candidate.get("rt_index"), 0)
            last_context = {
                "event_id": int(event_id),
                "x": int(x),
                "y": int(y),
                "target": resolved_target,
            }
            last_target_source = target_source
            view_format, raw_typeless = await pixel_trace._pixel_history_view(controller, target_rid, target_texture_desc)
            cast = view_format.compType if view_format is not None else (renderdoc_api._get_rd().CompType.UInt if raw_typeless else None)

            try:
                history_options = {"type_cast": cast} if cast is not None else {}
                history_raw = await pixel_trace._checked_pixel_history_raw(
                    controller,
                    target_rid,
                    x,
                    y,
                    target_sub,
                    **history_options,
                )
            except pixel_trace.PixelHistoryInputAttachmentConflict as exc:
                pixel_history_conflicts.append(exc)
                attempts_log.append({"target_source": target_source, "stage": "pixel_history",
                                     "resolved_context": last_context,
                                     "error": "pixel_history_unsupported_input_attachment",
                                     "usage_event_id": exc.usage_event_id,
                                     "image_usage_flags": exc.image_usage_flags})
                continue
            except Exception as exc:
                history_items: List[Dict[str, Any]] = []
                history_summary = {
                    "hit_count": 0,
                    "matched_event_hit_count": 0,
                    "passed_hit_count": 0,
                    "viable_hit_count": 0,
                    "primitive_ids": [],
                    "error": str(exc),
                }
            else:
                color_type = ("uint" if raw_typeless else pixel_trace._pixel_history_color_type(
                    SimpleNamespace(format=view_format) if view_format is not None else target_texture_desc))
                history_items = [pixel_trace._pixel_history_item_payload(item, color_type) for item in history_raw]
                history_summary = pixel_trace._pixel_history_summary(history_items, event_id)
                if raw_typeless:
                    history_summary["interpretation_note"] = "无类型格式，视图格式未知，数值为原始整数"

            history_summary["target_source"] = target_source
            history_summary["target"] = resolved_target
            last_history_summary = history_summary
            if int(history_summary.get("matched_event_hit_count", 0)) > 0:
                matched_event_hit_seen = True
            if int(history_summary.get("matched_event_hit_count", 0)) == 0:
                cross_event_hits = sum(
                    1 for item in history_items
                    if int(item.get("event_id") or 0) > 0
                    and int(item.get("event_id") or 0) != int(event_id)
                )
                cross_event_rejections += cross_event_hits
                attempts_log.append(
                    {
                        "target_source": target_source,
                        "stage": "pixel_history",
                        "resolved_context": last_context,
                        "error": (
                            "Cross-event shader debug fallback is not allowed for rd.shader.debug_start"
                            if cross_event_hits else
                            "Selected target has no pixel-history hit for the requested event"
                        ),
                        "matched_event_hit_count": 0,
                    },
                )
                continue
            default_sample = sample_override if sample_override is not None else pixel_trace._subresource_to_dict(target_sub)["sample"]
            default_view = view_override if view_override is not None else 0

            attempts: List[Tuple[str, str, int, Optional[int], Optional[int], Optional[int]]] = []
            seen_attempts: set[Tuple[str, int, Optional[int], Optional[int], Optional[int]]] = set()

            def add_attempt(
                label: str,
                origin: str,
                event_value: int,
                sample_value: Optional[int],
                view_value: Optional[int],
                primitive_value: Optional[int],
            ) -> None:
                key = (str(target_rid), int(event_value), sample_value, view_value, primitive_value)
                if key in seen_attempts:
                    return
                seen_attempts.add(key)
                attempts.append((label, origin, int(event_value), sample_value, view_value, primitive_value))

            add_attempt("user_context", "explicit", event_id, sample_override, view_override, primitive_override)
            add_attempt("default_context", "default", event_id, default_sample, default_view, primitive_override)

            for item in history_items:
                if not bool(item.get("passed")):
                    continue
                if bool(item.get("shader_discarded")) or bool(item.get("unbound_ps")):
                    continue
                candidate_event = int(item.get("event_id") or 0)
                if candidate_event <= 0:
                    continue
                if candidate_event != int(event_id):
                    cross_event_rejections += 1
                    attempts_log.append(
                        {
                            "target_source": target_source,
                            "label": "pixel_history_match",
                            "origin": "pixel_history",
                            "event_id": int(candidate_event),
                            "error": "Cross-event shader debug fallback is not allowed for rd.shader.debug_start",
                        },
                    )
                    continue
                raw_primitive = item.get("primitive_id")
                candidate_primitive = int(raw_primitive) if raw_primitive is not None else -1
                if candidate_primitive < 0:
                    continue
                add_attempt(
                    "pixel_history_match",
                    "pixel_history",
                    candidate_event,
                    default_sample,
                    default_view,
                    candidate_primitive,
                )

            for label, origin, attempt_event, attempt_sample, attempt_view, attempt_primitive in attempts:
                if int(attempt_event) != int(last_context.get("event_id", event_id)):
                    cross_event_rejections += 1
                    attempts_log.append(
                        {
                            "target_source": target_source,
                            "label": label,
                            "origin": origin,
                            "event_id": int(attempt_event),
                            "error": "Cross-event shader debug fallback is not supported",
                        },
                    )
                    continue
                inputs = rd.DebugPixelInputs()
                if attempt_sample is not None:
                    inputs.sample = int(attempt_sample)
                if attempt_view is not None:
                    inputs.view = int(attempt_view)
                if attempt_primitive is not None:
                    inputs.primitive = int(attempt_primitive)
                debug_attempt_count += 1
                try:
                    trace = await renderdoc_api._offload(controller.DebugPixel, x, y, inputs)
                except Exception as exc:
                    debug_exception_count += 1
                    attempts_log.append(
                        {
                            "target_source": target_source,
                            "label": label,
                            "origin": origin,
                            "event_id": int(attempt_event),
                            "resolved_context": {
                                "event_id": int(attempt_event),
                                "x": int(x),
                                "y": int(y),
                                "sample": int(attempt_sample if attempt_sample is not None else resolved_target["subresource"]["sample"]),
                                "view": int(attempt_view if attempt_view is not None else 0),
                                "primitive": int(attempt_primitive) if attempt_primitive is not None else None,
                                "target": resolved_target,
                            },
                            "pixel_history_hit_count": int(history_summary.get("hit_count", 0)),
                            "matched_event_hit_count": int(history_summary.get("matched_event_hit_count", 0)),
                            "stage": "debug_pixel",
                            "error": f"DebugPixel failed: {exc}",
                            "exception_type": type(exc).__name__,
                        },
                    )
                    continue
                effective_context = {
                    "event_id": int(attempt_event),
                    "x": int(x),
                    "y": int(y),
                    "sample": int(attempt_sample if attempt_sample is not None else resolved_target["subresource"]["sample"]),
                    "view": int(attempt_view if attempt_view is not None else 0),
                    "primitive": int(attempt_primitive) if attempt_primitive is not None else None,
                    "target": resolved_target,
                }
                # Native ShaderDebugTrace is valid when it owns a debugger handle.
                trace_debugger = getattr(trace, "debugger", None) if trace is not None else None
                valid = trace_debugger is not None
                missing_debugger_handle = trace is not None and trace_debugger is None
                if missing_debugger_handle:
                    debugger_missing_count += 1
                attempts_log.append(
                    {
                        "target_source": target_source,
                        "label": label,
                        "origin": origin,
                        "event_id": int(attempt_event),
                        "resolved_context": effective_context,
                        "pixel_history_hit_count": int(history_summary.get("hit_count", 0)),
                        "matched_event_hit_count": int(history_summary.get("matched_event_hit_count", 0)),
                        "trace_valid": valid,
                        "stage": "debug_pixel",
                    },
                )
                if not valid and missing_debugger_handle:
                    attempts_log[-1]["failure_stage"] = "trace_state"
                    attempts_log[-1]["error"] = "Debug trace was created without a debugger handle"
                if not valid and trace is None:
                    invalid_trace_count += 1
                last_context = effective_context
                if valid:
                    break
                if trace is not None:
                    invalid_trace_count += 1
                    try:
                        await renderdoc_api._offload(controller.FreeTrace, trace)
                    except Exception:
                        pass
                    trace = None
            if trace is not None and getattr(trace, "debugger", None) is not None:
                break

        if trace is None or getattr(trace, "debugger", None) is None:
            if pixel_history_conflicts and len(pixel_history_conflicts) == configured_target_count and not target_config_failures:
                return await pixel_trace._pixel_history_conflict_error(session_id, inspection_original_event, pixel_history_conflicts[0])
            failure_stage = "debug_pixel"
            failure_reason = "invalid_trace"
            error_code = "shader_debug_event_binding_unavailable"
            error_category = "capability"
            error_message = "Precise event-bound shader debug is unavailable for the requested event"

            if configured_target_count == 0 and target_config_failures > 0:
                failure_stage = "configure_target"
                failure_reason = "all_targets_failed"
                error_code = "shader_debug_target_config_failed"
                error_category = "runtime"
                error_message = "Failed to configure any shader debug target for the requested event"
            elif debug_exception_count > 0 and debug_attempt_count == debug_exception_count:
                failure_stage = "debug_pixel"
                failure_reason = "debug_pixel_exception"
                error_code = "shader_debug_start_failed"
                error_category = "runtime"
                error_message = "Shader debug startup failed while requesting the backend trace"
            elif debugger_missing_count > 0:
                failure_stage = "trace_state"
                failure_reason = "debugger_handle_missing"
                error_code = "shader_debug_start_failed"
                error_category = "runtime"
                error_message = "Shader debug trace was created without a usable debugger handle"
            elif not matched_event_hit_seen and cross_event_rejections > 0:
                failure_stage = "pixel_history"
                failure_reason = "cross_event_only"
            elif not matched_event_hit_seen:
                failure_stage = "pixel_history"
                failure_reason = "no_event_hit"
            elif invalid_trace_count > 0:
                failure_stage = "debug_pixel"
                failure_reason = "invalid_trace"

            details = {
                "resolved_context": last_context,
                "pixel_history_summary": last_history_summary,
                "attempts": attempts_log,
                "selected_target_source": last_target_source,
                "failure_stage": failure_stage,
                "failure_reason": failure_reason,
                "target_config_failures": int(target_config_failures),
                "configured_target_count": int(configured_target_count),
                "debug_attempt_count": int(debug_attempt_count),
                "debug_exception_count": int(debug_exception_count),
                "invalid_trace_count": int(invalid_trace_count),
                "cross_event_rejections": int(cross_event_rejections),
                "matched_event_hit_seen": bool(matched_event_hit_seen),
                "debugger_missing_count": int(debugger_missing_count),
            }
            if error_category == "runtime":
                return envelope.failure(
                    error_message,
                    code=error_code,
                    category=error_category,
                    details=details,
                )
            return envelope.capability_failure(
                error_code,
                error_message,
                capability="shader_debug",
                reason="The replay backend could not provide a valid debug trace without leaving the requested event.",
                source="renderdoc_runtime",
                action=action,
                **details,
            )
        shader_debug_id = _new_id("sdbg")
        resolved_context = dict(last_context)
        resolved_event_id = int(resolved_context.get("event_id") or event_id)
        try:
            api_properties = await renderdoc_api._offload(controller.GetAPIProperties)
            debug_qualification = None
            if api_properties.pipelineType == rd.GraphicsAPI.D3D12:
                d3d12_state = await renderdoc_api._offload(controller.GetD3D12PipelineState)
                debug_qualification = shader_debug._coarse_pixel_debug_qualification(d3d12_state.rasterizer.state)
        except Exception:
            await renderdoc_api._offload(controller.FreeTrace, trace)
            raise
        live_state._runtime.shader_debugs[shader_debug_id] = live_state.ShaderDebugHandle(
            shader_debug_id=shader_debug_id,
            session_id=session_id,
            mode=mode,
            event_id=resolved_event_id,
            trace=trace,
            debugger=getattr(trace, "debugger", None),
            current_state=None,
            resolved_context=resolved_context,
            selected_target_source=last_target_source,
            pixel_history_summary=dict(last_history_summary),
            debug_qualification=debug_qualification,
        )
        return envelope.success(
            shader_debug_id=shader_debug_id,
            initial_state={"pc": 0},
            resolved_context=resolved_context,
            resolved_event_id=resolved_event_id,
            selected_target_source=last_target_source,
            pixel_history_summary=last_history_summary,
            **({"debug_qualification": debug_qualification} if debug_qualification else {}),
        )

    if action in {"get_debug_state", "list_replacements", "revert_replacement", "edit_and_replace", "get_messages", "extract_binary", "get_source", "list_entry_points", "get_bindpoint_mapping", "get_constant_block_layout", "get_constant_buffer_contents", "get_reflection", "get_disassembly"}:
        pass
    else:
        return envelope.failure(f"Unsupported shader action: {action}", code="runtime_error")

    if action == "get_debug_state":
        handle = shader_debug._require_shader_debug_handle(session_id, str(args.get("shader_debug_id", "")))
        return envelope.success(
            state=shader_debug._shader_debug_state_payload(handle, args.get("detail_level", "full")),
            resolved_event_id=int(handle.event_id or 0),
            resolved_context=handle.resolved_context,
            selected_target_source=handle.selected_target_source,
            pixel_history_summary=handle.pixel_history_summary,
            **({"debug_qualification": handle.debug_qualification} if handle.debug_qualification else {}),
        )

    if action == "list_replacements":
        replacements = shader_patches._list_replacement_payloads(session_id)
        return envelope.success(replacements=replacements)

    if action == "revert_replacement":
        coerce._require(args, "replacement_id")
        replacement_id = str(args["replacement_id"])
        repl = shader_patches._list_replacement_payloads(session_id)
        if live_state._patch_engine is None:
            return envelope.failure("Shader patch engine is not initialized", code="shader_replace_unavailable", category="runtime")
        reverted = await live_state._patch_engine.revert_patch(session_id, replacement_id, live_state._session_manager)
        if not reverted:
            return envelope.failure(
                f"Unknown replacement_id: {replacement_id}",
                code="replacement_not_found",
                category="not_found",
                details={"replacement_id": replacement_id, "session_id": session_id},
            )
        remaining_replacements = [
            r for r in repl if str(r.get("replacement_id")) != replacement_id
        ]
        live_state._runtime.shader_replacements[session_id] = remaining_replacements
        live_state._runtime.restored_shader_sessions.add(session_id)
        shader_patches._sync_context_session_replacements(session_id, remaining_replacements)
        return envelope.success(replacement_id=replacement_id, reverted=True)

    if action == "edit_and_replace":
        stage = renderdoc_api._parse_stage(args.get("stage"))
        if live_state._patch_engine is None:
            return envelope.capability_failure(
                "shader_replace_unavailable",
                "Runtime shader replacement is not initialized",
                capability="shader_replace",
                reason="Shader patch engine is not initialized.",
                source="runtime_build",
                action=action,
            )
        patch_supported, patch_reason = truth_matrix._session_replace_capability(session_id, controller)
        if not patch_supported:
            return envelope.capability_failure(
                "shader_replace_backend_unsupported",
                "Runtime shader replacement is unavailable for this replay backend",
                capability="shader_replace",
                reason=patch_reason,
                source="renderdoc_runtime",
                action=action,
                session_id=session_id,
                resolved_event_id=int(event_id),
            )
        ops_payload = coerce._as_list(args.get("ops"), default=[])
        source_payload: Dict[str, Any] = {}
        source_text = ""
        has_source_input = any(
            args.get(name) not in (None, "")
            for name in ("source_text", "source_path")
        )
        if has_source_input:
            try:
                source_payload = shader_patches._normalize_shader_source_input(args)
                source_text = str(source_payload["source"])
            except (OSError, ValueError) as exc:
                return envelope.failure(
                    str(exc),
                    code="validation_error",
                    category="validation",
                    details={
                        "source_kind": "invalid",
                        "resolved_source_path": str(args.get("source_path") or ""),
                        "include_dirs": coerce._as_list(args.get("include_dirs"), default=[]),
                        "entry": str(args.get("entry") or ""),
                        "target": str(args.get("target") or ""),
                        "failure_stage": "validate_edit_input",
                    },
                )
        diff_text = str(args.get("diff_text") or "")
        edit_input_count = sum(
            1
            for item in (
                bool(ops_payload),
                bool(source_text),
                bool(diff_text),
            )
            if item
        )
        if edit_input_count != 1:
            return envelope.failure(
                "rd.shader.edit_and_replace requires exactly one edit input: ops, source_text/source_path, or diff_text",
                code="validation_error",
                category="validation",
            )
        if ops_payload:
            supported_ops = {"force_full_precision", "insert_guard"}
            invalid_ops = [
                str((item or {}).get("op") if isinstance(item, dict) else "")
                for item in ops_payload
                if str((item or {}).get("op") if isinstance(item, dict) else "") not in supported_ops
            ]
            if invalid_ops:
                return envelope.failure(
                    "Unsupported shader patch op. Use force_full_precision, insert_guard, source_text, or diff_text.",
                    code="validation_error",
                    category="validation",
                    details={
                        "unsupported_ops": invalid_ops,
                        "supported_ops": sorted(supported_ops),
                        "agent_text_edit_inputs": ["source_text", "diff_text"],
                    },
                )
        shader_id = str(args.get("shader_id", "")).strip()
        try:
            _, shader_id, _ = await _resolve_shader_binding(
                shader_id=shader_id,
                stage_name=stage,
                require_reflection=False,
            )
        except CoreError as exc:
            return envelope.failure(exc.message, code=exc.code, category=exc.category, details=dict(exc.details))
        source_target = str(args.get("source_target") or "")
        source_encoding = str(args.get("source_encoding") or "")
        expected_source_hash = str(args.get("expected_source_hash") or "")
        max_diff_ops = coerce._as_int(args.get("max_diff_ops"), 20)
        preserve_outputs = coerce._as_bool(args.get("preserve_outputs"), True)
        patch_spec = PatchSpec.model_validate(
            {
                "patch_id": str(args.get("replacement_id") or _new_id("repl")),
                "target_event_id": int(event_id),
                "target_stage": ShaderStage(stage),
                "target_shader_id": shader_id,
                "intent": str(args.get("intent") or "shader_replace"),
                "ops": ops_payload,
                "source_text": source_text,
                "source_path": str(source_payload.get("resolved_source_path") or args.get("source_path") or ""),
                "diff_text": diff_text,
                "source_target": source_target,
                "source_encoding": source_encoding,
                "entry": str(args.get("entry") or ""),
                "target": str(args.get("target") or ""),
                "include_dirs": list(source_payload.get("include_dirs") or coerce._as_list(args.get("include_dirs"), default=[])),
                "expected_source_hash": expected_source_hash,
                "max_diff_ops": max_diff_ops,
                "preserve_outputs": preserve_outputs,
            }
        )
        emit_patch_artifacts = coerce._as_bool(args.get("emit_patch_artifacts"), False)
        patch_output_dir = str(args.get("output_dir") or "").strip()
        patch_result = await live_state._patch_engine.apply_patch(
            session_id=session_id,
            event_id=int(event_id),
            stage=ShaderStage(stage),
            session_manager=live_state._session_manager,
            patch_spec=patch_spec,
        )
        if not patch_result.success:
            error_details = {
                "session_id": session_id,
                "resolved_event_id": int(event_id),
                "stage": stage.upper(),
                "shader_id": shader_id,
                "replacement_id": patch_spec.patch_id,
            }
            if patch_result.error_details:
                error_details.update(dict(patch_result.error_details))
            recoverable_prebuild = (
                patch_result.error_code in {"host_tool_unavailable", "shader_assembly_failed", "shader_validation_failed", "shader_source_mismatch"}
                or (patch_result.error_code == "shader_patch_op_unsupported_for_encoding"
                    and error_details.get("failure_stage") == "validate_edit_plan"
                    and error_details.get("failure_reason") == "source_encoding_not_safely_replaceable")
            )
            if (recoverable_prebuild and error_details.get("replacement_attempted") is False
                    and inspection_original_event > 0):
                error_details.pop("context_preserved", None)
                try:
                    restored_event = await replay_access._ensure_event(session_id, inspection_original_event)
                    if restored_event != inspection_original_event or replay_access._active_event(session_id) != inspection_original_event:
                        raise RuntimeError("Replay event did not match the original event after restoration")
                except Exception as restore_error:
                    return envelope.failure(
                        f"Failed to restore replay after shader edit was rejected: {restore_error}",
                        code="shader_edit_recovery_failed", category="runtime",
                        details={**error_details, "context_id": live_state._runtime_context_id(),
                                 "original_error_code": patch_result.error_code, "replay_state_restored": False},
                    )
                error_details.update(context_id=live_state._runtime_context_id(), replay_state_restored=True,
                                     restored_event_id=inspection_original_event)
            return envelope.failure(
                patch_result.error_message or "Shader replacement failed",
                code=patch_result.error_code or "shader_replace_failed",
                category=patch_result.error_category or "runtime",
                details=error_details,
            )
        no_source_change = bool(
            patch_result.applied_to_shader_hash
            and patch_result.applied_to_shader_hash == patch_result.original_shader_hash
            and any(
                "no source changes before recompilation" in str(msg).lower()
                for msg in (patch_result.messages or [])
            )
        )
        replacement = {
            "replacement_id": patch_spec.patch_id,
            "stage": stage.upper(),
            "resolved_event_id": int(event_id),
            "original_shader_id": shader_id,
            "status": "noop" if no_source_change else "applied",
            "messages": list(patch_result.messages or []),
            "applied_to_shader_hash": patch_result.applied_to_shader_hash,
            "original_shader_hash": patch_result.original_shader_hash,
            "compile": {
                "encoding": str(patch_result.encoding or ""),
                "disassembly_target": str(patch_result.disassembly_target or ""),
                "entry_point": str(patch_result.entry_point or ""),
                "compile_flags": list(patch_result.compile_flags or []),
                "build_input": dict(patch_result.build_input),
            },
            "patch_spec": shader_patches._patch_spec_payload_from_args(
                patch_spec,
                ops_payload=ops_payload,
                source_text=source_text,
                diff_text=diff_text,
                source_target=source_target,
                source_encoding=source_encoding,
                expected_source_hash=expected_source_hash,
                max_diff_ops=max_diff_ops,
                preserve_outputs=preserve_outputs,
            ),
        }
        edit_plan = dict(patch_result.edit_plan) or shader_patches._shader_edit_plan(
            source_encoding=str(patch_result.encoding or ""),
            disassembly_target=str(patch_result.disassembly_target or ""),
            source=str(patch_result.source_before_text or ""),
            source_available=bool(patch_result.source_before_text),
        )
        replacement["edit_plan"] = edit_plan
        if emit_patch_artifacts or patch_output_dir:
            base_stem = f"shader_patch_ev{int(event_id)}_{stage}_{patch_spec.patch_id}"
            before_payload = await artifact_payloads._store_text_artifact_payload(
                str(patch_result.source_before_text or ""),
                stem=f"{base_stem}_before",
                suffix=".txt",
                output_dir=patch_output_dir,
                title="shader_source_before",
            )
            after_payload = await artifact_payloads._store_text_artifact_payload(
                str(patch_result.source_after_text or ""),
                stem=f"{base_stem}_after",
                suffix=".txt",
                output_dir=patch_output_dir,
                title="shader_source_after",
            )
            diff_text = ""
            if patch_result.source_before_text or patch_result.source_after_text:
                diff_text = "".join(
                    difflib.unified_diff(
                        str(patch_result.source_before_text or "").splitlines(keepends=True),
                        str(patch_result.source_after_text or "").splitlines(keepends=True),
                        fromfile="before",
                        tofile="after",
                    )
                )
            diff_payload = await artifact_payloads._store_text_artifact_payload(
                diff_text,
                stem=f"{base_stem}_diff",
                suffix=".diff",
                output_dir=patch_output_dir,
                title="shader_patch_diff",
                mime="text/x-diff",
            )
            patch_artifacts = {
                "source_before": before_payload,
                "source_after": after_payload,
                "patch_diff": diff_payload,
            }
            if patch_result.build_input_bytes:
                is_spirv = patch_result.build_input.get("byte_kind") == "spirv-module"
                patch_artifacts["build_input"] = await artifact_payloads._store_bytes_artifact_payload(
                    patch_result.build_input_bytes, stem=f"{base_stem}_build_input",
                    suffix=".spv" if is_spirv else ".txt", output_dir=patch_output_dir,
                    title="shader_build_input", mime="application/octet-stream" if is_spirv else "text/plain",
                )
            replacement["artifacts"] = {
                key: value
                for key, value in patch_artifacts.items()
                if value
            }
        if not no_source_change:
            shader_patches._store_replacement_payload(session_id, replacement)
            try:
                await shader_patches._validate_remote_replacement_persistence(session_id, replacement)
            except Exception as exc:
                remaining = [
                    item
                    for item in context_records._replacement_metadata_entries(session_id)
                    if str(item.get("replacement_id") or "") != str(replacement.get("replacement_id") or "")
                ]
                live_state._runtime.shader_replacements[session_id] = remaining
                shader_patches._sync_context_session_replacements(session_id, remaining)
                if live_state._patch_engine is not None:
                    try:
                        await live_state._patch_engine.revert_patch(
                            session_id,
                            str(replacement.get("replacement_id") or ""),
                            live_state._session_manager,
                        )
                    except Exception:
                        live_state.logger.debug(
                            "Best-effort replacement revert after remote persistence validation failed",
                            exc_info=True,
                        )
                details = {
                    "session_id": session_id,
                    "resolved_event_id": int(event_id),
                    "stage": stage.upper(),
                    "shader_id": shader_id,
                    "replacement_id": str(replacement.get("replacement_id") or ""),
                    "failure_stage": "validate_remote_recovery",
                    "failure_reason": "remote_replacement_persistence_failed",
                    "replacement_attempted": True,
                    "cleanup_attempted": True,
                    "context_preserved": True,
                    "exception_type": type(exc).__name__,
                }
                if isinstance(exc, RuntimeToolError):
                    nested = dict(getattr(exc, "details", {}) or {})
                    nested_details = dict(nested.get("details") or {})
                    details.update(nested)
                    details.update(nested_details)
                    code = str(nested.get("code") or nested_details.get("code") or "shader_replace_preserve_outputs_failed")
                    category = str(nested.get("category") or nested_details.get("category") or "runtime")
                    message = str(exc)
                else:
                    code = "shader_replace_preserve_outputs_failed"
                    category = "runtime"
                    message = str(exc)
                return envelope.failure(
                    message or "Remote shader replacement failed persistence validation",
                    code=code,
                    category=category,
                    details=details,
                )
        return envelope.success(
            replacement_id=replacement["replacement_id"],
            status=replacement["status"],
            resolved_event_id=int(event_id),
            messages=replacement["messages"],
            edit_plan=edit_plan,
            replacement=replacement,
        )

    if action == "get_messages":
        severity_min = str(args.get("severity_min", "info"))
        replacements = live_state._runtime.shader_replacements.get(session_id, [])
        messages = []
        for r in replacements:
            for msg in r.get("messages", []):
                messages.append({"severity": "info", "message": msg})
        return envelope.success(messages=messages, severity_min=severity_min)

    if action == "extract_binary":
        shader_id = str(args.get("shader_id", "")).strip()
        try:
            stage, shader_id, reflection = await _resolve_shader_binding(
                shader_id=shader_id,
                stage_name=args.get("stage"),
                require_reflection=True,
            )
        except CoreError as exc:
            return envelope.failure(exc.message, code=exc.code, category=exc.category, details=dict(exc.details))
        raw_bytes = shader_patches._shader_raw_bytes(reflection)
        if not raw_bytes:
            return envelope.capability_failure(
                "shader_binary_export_unavailable",
                "Shader reflection does not expose raw bytes for the requested shader",
                capability="shader_binary_export",
                reason="Shader reflection does not expose raw bytes for the requested shader.",
                source="renderdoc_runtime",
                action=action,
                session_id=session_id,
                shader_id=shader_id,
                resolved_event_id=int(event_id),
            )
        encoding_name = shader_patches._shader_encoding_name(getattr(reflection, "encoding", ""))
        container = str(args.get("container") or encoding_name or "bin").strip().lower() or "bin"
        result: Dict[str, Any] = {
            "shader_id": shader_id,
            "encoding": encoding_name,
            "container": container,
            "byte_size": len(raw_bytes),
            "resolved_event_id": int(event_id),
        }
        output_path = args.get("output_path")
        suffix = shader_patches._shader_binary_suffix(container or encoding_name)
        if output_path:
            out = Path(str(output_path))
            if out.suffix == "":
                out = out.with_suffix(suffix)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(raw_bytes)
            result["saved_path"] = str(out)
        else:
            assert live_state._artifact_store is not None
            artifact = await live_state._artifact_store.store(raw_bytes, mime="application/octet-stream", suffix=suffix)
            result["artifact_path"] = artifact_payloads._artifact_path(artifact)
        if coerce._as_bool(args.get("as_base64"), False):
            import base64

            result["base64"] = base64.b64encode(raw_bytes).decode("ascii")
        return envelope.success(**result)
    async def _inspection_error(message: str, code: str, details: Dict[str, Any], category: str = "runtime") -> envelope.Outcome:
        if inspection_original_event > 0:
            try:
                restored_event = await replay_access._ensure_event(session_id, inspection_original_event)
                if restored_event != inspection_original_event or replay_access._active_event(session_id) != inspection_original_event:
                    raise RuntimeError("Replay event did not match the original event after restoration")
            except Exception as restore_error:
                return envelope.failure(
                    f"Failed to restore replay after shader inspection failed: {restore_error}",
                    code="shader_inspection_recovery_failed", category="runtime",
                    details={**details, "context_id": live_state._runtime_context_id(), "session_id": session_id,
                             "resolved_event_id": int(event_id), "original_error_code": code,
                             "replay_state_restored": False},
                )
            details = {**details, "context_id": live_state._runtime_context_id(),
                       "replay_state_restored": True, "restored_event_id": inspection_original_event}
        return envelope.failure(message, code=code, category=category, details=details)

    if action == "get_source":
        requested_shader_id = str(args.get("shader_id", "")).strip()
        try:
            stage_name, resolved_shader_id, reflection = await _resolve_shader_binding(
                shader_id=requested_shader_id,
                stage_name=args.get("stage"),
                require_reflection=True,
            )
        except CoreError as exc:
            if exc.code in {"shader_binding_lookup_failed", "shader_reflection_unavailable"}:
                return await _inspection_error(exc.message, exc.code, dict(exc.details))
            return envelope.failure(exc.message, code=exc.code, category=exc.category, details=dict(exc.details))
        try:
            source_encoding = shader_patches._shader_encoding_name(getattr(reflection, "encoding", ""))
            debug_info = getattr(reflection, "debugInfo", None)
            native_files = getattr(debug_info, "files", None) if debug_info is not None else None
            if native_files is None:
                return await _inspection_error(
                    "Native shader source metadata is unavailable", "shader_source_metadata_unavailable",
                    {"failure_stage": "source_lookup", "failure_reason": "source_metadata_unavailable",
                     "shader_id": resolved_shader_id, "stage": stage_name.upper()}, category="capability",
                )
            # Native files contain captured text; filenames never authorize host file reads.
            files = []
            for native_file in native_files:
                filename, contents = native_file.filename, native_file.contents
                if not isinstance(filename, str) or not isinstance(contents, str):
                    raise TypeError("Native shader source filename and contents must be text")
                files.append({"filename": filename, "contents": contents})
            debug_encoding = shader_patches._shader_encoding_name(getattr(debug_info, "encoding", ""))
            if debug_encoding in {"unknown", "none"}:
                debug_encoding = ""
            entry_point = getattr(debug_info, "entrySourceName", None)
            if entry_point is not None and not isinstance(entry_point, str):
                raise TypeError("Native source entry name must be text")
            entry_point = entry_point or None
            source_debug = getattr(debug_info, "sourceDebugInformation", None)
            if source_debug is not None and not isinstance(source_debug, bool):
                raise TypeError("Native source debugging availability must be boolean")
            native_flags = getattr(debug_info, "compileFlags", None)
            compile_flags = None
            if native_flags is not None:
                compile_flags = []
                for flag in native_flags.flags:
                    if not isinstance(flag.name, str) or not isinstance(flag.value, str):
                        raise TypeError("Native shader compile flags must contain text names and values")
                    compile_flags.append({"name": flag.name, "value": flag.value})
        except Exception as exc:
            return await _inspection_error(
                f"Failed to read native shader source: {exc}", "shader_source_lookup_failed",
                {"failure_stage": "source_lookup", "failure_reason": "native_source_read_failed",
                 "shader_id": resolved_shader_id, "stage": stage_name.upper()},
            )
        # RenderDoc defines the first file as the entry source, not the first nonempty include.
        source = files[0]["contents"] if files and files[0]["contents"].strip() else None
        common = {
            "source": source, "files": files, "source_available": source is not None,
            "source_encoding": debug_encoding or None, "entry_point": entry_point,
            "compile_flags": compile_flags,
            "source_debug_information": bool(source_debug) if source_debug is not None else None,
            "shader_id": resolved_shader_id, "stage": stage_name.upper(), "resolved_event_id": int(event_id),
        }
        if source is not None:
            return envelope.success(**common, edit_plan=shader_patches._shader_edit_plan(source_encoding=debug_encoding, source=source))
        edit_plan = shader_patches._shader_edit_plan(source_encoding=source_encoding, source_available=False)
        replacement_supported, replacement_reason = truth_matrix._session_replace_capability(session_id, controller)
        try:
            supported_encodings = await renderdoc_api._offload(truth_matrix._supported_source_encoding_names, controller)
        except Exception as exc:
            full_source_replacement = {
                "available": None,
                "reason": f"Could not query target shader encodings: {exc}",
            }
        else:
            text_encodings = [name for name in supported_encodings if name in {"hlsl", "glsl"}]
            full_source_replacement = {
                "available": bool(replacement_supported and text_encodings),
                "runtime_replacement_supported": replacement_supported,
                "runtime_replacement_reason": replacement_reason,
                "supported_source_encodings": supported_encodings,
                "supported_text_encodings": text_encodings,
                "input_kind": "user_full_source",
                "allowed_edit_inputs": ["source_text", "source_path"],
                "recommended_next_tool": "rd.shader.edit_and_replace" if replacement_supported and text_encodings else None,
                "note": (
                    "Full replacement requires separately supplied source; native disassembly remains read-only. "
                    "A single-contribution comparison requires matching semantics and baseline validation."
                ),
            }
        edit_plan["full_source_replacement"] = full_source_replacement
        fallback_args = shader_patches._shader_source_fallback_args(
            session_id=session_id, event_id=int(event_id), stage=stage_name,
            shader_id=resolved_shader_id, source_encoding=source_encoding,
        )
        fallback = {
            "tool": "rd.shader.get_disassembly", "args": fallback_args,
            "reason": "entry shader source contents are unavailable" if files else "original shader source is unavailable from capture debug information",
        }
        return envelope.success(
            **common, fallback=fallback, fallback_tool="rd.shader.get_disassembly", fallback_args=fallback_args,
            edit_plan=edit_plan, failure_stage="source_lookup",
            failure_reason="entry_source_contents_unavailable" if files else "source_debug_info_unavailable",
        )

    if action == "get_constant_buffer_contents":
        requested_shader_id = str(args.get("shader_id", "")).strip()
        try:
            stage_name, resolved_shader_id, reflection = await _resolve_shader_binding(
                shader_id=requested_shader_id,
                stage_name=args.get("stage"),
                require_reflection=True,
            )
        except CoreError as exc:
            return envelope.failure(exc.message, code=exc.code, category=exc.category, details=dict(exc.details))
        slot_value = coerce._as_int(args.get("slot"), 0) if args.get("slot") is not None else None
        native_shader_id = await renderdoc_api._offload(pipe.GetShader, renderdoc_api._rd_stage(stage_name))
        cbuffer_entries = await shader_values._collect_constant_buffers(
            controller,
            pipe,
            reflection,
            stage_name,
            native_shader_id,
            slot=slot_value,
            array_index=coerce._as_int(args.get("array_index"), 0),
            include_contents=True,
            max_bytes=coerce._as_int(args.get("max_bytes"), 1048576),
            flatten=coerce._as_bool(args.get("flatten"), True),
        )
        cbuffer_payload = dict(cbuffer_entries[0]) if cbuffer_entries else {}
        decoded_values = cbuffer_payload.get("flattened_contents") or cbuffer_payload.get("contents")
        if cbuffer_payload and not decoded_values:
            resource_id = str(cbuffer_payload.get("resource_id") or "").strip()
            offset = coerce._as_int(cbuffer_payload.get("offset"), 0)
            byte_size = coerce._as_int(cbuffer_payload.get("byte_size") or cbuffer_payload.get("size"), 0)
            window = shader_values._constant_buffer_byte_window(byte_size, coerce._as_int(cbuffer_payload.get("size"), 0), coerce._as_int(args.get("max_bytes"), 1048576))
            read_length = min(window["required_bytes"], window["permitted_bytes"])
            if resource_id and read_length > 0:
                try:
                    rid = await replay_access._resolve_resource_id(session_id, resource_id)
                    raw = await renderdoc_api._offload(controller.GetBufferData, rid, offset, read_length)
                    raw_bytes = bytes(raw or b"")
                    if len(raw_bytes) != read_length:
                        raise ValueError(f"Native constant buffer read returned {len(raw_bytes)} bytes for {read_length} requested")
                    cbuffer_payload["raw_fallback"] = {
                        "resource_id": resource_id,
                        "offset": offset,
                        "byte_size": len(raw_bytes),
                        "hex_preview": raw_bytes[:256].hex(),
                        "preview_bytes": min(len(raw_bytes), 256),
                        "preview_truncated": len(raw_bytes) > 256,
                        "block_bytes": window["required_bytes"],
                        "requested_bytes": read_length,
                        "truncated": len(raw_bytes) < window["required_bytes"],
                        "recommended_next_tool": "rd.export.buffer",
                        "recommended_args": {
                            "session_id": session_id,
                            "buffer_id": resource_id,
                            "offset": offset,
                            "size": min(window["required_bytes"], window["binding_bytes"] or window["required_bytes"]),
                        },
                    }
                    cbuffer_payload["decode_status"] = "raw_fallback"
                    return envelope.success(cbuffer=cbuffer_payload, shader_id=resolved_shader_id, resolved_event_id=int(event_id))
                except Exception as exc:
                    cbuffer_payload["raw_fallback_error"] = str(exc)
            return await _inspection_error(
                "Constant buffer reflection data is unavailable and raw buffer data could not be read",
                code="constant_buffer_data_unavailable",
                details={
                    "session_id": session_id,
                    "shader_id": resolved_shader_id,
                    "resolved_event_id": int(event_id),
                    "stage": stage_name.upper(),
                    "slot": slot_value,
                    "cbuffer": cbuffer_payload,
                    "failure_stage": "decode_constant_buffer",
                    "failure_reason": window["status"] if not window["complete_range_permitted"] else "reflection_unavailable_without_raw_fallback",
                },
            )
        if not cbuffer_payload:
            return await _inspection_error(
                "No constant buffer data is available for the requested stage/slot",
                code="constant_buffer_data_unavailable",
                details={"session_id": session_id, "shader_id": resolved_shader_id, "resolved_event_id": int(event_id), "stage": stage_name.upper(), "slot": slot_value,
                         "failure_stage": "decode_constant_buffer", "failure_reason": "slot_unavailable"},
            )
        return envelope.success(cbuffer=cbuffer_payload, shader_id=resolved_shader_id, resolved_event_id=int(event_id))

    if action in {"list_entry_points", "get_bindpoint_mapping", "get_constant_block_layout", "get_reflection", "get_disassembly"}:
        shader_id = str(args.get("shader_id", "")).strip()
        try:
            stage, shader_id, reflection = await _resolve_shader_binding(
                shader_id=shader_id,
                stage_name=args.get("stage"),
                require_reflection=action in {"get_reflection", "get_disassembly"},
            )
        except CoreError as exc:
            return envelope.failure(exc.message, code=exc.code, category=exc.category, details=dict(exc.details))
        if action == "list_entry_points":
            entries = []
            if reflection is not None:
                entries.append({"name": str(getattr(reflection, "entryPoint", "main")), "stage": stage.upper()})
            return envelope.success(entry_points=entries, shader_id=shader_id, resolved_event_id=int(event_id))
        if action == "get_bindpoint_mapping":
            mapping = []
            if reflection is not None:
                for ro in getattr(reflection, "readOnlyResources", []) or []:
                    mapping.append({"resource_name": str(getattr(ro, "name", "")), "bindpoint": int(getattr(ro, "bindPoint", 0)), "type": "SRV", "stage": stage.upper()})
                for rw in getattr(reflection, "readWriteResources", []) or []:
                    mapping.append({"resource_name": str(getattr(rw, "name", "")), "bindpoint": int(getattr(rw, "bindPoint", 0)), "type": "UAV", "stage": stage.upper()})
            return envelope.success(mapping=mapping, shader_id=shader_id, resolved_event_id=int(event_id))
        if action == "get_constant_block_layout":
            block_name_or_index = args.get("block_name_or_index")
            blocks = getattr(reflection, "constantBlocks", []) or []
            selected = None
            if isinstance(block_name_or_index, int):
                if 0 <= block_name_or_index < len(blocks):
                    selected = blocks[block_name_or_index]
            else:
                key = str(block_name_or_index)
                for block in blocks:
                    if str(getattr(block, "name", "")) == key:
                        selected = block
                        break
            if selected is None and blocks:
                selected = blocks[0]
            if selected is None:
                return envelope.success(layout={}, shader_id=shader_id, resolved_event_id=int(event_id))
            layout = {
                "name": str(getattr(selected, "name", "")),
                "byte_size": int(getattr(selected, "byteSize", 0)),
                "vars": [
                    {
                        "name": str(getattr(v, "name", "")),
                        "offset": int(getattr(v, "byteOffset", 0)),
                        "type": str(getattr(getattr(v, "type", None), "descriptor", None)),
                    }
                    for v in (getattr(selected, "variables", []) or [])
                ],
            }
            return envelope.success(layout=layout, shader_id=shader_id, resolved_event_id=int(event_id))
        if action == "get_reflection":
            native_debug_info = getattr(reflection, "debugInfo", None) if reflection is not None else None
            native_debuggable = getattr(native_debug_info, "debuggable", None)
            native_source_debug = getattr(native_debug_info, "sourceDebugInformation", None)
            native_debug_status = getattr(native_debug_info, "debugStatus", None)
            refl = {
                "entry_points": [str(getattr(reflection, "entryPoint", "main"))] if reflection else [],
                "inputs": [],
                "outputs": [],
                "resources": [],
                "constant_blocks": [],
                "samplers": [],
                "debug_info": {
                    "debuggable": bool(native_debuggable) if native_debuggable is not None else None,
                    "source_debug_information": bool(native_source_debug) if native_source_debug is not None else None,
                    "status": str(native_debug_status) if native_debug_status is not None else None,
                },
            }
            if reflection is not None:
                for ro in getattr(reflection, "readOnlyResources", []) or []:
                    refl["resources"].append({"name": str(getattr(ro, "name", "")), "bindpoint": int(getattr(ro, "bindPoint", 0)), "type": "SRV"})
                for cb in getattr(reflection, "constantBlocks", []) or []:
                    refl["constant_blocks"].append({"name": str(getattr(cb, "name", "")), "byte_size": int(getattr(cb, "byteSize", 0))})
            return envelope.success(reflection=refl, shader_id=shader_id, resolved_event_id=int(event_id))
        if action == "get_disassembly":
            requested_target = str(args.get("target", "auto"))
            requested_encoding = str(args.get("source_encoding") or "")
            try:
                text, resolved_encoding, resolved_target, is_raw_spirv_asm = await renderdoc_api._offload(
                    PatchEngine._resolve_source,
                    controller,
                    pipe,
                    reflection,
                    ShaderStage(stage),
                    session_id,
                    requested_target=requested_target if requested_target != "auto" else "",
                    requested_encoding=requested_encoding,
                )
            except HostToolUnavailableError as exc:
                return await _inspection_error(
                    str(exc), "host_tool_unavailable",
                    {"failure_stage": "disassembly", "replacement_attempted": False,
                     "effects_attempted": False, "context_preserved": True}, category="capability")
            except RuntimeError as exc:
                return envelope.failure(
                    str(exc),
                    code="shader_disassembly_unavailable",
                    category="runtime",
                    details={
                        "session_id": session_id,
                        "resolved_event_id": int(event_id),
                        "shader_id": shader_id,
                        "requested_target": requested_target,
                        "requested_source_encoding": requested_encoding,
                        "failure_stage": "disassembly",
                        "failure_reason": "source_unavailable",
                    },
                )
            target_discovery = await _disassembly_target_metadata(controller)
            source_encoding_name = shader_patches._shader_encoding_name(resolved_encoding)
            if PatchEngine._is_raw_spirv_asm_request(requested_target, requested_encoding) or bool(is_raw_spirv_asm):
                source_encoding_name = "spirvasm"
            elif PatchEngine._is_raw_dxil_asm_request(requested_target, requested_encoding):
                source_encoding_name = "dxilasm"
            edit_plan = shader_patches._shader_edit_plan(
                source_encoding=source_encoding_name,
                disassembly_target=str(resolved_target or ""),
                source=str(text or ""),
                source_available=bool(text),
            )
            if not text:
                return envelope.success(
                    disassembly="",
                    target=str(resolved_target or ""),
                    source_encoding=source_encoding_name,
                    is_raw_spirv_asm=bool(is_raw_spirv_asm),
                    edit_plan=edit_plan,
                    shader_id=shader_id,
                    resolved_event_id=int(event_id),
                    source_hash="",
                    **target_discovery,
                )
            return envelope.success(
                disassembly=str(text),
                target=str(resolved_target or ""),
                source_encoding=source_encoding_name,
                is_raw_spirv_asm=bool(is_raw_spirv_asm),
                edit_plan=edit_plan,
                shader_id=shader_id,
                resolved_event_id=int(event_id),
                source_hash=hashlib.sha256(str(text).encode("utf-8")).hexdigest(),
                **target_discovery,
            )

    return envelope.failure(f"Unsupported shader action: {action}", code="runtime_error")
