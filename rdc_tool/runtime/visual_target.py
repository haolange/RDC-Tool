"""Choosing the texture that represents what an event drew or presented."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

from rdc_tool.core.errors import CoreError
from rdc_tool.runtime import (
    action_index,
    coerce,
    context_records,
    live_state,
    renderdoc_api,
    replay_access,
    texture_naming,
    truth_matrix,
)


async def _choose_visual_output_target(
    session_id: str,
    event_id: int,
    *,
    target: Optional[Dict[str, Any]] = None,
) -> Tuple[Any, Optional[Any], Optional[int], str]:
    parsed_target = target or {}
    explicit_target = parsed_target.get("texture_id") or parsed_target.get("textureId")
    requested_rt_index_raw = parsed_target.get("rt_index")
    if requested_rt_index_raw is None:
        requested_rt_index_raw = parsed_target.get("rtIndex")
    has_requested_rt_index = requested_rt_index_raw is not None
    requested_rt_index = coerce._as_int(requested_rt_index_raw, 0 if not explicit_target else -1)
    chosen_output_slot: Optional[int] = None
    best_texture_desc: Optional[Any] = None
    best_target_source = "event_output_slot"

    if explicit_target:
        target_texture_id, texture_desc = await replay_access._get_texture_descriptor(
            session_id,
            explicit_target,
            event_id=event_id,
        )
        return target_texture_id, texture_desc, None, "explicit_resource"

    output_targets = await replay_access._output_target_resource_ids(session_id, event_id)
    requested_output: Optional[Tuple[Any, int]] = None
    for candidate_id, candidate_slot in output_targets:
        if int(candidate_slot) == int(requested_rt_index):
            requested_output = (candidate_id, int(candidate_slot))
            break

    if requested_output is not None:
        best_texture_id, chosen_output_slot = requested_output
        target_texture_id, texture_desc = await replay_access._get_texture_descriptor(
            session_id,
            best_texture_id,
            event_id=event_id,
        )
        return target_texture_id, texture_desc, chosen_output_slot, best_target_source

    if output_targets and requested_rt_index >= 0 and has_requested_rt_index:
        available_slots = [int(slot) for _, slot in output_targets]
        raise _preview_error(
            "preview_event_output_slot_unavailable",
            (
                f"Active event {int(event_id)} does not expose RT slot {int(requested_rt_index)}; "
                f"available slots: {available_slots}"
            ),
            context_id=live_state._runtime_context_id(),
            session_id=session_id,
            event_id=event_id,
            backend=str(context_records._context_state(live_state._runtime_context_id()).get('backend') or 'local'),
        )

    if has_requested_rt_index and requested_rt_index >= 0 and not output_targets:
        raise _preview_error(
            "preview_event_output_unavailable",
            (
                f"Active event {int(event_id)} exposes no framebuffer output targets; "
                f"requested RT slot {int(requested_rt_index)}"
            ),
            context_id=live_state._runtime_context_id(),
            session_id=session_id,
            event_id=event_id,
            backend=str(context_records._context_state(live_state._runtime_context_id()).get('backend') or 'local'),
        )

    best_texture_id: Optional[Any] = None
    best_score = float("-inf")
    for candidate_id, candidate_slot in output_targets:
        try:
            stats = await live_state._render_service.get_texture_stats(
                session_id=session_id,
                event_id=event_id,
                texture_id=candidate_id,
                session_manager=live_state._session_manager,
            )
            channels = coerce._as_dict(stats.get("channels"), default={})
            rgb_spread = 0.0
            for channel in ("r", "g", "b"):
                channel_data = coerce._as_dict(channels.get(channel), default={})
                cmin = channel_data.get("min")
                cmax = channel_data.get("max")
                if cmin is None or cmax is None:
                    continue
                try:
                    rgb_spread += abs(float(cmax) - float(cmin))
                except Exception:
                    continue
            alpha = coerce._as_dict(channels.get("a"), default={})
            try:
                alpha_spread = abs(float(alpha.get("max", 0.0)) - float(alpha.get("min", 0.0)))
            except Exception:
                alpha_spread = 0.0
            score = (rgb_spread * 10.0) + alpha_spread
            if not coerce._as_bool(stats.get("has_any_nan"), False) and not coerce._as_bool(stats.get("has_any_inf"), False):
                score += 0.1
            if score > best_score:
                best_score = score
                best_texture_id = candidate_id
                best_texture_desc = None
                chosen_output_slot = candidate_slot
        except Exception:
            continue

    if best_texture_id is None:
        binding_candidates = await replay_access._binding_texture_candidates_for_event(session_id, event_id)
        for candidate_id, texture_desc, binding_type, binding_name, binding_index in binding_candidates:
            score = 50.0 if binding_type == "SRV" else 100.0
            name_text = str(binding_name or "").strip().lower()
            if name_text:
                if any(hint in name_text for hint in ("output", "result", "scene", "color", "final", "lit", "compose")):
                    score += 10.0
                if any(hint in name_text for hint in texture_naming._MASK_HINTS):
                    score -= 15.0
                if any(hint in name_text for hint in texture_naming._NORMAL_HINTS):
                    score -= 20.0
            try:
                width = int(getattr(texture_desc, "width", 0) or 0)
                height = int(getattr(texture_desc, "height", 0) or 0)
                if width > 0 and height > 0:
                    score += min(float(width * height) / 262144.0, 8.0)
            except Exception:
                pass
            try:
                stats = await live_state._render_service.get_texture_stats(
                    session_id=session_id,
                    event_id=event_id,
                    texture_id=candidate_id,
                    session_manager=live_state._session_manager,
                )
                channels = coerce._as_dict(stats.get("channels"), default={})
                rgb_spread = 0.0
                for channel in ("r", "g", "b"):
                    channel_data = coerce._as_dict(channels.get(channel), default={})
                    cmin = channel_data.get("min")
                    cmax = channel_data.get("max")
                    if cmin is None or cmax is None:
                        continue
                    try:
                        rgb_spread += abs(float(cmax) - float(cmin))
                    except Exception:
                        continue
                alpha = coerce._as_dict(channels.get("a"), default={})
                try:
                    alpha_spread = abs(float(alpha.get("max", 0.0)) - float(alpha.get("min", 0.0)))
                except Exception:
                    alpha_spread = 0.0
                score += (rgb_spread * 10.0) + alpha_spread
                if not coerce._as_bool(stats.get("has_any_nan"), False) and not coerce._as_bool(stats.get("has_any_inf"), False):
                    score += 0.1
            except Exception:
                pass
            if score > best_score:
                best_score = score
                best_texture_id = candidate_id
                best_texture_desc = texture_desc
                chosen_output_slot = None
                best_target_source = f"event_binding_{binding_type.lower()}_{binding_index}"

    if best_texture_id is None:
        if output_targets:
            best_texture_id, chosen_output_slot = output_targets[0]
            best_texture_desc = None
        else:
            raise _preview_error(
                "preview_event_output_unavailable",
                f"Active event {int(event_id)} has no previewable output target",
                context_id=live_state._runtime_context_id(),
                session_id=session_id,
                event_id=event_id,
                backend=str(context_records._context_state(live_state._runtime_context_id()).get('backend') or 'local'),
            )

    if best_texture_desc is not None:
        return best_texture_id, best_texture_desc, chosen_output_slot, best_target_source

    target_texture_id, texture_desc = await replay_access._get_texture_descriptor(
        session_id,
        best_texture_id,
        event_id=event_id,
    )
    return target_texture_id, texture_desc, chosen_output_slot, best_target_source


def _has_explicit_visual_target(target: Optional[Dict[str, Any]]) -> bool:
    parsed = target or {}
    return bool(
        parsed.get("texture_id")
        or parsed.get("textureId")
        or parsed.get("rt_index") is not None
        or parsed.get("rtIndex") is not None
    )


def _requested_visual_target_semantic(target: Optional[Dict[str, Any]]) -> str:
    parsed = target or {}
    raw = parsed.get("semantic")
    if raw is None:
        raw = parsed.get("target_semantic")
    if raw is None:
        raw = parsed.get("targetSemantic")
    semantic = str(raw or "").strip().lower()
    if semantic:
        return semantic
    return "event_output" if _has_explicit_visual_target(parsed) else "swapchain"


def _is_present_action(action: Any) -> bool:
    return bool(int(getattr(action, "flags", 0)) & int(renderdoc_api._get_rd().ActionFlags.Present))


def _usage_event_id(entry: Any) -> int:
    return int(
        getattr(
            entry,
            "eventId",
            getattr(entry, "event_id", getattr(entry, "raw_event_id", 0)),
        )
        or 0
    )


def _usage_text(entry: Any) -> str:
    usage = getattr(entry, "usage", "")
    try:
        name = getattr(usage, "name", None)
        if name:
            return str(name)
    except Exception:
        pass
    return str(usage or "")


def _texture_area(texture_desc: Any) -> int:
    try:
        width = int(getattr(texture_desc, "width", 0) or 0)
        height = int(getattr(texture_desc, "height", 0) or 0)
        return max(0, width) * max(0, height)
    except Exception:
        return 0


def _looks_like_depth_texture(texture_desc: Any) -> bool:
    name = str(getattr(texture_desc, "name", "") or "").lower()
    fmt = texture_naming._texture_format_name(texture_desc).lower()
    if any(hint in name for hint in ("depth", "stencil", "shadow", "zbuffer", "z-buffer")):
        return True
    return any(hint in fmt for hint in ("d16", "d24", "d32", "depth", "stencil"))


async def _resolve_swapchain_present_target(
    session_id: str,
    requested_event_id: int,
) -> Tuple[Any, Optional[Any], Dict[str, Any]]:
    controller = await replay_access._get_controller(session_id)
    _, flat_actions, _ = await replay_access._load_action_index(session_id, controller=controller)
    present_actions = [
        action
        for action in flat_actions
        if int(getattr(action, "eventId", 0) or 0) > 0 and _is_present_action(action)
    ]
    if not present_actions:
        raise _preview_error(
            "swapchain_present_event_unavailable",
            "Capture action tree does not expose a Present event",
            context_id=live_state._runtime_context_id(),
            session_id=session_id,
            event_id=int(requested_event_id or 0),
            backend=str(context_records._context_state(live_state._runtime_context_id()).get("backend") or "local"),
        )

    requested = int(requested_event_id or 0)
    eligible_present_actions = [
        action
        for action in present_actions
        if requested <= 0 or int(getattr(action, "eventId", 0) or 0) <= requested
    ]
    if not eligible_present_actions:
        eligible_present_actions = present_actions
    present_action = max(eligible_present_actions, key=lambda action: int(getattr(action, "eventId", 0) or 0))
    present_event_id = int(getattr(present_action, "eventId", 0) or 0)
    present_name = action_index._action_name(present_action)

    textures = await renderdoc_api._offload(controller.GetTextures)
    candidates: List[Tuple[int, int, Any, Any, str]] = []
    inspected = 0
    for texture_desc in textures:
        rid = getattr(texture_desc, "resourceId", None)
        if rid is None or _looks_like_depth_texture(texture_desc):
            continue
        inspected += 1
        try:
            usage_entries = await renderdoc_api._offload(controller.GetUsage, rid)
        except Exception:
            continue
        best_usage_event = 0
        best_usage_text = ""
        saw_present_usage = False
        for entry in usage_entries or []:
            usage_event = _usage_event_id(entry)
            usage_text = _usage_text(entry)
            if usage_event <= 0:
                continue
            is_present_usage = "present" in usage_text.lower() or usage_event == present_event_id
            if not is_present_usage:
                continue
            saw_present_usage = saw_present_usage or "present" in usage_text.lower()
            if usage_event > best_usage_event and usage_event <= present_event_id:
                best_usage_event = usage_event
                best_usage_text = usage_text
        if best_usage_event <= 0:
            continue
        score = best_usage_event * 1000 + min(_texture_area(texture_desc), 64_000_000)
        if saw_present_usage:
            score += 100_000_000
        candidates.append((score, best_usage_event, rid, texture_desc, best_usage_text))

    if not candidates:
        err = _preview_error(
            "swapchain_target_unavailable",
            "RenderDoc did not expose a texture resource usage entry for the selected Present event",
            context_id=live_state._runtime_context_id(),
            session_id=session_id,
            event_id=present_event_id,
            backend=str(context_records._context_state(live_state._runtime_context_id()).get("backend") or "local"),
        )
        err.details.update(
            {
                "present_event_id": present_event_id,
                "present_action_name": present_name,
                "inspected_texture_count": inspected,
            }
        )
        raise err

    _, usage_event_id, texture_id, texture_desc, usage_name = max(candidates, key=lambda item: item[0])
    texture_id, texture_desc = await replay_access._get_texture_descriptor(session_id, texture_id, event_id=present_event_id)
    payload = {
        "texture_id": str(texture_id),
        "output_slot": None,
        "target_source": "swapchain_present",
        "texture_format": texture_naming._texture_format_name(texture_desc),
        "resolved_event_id": int(present_event_id),
        "present_event_id": int(present_event_id),
        "present_action_name": present_name,
        "present_usage_event_id": int(usage_event_id),
        "present_usage": str(usage_name or ""),
    }
    return texture_id, texture_desc, payload


async def _resolve_visual_target_for_event(
    session_id: str,
    event_id: int,
    *,
    target: Optional[Dict[str, Any]] = None,
) -> Tuple[Any, Optional[Any], Dict[str, Any], Dict[str, Any]]:
    parsed_target = target or {}
    semantic = _requested_visual_target_semantic(parsed_target)
    if semantic not in {"swapchain", "event_output"}:
        err = _preview_error(
            "preview_target_semantic_invalid",
            f"Unsupported screenshot target semantic: {semantic}",
            context_id=live_state._runtime_context_id(),
            session_id=session_id,
            event_id=int(event_id),
            backend=str(context_records._context_state(live_state._runtime_context_id()).get("backend") or "local"),
        )
        err.details.update(
            {
                "requested_semantic": semantic,
                "supported_semantics": ["swapchain", "event_output"],
            }
        )
        raise err

    swapchain_error: Optional[CoreError] = None
    if semantic == "swapchain" and not _has_explicit_visual_target(parsed_target):
        try:
            texture_id, texture_desc, target_payload = await _resolve_swapchain_present_target(
                session_id,
                int(event_id),
            )
            resolved_event_id = int(target_payload.get("resolved_event_id") or event_id)
            truth_meta = dict(await truth_matrix._event_truth_metadata(session_id, resolved_event_id))
            target_payload["requested_semantic"] = semantic
            return texture_id, texture_desc, target_payload, truth_meta
        except CoreError as exc:
            swapchain_error = exc
        except Exception as exc:
            swapchain_error = _preview_error(
                "swapchain_target_unavailable",
                f"Failed to resolve swapchain Present target: {exc}",
                context_id=live_state._runtime_context_id(),
                session_id=session_id,
                event_id=int(event_id),
                backend=str(context_records._context_state(live_state._runtime_context_id()).get("backend") or "local"),
            )

    try:
        texture_id, texture_desc, chosen_output_slot, target_source = await _choose_visual_output_target(
            session_id,
            event_id,
            target=target,
        )
    except CoreError as exc:
        if swapchain_error is not None:
            exc.details["swapchain_error"] = {
                "code": swapchain_error.code,
                "category": swapchain_error.category,
                "message": swapchain_error.message,
                "details": dict(swapchain_error.details),
            }
        raise
    truth_meta = dict(await truth_matrix._event_truth_metadata(session_id, int(event_id)))
    reasons = list(truth_meta.get("summary_degraded_reasons") or [])
    if semantic == "swapchain" and swapchain_error is not None:
        if "swapchain_target_unavailable" not in reasons:
            reasons.append("swapchain_target_unavailable")
        truth_meta["binding_truth_level"] = "binding_degraded"
        truth_meta["evidence_truth_level"] = "visual_evidence_only"
        target_source = "event_output_fallback"
        truth_meta["swapchain_error"] = {
            "code": swapchain_error.code,
            "category": swapchain_error.category,
            "message": swapchain_error.message,
            "details": dict(swapchain_error.details),
        }
    if str(target_source or "").startswith("event_binding_"):
        if "visual_target_binding_fallback" not in reasons:
            reasons.append("visual_target_binding_fallback")
        truth_meta["binding_truth_level"] = "binding_degraded"
        truth_meta["evidence_truth_level"] = "visual_evidence_only"
    truth_meta["summary_degraded_reasons"] = reasons
    target_payload = {
        "texture_id": str(texture_id),
        "output_slot": int(chosen_output_slot) if chosen_output_slot is not None else None,
        "target_source": str(target_source or ""),
        "texture_format": texture_naming._texture_format_name(texture_desc),
        "resolved_event_id": int(event_id),
        "requested_semantic": semantic,
    }
    if swapchain_error is not None:
        target_payload["fallback_reason"] = "swapchain_target_unavailable"
        target_payload["swapchain_error"] = {
            "code": swapchain_error.code,
            "category": swapchain_error.category,
            "message": swapchain_error.message,
            "details": dict(swapchain_error.details),
        }
    return texture_id, texture_desc, target_payload, truth_meta


def _preview_error(
    code: str,
    message: str,
    *,
    context_id: str,
    session_id: str = "",
    event_id: int = 0,
    backend: str = "local",
) -> CoreError:
    return CoreError(
        code=code,
        message=message,
        category="runtime",
        details={
            "context_id": context_id,
            "session_id": str(session_id or ""),
            "event_id": int(event_id or 0),
            "backend": str(backend or "local"),
            "view_mode": "active_event",
        },
    )


async def _pick_previewable_default_event_id(
    session_id: str,
    actions: Sequence[Any],
    *,
    fallback_event_id: int = 0,
) -> int:
    fallback = int(fallback_event_id or action_index._pick_default_event_id(actions) or 0)
    flat, _ = action_index._build_action_index(actions)
    candidate_event_ids: List[int] = []
    if fallback > 0:
        candidate_event_ids.append(fallback)
    for action in flat:
        event_id = int(getattr(action, "eventId", 0))
        if event_id <= 0 or event_id in candidate_event_ids:
            continue
        flags = action_index._map_action_flags(getattr(action, "flags", 0))
        if flags.get("is_draw") or flags.get("is_dispatch"):
            candidate_event_ids.append(event_id)
    for candidate_event_id in candidate_event_ids:
        try:
            await _choose_visual_output_target(
                session_id,
                candidate_event_id,
            )
            return candidate_event_id
        except Exception:
            continue
    if fallback > 0:
        controller = await replay_access._get_controller(session_id)
        await renderdoc_api._offload(controller.SetFrameEvent, fallback, True)
        replay_access._store_active_event(session_id, fallback)
    return fallback
