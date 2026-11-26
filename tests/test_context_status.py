"""`context status` is read-only: it never starts a process and never writes state."""
from __future__ import annotations

import json
import os
import subprocess

import pytest

from rdc_tool import cli
from rdc_tool.daemon import client as daemon_client
from rdc_tool.daemon import server as daemon_server
from rdc_tool.daemon.state import state_path
from rdc_tool.io_utils import atomic_write_json
from rdc_tool.platform import process
from rdc_tool.platform.ipc import Endpoint
from rdc_tool.runtime_state import context_state_path, save_context_state
from rdc_tool.runtime_worker_state import worker_state_path

CONTEXT = "status-read-only"
WORKER_EXIT = {"pid": 4242, "birth": "gone", "reason": "no_progress", "trace_id": "trc_dead",
               "request_id": "req-dead", "stack_log": {"path": "/logs/worker.log", "tail": "Timeout (0:04:55)!"}}


@pytest.fixture
def recorded_context():
    save_context_state({
        "current_session_id": "sess-owned", "current_capture_file_id": "cap-owned",
        "captures": {"cap-owned": {"file_path": "/captures/owned.rdc"}},
        "sessions": {"sess-owned": {"session_id": "sess-owned", "capture_file_id": "cap-owned", "is_live": False,
                                    "state": "degraded", "active_event_id": 77,
                                    "recovery": {"status": "requires_restart", "last_error": "worker stuck",
                                                 "worker_exit": WORKER_EXIT}}}}, CONTEXT)
    atomic_write_json(state_path(CONTEXT), {
        "context_id": CONTEXT, "endpoint": "gone-endpoint", "token": "secret-token", "pid": 999999,
        "birth": "linux-start-ticks:gone:1", "started_at": "2026-11-26T00:00:00+00:00",
        "active_operation": {"operation": "rd.debug.run_to", "stage": "stepping", "request_id": "req-dead"},
        "worker_lifecycle": [{"event": "exited", "reason": "no_progress", "pid": 4242}]})
    atomic_write_json(worker_state_path(CONTEXT), {"context_id": CONTEXT, "running": True, "pid": 999998,
                                                    "birth": "linux-start-ticks:gone:2"})
    paths = [state_path(CONTEXT), context_state_path(CONTEXT), worker_state_path(CONTEXT)]
    yield paths
    for path in paths:
        path.unlink(missing_ok=True)


def test_status_without_a_daemon_reads_recorded_state_and_probes_identities(monkeypatch, capsys, recorded_context):
    def no_spawn(*args, **kwargs):
        raise AssertionError("context status must not start a process")
    monkeypatch.setattr(subprocess, "Popen", no_spawn)
    monkeypatch.setattr(daemon_client, "ensure_daemon", no_spawn)
    monkeypatch.setattr(daemon_client, "cleanup_stale_daemon_states", no_spawn)
    before = {path: os.stat(path).st_mtime_ns for path in recorded_context}
    args = cli._build_parser().parse_args(["--daemon-context", CONTEXT, "context", "status", "--json"])
    assert cli._cmd_context_status(args) == cli.EXIT_OK
    payload = json.loads(capsys.readouterr().out)
    assert {path: os.stat(path).st_mtime_ns for path in recorded_context} == before
    assert payload["result_kind"] == "rdc_tool.context.status" and payload["ok"] is True
    data = payload["data"]
    assert data["source"] == "state_files"
    assert data["daemon"]["state"] == "exited" and data["daemon"]["pid"] == 999999
    assert data["worker"]["state"] == "exited" and data["worker"]["pid"] == 999998
    assert data["active_operation"]["request_id"] == "req-dead"
    assert data["worker_lifecycle"] == [{"event": "exited", "reason": "no_progress", "pid": 4242}]
    assert data["session_locator"] == {"rdc_path": "/captures/owned.rdc", "session_id": "sess-owned",
                                       "frame_index": 0, "active_event_id": 77}
    session = data["sessions"][0]
    assert session["recovery"]["requires_restart"] is True
    assert session["recovery"]["worker_exit"] == WORKER_EXIT
    assert "secret-token" not in json.dumps(payload)


def test_daemon_status_neither_writes_state_nor_starts_a_worker(monkeypatch, recorded_context):
    daemon = daemon_server.DaemonRuntime(endpoint=Endpoint("fixture"), token="fixture", daemon_context=CONTEXT)
    monkeypatch.setattr(daemon, "_persist_state", lambda: pytest.fail("context status persisted daemon state"))
    monkeypatch.setattr(daemon, "_ensure_worker", lambda: pytest.fail("context status started a worker"))
    daemon.state["active_operation"] = {"operation": "rd.capture.open_replay", "stage": "opening",
                                        "native_call": {"name": "OpenCapture", "phase": "enter", "at_ms": 1}}
    daemon.state["worker_lifecycle"] = [{"event": "started", "pid": 7}]
    activity = daemon.state["last_activity_at"]
    result = daemon.handle_request({"method": "context_status"})["result"]
    assert daemon.state["last_activity_at"] == activity
    assert result["source"] == "daemon"
    assert result["daemon"] == {"state": "alive", "pid": os.getpid(), "start_generation": process.self_identity().birth,
                                "started_at": daemon.state["started_at"], "last_activity_at": activity}
    assert result["worker"]["state"] == "exited" and result["worker"]["pid"] == 999998
    assert result["active_operation"]["native_call"]["name"] == "OpenCapture"
    assert result["worker_lifecycle"] == [{"event": "started", "pid": 7}]
    assert result["queued_request_ids"] == []
    assert result["sessions"][0]["recovery"]["worker_exit"]["reason"] == "no_progress"


def test_live_daemon_answers_status_through_its_read_only_method(monkeypatch, recorded_context):
    calls = []
    def request(method, **kwargs):
        calls.append(method)
        return {"ok": True, "result": {"source": "daemon", "context_id": CONTEXT}}
    monkeypatch.setattr(daemon_client.process, "is_alive", lambda identity: True)
    monkeypatch.setattr(daemon_client, "daemon_request", request)
    assert daemon_client.read_context_status(CONTEXT) == {"source": "daemon", "context_id": CONTEXT}
    assert calls == ["context_status"]
    # A daemon that cannot answer leaves the recorded view, marked as unreachable.
    monkeypatch.setattr(daemon_client, "daemon_request", lambda method, **kwargs: (_ for _ in ()).throw(OSError("refused")))
    fallback = daemon_client.read_context_status(CONTEXT)
    assert fallback["source"] == "state_files" and fallback["daemon"]["reason"].startswith("daemon_unreachable")


def test_status_of_an_unknown_context_is_empty_and_creates_no_state(monkeypatch, capsys):
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: pytest.fail("context status must not start a process"))
    args = cli._build_parser().parse_args(["--daemon-context", "never-used-context", "context", "status", "--json"])
    assert cli._cmd_context_status(args) == cli.EXIT_OK
    data = json.loads(capsys.readouterr().out)["data"]
    assert data["daemon"]["state"] == "absent" and data["worker"]["state"] == "absent"
    assert data["sessions"] == []
    assert not state_path("never-used-context").exists()
    assert not context_state_path("never-used-context").exists()
