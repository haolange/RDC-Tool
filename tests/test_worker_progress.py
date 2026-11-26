from dataclasses import asdict
import io
import json
import threading
from types import SimpleNamespace

import pytest

from rdc_tool.runtime import worker_main
from rdc_tool.daemon.server import DaemonRuntime
from rdc_tool.daemon.worker import RuntimeWorkerProcess
from rdc_tool.progress import ProgressEvent
from rdc_tool.runtime import dispatch as runtime_dispatch
from rdc_tool.runtime import runtime_lifecycle


def event(stage="installing", **changes):
    return asdict(ProgressEvent(trace_id="trace-owned", operation="rd.remote.connect", stage=stage,
        message=stage, details={"installation": {"installed_apk": stage == "cancelled"}}, **changes))


def worker(monkeypatch, frames):
    process = RuntimeWorkerProcess(context_id="progress-test")
    process._proc = SimpleNamespace(poll=lambda: None, stdin=io.StringIO())
    monkeypatch.setattr(process, "_save_state", lambda: None)
    for frame in frames:
        process._queue.put(frame)
    return process


def test_correlated_worker_progress_reaches_daemon_status_before_final(monkeypatch):
    daemon = object.__new__(DaemonRuntime)
    daemon.state = {"active_operation": {}}
    daemon._state_lock = threading.RLock()
    daemon.running = True
    monkeypatch.setattr(daemon, "_prune_clients_locked", lambda now: None)
    monkeypatch.setattr(daemon, "_refresh_state_from_runtime_locked", lambda: None)
    monkeypatch.setattr(daemon, "_persist_state", lambda: None)
    observed = []
    class Sink:
        def publish(self, progress):
            daemon.publish(progress)
            observed.append(daemon._status_payload()["result"]["state"]["active_operation"])
    frames = [{"id": "old-request", "kind": "progress", "event": {"invalid": True}}]
    frames += [{"id": "wrk_1", "kind": "progress", "event": event(stage)}
        for stage in ("checking", "installing", "starting", "verifying", "cancelled")]
    final = {"id": "wrk_1", "ok": True, "result": {"ok": False, "error": {"code": "remote_connect_cancelled"}}}
    process = worker(monkeypatch, frames + [final])
    assert process.request("exec", {"operation": "rd.remote.connect"}, frame_sink=Sink()) == final
    assert [item["stage"] for item in observed] == ["checking", "installing", "starting", "verifying", "cancelled"]
    assert all(item["trace_id"] == "trace-owned" for item in observed)
    assert observed[-1]["details"]["installation"]["installed_apk"] is True
    # A delayed old frame cannot contaminate the following request.
    process._queue.put({"id": "wrk_1", "kind": "progress", "event": event("late")})
    process._queue.put({"id": "wrk_2", "ok": True, "result": {"done": True}})
    assert process.request("exec", {"operation": "rd.remote.connect"}, frame_sink=Sink())["result"] == {"done": True}
    assert len(observed) == 5


@pytest.mark.parametrize("change", [{"trace_id": ""}, {"operation": "rd.other"}, {"ts_ms": True},
    {"details": []}, {"progress_pct": float("nan")}, {"extra": True}])
def test_invalid_progress_frame_is_not_published(monkeypatch, change):
    payload = {**event(), **change}
    process = worker(monkeypatch, [{"id": "wrk_1", "kind": "progress", "event": payload}])
    class Sink:
        def publish(self, progress):
            pytest.fail("invalid event published")
    with pytest.raises(RuntimeError, match="progress"):
        process.request("exec", {"operation": "rd.remote.connect"}, frame_sink=Sink())


def test_sink_failure_does_not_lose_final_operation_receipt(monkeypatch):
    final = {"id": "wrk_1", "ok": True, "result": {"installed_apk": True}}
    process = worker(monkeypatch, [{"id": "wrk_1", "kind": "progress", "event": event()}, final])
    class Sink:
        def publish(self, progress):
            raise OSError("status persistence unavailable")
    assert process.request("exec", {"operation": "rd.remote.connect"}, frame_sink=Sink()) == final


@pytest.mark.parametrize("sink_write_fails", [False, True])
def test_runtime_worker_progress_and_final_reply_share_request_identity(monkeypatch, sink_write_fails):
    monkeypatch.setenv("RDC_TOOL_CONTEXT_ID", "default")
    outputs = []
    def emit(payload):
        if payload.get("kind") == "progress" and sink_write_fails:
            raise OSError("progress pipe write failed")
        outputs.append(payload)
    async def dispatch(operation, args, *, progress_sink, **kwargs):
        progress_sink.publish(ProgressEvent(trace_id="trace-owned", operation=operation, stage="installing", message="Installing"))
        return {"ok": True, "data": {"installed_apk": True}}
    async def shutdown(*, clear_context_state):
        assert clear_context_state is False
    monkeypatch.setattr(runtime_dispatch, "dispatch_operation", dispatch)
    monkeypatch.setattr(runtime_lifecycle, "runtime_shutdown", shutdown)
    requests = [{"id": "call", "method": "exec", "params": {"operation": "rd.remote.connect"}},
        {"id": "stop", "method": "shutdown"}]
    monkeypatch.setattr(worker_main.sys, "stdin", io.StringIO("\n".join(json.dumps(item) for item in requests)))
    monkeypatch.setattr(worker_main, "_emit", emit)
    assert worker_main.main(["--context-id", "progress-worker"]) == 0
    if not sink_write_fails:
        progress = next(item for item in outputs if item.get("kind") == "progress")
        assert progress["id"] == "call"
        assert progress["event"]["stage"] == "installing"
    final = next(item for item in outputs if item.get("id") == "call" and "result" in item)
    assert final["result"]["data"]["installed_apk"] is True
    assert outputs[-1]["result"] == {"stopped": True}


def test_reader_thread_exit_retains_progress_and_final_reply(monkeypatch):
    final = {"id": "wrk_1", "ok": True, "result": {"stopped": True}}
    frames = [{"id": "wrk_1", "kind": "progress", "event": event("cancelled")}, final]
    process = worker(monkeypatch, [])
    reader = threading.Thread(target=process._pump_stdout,
        args=(io.StringIO("\n".join(json.dumps(item) for item in frames) + "\n"),))
    reader.start()
    reader.join(1)
    assert not reader.is_alive()
    observed = []
    sink = SimpleNamespace(publish=observed.append)
    assert process.request("exec", {"operation": "rd.remote.connect"}, frame_sink=sink) == final
    assert observed[0].stage == "cancelled"
    assert process._queue.get_nowait() == {"kind": "eof"}


def test_trace_change_inside_request_is_rejected(monkeypatch):
    first = event()
    second = {**event("starting"), "trace_id": "other-trace"}
    process = worker(monkeypatch, [{"id": "wrk_1", "kind": "progress", "event": item} for item in (first, second)])
    observed = []
    with pytest.raises(RuntimeError, match="trace changed"):
        process.request("exec", {"operation": "rd.remote.connect"}, frame_sink=SimpleNamespace(publish=observed.append))
    assert len(observed) == 1


def native(name="SetFrameEvent", **changes):
    return {"id": "wrk_1", "kind": "native_call", "trace_id": "trace-owned", "name": name, "phase": "enter",
            "ts_ms": 1700000000000, **changes}


def test_native_call_frames_reach_the_daemon_in_memory_without_a_state_write(monkeypatch):
    daemon = object.__new__(DaemonRuntime)
    daemon.state = {"active_operation": {"operation": "rd.remote.connect", "stage": "starting", "trace_id": ""}}
    daemon._state_lock = threading.RLock()
    monkeypatch.setattr(daemon, "_persist_state", lambda: pytest.fail("native-call frames are not persisted per frame"))
    final = {"id": "wrk_1", "ok": True, "result": {"done": True}}
    process = worker(monkeypatch, [native(), native("OpenCapture", phase="exit"), final])
    assert process.request("exec", {"operation": "rd.remote.connect"}, frame_sink=daemon) == final
    active = daemon.state["active_operation"]
    assert active["native_call"] == {"name": "OpenCapture", "phase": "exit", "at_ms": 1700000000000}
    assert active["trace_id"] == "trace-owned"
    assert active["last_progress_ms"] > 0


@pytest.mark.parametrize("change", [{"trace_id": ""}, {"name": ""}, {"phase": "running"}, {"ts_ms": True},
    {"ts_ms": 0}, {"extra": 1}])
def test_invalid_native_call_frame_is_rejected(monkeypatch, change):
    process = worker(monkeypatch, [native(**change)])
    sink = SimpleNamespace(publish=lambda event: pytest.fail("published"),
                           native_call=lambda frame: pytest.fail("invalid frame published"))
    with pytest.raises(RuntimeError, match="native-call frame"):
        process.request("exec", {"operation": "rd.remote.connect"}, frame_sink=sink)


def test_native_call_trace_must_match_the_request_progress_trace(monkeypatch):
    frames = [{"id": "wrk_1", "kind": "progress", "event": event()}, native(trace_id="other-trace")]
    process = worker(monkeypatch, frames)
    with pytest.raises(RuntimeError, match="trace changed"):
        process.request("exec", {"operation": "rd.remote.connect"},
                        frame_sink=SimpleNamespace(publish=lambda event: None, native_call=lambda frame: None))


def test_worker_reports_native_calls_under_the_request_identity(monkeypatch):
    from rdc_tool import native_calls
    monkeypatch.setenv("RDC_TOOL_CONTEXT_ID", "default")
    outputs = []
    async def dispatch(operation, args, *, trace_id, **kwargs):
        def OpenCapture():
            return None
        await native_calls.offload(OpenCapture)
        return {"ok": True, "meta": {"trace_id": trace_id}}
    async def shutdown(**kwargs):
        return None
    monkeypatch.setattr(runtime_dispatch, "dispatch_operation", dispatch)
    monkeypatch.setattr(runtime_lifecycle, "runtime_shutdown", shutdown)
    requests = [{"id": "call", "method": "exec", "params": {"operation": "rd.capture.open_replay", "trace_id": "trc_daemon"}},
                {"id": "stop", "method": "shutdown"}]
    monkeypatch.setattr(worker_main.sys, "stdin", io.StringIO("\n".join(json.dumps(item) for item in requests)))
    monkeypatch.setattr(worker_main, "_emit", outputs.append)
    assert worker_main.main(["--context-id", "native-frames"]) == 0
    frame = next(item for item in outputs if item.get("kind") == "native_call")
    assert frame == {"id": "call", "kind": "native_call", "trace_id": "trc_daemon", "name": "OpenCapture",
                     "phase": "enter", "ts_ms": frame["ts_ms"]}
    final = next(item for item in outputs if item.get("id") == "call" and "result" in item)
    assert final["result"]["meta"]["trace_id"] == "trc_daemon"
