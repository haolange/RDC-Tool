"""rd.perf.* operations."""

from __future__ import annotations

from typing import Any, Dict

from rdc_tool.core.errors import CoreError
from rdc_tool.runtime import coerce, context_records, envelope, live_state, renderdoc_api, replay_access


async def dispatch(action: str, args: Dict[str, Any]) -> envelope.Outcome:
    coerce._require(args, "session_id")
    session_id = str(args["session_id"])
    if action == "get_frame_timing":
        from rdc_tool.core.perf_service import measure_frame_gpu
        from rdc_tool.core.replay_read import ReplayRestoreError, preserving_event
        controller = await replay_access._get_controller(session_id)
        original_event = replay_access._active_event(session_id)
        async def measure():
            return await measure_frame_gpu(controller, renderdoc_api._get_rd(), samples=int(args.get("samples", 3)),
                                           warmup=int(args.get("warmup", 1)))
        try:
            timing = await preserving_event(controller, original_event, measure)
        except ReplayRestoreError as exc:
            context_records._update_context_session_record(session_id, recovery_status="requires_restart", last_error=str(exc))
            raise CoreError(code="replay_restore_failed", message=str(exc), category="runtime") from exc
        return envelope.success(session_id=session_id, capture_file_id=live_state._runtime.replays[session_id].capture_file_id,
                   frame_timing=timing, restored_event_id=original_event,
                   replay_state_restored=True,
                   replacement_ids=sorted(str(item["replacement_id"]) for item in live_state._runtime.shader_replacements.get(session_id, [])))
    if action == "enumerate_counters":
        counters = await live_state._perf_service.enumerate_counters(session_id, live_state._session_manager)
        return envelope.success(counters=counters)
    if action == "describe_counter":
        coerce._require(args, "counter_id")
        cid = coerce._as_int(args["counter_id"])
        controller = await replay_access._get_controller(session_id)
        try:
            desc = await renderdoc_api._offload(controller.DescribeCounter, cid)
        except Exception as exc:
            return envelope.failure(
                f"Counter not found: {cid}",
                code="counter_not_found",
                category="runtime",
                details={"counter_id": cid, "session_id": session_id, "error": str(exc)},
            )
        counter = {
            "counter_id": int(cid),
            "name": str(getattr(desc, "name", "")),
            "description": str(getattr(desc, "description", "")),
            "unit": str(getattr(desc, "unit", "")),
            "result_type": str(getattr(desc, "resultType", "")),
        }
        return envelope.success(counter=counter)
    if action == "sample_counters":
        counter_ids = [int(v) for v in coerce._as_list(args.get("counter_ids"), default=[])]
        event_range = coerce._as_dict(args.get("event_range"), default={})
        lo = coerce._as_int(event_range.get("start_event_id", event_range.get("lo", 0)), 0)
        hi_default = replay_access._active_event(session_id) or 10**9
        hi = coerce._as_int(event_range.get("end_event_id", event_range.get("hi", hi_default)), hi_default)
        if not counter_ids:
            all_counters = await live_state._perf_service.enumerate_counters(session_id, live_state._session_manager)
            counter_ids = [int(c["counter_id"]) for c in all_counters]
        perf = await live_state._perf_service.sample_counters(session_id, (lo, hi), counter_ids, live_state._session_manager)
        stride = coerce._as_int(args.get("stride"), 1)
        if stride < 1:
            return envelope.failure("Counter stride must be positive", code="validation_error")
        if stride != 1:
            return envelope.failure("Counter sampling currently supports stride=1 only", code="counter_stride_unsupported")
        return envelope.success(perf=perf.model_dump(mode="json"))
    if action == "get_event_durations":
        max_events = coerce._as_int(args.get("max_events"), 200)
        if max_events < 1:
            return envelope.failure("max_events must be positive", code="validation_error")
        event_range = coerce._as_dict(args.get("event_range"), default={})
        if event_range:
            lo = coerce._as_int(event_range.get("start_event_id"), 0)
            hi = coerce._as_int(event_range.get("end_event_id"), 0)
            if lo < 0 or hi < lo:
                return envelope.failure("Invalid duration event range", code="validation_error")
            top = await live_state._perf_service.detect_hotspots(session_id, live_state._session_manager, top_k=0)
            top = [item for item in top if lo <= int(item["event_id"]) <= hi][:max_events]
        else:
            top = await live_state._perf_service.detect_hotspots(session_id, live_state._session_manager, top_k=max_events)
        return envelope.success(event_durations=top)
    return envelope.failure(f"Unsupported perf action: {action}", code="runtime_error")
