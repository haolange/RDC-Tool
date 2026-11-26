"""Per-context operation log: start, stage and finish records with timing."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from rdc_tool import progress, remote_bootstrap
from rdc_tool.context_snapshot import normalize_context_id
from rdc_tool.runtime import context_records, live_state, settings
from rdc_tool.runtime_state import append_runtime_log


def _trim_stage_events(stages: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return list(stages or [])[-32:]


def _summarize_args(args: Dict[str, Any]) -> Dict[str, Any]:
    summary: Dict[str, Any] = {"arg_keys": sorted(str(key) for key in args.keys())}
    for key, value in list(args.items())[:8]:
        if isinstance(value, (str, int, float, bool)) or value is None:
            summary[str(key)] = value
        elif isinstance(value, dict):
            summary[str(key)] = {"keys": sorted(str(item) for item in value.keys())[:8]}
        elif isinstance(value, list):
            summary[str(key)] = {"len": len(value)}
        else:
            summary[str(key)] = {"type": type(value).__name__}
    return summary


def _upsert_operation_entry(
    state: Dict[str, Any],
    trace_id: str,
    *,
    defaults: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    recent = list(state.get("recent_operations") or [])
    existing = next((item for item in recent if isinstance(item, dict) and str(item.get("trace_id") or "") == str(trace_id)), None)
    if existing is None:
        existing = {
            "trace_id": str(trace_id),
            "operation": "",
            "transport": "",
            "status": "running",
            "args_summary": {},
            "stages": [],
            "result_ok": None,
            "error_code": "",
            "error_message": "",
            "duration_ms": 0,
            "started_at_ms": settings._now_ms(),
            "updated_at_ms": settings._now_ms(),
            "recovery_attempted": False,
        }
        recent.insert(0, existing)
    if isinstance(defaults, dict):
        for key, value in defaults.items():
            existing.setdefault(key, value)
    limit = int(state.get("limits", {}).get("max_recent_operations") or settings._runtime_limits().get("max_recent_operations", 64))
    state["recent_operations"] = [item for item in recent if isinstance(item, dict)]
    state["recent_operations"] = state["recent_operations"][: max(limit * 2, 8)]
    return existing


def _record_operation_start(
    context_id: str,
    *,
    trace_id: str,
    operation: str,
    transport: str,
    args: Dict[str, Any],
) -> None:
    ctx = normalize_context_id(context_id)
    state = context_records._context_state(ctx)
    if str(operation or "").startswith("rd.remote."):
        state["backend"] = "remote"
    elif operation == "rd.capture.open_replay":
        options = args.get("options") if isinstance(args.get("options"), dict) else {}
        state["backend"] = "remote" if str(options.get("remote_id") or "").strip() else "local"
    entry = _upsert_operation_entry(
        state,
        str(trace_id),
        defaults={
            "operation": str(operation),
            "transport": str(transport),
            "args_summary": _summarize_args(args),
            "started_at_ms": settings._now_ms(),
        },
    )
    entry["operation"] = str(operation)
    entry["transport"] = str(transport)
    entry["args_summary"] = _summarize_args(args)
    entry["status"] = "running"
    entry["updated_at_ms"] = settings._now_ms()
    metrics = dict(state.get("metrics") or {})
    metrics["operation_count"] = int(metrics.get("operation_count") or 0) + 1
    metrics["last_operation_ms"] = settings._now_ms()
    state["metrics"] = metrics
    context_records._store_context_state(state, ctx)


def _record_operation_stage(
    context_id: str,
    *,
    trace_id: str,
    stage: str,
    message: str,
    progress_pct: Optional[float] = None,
    details: Optional[Dict[str, Any]] = None,
) -> None:
    ctx = normalize_context_id(context_id)
    state = context_records._context_state(ctx)
    entry = _upsert_operation_entry(state, str(trace_id))
    stages = list(entry.get("stages") or [])
    stages.append(
        {
            "stage": str(stage),
            "message": str(message),
            "progress_pct": progress_pct,
            "details": dict(details or {}),
            "ts_ms": settings._now_ms(),
        }
    )
    entry["stages"] = _trim_stage_events(stages)
    entry["updated_at_ms"] = settings._now_ms()
    context_records._store_context_state(state, ctx)


def _record_operation_finish(
    context_id: str,
    *,
    trace_id: str,
    payload: Dict[str, Any],
) -> None:
    ctx = normalize_context_id(context_id)
    state = context_records._context_state(ctx)
    entry = _upsert_operation_entry(state, str(trace_id))
    meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
    error = payload.get("error") if isinstance(payload.get("error"), dict) else {}
    ok = bool(payload.get("ok"))
    duration_ms = int(meta.get("duration_ms") or entry.get("duration_ms") or 0)
    entry["result_ok"] = ok
    entry["status"] = "completed" if ok else "failed"
    entry["error_code"] = str(error.get("code") or "")
    entry["error_message"] = str(error.get("message") or "")
    entry["duration_ms"] = duration_ms
    entry["updated_at_ms"] = settings._now_ms()
    metrics = dict(state.get("metrics") or {})
    if not ok:
        metrics["operation_error_count"] = int(metrics.get("operation_error_count") or 0) + 1
    durations = list(metrics.get("recent_operation_duration_ms") or [])
    if duration_ms >= 0:
        durations.append(duration_ms)
    metrics["recent_operation_duration_ms"] = durations[-64:]
    metrics["last_operation_ms"] = settings._now_ms()
    state["metrics"] = metrics
    limit = int(state.get("limits", {}).get("max_recent_operations") or settings._runtime_limits().get("max_recent_operations", 64))
    state["recent_operations"] = list(state.get("recent_operations") or [])[: max(limit, 1)]
    context_records._store_context_state(state, ctx)


def _current_trace_details() -> Dict[str, str]:
    reporter = progress.current_reporter()
    if reporter is None:
        return {"trace_id": "", "operation": ""}
    return {"trace_id": str(reporter.trace_id or ""), "operation": str(reporter.operation or "")}


def _record_log(level: str, message: str, context: Optional[Dict[str, Any]] = None) -> None:
    trace = _current_trace_details()
    ctx = normalize_context_id(live_state._runtime_context_id())
    entry = {
        "ts_ms": settings._now_ms(),
        "level": level.lower(),
        "message": message,
        "context": context or {},
        "trace_id": trace["trace_id"],
        "operation": trace["operation"],
        "context_id": ctx,
    }
    live_state._runtime.logs.append(entry)
    if len(live_state._runtime.logs) > 5000:
        live_state._runtime.logs = live_state._runtime.logs[-5000:]
    try:
        append_runtime_log(ctx, entry)
    except Exception:
        pass


def _progress(
    stage: str,
    message: str,
    *,
    progress_pct: float | None = None,
    details: Optional[Dict[str, Any]] = None,
) -> None:
    # Reported progress is what keeps a no-progress budget alive.
    remote_bootstrap.connection_progressed()
    reporter = progress.current_reporter()
    if reporter is None:
        return
    _record_operation_stage(
        live_state._runtime_context_id(),
        trace_id=str(reporter.trace_id),
        stage=str(stage),
        message=str(message),
        progress_pct=progress_pct,
        details=details,
    )
    reporter.emit(stage, message, progress_pct=progress_pct, details=details)
