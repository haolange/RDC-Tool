"""Structured progress and the per-request execution scope shared by daemon, worker and core services."""

from __future__ import annotations

import contextvars
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Protocol

from rdc_tool import timeout_policy

# Native-call frames: an enter frame is always sent when the call name changes,
# otherwise at most once per interval; an exit frame only for calls slower than
# the threshold. Together they bound the frame rate while every long native call
# still leaves an observable trace for the no-progress watchdog.
NATIVE_CALL_ENTER_INTERVAL_S = 0.5
NATIVE_CALL_EXIT_MIN_S = 1.0


def _now_ms() -> int:
    return int(time.time() * 1000)


@dataclass
class ProgressEvent:
    trace_id: str
    operation: str
    stage: str
    message: str
    progress_pct: Optional[float] = None
    details: Dict[str, Any] = field(default_factory=dict)
    ts_ms: int = field(default_factory=_now_ms)


@dataclass(frozen=True)
class NativeCallFrame:
    trace_id: str
    name: str
    phase: str  # "enter" | "exit"
    ts_ms: int


class ProgressSink(Protocol):
    def publish(self, event: ProgressEvent) -> None:
        ...


class FrameSink(ProgressSink, Protocol):
    def native_call(self, frame: NativeCallFrame) -> None:
        ...


class ProgressReporter:
    def __init__(
        self,
        *,
        trace_id: str,
        operation: str,
        sink: Optional[ProgressSink] = None,
    ) -> None:
        self.trace_id = str(trace_id)
        self.operation = str(operation)
        self.sink = sink

    def emit(
        self,
        stage: str,
        message: str,
        *,
        progress_pct: Optional[float] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> ProgressEvent:
        event = ProgressEvent(
            trace_id=self.trace_id,
            operation=self.operation,
            stage=str(stage),
            message=str(message),
            progress_pct=progress_pct,
            details=dict(details or {}),
        )
        if self.sink is not None:
            self.sink.publish(event)
        return event


class RequestScope:
    """One worker request: its identity, no-progress budget, cancellation and the sink that carries its frames.

    ``cancelled`` is set by the worker's stdin reader when the daemon cancels the
    request; loops that run inside one native call poll it.
    """

    def __init__(self, *, request_id: str, trace_id: str, no_progress_ms: int = timeout_policy.DEFAULT_NO_PROGRESS_MS,
                 sink: Optional[FrameSink] = None) -> None:
        self.request_id = str(request_id)
        self.trace_id = str(trace_id)
        self.no_progress_ms = int(no_progress_ms)
        self.sink = sink
        self.cancelled = threading.Event()
        self._lock = threading.Lock()
        self._last_name = ""
        self._last_enter = 0.0

    def native_call(self, name: str, phase: str) -> None:
        if self.sink is None:
            return
        if phase == "enter":
            now = time.monotonic()
            with self._lock:
                if name == self._last_name and now - self._last_enter < NATIVE_CALL_ENTER_INTERVAL_S:
                    return
                self._last_name, self._last_enter = name, now
        try:
            self.sink.native_call(NativeCallFrame(self.trace_id, name, phase, _now_ms()))
        except Exception:
            # Frame delivery cannot change the native call's outcome.
            logging.getLogger(__name__).warning("Native-call frame delivery failed", exc_info=True)


_CURRENT_PROGRESS_REPORTER: contextvars.ContextVar[ProgressReporter | None] = contextvars.ContextVar(
    "rdc_tool_current_progress_reporter", default=None)
_CURRENT_REQUEST: contextvars.ContextVar[RequestScope | None] = contextvars.ContextVar(
    "rdc_tool_current_request", default=None)


def current_reporter() -> ProgressReporter | None:
    return _CURRENT_PROGRESS_REPORTER.get()


def current_request() -> RequestScope | None:
    return _CURRENT_REQUEST.get()


def cancel_requested() -> bool:
    """True once the running request has been cancelled."""
    scope = _CURRENT_REQUEST.get()
    return scope is not None and scope.cancelled.is_set()


def current_no_progress_ms() -> int:
    """The running request's no-progress budget, or the published default outside a request."""
    scope = _CURRENT_REQUEST.get()
    return scope.no_progress_ms if scope is not None else timeout_policy.DEFAULT_NO_PROGRESS_MS
