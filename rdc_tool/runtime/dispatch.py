"""Execute one rd.* operation: context bookkeeping, routing and the canonical result envelope."""

from __future__ import annotations

import json
import time
from typing import Any, Dict, Optional

from rdc_tool import runtime_process_identity
from rdc_tool.context_snapshot import normalize_context_id
from rdc_tool.core.artifact_publisher import ArtifactPublisher
from rdc_tool.core.contracts import canonical_error, canonical_success, collect_artifact_candidates
from rdc_tool.core.errors import InternalToolError, map_exception
from rdc_tool.progress import ProgressReporter, ProgressSink
from rdc_tool.runtime import (
    context_records,
    live_state,
    oplog,
    preview_sync,
    routing,
    runtime_lifecycle,
    session_recovery,
)

# Operations that open, close or synchronise the preview themselves.
_PREVIEW_MANAGED_OPERATIONS = frozenset({
    "rd.session.open_preview",
    "rd.session.close_preview",
    "rd.session.observe",
    "rd.session.get_replay_events",
    "rd.capture.open_replay",
    "rd.event.set_active",
    "rd.replay.set_frame",
    "rd.session.get_context",
    "rd.session.select_session",
    "rd.session.resume",
})
_publisher = ArtifactPublisher()


async def dispatch_operation(
    operation: str,
    args: Optional[Dict[str, Any]] = None,
    *,
    transport: str = "core",
    remote: bool = False,
    context_id: Optional[str] = None,
    progress_sink: Optional[ProgressSink] = None,
) -> Dict[str, Any]:
    await runtime_lifecycle.runtime_startup()
    call_args = dict(args or {})
    chosen_context_id = normalize_context_id(context_id or call_args.get("context_id") or live_state._runtime_context_id())
    ctx = live_state.ExecutionContext(transport=transport, remote=remote, metadata={"context_id": chosen_context_id})
    ctx.progress_reporter = ProgressReporter(trace_id=ctx.trace_id, operation=operation, sink=progress_sink)
    arg_keys = ",".join(sorted(call_args.keys())) if call_args else "-"
    live_state.logger.info("op.start transport=%s remote=%s op=%s trace_id=%s arg_keys=%s",
                           transport, remote, operation, ctx.trace_id, arg_keys)
    context_token = live_state._CURRENT_CONTEXT_ID.set(chosen_context_id)
    progress_token = live_state._CURRENT_PROGRESS_REPORTER.set(ctx.progress_reporter)
    try:
        oplog._record_operation_start(chosen_context_id, trace_id=ctx.trace_id, operation=operation,
                                      transport=transport, args=call_args)
        try:
            await session_recovery.ensure_context_ready(chosen_context_id)
            if operation not in _PREVIEW_MANAGED_OPERATIONS:
                await preview_sync._auto_sync_preview_if_enabled(chosen_context_id)
            payload = await _execute(operation, call_args, ctx)
            context_records._postprocess_context_snapshot(operation, call_args, payload, ctx)
        except Exception as exc:  # noqa: BLE001
            core_exc = map_exception(exc)
            payload = canonical_error(result_kind=str(operation), code=core_exc.code, category=core_exc.category,
                                      message=core_exc.message, details=core_exc.details, trace_id=ctx.trace_id,
                                      transport=ctx.transport)
        if operation not in _PREVIEW_MANAGED_OPERATIONS:
            await preview_sync._auto_sync_preview_if_enabled(chosen_context_id)
        oplog._record_operation_finish(chosen_context_id, trace_id=ctx.trace_id, payload=payload)
        meta = payload.setdefault("meta", {})
        meta["process_identity"] = runtime_process_identity.runtime_process_identity()
        live_state.logger.info("op.done transport=%s op=%s trace_id=%s ok=%s duration_ms=%s", transport, operation,
                               str(meta.get("trace_id") or ctx.trace_id), bool(payload.get("ok")), meta.get("duration_ms"))
        return payload
    finally:
        live_state._CURRENT_PROGRESS_REPORTER.reset(progress_token)
        live_state._CURRENT_CONTEXT_ID.reset(context_token)


async def _execute(operation: str, args: Dict[str, Any], ctx: live_state.ExecutionContext) -> Dict[str, Any]:
    start = time.perf_counter()
    try:
        normalized = await _normalize(operation, await routing.route(operation, dict(args)), ctx)
    except Exception as exc:  # noqa: BLE001
        core_exc = map_exception(exc)
        live_state.logger.debug("Operation failed for %s: %s", operation, core_exc)
        return canonical_error(result_kind=str(operation), code=core_exc.code, category=core_exc.category,
                               message=core_exc.message, details=core_exc.details, trace_id=ctx.trace_id,
                               transport=ctx.transport, duration_ms=int((time.perf_counter() - start) * 1000))
    meta = normalized.setdefault("meta", {})
    meta.setdefault("trace_id", ctx.trace_id)
    meta.setdefault("transport", ctx.transport)
    meta.setdefault("duration_ms", int((time.perf_counter() - start) * 1000))
    return normalized


async def _normalize(operation: str, raw: Any, ctx: live_state.ExecutionContext) -> Dict[str, Any]:
    if isinstance(raw, str):
        text = raw.strip()
        if text.startswith("{") and text.endswith("}"):
            try:
                raw = json.loads(text)
            except json.JSONDecodeError as exc:
                raise InternalToolError(
                    f"Operation returned non-JSON string for {operation}",
                    {"preview": text[:160]},
                ) from exc
        else:
            raw = {"raw": raw}

    if isinstance(raw, dict) and all(
        key in raw for key in ("schema_version", "tool_version", "result_kind", "ok", "data", "artifacts", "error", "meta")
    ):
        raw.setdefault("projections", {})
        return raw

    if not isinstance(raw, dict):
        raw = {"value": raw}

    if "success" in raw or "error_message" in raw:
        success = bool(raw.get("success", True))
        if success:
            data = {
                k: v
                for k, v in raw.items()
                if k not in {"success", "error_message", "ok", "error", "schema_version", "tool_version", "result_kind", "data", "artifacts", "meta", "projections"}
            }
            artifacts = await _publisher.publish_candidates(
                collect_artifact_candidates(raw),
            )
            source_meta = raw.get("meta")
            if not isinstance(source_meta, dict):
                source_meta = {}
            return canonical_success(
                result_kind=str(operation),
                data=data,
                artifacts=artifacts,
                projections=dict(raw.get("projections") or {}),
                meta={
                    key: value
                    for key, value in source_meta.items()
                    if key not in {"trace_id", "transport", "duration_ms"}
                },
                trace_id=ctx.trace_id,
                transport=ctx.transport,
            )
        error_message = str(raw.get("error_message") or "Operation failed")
        details = {
            k: v
            for k, v in raw.items()
            if k
            not in {
                "success",
                "error_message",
                "ok",
                "error",
                "schema_version",
                "tool_version",
                "result_kind",
                "data",
                "artifacts",
                "meta",
                "code",
                "error_code",
                "category",
                "details",
                "projections",
            }
        }
        explicit_details = raw.get("details")
        if isinstance(explicit_details, dict):
            details = {**explicit_details, **details}
        return canonical_error(
            result_kind=str(operation),
            code=str(raw.get("code") or raw.get("error_code") or "runtime_error"),
            category=str(raw.get("category") or "runtime"),
            message=error_message,
            details=details,
            meta=dict(raw.get("meta") or {}),
            trace_id=ctx.trace_id,
            transport=ctx.transport,
        )

    if "ok" in raw and isinstance(raw.get("data"), dict):
        success = bool(raw.get("ok"))
        if success:
            artifacts = list(raw.get("artifacts") or [])
            if not artifacts:
                artifacts = await _publisher.publish_candidates(
                    collect_artifact_candidates(raw.get("data") or {}),
                )
            return canonical_success(
                result_kind=str(raw.get("result_kind") or operation),
                data=dict(raw.get("data") or {}),
                artifacts=artifacts,
                projections=dict(raw.get("projections") or {}),
                meta=dict(raw.get("meta") or {}),
                trace_id=ctx.trace_id,
                transport=ctx.transport,
            )
        err = raw.get("error") if isinstance(raw.get("error"), dict) else {}
        return canonical_error(
            result_kind=str(raw.get("result_kind") or operation),
            code=str(err.get("code") or "runtime_error"),
            category=str(err.get("category") or "runtime"),
            message=str(err.get("message") or "Operation failed"),
            details=dict(err.get("details") or {}),
            artifacts=list(raw.get("artifacts") or []),
            meta=dict(raw.get("meta") or {}),
            trace_id=ctx.trace_id,
            transport=ctx.transport,
        )

    artifacts = await _publisher.publish_candidates(
        collect_artifact_candidates(raw),
    )
    return canonical_success(
        result_kind=str(operation),
        data=raw,
        artifacts=artifacts,
        trace_id=ctx.trace_id,
        transport=ctx.transport,
    )