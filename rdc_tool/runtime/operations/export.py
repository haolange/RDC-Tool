"""rd.export.* operations."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List

from rdc_tool.core.errors import CoreError
from rdc_tool.runtime import (
    coerce,
    envelope,
    live_state,
    renderdoc_api,
    replay_access,
    shader_values,
    texture_export,
    texture_naming,
    visual_target,
)
from rdc_tool.runtime.operations import pipeline as pipeline_ops
from rdc_tool.runtime.operations import shader as shader_ops
from rdc_tool.runtime.operations import texture as texture_ops


async def dispatch(action: str, args: Dict[str, Any]) -> envelope.Outcome:
    coerce._require(args, "session_id")
    session_id = str(args["session_id"])

    if action == "screenshot":
        requested_formats = texture_naming._parse_requested_formats(args.get("file_format", "png"))
        allowed_formats = {"png", "jpg", "exr", "hdr"}
        special_formats = {"auto", "smart", "all", "*"}
        if not any(fmt in allowed_formats or fmt in special_formats for fmt in requested_formats):
            return envelope.failure("Unsupported screenshot format", code="screenshot_format_unsupported",
                                    category="validation", details={"session_id": session_id,
                                        "failure_stage": "validate_format", "effects_attempted": False, "context_preserved": True})
        target = coerce._parse_target_like(args.get("target"))
        original_event = replay_access._active_event(session_id)
        event_id = coerce._as_int(args.get("event_id"), original_event)
        if event_id <= 0:
            event_id = await replay_access._ensure_event(session_id, None)
        explicit_target = target.get("texture_id") or target.get("textureId")
        try:
            target_texture_id, texture_desc, visual_target_payload, truth_meta = await visual_target._resolve_visual_target_for_event(
                session_id,
                event_id,
                target=target,
            )
        except CoreError as exc:
            failure_message, failure_code, failure_category = exc.message, exc.code, exc.category
            details = dict(exc.details)
        except Exception as exc:
            failure_message = f"Failed to resolve screenshot target: {exc}"
            failure_code, failure_category = "screenshot_target_unavailable", "runtime"
            details = {}
        else:
            failure_message = None
        if failure_message is not None:
            details["session_id"] = session_id
            details["event_id"] = int(event_id)
            details["failure_stage"] = "resolve_visual_target"
            if original_event > 0:
                try:
                    restored_event = await replay_access._ensure_event(session_id, original_event)
                    if restored_event != original_event or replay_access._active_event(session_id) != original_event:
                        raise RuntimeError("Replay event did not match the original event after restoration")
                except Exception as exc:
                    return envelope.failure(
                        f"Failed to restore replay after screenshot target resolution failed: {exc}",
                        code="screenshot_target_recovery_failed",
                        category="runtime",
                        details={
                            "context_id": live_state._runtime_context_id(),
                            "session_id": session_id,
                            "event_id": int(event_id),
                            "failure_stage": "resolve_visual_target",
                            "original_error_code": failure_code,
                            "replay_state_restored": False,
                            "artifact_write_attempted": False,
                        },
                    )
                details.update({
                    "context_id": live_state._runtime_context_id(),
                    "replay_state_restored": True,
                    "restored_event_id": original_event,
                    "artifact_write_attempted": False,
                })
            return envelope.failure(failure_message, code=failure_code, category=failure_category, details=details)
        chosen_output_slot = visual_target_payload.get("output_slot") if isinstance(visual_target_payload, dict) else None
        target_source = str(visual_target_payload.get("target_source") or "") if isinstance(visual_target_payload, dict) else ""
        resolved_event_id = coerce._as_int(
            visual_target_payload.get("resolved_event_id") if isinstance(visual_target_payload, dict) else None,
            int(event_id),
        )
        present_event_id = coerce._as_int(
            visual_target_payload.get("present_event_id") if isinstance(visual_target_payload, dict) else None,
            0,
        )
        binding_index = await replay_access._binding_name_index_for_event(session_id, resolved_event_id)
        name_info = texture_naming._compose_texture_name_info(
            target_texture_id,
            resource_name=str(getattr(texture_desc, "name", "")) if texture_desc is not None else "",
            binding_names=binding_index.get(str(target_texture_id), []),
            alias_name=live_state._runtime.aliases.get(str(target_texture_id), ""),
        )
        recommended_formats = texture_naming._recommend_formats_for_texture(
            texture_desc,
            name_info=name_info,
            for_screenshot=True,
        )
        requested_format_value = args.get("file_format")
        if requested_format_value is None:
            requested_format_value = "png"
        requested_formats = texture_naming._parse_requested_formats(requested_format_value)
        selected_formats = texture_naming._select_export_formats(
            requested_formats,
            recommended_formats=recommended_formats,
        )
        valid_formats = [fmt for fmt in selected_formats if fmt in allowed_formats]
        if not valid_formats:
            allowed_text = ", ".join(sorted(allowed_formats))
            requested_text = ", ".join(selected_formats) or ", ".join(requested_formats)
            return envelope.failure(
                f"rd.export.screenshot only supports {allowed_text}; got '{requested_text}'", code="runtime_error",
            )
        base_output_path = args.get("output_path")
        if chosen_output_slot is not None and not explicit_target:
            role_stem = f"framebuffer_rt{chosen_output_slot}"
        else:
            role_stem = "framebuffer"
        base_name_stem = texture_naming._safe_name_token(f"ev{resolved_event_id}_{role_stem}_{name_info['name_stem']}")
        multi_export = len(valid_formats) > 1
        include_alpha = coerce._as_bool(args.get("include_alpha"), False)
        exports: List[Dict[str, Any]] = []
        for export_format in valid_formats:
            resolved_output_path = texture_naming._resolve_export_output_path(
                base_output_path,
                name_stem=base_name_stem,
                file_format=export_format,
                multi=multi_export,
            )
            rendered = await texture_ops.dispatch(
                "render_overlay",
                {
                    "session_id": session_id,
                    "texture_id": str(target_texture_id),
                    "event_id": resolved_event_id,
                    "overlay": args.get("overlay", "none"),
                    "output_path": resolved_output_path,
                    "file_format": export_format,
                    "include_alpha": include_alpha,
                },
            )
            if not rendered.ok:
                details = dict(rendered.details)
                details.setdefault("session_id", session_id)
                details.setdefault("event_id", int(resolved_event_id))
                details.setdefault("requested_event_id", int(event_id))
                details.setdefault("texture_id", str(target_texture_id))
                details.setdefault("target_source", target_source)
                details.setdefault("chosen_output_slot", chosen_output_slot)
                if present_event_id > 0:
                    details.setdefault("present_event_id", int(present_event_id))
                if isinstance(visual_target_payload, dict) and visual_target_payload.get("swapchain_error"):
                    details.setdefault("swapchain_error", visual_target_payload.get("swapchain_error"))
                details.setdefault("failure_stage", "save_texture")
                return envelope.failure(rendered.message, code=rendered.code, category=rendered.category, details=details)
            payload = rendered.data
            export_meta = dict(rendered.meta)
            image_width = coerce._as_int(export_meta.get("width"), 0)
            image_height = coerce._as_int(export_meta.get("height"), 0)
            if image_width <= 0 or image_height <= 0:
                return envelope.failure(
                    "Screenshot renderer did not report the exported image dimensions",
                    code="screenshot_dimensions_unavailable",
                    category="runtime",
                    details={
                        "session_id": session_id,
                        "event_id": int(resolved_event_id),
                        "texture_id": str(target_texture_id),
                        "file_format": export_format,
                    },
                )
            exports.append(
                {
                    "file_format": export_format,
                    "artifact_path": payload.get("artifact_path"),
                    "saved_path": payload.get("saved_path") or payload.get("image_path") or payload.get("artifact_path"),
                    "image_path": payload.get("image_path") or payload.get("saved_path") or payload.get("artifact_path"),
                    "meta": export_meta,
                    "width": image_width,
                    "height": image_height,
                    "binding_truth_level": payload.get("binding_truth_level"),
                    "visual_truth_level": payload.get("visual_truth_level"),
                    "evidence_truth_level": payload.get("evidence_truth_level"),
                    "summary_degraded_reasons": list(payload.get("summary_degraded_reasons") or []),
                },
            )
        if not multi_export:
            single = exports[0]
            degraded_reasons = list(truth_meta.get("summary_degraded_reasons") or [])
            return envelope.success(
                artifact_path=single["artifact_path"],
                saved_path=single["saved_path"],
                image_path=single["image_path"],
                meta=single["meta"],
                width=single["width"],
                height=single["height"],
                texture_width=int(getattr(texture_desc, "width", 0) or 0) if texture_desc is not None else 0,
                texture_height=int(getattr(texture_desc, "height", 0) or 0) if texture_desc is not None else 0,
                resolved_event_id=int(resolved_event_id),
                requested_event_id=int(event_id),
                present_event_id=int(present_event_id) if present_event_id > 0 else None,
                present_action_name=visual_target_payload.get("present_action_name") if isinstance(visual_target_payload, dict) else None,
                present_usage=visual_target_payload.get("present_usage") if isinstance(visual_target_payload, dict) else None,
                selected_formats=valid_formats,
                requested_formats=requested_formats,
                recommended_formats=recommended_formats,
                name_info=name_info,
                texture_format=texture_naming._texture_format_name(texture_desc),
                chosen_output_slot=chosen_output_slot,
                texture_id=str(target_texture_id),
                target_source=target_source,
                requested_semantic=visual_target_payload.get("requested_semantic") if isinstance(visual_target_payload, dict) else None,
                fallback_reason=visual_target_payload.get("fallback_reason") if isinstance(visual_target_payload, dict) else None,
                swapchain_error=visual_target_payload.get("swapchain_error") if isinstance(visual_target_payload, dict) else None,
                binding_truth_level=truth_meta.get("binding_truth_level"),
                visual_truth_level=single.get("visual_truth_level") or truth_meta.get("visual_truth_level"),
                evidence_truth_level=single.get("evidence_truth_level") or truth_meta.get("evidence_truth_level"),
                summary_degraded=bool(degraded_reasons),
                summary_degraded_reasons=degraded_reasons,
            )
        degraded_reasons = list(truth_meta.get("summary_degraded_reasons") or [])
        return envelope.success(
            exports=exports,
            saved_paths=[item["saved_path"] for item in exports],
            image_paths=[item["image_path"] for item in exports],
            width=exports[0]["width"],
            height=exports[0]["height"],
            texture_width=int(getattr(texture_desc, "width", 0) or 0) if texture_desc is not None else 0,
            texture_height=int(getattr(texture_desc, "height", 0) or 0) if texture_desc is not None else 0,
            resolved_event_id=int(resolved_event_id),
            requested_event_id=int(event_id),
            present_event_id=int(present_event_id) if present_event_id > 0 else None,
            present_action_name=visual_target_payload.get("present_action_name") if isinstance(visual_target_payload, dict) else None,
            present_usage=visual_target_payload.get("present_usage") if isinstance(visual_target_payload, dict) else None,
            selected_formats=valid_formats,
            requested_formats=requested_formats,
            recommended_formats=recommended_formats,
            name_info=name_info,
            texture_format=texture_naming._texture_format_name(texture_desc),
            chosen_output_slot=chosen_output_slot,
            texture_id=str(target_texture_id),
            target_source=target_source,
            requested_semantic=visual_target_payload.get("requested_semantic") if isinstance(visual_target_payload, dict) else None,
            fallback_reason=visual_target_payload.get("fallback_reason") if isinstance(visual_target_payload, dict) else None,
            swapchain_error=visual_target_payload.get("swapchain_error") if isinstance(visual_target_payload, dict) else None,
            binding_truth_level=truth_meta.get("binding_truth_level"),
            visual_truth_level=exports[0].get("visual_truth_level") if exports else truth_meta.get("visual_truth_level"),
            evidence_truth_level=exports[0].get("evidence_truth_level") if exports else truth_meta.get("evidence_truth_level"),
            summary_degraded=bool(degraded_reasons),
            summary_degraded_reasons=degraded_reasons,
        )
    if action == "texture":
        return await texture_export._export_texture_file({"session_id": session_id, **dict(args or {})})
    if action == "buffer":
        return await texture_export._export_buffer_file({"session_id": session_id, **dict(args or {})})
    if action == "mesh":
        return await texture_export._export_mesh_file({"session_id": session_id, **dict(args or {})})
    if action == "shader_bundle":
        coerce._require(args, "event_id", "output_dir")
        resolved_event_id = await replay_access._ensure_event(session_id, coerce._as_int(args.get("event_id"), 0))
        output_dir = Path(str(args["output_dir"]))
        output_dir.mkdir(parents=True, exist_ok=True)
        include_binaries = coerce._as_bool(args.get("include_binaries"), True)
        include_reflection = coerce._as_bool(args.get("include_reflection"), True)
        include_disassembly = coerce._as_bool(args.get("include_disassembly"), True)
        disassembly_target = str(args.get("disassembly_target") or "auto")
        stage_payloads = []
        failures = []
        for stage in renderdoc_api._stage_candidates():
            shader_result = await pipeline_ops.dispatch(
                "get_shader",
                {"session_id": session_id, "stage": stage, "event_id": resolved_event_id},
            )
            shader_payload = shader_result.data if shader_result.ok else {}
            if shader_payload.get("shader", {}).get("shader_id"):
                shader = dict(shader_payload["shader"])
                shader_id = str(shader["shader_id"])
                stage_name = str(shader.get("stage") or stage).lower()
                entry = {
                    **shader,
                    "resolved_event_id": int(shader_payload.get("resolved_event_id") or resolved_event_id),
                    "exports": {},
                }
                for kind, enabled, shader_action in (
                    ("binary", include_binaries, "extract_binary"),
                    ("reflection", include_reflection, "get_reflection"),
                    ("disassembly", include_disassembly, "get_disassembly"),
                ):
                    if not enabled:
                        continue
                    call_args = {
                        "session_id": session_id,
                        "event_id": int(resolved_event_id),
                        "stage": stage_name,
                        "shader_id": shader_id,
                    }
                    if kind == "binary":
                        call_args["output_path"] = str(output_dir / f"{stage_name}-shader")
                    elif kind == "disassembly":
                        call_args["target"] = disassembly_target
                    exported = await shader_ops.dispatch(shader_action, call_args)
                    if not exported.ok:
                        failure = {"stage": stage_name, "kind": kind, "code": exported.code, "message": exported.message}
                        failures.append(failure)
                        entry["exports"][kind] = {"available": False, "error": failure}
                        continue
                    result = exported.data
                    if kind == "disassembly" and disassembly_target != "auto" and result.get("target") != disassembly_target:
                        failure = {"stage": stage_name, "kind": kind, "code": "shader_disassembly_target_mismatch",
                                   "message": "Disassembly export did not return the explicitly requested target",
                                   "requested_target": disassembly_target, "actual_target": result.get("target")}
                        failures.append(failure)
                        entry["exports"][kind] = {"available": False, "error": failure}
                        continue
                    if kind == "binary":
                        saved_path = Path(str(result.get("saved_path") or ""))
                        if not saved_path.is_file():
                            failure = {"stage": stage_name, "kind": kind, "code": "shader_export_missing", "message": "Binary export returned no file"}
                            failures.append(failure)
                            entry["exports"][kind] = {"available": False, "error": failure}
                            continue
                        content = saved_path.read_bytes()
                    else:
                        content = (
                            json.dumps(result.get("reflection"), ensure_ascii=False, indent=2).encode("utf-8")
                            if kind == "reflection"
                            else str(result.get("disassembly") or "").encode("utf-8")
                        )
                        if kind == "disassembly" and not content:
                            failure = {"stage": stage_name, "kind": kind, "code": "shader_disassembly_empty", "message": "Disassembly export returned no source"}
                            failures.append(failure)
                            entry["exports"][kind] = {"available": False, "error": failure}
                            continue
                        saved_path = output_dir / f"{stage_name}-{kind}.{'json' if kind == 'reflection' else 'txt'}"
                        saved_path.write_bytes(content)
                    entry["exports"][kind] = {
                        "available": True,
                        "path": str(saved_path),
                        "sha256": hashlib.sha256(content).hexdigest(),
                        "size_bytes": len(content),
                        **({"target": result.get("target"), "source_encoding": result.get("source_encoding"),
                            "is_raw_spirv_asm": result.get("is_raw_spirv_asm"), "source_hash": result.get("source_hash"),
                            "edit_plan": result.get("edit_plan")} if kind == "disassembly" else {}),
                    }
                stage_payloads.append(entry)
        if not stage_payloads:
            return envelope.failure(
                f"No bound shaders available for event {int(resolved_event_id)}",
                code="shader_bundle_empty",
                category="runtime",
                details={"session_id": session_id, "resolved_event_id": int(resolved_event_id)},
            )
        bundle_json = output_dir / "shader_bundle.json"
        bundle_json.write_text(
            json.dumps(
                {
                    "requested_event_id": coerce._as_int(args.get("event_id"), 0),
                    "resolved_event_id": int(resolved_event_id),
                    "disassembly_target": disassembly_target,
                    "shaders": stage_payloads,
                    "complete": not failures,
                    "failures": failures,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return envelope.success(output_dir=str(output_dir), bundle_path=str(bundle_json), resolved_event_id=int(resolved_event_id), complete=not failures, failures=failures, disassembly_target=disassembly_target)
    if action == "cbuffer_dump":
        coerce._require(args, "output_dir")
        output_dir = Path(str(args["output_dir"]))
        output_dir.mkdir(parents=True, exist_ok=True)
        stages = [str(item).lower() for item in coerce._as_list(args.get("stages"), default=["vs", "ps", "cs"])]
        slots_arg = args.get("slots")
        slots = [coerce._as_int(item) for item in coerce._as_list(slots_arg, default=[])] if slots_arg is not None else []
        dumped: List[str] = []
        failures: List[Dict[str, Any]] = []
        limited_raw_export = False
        for stage in stages:
            call_args: Dict[str, Any] = {
                "session_id": session_id,
                "stage": stage,
                "include_contents": coerce._as_bool(args.get("include_decoded"), True),
                "max_bytes": coerce._as_int(args.get("max_bytes"), 1048576),
                "flatten": True,
            }
            constant_buffers = await pipeline_ops.dispatch("get_constant_buffers", call_args)
            if not constant_buffers.ok:
                failures.append({"stage": stage, "error": constant_buffers.message, "code": constant_buffers.code})
                continue
            buffers = list(constant_buffers.data.get("constant_buffers", []) or [])
            if slots:
                buffers = [item for item in buffers if coerce._as_int((item or {}).get("slot"), -1) in slots]
            if coerce._as_bool(args.get("include_decoded"), True):
                for item in buffers:
                    if item.get("decode_error"):
                        failures.append({"stage": stage, "slot": item.get("slot"), "code": "constant_buffer_decode_unavailable", "error": item["decode_error"]})
            if coerce._as_bool(args.get("include_raw"), False):
                for item in buffers:
                    resource_id = str((item or {}).get("resource_id") or "").strip()
                    byte_size = coerce._as_int((item or {}).get("byte_size") or (item or {}).get("size"), 0)
                    offset = coerce._as_int((item or {}).get("offset"), 0)
                    window = shader_values._constant_buffer_byte_window(byte_size, coerce._as_int((item or {}).get("size"), 0), coerce._as_int(args.get("max_bytes"), 1048576))
                    raw_length = min(window["required_bytes"], window["permitted_bytes"])
                    if not resource_id or raw_length <= 0:
                        continue
                    limited_raw_export = limited_raw_export or raw_length < window["required_bytes"]
                    item["raw_export_coverage"] = {"block_bytes": window["required_bytes"], "requested_bytes": raw_length,
                                                   "truncated": raw_length < window["required_bytes"]}
                    try:
                        raw_export = await texture_export._export_buffer_file(
                            {
                                "session_id": session_id,
                                "buffer_id": resource_id,
                                "offset": offset,
                                "size": raw_length,
                                "output_path": str(output_dir / f"cbuffer_{stage}_slot{coerce._as_int((item or {}).get('slot'), 0)}.bin"),
                            }
                        )
                        if raw_export.ok:
                            item["raw_path"] = raw_export.data.get("saved_path")
                        else:
                            failures.append({"stage": stage, "slot": (item or {}).get("slot"), "code": raw_export.code, "error": raw_export.message})
                    except Exception as exc:
                        failures.append({"stage": stage, "slot": (item or {}).get("slot"), "error": str(exc), "code": "raw_export_failed"})
            file_path = output_dir / f"cbuffer_{stage}.json"
            file_path.write_text(json.dumps(buffers, ensure_ascii=False, indent=2), encoding="utf-8")
            dumped.append(str(file_path))
        if failures and not dumped:
            return envelope.failure("All constant buffer exports failed", code="cbuffer_export_failed", details={"failures": failures})
        return envelope.success(dumped_paths=dumped, saved_files=dumped, failures=failures, partial=bool(failures) or limited_raw_export, stages=stages, slots=slots)
    return envelope.failure(f"Unsupported export action: {action}", code="runtime_error")
