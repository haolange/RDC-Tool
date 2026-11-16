"""Execute one rd.* operation: context bookkeeping, routing and the canonical result envelope."""

from __future__ import annotations

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
    envelope,
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
# Set by the envelope itself; an operation's meta cannot override them.
_ENVELOPE_META = frozenset({"trace_id", "transport", "duration_ms"})


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


async def _normalize(operation: str, outcome: Any, ctx: live_state.ExecutionContext) -> Dict[str, Any]:
    if isinstance(outcome, envelope.Success):
        return canonical_success(
            result_kind=operation,
            data=outcome.data,
            artifacts=await _publisher.publish_candidates(collect_artifact_candidates(outcome.data)),
            projections=outcome.projections,
            meta={key: value for key, value in outcome.meta.items() if key not in _ENVELOPE_META},
            trace_id=ctx.trace_id,
            transport=ctx.transport,
        )
    if isinstance(outcome, envelope.Failure):
        return canonical_error(
            result_kind=operation,
            code=outcome.code,
            category=outcome.category,
            message=outcome.message,
            details=outcome.details,
            trace_id=ctx.trace_id,
            transport=ctx.transport,
        )
    raise InternalToolError(f"{operation} returned {type(outcome).__name__} instead of an operation outcome")
