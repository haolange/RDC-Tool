"""Dedicated worker process for RenderDoc-backed runtime execution."""

from __future__ import annotations

import argparse
import asyncio
import collections
import faulthandler
import io
import json
import logging
import os
import queue
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from typing import Any, Awaitable, Dict

from rdc_tool.context_snapshot import normalize_context_id
from rdc_tool.core.contracts import canonical_error
from rdc_tool.io_utils import safe_json_text, safe_stream_write
from rdc_tool.platform import process
from rdc_tool.platform.process import ProcessIdentity
from rdc_tool import progress, timeout_policy
from rdc_tool.progress import NativeCallFrame, ProgressEvent, RequestScope

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")
if hasattr(sys.stdin, "reconfigure"):
    sys.stdin.reconfigure(encoding="utf-8")


# The event loop thread and the replay thread (native transfer callbacks) both
# write frames; one line must never interleave with another.
_EMIT_LOCK = threading.Lock()


def _emit(payload: Dict[str, Any]) -> None:
    text = safe_json_text(payload) + "\n"
    with _EMIT_LOCK:
        safe_stream_write(text, sys.stdout)


class _StackDumps:
    """faulthandler's watchdog for the running request.

    The dump runs on faulthandler's own C thread and reads every Python
    thread's frames without taking the GIL, so it still reports where the
    worker is while a native call holds the interpreter. It fires just before
    the daemon's no-progress watchdog and is re-armed, at most once a second,
    whenever the request reports a frame.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._enabled = False
        self._after_s = 0.0
        self._armed_at = 0.0

    def enable(self) -> None:
        try:
            faulthandler.enable(file=sys.stderr, all_threads=True)
        except (AttributeError, OSError, ValueError, io.UnsupportedOperation):
            return
        self._enabled = True

    def _arm_locked(self) -> None:
        faulthandler.dump_traceback_later(self._after_s, repeat=False, file=sys.stderr, exit=False)
        self._armed_at = time.monotonic()

    def arm(self, no_progress_ms: int) -> None:
        with self._lock:
            if self._enabled:
                self._after_s = timeout_policy.stack_dump_after_s(no_progress_ms)
                self._arm_locked()

    def touch(self) -> None:
        with self._lock:
            if self._after_s and time.monotonic() - self._armed_at >= timeout_policy.STACK_DUMP_REARM_INTERVAL_S:
                self._arm_locked()

    def cancel(self) -> None:
        with self._lock:
            if self._after_s:
                self._after_s = 0.0
                faulthandler.cancel_dump_traceback_later()


_STACK_DUMPS = _StackDumps()


class _WorkerFrameSink:
    """Carries one request's progress and native-call frames to the daemon."""

    def __init__(self, request_id: str) -> None:
        self.request_id = request_id

    def _send(self, payload: Dict[str, Any]) -> None:
        try:
            _emit({"id": self.request_id, **payload})
        except Exception:
            # Frame delivery cannot change the native operation outcome.
            logging.getLogger(__name__).warning("Worker frame delivery failed", exc_info=True)
        _STACK_DUMPS.touch()

    def publish(self, event: ProgressEvent) -> None:
        self._send({"kind": "progress", "event": asdict(event)})

    def native_call(self, frame: NativeCallFrame) -> None:
        self._send({"kind": "native_call", "trace_id": frame.trace_id, "name": frame.name,
                    "phase": frame.phase, "ts_ms": frame.ts_ms})


class _RequestControl:
    """What the stdin reader needs to cancel the running request.

    A cancel line is handled on the reader thread, never behind the request it
    cancels: it sets the request's event (loops inside one native call poll it)
    and cancels the request's task at its next await, which waits for any
    running native call to settle first. A cancel that overtakes its exec line
    is remembered briefly, so the request is refused before it starts.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._active: tuple[RequestScope, asyncio.Task, asyncio.AbstractEventLoop] | None = None
        self._early: "collections.deque[tuple[str, float]]" = collections.deque(maxlen=32)

    def begin(self, scope: RequestScope) -> bool:
        """Register the running request; False when it was cancelled before it started."""
        now = time.monotonic()
        with self._lock:
            early = [item for item in self._early if item[0] == scope.request_id
                     and now - item[1] <= timeout_policy.CANCEL_GRACE_S]
            if early:
                self._early.remove(early[0])
                scope.cancelled.set()
                return False
            task = asyncio.current_task()
            assert task is not None
            self._active = (scope, task, asyncio.get_running_loop())
            return True

    def end(self) -> None:
        with self._lock:
            self._active = None

    def cancel(self, request_id: str) -> None:
        with self._lock:
            active = self._active
            if active is None or active[0].request_id != request_id:
                self._early.append((request_id, time.monotonic()))
                return
        scope, task, loop = active
        scope.cancelled.set()
        loop.call_soon_threadsafe(task.cancel)


_CONTROL = _RequestControl()


# The result of a request that was cancelled before it started.
_NOT_STARTED = object()


async def _in_request(scope: RequestScope, work: Awaitable[Any]) -> Any:
    token = progress._CURRENT_REQUEST.set(scope)
    try:
        if not _CONTROL.begin(scope):
            work.close()  # type: ignore[attr-defined]
            return _NOT_STARTED
        try:
            return await work
        finally:
            _CONTROL.end()
    finally:
        progress._CURRENT_REQUEST.reset(token)


def _cancelled_envelope(operation: str, scope: RequestScope, *, started: bool) -> Dict[str, Any]:
    # A started request stopped at a native-call boundary: native calls that had
    # completed are not rolled back, and the operation's own cleanup has run.
    return canonical_error(
        result_kind=operation, code="operation_cancelled", category="runtime",
        message=f"{operation} was cancelled" + ("" if started else " before it started"),
        details={"failure_stage": "running" if started else "queued", "reason": "cancel_requested",
                 "outcome": "cancelled" if started else "not_started", "request_id": scope.request_id,
                 "trace_id": scope.trace_id},
        trace_id=scope.trace_id, transport="daemon")


def _read_requests(stream: Any, requests: "queue.Queue[Dict[str, Any] | None]") -> None:
    """The dedicated stdin reader: control lines act at once, requests queue for the main loop."""
    try:
        for line in stream:
            text = str(line).strip()
            if not text:
                continue
            try:
                request = json.loads(text)
            except Exception as exc:  # noqa: BLE001
                _emit({"id": "", "ok": False, "error": {"message": f"invalid request: {exc}"}})
                continue
            if isinstance(request, dict) and request.get("kind") == "cancel":
                _CONTROL.cancel(str(request.get("request_id") or ""))
                continue
            requests.put(request if isinstance(request, dict) else {})
    finally:
        requests.put(None)


def _run_request(runner: asyncio.Runner, scope: RequestScope, work: Awaitable[Any]) -> Any:
    _STACK_DUMPS.arm(scope.no_progress_ms)
    try:
        return runner.run(_in_request(scope, work))
    finally:
        _STACK_DUMPS.cancel()


def _context_id() -> str:
    return normalize_context_id(os.environ.get("RDC_TOOL_CONTEXT_ID"))


def _parent_daemon() -> ProcessIdentity:
    return ProcessIdentity(int(os.environ.get("RDC_TOOL_DAEMON_PID") or 0), os.environ.get("RDC_TOOL_DAEMON_BIRTH", ""))


def _watch_parent_daemon() -> None:
    parent = _parent_daemon()
    if parent.pid > 0:
        process.watch_parent(parent, lambda: os._exit(0))
        # The daemon pumps this worker's stderr into worker.log: stack dumps
        # and fatal-signal tracebacks go there.
        _STACK_DUMPS.enable()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="RDC-Tool RenderDoc runtime worker")
    parser.add_argument("--context-id", default=_context_id())
    args = parser.parse_args(argv)
    context_id = str(args.context_id or "default").strip() or "default"
    os.environ["RDC_TOOL_CONTEXT_ID"] = context_id

    try:
        from rdc_tool.runtime import dispatch, runtime_lifecycle
    except Exception as exc:  # noqa: BLE001
        _emit({"kind": "startup_error", "message": f"{exc.__class__.__name__}: {exc}"})
        return 1

    _watch_parent_daemon()
    from rdc_tool.runtime_identity import loaded_runtime_identity
    from rdc_tool.runtime_paths import binaries_root, pymodules_dir

    def loaded_runtime() -> dict[str, Any]:
        return loaded_runtime_identity(binaries_root(), pymodules_dir())

    runtime_dirs = {
        "binaries_dir": str(binaries_root().resolve()),
        "pymodules_dir": str(pymodules_dir().resolve()),
        "source_manifest": str((binaries_root() / "manifest.runtime.json").resolve()),
    }

    _emit(
        {
            "kind": "ready",
            "context_id": context_id,
            "pid": os.getpid(),
            **runtime_dirs,
            "loaded_runtime": loaded_runtime(),
        }
    )

    # Controller and proxy graphics state require one persistent replay thread.
    # Closing a per-request asyncio.run executor invalidates that native context.
    with asyncio.Runner() as runner:
        runner.get_loop().set_default_executor(ThreadPoolExecutor(max_workers=1, thread_name_prefix="rdc-tool-replay"))
        shutdown_complete = False
        requests: "queue.Queue[Dict[str, Any] | None]" = queue.Queue()
        threading.Thread(target=_read_requests, args=(sys.stdin, requests), name="rdc-tool-worker-stdin",
                         daemon=True).start()
        try:
            while (request := requests.get()) is not None:
                req_id = str(request.get("id") or "")
                method = str(request.get("method") or "").strip()
                params = request.get("params") if isinstance(request.get("params"), dict) else {}
                try:
                    if method == "exec":
                        operation = str(params.get("operation") or "")
                        cleanup = operation in {"rd.core.shutdown", "rd.capture.close_replay", "rd.remote.disconnect"}
                        if not cleanup and loaded_runtime()["status"] == "mismatch":
                            raise RuntimeError("Loaded RenderDoc paths differ from the configured runtime")
                        sink = _WorkerFrameSink(req_id)
                        scope = RequestScope(
                            request_id=str(params.get("request_id") or req_id), sink=sink,
                            trace_id=str(params.get("trace_id") or f"trc_{uuid.uuid4().hex[:12]}"),
                            no_progress_ms=int(params.get("no_progress_ms") or timeout_policy.DEFAULT_NO_PROGRESS_MS))
                        try:
                            result = _run_request(runner, scope,
                                dispatch.dispatch_operation(
                                    operation,
                                    dict(params.get("args") or {}),
                                    transport=str(params.get("transport") or "daemon"),
                                    remote=bool(params.get("remote", False)),
                                    context_id=context_id,
                                    progress_sink=sink,
                                    trace_id=scope.trace_id,
                                )
                            )
                        except asyncio.CancelledError:
                            result = _cancelled_envelope(operation, scope, started=True)
                        if result is _NOT_STARTED:
                            result = _cancelled_envelope(operation, scope, started=False)
                        observed = loaded_runtime()
                        if not cleanup and observed["status"] == "mismatch":
                            raise RuntimeError("Loaded RenderDoc paths differ from the configured runtime")
                        _emit({"id": req_id, "ok": True, "result": result, "loaded_runtime": observed})
                        continue
                    if method == "clear_context":
                        sink = _WorkerFrameSink(req_id)
                        scope = RequestScope(request_id=req_id, sink=sink, trace_id=f"trc_{uuid.uuid4().hex[:12]}")
                        result = _run_request(runner, scope,
                            dispatch.dispatch_operation(
                                "rd.session.clear_context",
                                {},
                                transport="daemon",
                                remote=False,
                                context_id=context_id,
                                progress_sink=sink,
                                trace_id=scope.trace_id,
                            )
                        )
                        _emit({"id": req_id, "ok": True, "result": result})
                        continue
                    if method == "status":
                        _emit(
                            {
                                "id": req_id,
                                "ok": True,
                                "result": {
                                    "running": True,
                                    "pid": os.getpid(),
                                    **runtime_dirs,
                                    "loaded_runtime": loaded_runtime(),
                                },
                            }
                        )
                        continue
                    if method == "shutdown":
                        runner.run(runtime_lifecycle.runtime_shutdown(clear_context_state=False))
                        shutdown_complete = True
                        _emit({"id": req_id, "ok": True, "result": {"stopped": True}})
                        return 0
                    _emit({"id": req_id, "ok": False, "error": {"message": f"unknown worker method: {method}"}})
                except Exception as exc:  # noqa: BLE001
                    _emit({"id": req_id, "ok": False, "error": {"message": f"{exc.__class__.__name__}: {exc}"}})
        finally:
            if not shutdown_complete:
                runner.run(runtime_lifecycle.runtime_shutdown(clear_context_state=False))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
