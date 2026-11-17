"""Context-owned preview window state and synchronisation with the replay."""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from rdc_tool.context_snapshot import (
    default_preview_display_state,
    default_preview_state,
    normalize_context_id,
    normalize_preview_display_state,
    normalize_preview_state,
)
from rdc_tool.core.errors import CoreError
from rdc_tool.platform import preview as platform_preview
from rdc_tool.runtime import (
    context_records,
    live_state,
    oplog,
    renderdoc_api,
    replay_access,
    settings,
    texture_naming,
    visual_target,
)


def _preview_update_payload(
    context_id: str,
    preview: Dict[str, Any],
    *,
    enabled: Optional[bool] = None,
    state_name: Optional[str] = None,
    bound_session_id: Optional[str] = None,
    bound_capture_file_id: Optional[str] = None,
    bound_event_id: Optional[int] = None,
    backend: Optional[str] = None,
    recovered_from_session_id: Optional[str] = None,
    rebind_count: Optional[int] = None,
    last_error: Optional[str] = None,
    display: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    payload = dict(preview or {})
    if enabled is not None:
        payload["enabled"] = bool(enabled)
    if state_name is not None:
        payload["state"] = str(state_name or "").strip() or payload.get("state") or "disabled"
    if bound_session_id is not None:
        payload["bound_session_id"] = str(bound_session_id or "").strip()
    if bound_capture_file_id is not None:
        payload["bound_capture_file_id"] = str(bound_capture_file_id or "").strip()
    if bound_event_id is not None:
        payload["bound_event_id"] = int(bound_event_id or 0)
    if backend is not None:
        payload["backend"] = str(backend or "local").strip() or "local"
    if recovered_from_session_id is not None:
        payload["recovered_from_session_id"] = str(recovered_from_session_id or "").strip()
    if rebind_count is not None:
        payload["rebind_count"] = max(0, int(rebind_count or 0))
    if last_error is not None:
        payload["last_error"] = str(last_error or "").strip()
    if display is not None:
        payload["display"] = normalize_preview_display_state(display)
    payload["view_mode"] = "active_event"
    payload["updated_at_ms"] = settings._now_ms()
    return normalize_preview_state(payload, backend=str(payload.get("backend") or "local"))


def _store_preview_state(
    context_id: str,
    preview: Dict[str, Any],
) -> Dict[str, Any]:
    ctx = normalize_context_id(context_id)
    state = context_records._context_state(ctx)
    state["preview"] = normalize_preview_state(preview, backend=str(state.get("backend") or "local"))
    context_records._store_context_state(state, ctx)
    return context_records._sync_context_snapshot_from_state(ctx)


def _preview_display_state(**fields: Any) -> Dict[str, Any]:
    payload = default_preview_display_state()
    payload.update(fields)
    payload["fit_mode"] = live_state._PREVIEW_FIT_MODE
    payload["screen_cap_ratio"] = live_state._PREVIEW_SCREEN_CAP_RATIO
    return normalize_preview_display_state(payload)


def _rect_from_snapshot(value: Any) -> Dict[str, int] | None:
    if not isinstance(value, dict):
        return None
    try:
        x = int(round(float(value.get("x", 0))))
        y = int(round(float(value.get("y", 0))))
        width = int(round(float(value.get("width", 0))))
        height = int(round(float(value.get("height", 0))))
    except (TypeError, ValueError):
        return None
    if width <= 0 or height <= 0:
        return None
    return {
        "x": x,
        "y": y,
        "width": width,
        "height": height,
    }


def _clip_rect_to_extent(rect: Dict[str, int] | None, extent: Dict[str, int]) -> Dict[str, int] | None:
    if rect is None:
        return None
    width = max(0, int(extent.get("width") or 0))
    height = max(0, int(extent.get("height") or 0))
    if width <= 0 or height <= 0:
        return None
    raw_x = int(rect.get("x", 0))
    raw_y = int(rect.get("y", 0))
    raw_width = max(0, int(rect.get("width", 0)))
    raw_height = max(0, int(rect.get("height", 0)))
    x0 = max(0, raw_x)
    y0 = max(0, raw_y)
    x1 = min(width, raw_x + raw_width)
    y1 = min(height, raw_y + raw_height)
    clipped_width = x1 - x0
    clipped_height = y1 - y0
    if clipped_width <= 0 or clipped_height <= 0:
        return None
    return {
        "x": x0,
        "y": y0,
        "width": clipped_width,
        "height": clipped_height,
    }


def _intersect_rects(a: Dict[str, int] | None, b: Dict[str, int] | None) -> Dict[str, int] | None:
    if a is None:
        return b
    if b is None:
        return a
    left = max(int(a.get("x", 0)), int(b.get("x", 0)))
    top = max(int(a.get("y", 0)), int(b.get("y", 0)))
    right = min(int(a.get("x", 0)) + int(a.get("width", 0)), int(b.get("x", 0)) + int(b.get("width", 0)))
    bottom = min(int(a.get("y", 0)) + int(a.get("height", 0)), int(b.get("y", 0)) + int(b.get("height", 0)))
    width = right - left
    height = bottom - top
    if width <= 0 or height <= 0:
        return None
    return {
        "x": left,
        "y": top,
        "width": width,
        "height": height,
    }


def _preview_region_rects(
    framebuffer_extent: Dict[str, int],
    *,
    viewport_rect: Dict[str, int] | None,
    scissor_rect: Dict[str, int] | None,
) -> Tuple[Dict[str, int] | None, Dict[str, int] | None, Dict[str, int] | None]:
    viewport_clipped = _clip_rect_to_extent(viewport_rect, framebuffer_extent)
    scissor_clipped = _clip_rect_to_extent(scissor_rect, framebuffer_extent)
    effective = _intersect_rects(viewport_clipped, scissor_clipped)
    if effective is None:
        effective = scissor_clipped or viewport_clipped
    return viewport_clipped, scissor_clipped, effective


def _preview_title(
    context_id: str,
    *,
    backend: str,
    session_id: str,
    event_id: int,
    display: Optional[Dict[str, Any]] = None,
) -> str:
    display_payload = normalize_preview_display_state(display)
    framebuffer = dict(display_payload.get("framebuffer_extent") or {})
    window_rect = dict(display_payload.get("window_rect") or {})
    output_slot = display_payload.get("output_slot")
    marker_mode = str(display_payload.get("region_marker_mode") or "none")
    slot_text = f"RT{int(output_slot)}" if output_slot is not None else "resource"
    framebuffer_text = f"{int(framebuffer.get('width') or 0)}x{int(framebuffer.get('height') or 0)}"
    window_text = f"{int(window_rect.get('width') or 0)}x{int(window_rect.get('height') or 0)}"
    marker_text = "viewport/scissor" if marker_mode != "none" else "full-frame"
    return (
        f"RDC-Tool Preview [{context_id}] [{backend}] {session_id} "
        f"@ event {int(event_id)} [{slot_text}] fb={framebuffer_text} win={window_text} {marker_text}"
    )


def _preview_state_value(context_id: Optional[str] = None) -> Dict[str, Any]:
    ctx = normalize_context_id(context_id or live_state._runtime_context_id())
    state = context_records._context_state(ctx)
    preview = normalize_preview_state(
        state.get("preview"),
        backend=str(state.get("backend") or "local"),
    )
    state["preview"] = dict(preview)
    return preview


def _preview_binding(context_id: Optional[str] = None) -> Optional[live_state.PreviewBinding]:
    return live_state._runtime.previews.get(normalize_context_id(context_id or live_state._runtime_context_id()))


def _preview_window_closed(context_id: str, closed_by_user: bool) -> None:
    ctx = normalize_context_id(context_id)
    binding = live_state._runtime.previews.pop(ctx, None)
    if binding is not None and binding.output is not None:
        try:
            binding.output.Shutdown()
        except Exception:
            pass
        binding.output = None
    if not closed_by_user:
        return
    preview = _preview_state_value(ctx)
    preview = _preview_update_payload(
        ctx,
        preview,
        enabled=False,
        state_name="disabled",
        bound_session_id="",
        bound_capture_file_id="",
        bound_event_id=0,
        recovered_from_session_id="",
        last_error="",
        display=default_preview_display_state(),
    )
    _store_preview_state(ctx, preview)


async def _close_preview_output(binding: live_state.PreviewBinding) -> None:
    if binding.output is None:
        return
    output = binding.output
    binding.output = None
    try:
        await renderdoc_api._offload(output.Shutdown)
    except Exception:
        try:
            output.Shutdown()
        except Exception:
            pass


async def _close_preview_binding(
    context_id: Optional[str] = None,
    *,
    close_window: bool = True,
) -> Optional[live_state.PreviewBinding]:
    ctx = normalize_context_id(context_id or live_state._runtime_context_id())
    binding = live_state._runtime.previews.pop(ctx, None)
    if binding is None:
        return None
    await _close_preview_output(binding)
    if close_window:
        try:
            binding.host.close(by_user=False)
        except Exception:
            pass
    return binding


async def _create_preview_binding(
    context_id: str,
    *,
    title: str,
) -> live_state.PreviewBinding:
    try:
        host = platform_preview.create_preview_window(
            title=title,
            on_closed=lambda by_user, ctx=context_id: _preview_window_closed(ctx, by_user),
        )
    except platform_preview.PreviewWindowUnsupported as exc:
        raise CoreError(
            code="preview_unsupported_platform",
            message=str(exc),
            category="capability",
            details={"capability": "preview_window", "reason": "host_has_no_native_preview_window",
                     "source": "platform", "optional": True, "host_target": exc.host_target,
                     "context_id": context_id, "alternative": "rd.session.observe"},
        ) from exc
    try:
        host.start()
    except Exception as exc:  # noqa: BLE001
        raise visual_target._preview_error(
            "preview_window_create_failed",
            f"Failed to create preview window: {exc}",
            context_id=context_id,
        ) from exc
    binding = live_state.PreviewBinding(context_id=context_id, host=host)
    live_state._runtime.previews[context_id] = binding
    return binding


async def _ensure_preview_output(binding: live_state.PreviewBinding, session_id: str) -> Any:
    if binding.output is not None and binding.bound_session_id == str(session_id or ""):
        return binding.output
    await _close_preview_output(binding)
    rd = renderdoc_api._get_rd()
    if not hasattr(rd, "CreateWin32WindowingData"):
        raise visual_target._preview_error(
            "preview_backend_unavailable",
            "RenderDoc runtime does not expose CreateWin32WindowingData",
            context_id=binding.context_id,
            session_id=session_id,
            backend=binding.backend,
        )
    controller = await replay_access._get_controller(session_id)
    hwnd = int(binding.host.hwnd or 0)
    if hwnd <= 0:
        raise visual_target._preview_error(
            "preview_window_unavailable",
            "Preview window is not alive",
            context_id=binding.context_id,
            session_id=session_id,
            backend=binding.backend,
        )
    try:
        output = await renderdoc_api._offload(
            controller.CreateOutput,
            rd.CreateWin32WindowingData(hwnd),
            rd.ReplayOutputType.Texture,
        )
    except Exception as exc:  # noqa: BLE001
        raise visual_target._preview_error(
            "preview_output_create_failed",
            f"Failed to create preview output: {exc}",
            context_id=binding.context_id,
            session_id=session_id,
            backend=binding.backend,
        ) from exc
    binding.output = output
    return output


def _preview_overlay_for_marker(rd: Any, region_marker_mode: str) -> Any:
    if str(region_marker_mode or "none") == live_state._PREVIEW_REGION_MARKER_MODE:
        return getattr(rd.DebugOverlay, "ViewportScissor", rd.DebugOverlay.NoOverlay)
    return rd.DebugOverlay.NoOverlay


async def _build_preview_display_state(
    binding: live_state.PreviewBinding,
    *,
    session_id: str,
    event_id: int,
    texture_desc: Optional[Any],
    texture_id: Any,
    chosen_output_slot: Optional[int],
    target_source: str,
    force_geometry: bool = False,
) -> Dict[str, Any]:
    framebuffer_extent = {
        "width": max(0, int(getattr(texture_desc, "width", 0) or 0)),
        "height": max(0, int(getattr(texture_desc, "height", 0) or 0)),
    }
    viewport_rect = None
    scissor_rect = None
    effective_region_rect = None
    region_marker_mode = "none"
    if (
        live_state._pipeline_service is not None
        and chosen_output_slot is not None
        and str(target_source or "") == "event_output_slot"
    ):
        try:
            snapshot = await live_state._pipeline_service.snapshot_pipeline(
                session_id=session_id,
                event_id=int(event_id),
                session_manager=live_state._session_manager,
            )
            snapshot_dict = snapshot.model_dump(mode="json")
            viewport_rect, scissor_rect, effective_region_rect = _preview_region_rects(
                framebuffer_extent,
                viewport_rect=_rect_from_snapshot(snapshot_dict.get("viewport")),
                scissor_rect=_rect_from_snapshot(snapshot_dict.get("scissor")),
            )
            if viewport_rect is not None or scissor_rect is not None:
                region_marker_mode = live_state._PREVIEW_REGION_MARKER_MODE
        except Exception:
            viewport_rect = None
            scissor_rect = None
            effective_region_rect = None
            region_marker_mode = "none"

    geometry = binding.host.apply_framebuffer_geometry(
        framebuffer_extent.get("width", 0),
        framebuffer_extent.get("height", 0),
        screen_cap_ratio=live_state._PREVIEW_SCREEN_CAP_RATIO,
        force=force_geometry,
    )
    window_rect = dict(geometry.get("window_rect") or {"width": 0, "height": 0})
    return _preview_display_state(
        output_slot=chosen_output_slot,
        texture_id=str(texture_id or ""),
        texture_format=texture_naming._texture_format_name(texture_desc),
        framebuffer_extent=framebuffer_extent,
        viewport_rect=viewport_rect,
        scissor_rect=scissor_rect,
        effective_region_rect=effective_region_rect,
        region_marker_mode=region_marker_mode,
        window_rect=window_rect,
    )


async def _display_preview_binding(
    binding: live_state.PreviewBinding,
    *,
    session_id: str,
    event_id: int,
    force_geometry: bool = False,
) -> Dict[str, Any]:
    rd = renderdoc_api._get_rd()
    await replay_access._ensure_event(session_id, event_id)
    target_texture_id, texture_desc, chosen_output_slot, target_source = await visual_target._choose_visual_output_target(
        session_id,
        int(event_id),
    )
    display_state = await _build_preview_display_state(
        binding,
        session_id=session_id,
        event_id=int(event_id),
        texture_desc=texture_desc,
        texture_id=target_texture_id,
        chosen_output_slot=chosen_output_slot,
        target_source=target_source,
        force_geometry=force_geometry,
    )
    output = await _ensure_preview_output(binding, session_id)
    display = rd.TextureDisplay()
    display.resourceId = target_texture_id
    display.subresource = rd.Subresource()
    display.typeCast = rd.CompType.Typeless
    display.overlay = _preview_overlay_for_marker(
        rd,
        str(display_state.get("region_marker_mode") or "none"),
    )
    display.rawOutput = False
    display.red = True
    display.green = True
    display.blue = True
    display.alpha = False
    display.scale = 0.0
    display.rangeMin = 0.0
    display.rangeMax = 1.0
    display.hdrMultiplier = -1.0
    display.flipY = False
    try:
        await renderdoc_api._offload(output.SetTextureDisplay, display)
        await renderdoc_api._offload(output.Display)
    except Exception as exc:  # noqa: BLE001
        raise visual_target._preview_error(
            "preview_display_failed",
            f"Failed to display preview output: {exc}",
            context_id=binding.context_id,
            session_id=session_id,
            event_id=event_id,
            backend=binding.backend,
        ) from exc
    return {
        "texture_id": str(target_texture_id),
        "texture_format": texture_naming._texture_format_name(texture_desc),
        "chosen_output_slot": chosen_output_slot,
        "target_source": target_source,
        "display": display_state,
    }


async def _sync_context_preview(
    context_id: Optional[str] = None,
    *,
    strict: bool = False,
    enable_intent: Optional[bool] = None,
) -> Dict[str, Any]:
    ctx = normalize_context_id(context_id or live_state._runtime_context_id())
    state = context_records._context_state(ctx)
    state = context_records._select_session_from_state(state)
    context_records._store_context_state(state, ctx)
    preview = _preview_state_value(ctx)
    requested_enable = bool(preview.get("enabled"))
    if enable_intent is not None:
        requested_enable = bool(enable_intent)
        preview = _preview_update_payload(
            ctx,
            preview,
            enabled=bool(preview.get("enabled")) if requested_enable else False,
            state_name="disabled" if not requested_enable else ("starting" if not preview.get("enabled") else str(preview.get("state") or "starting")),
            last_error="",
            display=default_preview_display_state() if not requested_enable else preview.get("display"),
        )
        _store_preview_state(ctx, preview)
        preview = _preview_state_value(ctx)

    if not requested_enable:
        await _close_preview_binding(ctx)
        preview = _preview_update_payload(
            ctx,
            preview,
            enabled=False,
            state_name="disabled",
            bound_session_id="",
            bound_capture_file_id="",
            bound_event_id=0,
            recovered_from_session_id="",
            last_error="",
            display=default_preview_display_state(),
        )
        return _store_preview_state(ctx, preview)

    retain_enabled = bool(preview.get("enabled"))
    current_session_id = str(state.get("current_session_id") or "").strip()
    current_capture_file_id = str(state.get("current_capture_file_id") or "").strip()
    current_session_record = (
        dict((state.get("sessions") or {}).get(current_session_id) or {})
        if current_session_id
        else {}
    )
    current_backend = live_state._normalize_backend(
        current_session_record.get("backend_type"),
        default=str(state.get("backend") or "local"),
    )
    active_event_id = int(
        ((state.get("sessions") or {}).get(current_session_id) or {}).get("active_event_id")
        or ((preview.get("bound_event_id") or 0) if str(preview.get("bound_session_id") or "") == current_session_id else 0)
        or 0
    )
    if not current_session_id:
        await _close_preview_binding(ctx)
        error = visual_target._preview_error(
            "preview_session_required",
            "Preview requires a current replay session",
            context_id=ctx,
            backend=current_backend,
        )
        preview = _preview_update_payload(
            ctx,
            preview,
            enabled=retain_enabled,
            state_name="failed" if strict else "stale",
            bound_session_id="",
            bound_capture_file_id=current_capture_file_id,
            bound_event_id=0,
            backend=current_backend,
            last_error=error.message,
            display=default_preview_display_state(),
        )
        snapshot = _store_preview_state(ctx, preview)
        if strict:
            raise error
        return snapshot

    try:
        await replay_access._ensure_live_session(current_session_id)
    except CoreError as exc:
        await _close_preview_binding(ctx)
        preview = _preview_update_payload(
            ctx,
            preview,
            enabled=retain_enabled,
            state_name="failed" if strict else "stale",
            bound_session_id=current_session_id,
            bound_capture_file_id=current_capture_file_id,
            bound_event_id=0,
            backend=current_backend,
            last_error=exc.message,
            display=default_preview_display_state(),
        )
        snapshot = _store_preview_state(ctx, preview)
        if strict:
            raise
        return snapshot

    if active_event_id <= 0:
        await _close_preview_binding(ctx)
        error = visual_target._preview_error(
            "preview_event_required",
            "Preview requires a resolved active_event_id",
            context_id=ctx,
            session_id=current_session_id,
            backend=current_backend,
        )
        preview = _preview_update_payload(
            ctx,
            preview,
            enabled=retain_enabled,
            state_name="failed" if strict else "stale",
            bound_session_id=current_session_id,
            bound_capture_file_id=current_capture_file_id,
            bound_event_id=0,
            backend=current_backend,
            last_error=error.message,
            display=default_preview_display_state(),
        )
        snapshot = _store_preview_state(ctx, preview)
        if strict:
            raise error
        return snapshot

    controller = await replay_access._get_controller(current_session_id)
    _, _, by_event = await replay_access._load_action_index(current_session_id, controller=controller)
    if active_event_id not in by_event:
        await _close_preview_binding(ctx)
        error = visual_target._preview_error(
            "preview_event_not_resolvable",
            f"Active event is not resolvable for preview: {int(active_event_id)}",
            context_id=ctx,
            session_id=current_session_id,
            event_id=active_event_id,
            backend=current_backend,
        )
        preview = _preview_update_payload(
            ctx,
            preview,
            enabled=retain_enabled,
            state_name="failed" if strict else "stale",
            bound_session_id=current_session_id,
            bound_capture_file_id=current_capture_file_id,
            bound_event_id=active_event_id,
            backend=current_backend,
            last_error=error.message,
            display=default_preview_display_state(),
        )
        snapshot = _store_preview_state(ctx, preview)
        if strict:
            raise error
        return snapshot

    binding = _preview_binding(ctx)
    had_binding = binding is not None
    previous_session_id = str((binding.bound_session_id if binding is not None else "") or preview.get("bound_session_id") or "").strip()
    session_changed = bool(binding is not None and binding.bound_session_id and binding.bound_session_id != current_session_id)

    if binding is None:
        preview = _preview_update_payload(
            ctx,
            preview,
            enabled=retain_enabled,
            state_name="reconnecting" if preview.get("bound_session_id") else "starting",
            backend=current_backend,
            bound_session_id=current_session_id,
            bound_capture_file_id=current_capture_file_id,
            bound_event_id=active_event_id,
            last_error="",
            display=default_preview_state(backend=current_backend, enabled=True).get("display"),
        )
        _store_preview_state(ctx, preview)
        try:
            binding = await _create_preview_binding(
                ctx,
                title=_preview_title(
                    ctx,
                    backend=current_backend,
                    session_id=current_session_id,
                    event_id=active_event_id,
                    display=preview.get("display"),
                ),
            )
        except CoreError as exc:
            await _close_preview_binding(ctx)
            preview = _preview_update_payload(
                ctx,
                preview,
                enabled=retain_enabled,
                state_name="failed" if strict else "stale",
                bound_session_id=current_session_id if retain_enabled else "",
                bound_capture_file_id=current_capture_file_id if retain_enabled else "",
                bound_event_id=active_event_id if retain_enabled else 0,
                backend=current_backend,
                last_error=exc.message,
                display=default_preview_display_state(),
            )
            snapshot = _store_preview_state(ctx, preview)
            if strict:
                raise
            return snapshot
    elif session_changed:
        await _close_preview_output(binding)
        preview = _preview_update_payload(
            ctx,
            preview,
            enabled=True,
            state_name="reconnecting",
            backend=current_backend,
            bound_session_id=current_session_id,
            bound_capture_file_id=current_capture_file_id,
            bound_event_id=active_event_id,
            last_error="",
            display=default_preview_state(backend=current_backend, enabled=True).get("display"),
        )
        _store_preview_state(ctx, preview)

    try:
        binding_result = await _display_preview_binding(
            binding,
            session_id=current_session_id,
            event_id=active_event_id,
            force_geometry=(not had_binding) or session_changed,
        )
    except CoreError as exc:
        await _close_preview_binding(ctx)
        preview = _preview_update_payload(
            ctx,
            preview,
            enabled=retain_enabled,
            state_name="failed",
            bound_session_id=current_session_id,
            bound_capture_file_id=current_capture_file_id,
            bound_event_id=active_event_id,
            backend=current_backend,
            last_error=exc.message,
            display=default_preview_display_state(),
        )
        snapshot = _store_preview_state(ctx, preview)
        if strict:
            raise
        return snapshot

    binding.bound_session_id = current_session_id
    binding.bound_capture_file_id = current_capture_file_id
    binding.bound_event_id = int(active_event_id)
    binding.backend = current_backend
    binding.last_error = ""
    binding.display = normalize_preview_display_state(binding_result.get("display"))
    binding.host.set_title(
        _preview_title(
            ctx,
            backend=current_backend,
            session_id=current_session_id,
            event_id=active_event_id,
            display=binding.display,
        )
    )
    rebind_count = int(preview.get("rebind_count") or 0)
    if previous_session_id or (had_binding and session_changed):
        if previous_session_id != current_session_id or not had_binding:
            rebind_count += 1
    preview = _preview_update_payload(
        ctx,
        preview,
        enabled=True,
        state_name="live",
        bound_session_id=current_session_id,
        bound_capture_file_id=current_capture_file_id,
        bound_event_id=active_event_id,
        backend=current_backend,
        recovered_from_session_id=previous_session_id if previous_session_id and previous_session_id != current_session_id else "",
        rebind_count=rebind_count,
        last_error="",
        display=binding.display,
    )
    return _store_preview_state(ctx, preview)


async def _open_context_preview(context_id: Optional[str] = None, *, requested_session_id: str = "") -> Dict[str, Any]:
    ctx = normalize_context_id(context_id or live_state._runtime_context_id())
    state = context_records._context_state(ctx)
    state = context_records._select_session_from_state(state)
    context_records._store_context_state(state, ctx)
    current_session_id = str(state.get("current_session_id") or "").strip()
    wanted_session_id = str(requested_session_id or "").strip()
    if wanted_session_id and wanted_session_id != current_session_id:
        raise visual_target._preview_error(
            "preview_session_mismatch",
            (
                f"Preview only binds the current session for context {ctx}; "
                f"select session {wanted_session_id} first"
            ),
            context_id=ctx,
            session_id=wanted_session_id,
            backend=str(state.get("backend") or "local"),
        )
    snapshot = await _sync_context_preview(ctx, strict=True, enable_intent=True)
    state = context_records._context_state(ctx)
    return {
        "context_id": ctx,
        "current_session_id": str(state.get("current_session_id") or ""),
        "runtime": dict(snapshot.get("runtime") or {}),
        "preview": dict(snapshot.get("preview") or {}),
        "updated_at_ms": int(snapshot.get("updated_at_ms") or 0),
    }


async def _close_context_preview(context_id: Optional[str] = None) -> Dict[str, Any]:
    ctx = normalize_context_id(context_id or live_state._runtime_context_id())
    await _close_preview_binding(ctx)
    preview = _preview_state_value(ctx)
    snapshot = _store_preview_state(
        ctx,
        _preview_update_payload(
            ctx,
            preview,
            enabled=False,
            state_name="disabled",
            bound_session_id="",
            bound_capture_file_id="",
            bound_event_id=0,
            recovered_from_session_id="",
            last_error="",
            display=default_preview_display_state(),
        ),
    )
    state = context_records._context_state(ctx)
    return {
        "context_id": ctx,
        "current_session_id": str(state.get("current_session_id") or ""),
        "runtime": dict(snapshot.get("runtime") or {}),
        "preview": dict(snapshot.get("preview") or {}),
        "updated_at_ms": int(snapshot.get("updated_at_ms") or 0),
    }


async def _auto_sync_preview_if_enabled(context_id: Optional[str] = None) -> None:
    ctx = normalize_context_id(context_id or live_state._runtime_context_id())
    preview = _preview_state_value(ctx)
    if not preview.get("enabled"):
        return
    replay_access._event_effect_attempted()
    try:
        await _sync_context_preview(ctx, strict=False)
    except Exception as exc:  # noqa: BLE001
        oplog._record_log("warning", f"preview auto-sync failed: {exc}", {"context_id": ctx})
