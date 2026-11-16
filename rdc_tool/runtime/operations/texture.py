"""rd.texture.* operations."""

from __future__ import annotations

import asyncio
import base64
import io
import shutil
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict

import numpy as np

from rdc_tool import timeout_policy
from rdc_tool.core.errors import CoreError
from rdc_tool.core.render_service import TextureDecodeError
from rdc_tool.runtime import (
    artifact_payloads,
    coerce,
    envelope,
    live_state,
    pixel_trace,
    renderdoc_api,
    replay_access,
    texture_export,
    texture_naming,
    truth_matrix,
    visual_target,
)


async def dispatch(action: str, args: Dict[str, Any]) -> str:
    if action not in {"get_data", "get_region_values", "get_histogram", "compute_stats", "diff"}:
        return await _dispatch_texture_impl(action, args)
    session_id = str(args.get("session_id", ""))
    original_event = replay_access._active_event(session_id)
    try:
        return await _dispatch_texture_impl(action, args)
    except TextureDecodeError as exc:
        details = {"context_id": live_state._runtime_context_id(), "session_id": session_id,
                   "failure_stage": "decode_texture_readback"}
        try:
            if original_event <= 0 or await replay_access._ensure_event(session_id, original_event) != original_event \
                    or replay_access._active_event(session_id) != original_event:
                raise RuntimeError("Original replay event was not restored")
        except Exception as restore_error:
            return envelope._err(f"Texture readback failed; replay restoration failed: {restore_error}",
                        code="texture_readback_restore_failed", category="runtime",
                        details={**details, "replay_state_restored": False})
        return envelope._err(str(exc), code="texture_readback_decode_failed", category="validation",
                    details={**details, "replay_state_restored": True, "restored_event_id": original_event})


async def _dispatch_texture_impl(action: str, args: Dict[str, Any]) -> str:
    coerce._require(args, "session_id")
    session_id = str(args["session_id"])
    assert live_state._render_service is not None

    async def read_array(texture_id: Any, subresource: Dict[str, Any], *, event_id: Any = None, region: Any = None):
        resolved_event = await replay_access._ensure_event(session_id, int(event_id) if event_id is not None else None)
        rid = await replay_access._resolve_texture_id(session_id, texture_id, event_id=resolved_event)
        read_kwargs = {"region": region} if region is not None else {}
        arr, stats = await live_state._render_service.read_texture_array(session_id, resolved_event, rid, live_state._session_manager, subresource, **read_kwargs)
        return arr, stats, int(resolved_event), str(rid)

    if action == "get_data":
        coerce._require(args, "texture_id")
        subresource = coerce._as_dict(args.get("subresource"), default={})
        representation = str(args.get("representation", "numeric"))
        if representation not in {"numeric", "raw"}:
            return envelope._err("Invalid texture representation", code="validation_error")
        suffix = ".npz" if representation == "numeric" else ".bin"
        output_path = str(args.get("output_path") or "")
        if output_path and Path(output_path).suffix.lower() != suffix:
            return envelope._err(f"Texture output_path must use {suffix}", code="texture_output_path_extension_mismatch")
        rid = await replay_access._resolve_resource_id(session_id, args["texture_id"])
        controller = await replay_access._get_controller(session_id)
        async def read_texture(event):
            if representation == "numeric":
                arr, stats = await live_state._render_service.read_texture_array(session_id, event, rid, live_state._session_manager, subresource)
                output = io.BytesIO()
                np.savez_compressed(output, pixels=arr)
                return output.getvalue(), stats
            textures = await renderdoc_api._offload(controller.GetTextures)
            descriptor = next((item for item in textures if item.resourceId == rid), None)
            if descriptor is None:
                raise ValueError("Texture not found")
            sub = renderdoc_api._get_rd().Subresource()
            sub.mip, sub.slice, sub.sample = (int(subresource.get(key, 0)) for key in ("mip", "slice", "sample"))
            if (sub.mip < 0 or sub.mip >= descriptor.mips or sub.slice < 0
                    or sub.slice >= max(descriptor.arraysize, max(1, descriptor.depth >> sub.mip))
                    or sub.sample < 0 or sub.sample >= max(1, descriptor.msSamp)):
                raise ValueError("Invalid texture subresource")
            data = bytes(await renderdoc_api._offload(controller.GetTextureData, rid, sub))
            if not data:
                raise RuntimeError("Texture readback returned no bytes")
            return data, {"format": str(descriptor.format.Name()), "width": max(1, descriptor.width >> sub.mip),
                          "height": max(1, descriptor.height >> sub.mip), "byte_size": len(data)}
        (data, stats), metadata = await texture_export._read_at_capture_state(session_id, rid, args, read_texture)
        result = {"texture_id": str(rid), "stats": stats, "byte_size": len(data), **metadata,
                  "content_kind": "texture_readback_container" if representation == "numeric" else "texture_raw_bytes",
                  "container_format": "npz" if representation == "numeric" else "raw",
                  "target_metadata": {"texture_id": str(rid), "subresource": subresource, "region": None}}
        inline = coerce._as_bool(args.get("as_base64"), False)
        if inline:
            if len(data) > 1048576:
                return envelope._err("Inline texture limit is 1 MiB; select a smaller mip or export", code="output_budget_exceeded")
            result["base64"] = base64.b64encode(data).decode("ascii")
        if output_path:
            out = Path(output_path)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(data)
            result.update(artifact_path=str(out), saved_path=str(out))
        elif not inline:
            artifact = await live_state._artifact_store.store(data, mime="application/x-npz" if representation == "numeric" else "application/octet-stream", suffix=suffix)
            result.update(artifact_path=artifact_payloads._artifact_path(artifact), saved_path=artifact_payloads._artifact_path(artifact))
        return envelope._ok(**result)

    if action == "get_pixel_value":
        coerce._require(args, "texture_id", "x", "y")
        requested_event_id = coerce._as_int(args.get("event_id"), 0) if args.get("event_id") is not None else None
        try:
            event_id = await replay_access._ensure_event(session_id, requested_event_id)
        except CoreError as exc:
            if exc.code != "event_not_found" or requested_event_id is None:
                raise
            # _ensure_event validates an explicit id against the action index before SetFrameEvent.
            # This rejection cannot have moved the replay or attempted a texture readback.
            return envelope._err(
                exc.message,
                code=exc.code,
                category="validation",
                details={
                    **dict(exc.details),
                    "failure_stage": "validate_event",
                    "effects_attempted": False,
                    "context_preserved": True,
                },
            )
        rid = await replay_access._resolve_texture_id(session_id, args["texture_id"], event_id=event_id)
        pixel = await live_state._render_service.pick_pixel(
            session_id=session_id,
            event_id=event_id,
            texture_id=rid,
            x=coerce._as_int(args["x"]),
            y=coerce._as_int(args["y"]),
            session_manager=live_state._session_manager,
            subresource={key: coerce._as_int(args.get(key), 0) for key in ("mip", "slice", "sample")},
            value_type=str(args.get("as_type", "float")),
        )
        truth_meta = await truth_matrix._event_truth_metadata(session_id, int(event_id))
        return envelope._ok(
            pixel=pixel,
            resolved_event_id=int(event_id),
            texture_id=str(rid),
            target_metadata={
                "texture_id": str(rid),
                "x": coerce._as_int(args["x"]),
                "y": coerce._as_int(args["y"]),
            },
            binding_truth_level=truth_meta.get("binding_truth_level"),
            evidence_truth_level="structured_readback",
            summary_degraded_reasons=list(truth_meta.get("summary_degraded_reasons") or []),
        )

    if action == "get_region_values":
        coerce._require(args, "texture_id", "rect")
        rect = coerce._as_dict(args["rect"])
        region = {"x": coerce._as_int(rect.get("x"), 0), "y": coerce._as_int(rect.get("y"), 0), "width": coerce._as_int(rect.get("w"), 1), "height": coerce._as_int(rect.get("h"), 1)}
        subresource = {
            "mip": coerce._as_int(args.get("mip"), 0),
            "slice": coerce._as_int(args.get("slice"), 0),
            "sample": coerce._as_int(args.get("sample"), 0),
        }
        stride = coerce._as_int(args.get("stride"), 1)
        as_type = str(args.get("as_type", "float"))
        if stride < 1 or as_type not in {"float", "uint", "int"}:
            return envelope._err("Invalid region stride or value type", code="validation_error")
        arr, stats, resolved_event_id, resolved_texture_id = await read_array(args["texture_id"], subresource, region=region, event_id=args.get("event_id"))
        arr = arr[::stride, ::stride]
        if as_type != "float" and not np.isfinite(arr).all():
            return envelope._err("Cannot convert non-finite region to integers", code="texture_nonfinite_data")
        if stats.get("value_interpretation") != "raw_unsigned_integer":
            arr = arr.astype({"float": np.float64, "uint": np.uint32, "int": np.int32}[as_type])
        stats = texture_export._sampled_texture_stats(arr, stats, stride)
        inline_value_limit = 256
        inline_complete = arr.size <= inline_value_limit
        container = io.BytesIO()
        np.savez_compressed(container, pixels=arr)
        artifact_ref = await live_state._artifact_store.store(container.getvalue(), mime="application/x-npz", suffix=".npz")
        artifact_path = artifact_payloads._artifact_path(artifact_ref)
        truth_meta = await truth_matrix._event_truth_metadata(session_id, int(resolved_event_id))
        return envelope._ok(
            values=arr.tolist() if inline_complete else None,
            values_status="complete" if inline_complete else "omitted_limit",
            inline_value_limit=inline_value_limit,
            values_path=artifact_path,
            stats=stats,
            resolved_event_id=int(resolved_event_id),
            texture_id=str(resolved_texture_id),
            target_metadata={
                "texture_id": str(resolved_texture_id),
                "subresource": dict(subresource or {}),
                "region": dict(region or {}),
            },
            binding_truth_level=truth_meta.get("binding_truth_level"),
            evidence_truth_level=truth_meta.get("evidence_truth_level"),
            summary_degraded_reasons=list(truth_meta.get("summary_degraded_reasons") or []),
        )


    if action == "get_histogram":
        coerce._require(args, "texture_id")
        subresource = {"mip": coerce._as_int(args.get("mip"), 0), "slice": coerce._as_int(args.get("slice"), 0), "sample": coerce._as_int(args.get("sample"), 0)}
        arr, stats, resolved_event_id, _ = await read_array(args["texture_id"], subresource, event_id=args.get("event_id"))
        if arr.ndim != 3:
            return envelope._err("Texture format cannot be decoded into channels", code="texture_layout_unsupported")
        channels = str(args.get("channels", "r")).lower()
        bins = coerce._as_int(args.get("bins"), 256)
        rng = coerce._as_dict(args.get("range"), default={})
        out: Dict[str, Any] = {}
        mapping = {"r": 0, "g": 1, "b": 2, "a": 3}
        for c in channels:
            if c not in mapping or mapping[c] >= arr.shape[2]:
                return envelope._err("Invalid histogram channel", code="validation_error")
            channel_data = arr[..., mapping[c]].astype("float64")
            if not np.isfinite(channel_data).all():
                return envelope._err("Histogram contains non-finite samples", code="texture_nonfinite_data")
            if not channel_data.size or bins <= 0:
                return envelope._err("Histogram requires nonempty samples and positive bins", code="validation_error")
            low = coerce._as_float(rng.get("min"), float(channel_data.min()))
            high = coerce._as_float(rng.get("max"), float(channel_data.max()))
            if not np.isfinite(low) or not np.isfinite(high) or low > high:
                return envelope._err("Invalid histogram range", code="validation_error")
            hist, edges = np.histogram(channel_data, bins=bins, range=(low, high))
            out[c] = {"bins": hist.tolist(), "edges": edges.tolist()}
        return envelope._ok(histogram=out, resolved_event_id=int(resolved_event_id))

    if action == "get_pixel_history":
        coerce._require(args, "x", "y")
        if args.get("texture_id") is not None and args.get("target") is not None:
            return envelope._err("texture_id and target are mutually exclusive", code="validation_error")
        target = coerce._parse_target_like(args.get("target"))
        if set(target) - {"texture_id", "rt_index"} or (target.get("texture_id") is not None and target.get("rt_index") is not None):
            return envelope._err("Target requires only one of texture_id or rt_index", code="validation_error")
        controller = await replay_access._get_controller(session_id)
        original_event = replay_access._active_event(session_id)
        event_id = await replay_access._ensure_event(session_id, coerce._as_int(args["event_id"]) if args.get("event_id") is not None else None)
        if args.get("texture_id") is not None:
            rid, texture_desc = await replay_access._get_texture_descriptor(session_id, args["texture_id"], event_id=event_id)
        else:
            rid, texture_desc, _, _ = await visual_target._resolve_visual_target_for_event(
                session_id, event_id, target=target)
        rd = renderdoc_api._get_rd()
        sub = rd.Subresource()
        sub.mip = coerce._as_int(args.get("mip"), 0)
        sub.slice = coerce._as_int(args.get("slice"), 0)
        sub.sample = coerce._as_int(args.get("sample"), 0)
        view_format, raw_typeless = await pixel_trace._pixel_history_view(controller, rid, texture_desc)
        cast = view_format.compType if view_format is not None else (rd.CompType.UInt if raw_typeless else None)
        try:
            history_options = {"type_cast": cast} if cast is not None else {}
            history_raw = await pixel_trace._pixel_history_raw_with_timeout(
                controller,
                rid,
                coerce._as_int(args["x"]),
                coerce._as_int(args["y"]),
                sub,
                **history_options,
            )
        except pixel_trace.PixelHistoryInputAttachmentConflict as exc:
            return await pixel_trace._pixel_history_conflict_error(session_id, original_event, exc)
        except asyncio.TimeoutError:
            return envelope._err(
                pixel_trace._pixel_history_timeout_message(timeout_policy.PIXEL_HISTORY_TIMEOUT_S),
                code="pixel_history_timeout",
                category="runtime",
                details={
                    "session_id": session_id,
                    "texture_id": str(rid),
                    "x": coerce._as_int(args["x"]),
                    "y": coerce._as_int(args["y"]),
                    "timeout_seconds": float(timeout_policy.PIXEL_HISTORY_TIMEOUT_S),
                    "resolved_event_id": int(event_id),
                },
            )
        except Exception as exc:
            return envelope._err(f"PixelHistory unavailable: {exc}")
        color_type = ("uint" if raw_typeless else pixel_trace._pixel_history_color_type(
            SimpleNamespace(format=view_format) if view_format is not None else texture_desc))
        history = [pixel_trace._pixel_history_item_payload(item, color_type) for item in history_raw]
        truth_meta = await truth_matrix._event_truth_metadata(session_id, int(event_id))
        history_bindings = None
        if args.get("include_shaders", True):
            history_bindings = await pixel_trace._pixel_history_writer_bindings(session_id, int(event_id), history, controller)
        return envelope._ok(
            history=history,
            view_format=str(view_format.Name()) if view_format is not None else None,
            value_interpretation=("raw_unsigned_integer" if raw_typeless else "view_format" if view_format is not None else "resource_format"),
            interpretation_note="无类型格式，视图格式未知，数值为原始整数" if raw_typeless else None,
            history_bindings=history_bindings,
            history_bindings_status=("not_requested" if history_bindings is None else
                                     "partial" if any("error" in item for item in history_bindings) else "complete"),
            resolved_event_id=int(event_id),
            texture_id=str(rid),
            target_metadata={
                "texture_id": str(rid),
                "x": coerce._as_int(args["x"]),
                "y": coerce._as_int(args["y"]),
                "subresource": {"mip": int(sub.mip), "slice": int(sub.slice), "sample": int(sub.sample)},
            },
            binding_truth_level=truth_meta.get("binding_truth_level"),
            evidence_truth_level="structured_readback",
            summary_degraded_reasons=list(truth_meta.get("summary_degraded_reasons") or []),
        )

    if action == "render_overlay":
        event_id = coerce._as_int(args.get("event_id"), replay_access._active_event(session_id))
        if event_id <= 0:
            event_id = await replay_access._ensure_event(session_id, None)
        explicit_texture_id = args.get("texture_id")
        if explicit_texture_id is not None and str(explicit_texture_id).strip():
            source_texture_id, texture_desc = await replay_access._get_texture_descriptor(
                session_id,
                explicit_texture_id,
                event_id=event_id,
            )
            source = {"source": "texture", "texture_id": source_texture_id}
        else:
            source_texture_id, texture_desc = await replay_access._get_texture_descriptor(
                session_id,
                None,
                event_id=event_id,
            )
            source = {"source": "final_output"}
        binding_index = await replay_access._binding_name_index_for_event(session_id, event_id)
        name_info = texture_naming._compose_texture_name_info(
            source_texture_id,
            resource_name=str(getattr(texture_desc, "name", "")) if texture_desc is not None else "",
            binding_names=binding_index.get(str(source_texture_id), []),
            alias_name=live_state._runtime.aliases.get(str(source_texture_id), ""),
        )
        channels_arg = coerce._as_dict(args.get("channels"), default={})
        include_alpha = coerce._as_bool(
            args.get("include_alpha"),
            coerce._as_bool(channels_arg.get("a"), False),
        )
        view = {
            "overlay": str(args.get("overlay", "none")),
            "flip_y": coerce._as_bool(args.get("flip_y"), False),
            "channels": {
                "r": coerce._as_bool(channels_arg.get("r"), True),
                "g": coerce._as_bool(channels_arg.get("g"), True),
                "b": coerce._as_bool(channels_arg.get("b"), True),
                "a": include_alpha,
            },
        }
        artifact_ref, meta = await live_state._render_service.render_event(
            session_id=session_id,
            event_id=event_id,
            session_manager=live_state._session_manager,
            artifact_store=live_state._artifact_store,
            source_config=source,
            view_config=view,
            output_format=str(args.get("file_format", "png")),
        )
        artifact_path = artifact_payloads._artifact_path(artifact_ref)
        payload: Dict[str, Any] = {"artifact_path": artifact_path, "meta": meta}
        output_path = args.get("output_path")
        if output_path and artifact_path:
            out_path = Path(str(output_path))
            out_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(artifact_path, out_path)
            payload["saved_path"] = str(out_path)
        payload["image_path"] = payload.get("saved_path") or artifact_path
        payload["name_info"] = name_info
        payload["texture_format"] = texture_naming._texture_format_name(texture_desc)
        texture_width = int(getattr(texture_desc, "width", 0) or 0)
        texture_height = int(getattr(texture_desc, "height", 0) or 0)
        image_width = coerce._as_int(meta.get("width"), 0)
        image_height = coerce._as_int(meta.get("height"), 0)
        if texture_width > 0 and texture_height > 0 and image_width > 0 and image_height > 0:
            effective_scale = min(image_width / texture_width, image_height / texture_height)
            content_width = texture_width * effective_scale
            content_height = texture_height * effective_scale
            payload["image_mapping"] = {
                "status": "available",
                "source_size": {"width": texture_width, "height": texture_height},
                "effective_scale": effective_scale,
                "content_rect": {
                    "x": (image_width - content_width) / 2,
                    "y": (image_height - content_height) / 2,
                    "width": content_width,
                    "height": content_height,
                },
                "flip_y": view["flip_y"],
            }
        else:
            payload["image_mapping"] = {"status": "unavailable", "reason": "dimensions_unavailable"}
        truth_meta = await truth_matrix._event_truth_metadata(session_id, int(event_id))
        payload["resolved_event_id"] = int(event_id)
        payload["texture_id"] = str(source_texture_id)
        payload["target_source"] = str(source.get("source") or "texture")
        payload["binding_truth_level"] = truth_meta.get("binding_truth_level")
        payload["visual_truth_level"] = "visual_valid"
        payload["evidence_truth_level"] = "visual_evidence_only"
        payload["summary_degraded_reasons"] = list(truth_meta.get("summary_degraded_reasons") or [])
        return envelope._ok(**payload)


    if action in {"diff", "compute_stats"}:
        if action == "diff":
            coerce._require(args, "tex_a", "tex_b")
            tex_a = coerce._as_dict(args["tex_a"])
            tex_b = coerce._as_dict(args["tex_b"])
            arr_a, _, event_a, _ = await read_array(tex_a.get("texture_id"), coerce._as_dict(tex_a.get("subresource"), default={}), event_id=tex_a.get("event_id", args.get("event_id")))
            arr_b, _, event_b, _ = await read_array(tex_b.get("texture_id"), coerce._as_dict(tex_b.get("subresource"), default={}), event_id=tex_b.get("event_id", args.get("event_id")))
            if arr_a.ndim != 3 or arr_b.ndim != 3 or not arr_a.size or not arr_b.size:
                return envelope._err("Texture channel layout unavailable", code="texture_layout_unsupported")
            if not np.isfinite(arr_a).all() or not np.isfinite(arr_b).all():
                return envelope._err("Texture diff contains non-finite samples", code="texture_nonfinite_data")
            if arr_a.shape != arr_b.shape:
                return envelope._err("Texture shapes differ", code="texture_shape_mismatch")
            arr_a = arr_a.astype("float64")
            arr_b = arr_b.astype("float64")
            diff = arr_a - arr_b
            mse = float((diff ** 2).mean()) if diff.size else 0.0
            max_abs = float(np.abs(diff).max()) if diff.size else 0.0
            psnr = float(20 * np.log10(1.0 / np.sqrt(mse))) if mse > 0 else None
            metrics = {"mse": mse, "max_abs": max_abs, "psnr": psnr, "identical": mse == 0,
                       "psnr_peak": 1.0, "psnr_status": "infinite" if mse == 0 else "finite"}
            requested_metrics = args.get("metric", ["mse", "max_abs", "psnr"])
            if not isinstance(requested_metrics, list) or any(m not in {"mse", "max_abs", "psnr"} for m in requested_metrics):
                return envelope._err("Invalid texture diff metric", code="validation_error")
            return envelope._ok(diff={key: value for key, value in metrics.items() if key in requested_metrics or key in {"identical", "psnr_peak", "psnr_status"}}, event_a=int(event_a), event_b=int(event_b))
        coerce._require(args, "texture_id")
        arr, stats, resolved_event_id, resolved_texture_id = await read_array(
            args.get("texture_id"), {"mip": coerce._as_int(args.get("mip"), 0), "slice": coerce._as_int(args.get("slice"), 0), "sample": coerce._as_int(args.get("sample"), 0)}, event_id=args.get("event_id"))
        if arr.ndim != 3 or not arr.size:
            return envelope._err("Texture channel layout unavailable", code="texture_layout_unsupported")
        stride = coerce._as_int(args.get("stride"), 1)
        if stride < 1:
            return envelope._err("Statistics stride must be positive", code="validation_error")
        arr = arr[::stride, ::stride]
        stats = texture_export._sampled_texture_stats(arr, stats, stride)
        truth_meta = await truth_matrix._event_truth_metadata(session_id, int(resolved_event_id))
        return envelope._ok(
            stats={**dict(stats or {}), "event_id": int(resolved_event_id)},
            resolved_event_id=int(resolved_event_id),
            texture_id=str(resolved_texture_id),
            target_metadata={
                "texture_id": str(resolved_texture_id),
                "subresource": {
                    "mip": coerce._as_int(args.get("mip"), 0),
                    "slice": coerce._as_int(args.get("slice"), 0),
                    "sample": coerce._as_int(args.get("sample"), 0),
                },
                "region": None,
            },
            binding_truth_level=truth_meta.get("binding_truth_level"),
            evidence_truth_level=truth_meta.get("evidence_truth_level"),
            summary_degraded_reasons=list(truth_meta.get("summary_degraded_reasons") or []),
        )

    return envelope._err(f"Unsupported texture action: {action}")
