"""Cancelling a request: queued, cooperative and unsettled, against the real worker loop."""
from __future__ import annotations

import io
import json
import sys
import threading
import time
from pathlib import Path

import pytest

from rdc_tool import timeout_policy
from rdc_tool.daemon import server as daemon_server
from rdc_tool.daemon import worker as daemon_worker
from rdc_tool.platform import host, process
from rdc_tool.platform.ipc import Endpoint
from rdc_tool.platform.process import Liveness, ProcessIdentity
from rdc_tool.runtime import dispatch as runtime_dispatch
from rdc_tool.runtime import runtime_lifecycle, worker_main

FAKES = Path(__file__).resolve().parent / "fakes"


class _Conn:
    def __init__(self) -> None:
        self.sent = []
        self.replied = threading.Event()

    def send(self, message):
        self.sent.append(message)
        if "kind" not in message:
            self.replied.set()

    @property
    def reply(self):
        return next(message for message in self.sent if "kind" not in message)


def _daemon(monkeypatch, context="cancel-test"):
    daemon = daemon_server.DaemonRuntime(endpoint=Endpoint("fixture"), token="fixture", daemon_context=context)
    monkeypatch.setattr(daemon, "_persist_state", lambda: None)
    return daemon


def _start_exec(daemon, operation, request_id, conn=None):
    conn = conn or _Conn()
    thread = threading.Thread(target=daemon._serve_exec, args=(conn, {
        "operation": operation, "args": {}, "request_id": request_id, "no_progress_ms": 60000}), daemon=True)
    thread.start()
    return conn, thread


def _wait_running(daemon, request_id, timeout=10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with daemon._requests_lock:
            channel = daemon._requests.get(request_id)
        if channel is not None and channel.state == "running" and daemon.state["active_operation"].get("stage") not in (None, "starting"):
            return channel
        time.sleep(0.02)
    raise AssertionError(f"{request_id} did not start running")


def test_queued_request_is_cancelled_without_running(monkeypatch):
    monkeypatch.setattr(timeout_policy, "EXEC_LOCK_SLICE_S", 0.02)
    daemon = _daemon(monkeypatch)
    monkeypatch.setattr(daemon, "_refresh_state_from_runtime_locked", lambda: None)
    monkeypatch.setattr(daemon, "_request_worker", lambda *a, **k: pytest.fail("a queued cancelled request ran"))
    daemon._exec_lock.acquire()
    try:
        conn, thread = _start_exec(daemon, "rd.texture.get_data", "queued-1")
        while "queued-1" not in daemon._requests:
            time.sleep(0.01)
        receipt = daemon._cancel({"request_id": "queued-1"})["result"]
        thread.join(5)
    finally:
        daemon._exec_lock.release()
    assert receipt["outcome"] == "cancelled"
    assert receipt["request_id"] == "queued-1" and receipt["trace_id"].startswith("trc_")
    envelope = conn.reply["result"]
    assert (envelope["result_kind"], envelope["error"]["code"]) == ("rd.texture.get_data", "operation_cancelled")
    assert envelope["error"]["details"]["outcome"] == "not_started"
    # A late cancel for the same request reports how it ended; an unknown one is not_found.
    assert daemon._cancel({"request_id": "queued-1"})["result"]["outcome"] == "cancelled"
    assert daemon._cancel({"request_id": "never-seen"})["result"]["outcome"] == "not_found"


def test_cancel_line_that_overtakes_its_request_refuses_it_before_it_starts(monkeypatch):
    monkeypatch.setenv("RDC_TOOL_CONTEXT_ID", "default")
    async def dispatch(*args, **kwargs):
        pytest.fail("a request cancelled before it started ran")
    async def shutdown(**kwargs):
        return None
    monkeypatch.setattr(runtime_dispatch, "dispatch_operation", dispatch)
    monkeypatch.setattr(runtime_lifecycle, "runtime_shutdown", shutdown)
    lines = [{"kind": "cancel", "request_id": "req-early"},
             {"id": "wrk_1", "method": "exec", "params": {"operation": "rd.debug.run_to", "request_id": "req-early",
                                                           "trace_id": "trc_early"}},
             {"id": "stop", "method": "shutdown"}]
    monkeypatch.setattr(worker_main.sys, "stdin", io.StringIO("\n".join(json.dumps(line) for line in lines)))
    outputs = []
    monkeypatch.setattr(worker_main, "_emit", outputs.append)
    assert worker_main.main(["--context-id", "early-cancel"]) == 0
    envelope = next(item for item in outputs if item.get("id") == "wrk_1")["result"]
    assert envelope["error"]["code"] == "operation_cancelled"
    assert envelope["error"]["details"] == {"failure_stage": "queued", "reason": "cancel_requested",
                                            "outcome": "not_started", "request_id": "req-early", "trace_id": "trc_early"}


@pytest.fixture
def scripted_worker(monkeypatch):
    monkeypatch.setattr(daemon_worker, "child_python_argv",
                        lambda module, *args: [sys.executable, str(FAKES / "scripted_worker.py"), *args])
    monkeypatch.setattr(daemon_worker, "native_manifest_status", lambda root: {"status": "absent"})
    daemons = []
    yield daemons
    for daemon in daemons:
        if daemon._worker is not None:
            daemon._worker.stop()
            for path in Path(daemon._worker.log_path).parent.glob(f"worker_{daemon.daemon_context}.log*"):
                path.unlink(missing_ok=True)


@pytest.mark.skipif(host.IS_WINDOWS, reason="worker subprocess identities are read from /proc")
def test_running_request_stops_at_a_native_call_boundary_and_keeps_its_worker(monkeypatch, scripted_worker):
    daemon = _daemon(monkeypatch, "cancel-cooperative")
    scripted_worker.append(daemon)
    conn, thread = _start_exec(daemon, "test.cooperative", "coop-1")
    _wait_running(daemon, "coop-1")
    worker_before = daemon._worker.previous_identity()
    receipt = daemon._cancel({"request_id": "coop-1"})["result"]
    thread.join(5)
    assert receipt["outcome"] == "cancelled" and "worker_exit" not in receipt
    envelope = conn.reply["result"]
    assert envelope["error"]["code"] == "operation_cancelled"
    assert envelope["error"]["details"]["outcome"] == "cancelled"
    assert envelope["error"]["details"]["request_id"] == "coop-1"
    # The worker survived: the next request runs on the same process.
    follow_up, follow_thread = _start_exec(daemon, "test.quick", "coop-2")
    follow_thread.join(10)
    assert follow_up.reply["result"]["ok"] is True
    assert daemon._worker.previous_identity() == worker_before
    assert [entry["event"] for entry in daemon.state["worker_lifecycle"]] == ["started"]


@pytest.mark.skipif(host.IS_WINDOWS, reason="worker subprocess identities are read from /proc")
def test_unsettled_cancel_terminates_the_worker_as_stuck(monkeypatch, scripted_worker):
    monkeypatch.setattr(timeout_policy, "CANCEL_GRACE_S", 1.0)
    daemon = _daemon(monkeypatch, "cancel-unsettled")
    scripted_worker.append(daemon)
    conn, thread = _start_exec(daemon, "test.native_sleep", "stuck-1")
    _wait_running(daemon, "stuck-1")
    worker = daemon._worker.previous_identity()
    receipt = daemon._cancel({"request_id": "stuck-1"})["result"]
    thread.join(10)
    assert receipt["outcome"] == "terminated"
    assert receipt["worker_exit"] == {"pid": worker.pid, "start_generation": worker.birth,
                                      "reason": "cancel_unsettled", "exit_confirmed": True}
    envelope = conn.reply["result"]
    assert (envelope["error"]["code"], envelope["error"]["details"]["reason"]) == ("worker_stuck", "cancel_unsettled")
    assert process.probe(worker) is Liveness.EXITED
    assert daemon.state["worker_lifecycle"][-1]["reason"] == "cancel_unsettled"


def test_connection_budget_shares_the_request_cancellation():
    from rdc_tool import progress, remote_bootstrap
    scope = progress.RequestScope(request_id="req", trace_id="trc", no_progress_ms=60000)
    token = progress._CURRENT_REQUEST.set(scope)
    try:
        budget = remote_bootstrap._request_budget()
        assert budget.cancelled is scope.cancelled
        assert progress.cancel_requested() is False
        scope.cancelled.set()
        assert progress.cancel_requested() is True
        with pytest.raises(remote_bootstrap.AndroidRemoteBootstrapError) as raised:
            budget.remaining()
        assert raised.value.code == "remote_connect_cancelled"
    finally:
        progress._CURRENT_REQUEST.reset(token)


def test_debug_states_produced_during_a_cancelled_step_stay_with_the_handle():
    import asyncio
    from collections import deque
    from types import SimpleNamespace
    from rdc_tool import native_calls
    from rdc_tool.runtime.operations import debug
    entered, release = threading.Event(), threading.Event()
    def ContinueDebug(debugger):
        entered.set()
        assert release.wait(5)
        return ["state-1", "state-2"]
    handle = SimpleNamespace(debugger=object(), pending_states=deque())
    async def scenario():
        task = asyncio.create_task(native_calls.offload(debug._continue_debug_into, SimpleNamespace(ContinueDebug=ContinueDebug), handle))
        while not entered.is_set():
            await asyncio.sleep(0.01)
        task.cancel()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
    asyncio.run(scenario())
    assert list(handle.pending_states) == ["state-1", "state-2"]
