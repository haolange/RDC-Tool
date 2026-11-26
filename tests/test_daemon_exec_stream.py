"""The exec connection: heartbeats, streamed frames and a reply without a fixed deadline."""
from __future__ import annotations

import asyncio
import json
import threading
import time

import pytest

from rdc_tool import cli, timeout_policy
from rdc_tool.daemon import client as daemon_client
from rdc_tool.daemon import server as daemon_server
from rdc_tool.platform.ipc import Endpoint
from rdc_tool.platform.process import Liveness
from rdc_tool.progress import NativeCallFrame, ProgressEvent

STATE = {"endpoint": "fixture-endpoint", "token": "fixture-token", "pid": 4242, "birth": "daemon-birth",
         "context_id": "stream-test"}


class _Conn:
    """A client-side connection that replays scripted daemon messages."""

    def __init__(self, messages, *, delay: float = 0.0) -> None:
        self.messages = list(messages)
        self.sent = []
        self.delay = delay

    def send(self, payload):
        self.sent.append(payload)

    def poll(self, timeout):
        time.sleep(self.delay)
        return bool(self.messages)

    def recv(self):
        item = self.messages.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item

    def close(self):
        pass


def _client(monkeypatch, conn, liveness=Liveness.ALIVE):
    monkeypatch.setattr(daemon_client.ipc, "connect", lambda endpoint, authkey: conn)
    monkeypatch.setattr(daemon_client.process, "probe", lambda identity: liveness)


def test_exec_reply_follows_frames_and_heartbeats(monkeypatch):
    frames = [{"kind": "heartbeat", "request_id": "r1", "ts_ms": 1, "state": "running"},
              {"kind": "native_call", "request_id": "r1", "trace_id": "t", "name": "OpenCapture", "phase": "enter",
               "ts_ms": 2}]
    final = {"ok": True, "result": {"ok": True}}
    conn = _Conn([*frames, final])
    _client(monkeypatch, conn)
    seen = []
    assert daemon_client.daemon_request("exec", params={"operation": "rd.capture.open_replay", "request_id": "r1"},
                                        state=STATE, context="stream-test", on_frame=seen.append) == final
    assert seen == frames
    assert conn.sent == [{"method": "exec", "params": {"operation": "rd.capture.open_replay", "request_id": "r1"}}]


def test_exited_daemon_is_reported_as_lost_with_confirmed_exit(monkeypatch):
    _client(monkeypatch, _Conn([]), Liveness.EXITED)
    with pytest.raises(daemon_client.DaemonExecInterrupted) as raised:
        daemon_client.daemon_request("exec", params={"operation": "rd.texture.get_data", "request_id": "r2"},
                                     state=STATE, context="stream-test")
    assert raised.value.code == "daemon_lost"
    details = raised.value.details
    assert details["reason"] == "daemon_exited"
    assert details["daemon_exit_confirmed"] is True
    assert details["daemon"] == {"pid": 4242, "start_generation": "daemon-birth"}
    assert details["outcome"] == "unknown"
    assert (details["operation"], details["request_id"]) == ("rd.texture.get_data", "r2")


def test_closed_connection_is_reported_as_lost(monkeypatch):
    _client(monkeypatch, _Conn([EOFError("closed")]))
    with pytest.raises(daemon_client.DaemonExecInterrupted) as raised:
        daemon_client.daemon_request("exec", params={"operation": "rd.texture.get_data"}, state=STATE,
                                     context="stream-test")
    assert raised.value.code == "daemon_lost"
    assert raised.value.details["reason"] == "connection_closed"
    assert raised.value.details["daemon_exit_confirmed"] is False


def test_heartbeat_gap_of_a_live_daemon_is_reported_as_unresponsive(monkeypatch):
    monkeypatch.setattr(timeout_policy, "DAEMON_HEARTBEAT_GAP_S", 0.05)
    _client(monkeypatch, _Conn([], delay=0.02))
    with pytest.raises(daemon_client.DaemonExecInterrupted) as raised:
        daemon_client.daemon_request("clear_context", params={}, state=STATE, context="stream-test")
    assert raised.value.code == "daemon_unresponsive"
    assert raised.value.details["reason"] == "heartbeat_gap"
    assert raised.value.details["heartbeat_gap_ms"] >= 50


class _DaemonConn:
    """The daemon side of one client connection."""

    def __init__(self) -> None:
        self.sent = []
        self.replied = threading.Event()

    def send(self, message):
        self.sent.append(message)
        if "kind" not in message:
            self.replied.set()


def _daemon(monkeypatch):
    daemon = daemon_server.DaemonRuntime(endpoint=Endpoint("fixture"), token="fixture", daemon_context="stream-test")
    monkeypatch.setattr(daemon, "_persist_state", lambda: None)
    monkeypatch.setattr(daemon, "_refresh_state_from_runtime_locked", lambda: None)
    return daemon


@pytest.mark.parametrize("stream", [False, True])
def test_daemon_streams_frames_only_on_request_and_replies_last(monkeypatch, stream):
    daemon = _daemon(monkeypatch)
    calls = []

    def request_worker(method, params, *, no_progress_s, frames):
        calls.append((method, params, no_progress_s))
        frames.publish(ProgressEvent(trace_id=params["trace_id"], operation=params["operation"], stage="opening",
                                     message="Opening"))
        frames.native_call(NativeCallFrame(params["trace_id"], "OpenCapture", "enter", 1700000000000))
        return {"ok": True, "result": {"ok": True, "meta": {"trace_id": params["trace_id"]}}}

    monkeypatch.setattr(daemon, "_request_worker", request_worker)
    conn = _DaemonConn()
    daemon._serve_exec(conn, {"operation": "rd.capture.open_replay", "args": {}, "request_id": "req-1",
                              "no_progress_ms": 45000, "stream": stream})
    method, params, no_progress_s = calls[0]
    assert method == "exec"
    assert (params["request_id"], params["no_progress_ms"]) == ("req-1", 45000)
    assert params["trace_id"].startswith("trc_")
    assert no_progress_s == timeout_policy.watchdog_s(45000)
    assert conn.sent[0]["kind"] == "heartbeat" and conn.sent[0]["request_id"] == "req-1"
    assert conn.sent[-1] == {"ok": True, "result": {"ok": True, "meta": {"trace_id": params["trace_id"]}}}
    streamed = [message for message in conn.sent if message.get("kind") in {"progress", "native_call"}]
    if not stream:
        assert streamed == []
        return
    assert streamed == [
        {"kind": "progress", "request_id": "req-1", "trace_id": params["trace_id"], "operation": "rd.capture.open_replay",
         "stage": "opening", "message": "Opening", "progress_pct": None, "details": {}, "ts_ms": streamed[0]["ts_ms"]},
        {"kind": "native_call", "request_id": "req-1", "trace_id": params["trace_id"], "name": "OpenCapture",
         "phase": "enter", "ts_ms": 1700000000000},
    ]
    assert daemon.state["active_operation"] == {}


def test_daemon_rejects_an_invalid_budget_and_a_duplicate_request_before_running(monkeypatch):
    daemon = _daemon(monkeypatch)
    monkeypatch.setattr(daemon, "_request_worker", lambda *a, **k: pytest.fail("rejected request ran"))
    invalid = _DaemonConn()
    daemon._serve_exec(invalid, {"operation": "rd.core.get_version", "no_progress_ms": 10})
    assert invalid.sent == [{"ok": False, "error": {"code": "invalid_no_progress_ms", "category": "validation",
                                                    "message": invalid.sent[0]["error"]["message"],
                                                    "details": invalid.sent[0]["error"]["details"]}}]
    daemon._requests["req-dup"] = object()
    duplicate = _DaemonConn()
    daemon._serve_exec(duplicate, {"operation": "rd.core.get_version", "request_id": "req-dup"})
    assert duplicate.sent[0]["error"]["code"] == "request_id_conflict"


def test_queued_exec_heartbeats_until_it_runs(monkeypatch):
    monkeypatch.setattr(timeout_policy, "DAEMON_HEARTBEAT_INTERVAL_S", 0.02)
    monkeypatch.setattr(timeout_policy, "EXEC_LOCK_SLICE_S", 0.02)
    daemon = _daemon(monkeypatch)
    monkeypatch.setattr(daemon, "_request_worker", lambda *a, **k: {"ok": True, "result": {"ok": True}})
    conn = _DaemonConn()
    daemon._exec_lock.acquire()
    worker = threading.Thread(target=daemon._serve_exec, args=(conn, {"operation": "rd.core.get_version",
                                                                      "request_id": "queued"}))
    worker.start()
    time.sleep(0.15)
    assert not conn.replied.is_set()
    queued = [message for message in list(conn.sent) if message.get("kind") == "heartbeat"]
    assert len(queued) >= 3 and {message["state"] for message in queued} == {"queued"}
    daemon._exec_lock.release()
    assert conn.replied.wait(2)
    worker.join(2)
    assert conn.sent[-1] == {"ok": True, "result": {"ok": True}}


def test_cli_progress_stream_writes_frames_to_stderr_and_the_envelope_to_stdout(monkeypatch, capsys):
    frame = {"kind": "progress", "request_id": "req-cli", "trace_id": "t", "operation": "rd.core.get_version",
             "stage": "s", "message": "m", "progress_pct": None, "details": {}, "ts_ms": 1}
    envelope = {"ok": True, "result_kind": "rd.core.get_version", "data": {}}
    captured = {}

    def request(method, *, params, context, state, on_frame):
        captured.update(params)
        on_frame(frame)
        on_frame({"kind": "heartbeat", "request_id": "req-cli", "ts_ms": 2, "state": "running"})
        return {"ok": True, "result": envelope}

    monkeypatch.setattr(cli, "daemon_request", request)
    monkeypatch.setattr(cli, "_ensure_daemon_state", lambda context: dict(STATE))
    args = cli._build_parser().parse_args(["call", "rd.core.get_version", "--request-id", "req-cli",
                                           "--no-progress-ms", "60000", "--progress-stream"])
    assert asyncio.run(cli._cmd_call(args)) == cli.EXIT_OK
    out, err = capsys.readouterr()
    assert json.loads(out) == envelope
    assert [json.loads(line) for line in err.splitlines()] == [
        frame, {"kind": "heartbeat", "request_id": "req-cli", "ts_ms": 2, "state": "running"}]
    assert (captured["request_id"], captured["no_progress_ms"], captured["stream"]) == ("req-cli", 60000, True)
