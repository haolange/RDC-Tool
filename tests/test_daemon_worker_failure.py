from __future__ import annotations

import copy
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from rdc_tool.daemon import server as daemon_server
from rdc_tool.daemon import worker as daemon_worker
from rdc_tool.daemon.worker import WorkerFailure
from rdc_tool.platform import host, process
from rdc_tool.platform.ipc import Endpoint
from rdc_tool.platform.process import Liveness, ProcessIdentity

FAKES = Path(__file__).resolve().parent / "fakes"


def _bare_daemon(context: str = "owned-context") -> daemon_server.DaemonRuntime:
    daemon = object.__new__(daemon_server.DaemonRuntime)
    daemon.daemon_context = context
    daemon.state = {"worker_lifecycle": [], "active_operation": {}}
    daemon._state_lock = threading.Lock()
    return daemon


@pytest.mark.parametrize("method", ["exec", "clear_context"])
@pytest.mark.parametrize("failure, code, reason", [
    ("lost", "worker_lost", "worker_exited"),
    ("error_reply", "worker_request_failed", "worker_error"),
    ("daemon_side", "worker_request_failed", "daemon_error"),
])
def test_worker_request_failure_is_not_replayed(monkeypatch, method, failure, code, reason):
    calls = []
    stops = []
    saved = []
    state = {"sessions": {"session-a": {"capture_file_id": "capture-a", "is_live": True,
        "recovery": {"status": "ready"}, "shader_replacements": [{"replacement_id": "patch-a"}]},
        "session-b": {"capture_file_id": "capture-b", "is_live": True, "recovery": {"status": "ready"}}}}
    identity = ProcessIdentity(123, 'worker-birth')
    def request(*args, **kwargs):
        calls.append((args, kwargs))
        if failure == "lost":
            raise WorkerFailure("worker_lost", "worker_exited", "Worker exited before replying", worker=identity,
                                stack_log={"path": "worker.log", "tail": "Fatal Python error: Segmentation fault"},
                                trace_id="trc_owned")
        if failure == "error_reply":
            return {"ok": False, "error": {"message": "unexpected worker exception"}}
        raise TimeoutError("reply lost after native execution")
    worker = SimpleNamespace(request=request, stop=lambda: stops.append(True), log_path="worker.log",
                             previous_identity=lambda: identity)
    daemon = _bare_daemon()
    monkeypatch.setattr(daemon, "_ensure_worker", lambda: worker)
    monkeypatch.setattr(daemon_server.process, "probe", lambda identity: Liveness.EXITED)
    monkeypatch.setattr(daemon_server, "load_context_state", lambda context: copy.deepcopy(state))
    monkeypatch.setattr(daemon_server, "save_context_state", lambda value, context: saved.append((copy.deepcopy(value), context)), raising=False)
    with pytest.raises(WorkerFailure) as raised:
        daemon._request_worker(method, {"operation": "rd.shader.revert_replacement", "request_id": "req-owned",
                                        "trace_id": "trc_owned"}, no_progress_s=1)
    assert (raised.value.code, raised.value.reason) == (code, reason)
    assert raised.value.exit_confirmed is True
    assert raised.value.replay_requires_restart is True
    assert len(calls) == 1
    assert stops == [True]
    assert len(saved) == 1
    changed, context = saved[0]
    assert context == "owned-context"
    assert changed["recovery"]["status"] == "degraded"
    assert changed["recovery"]["degraded_session_ids"] == ["session-a", "session-b"]
    assert changed["recovery"]["recovered_session_ids"] == []
    assert changed["sessions"]["session-a"]["shader_replacements"] == [{"replacement_id": "patch-a"}]
    for record in changed["sessions"].values():
        assert record["recovery"]["status"] == "requires_restart"
        worker_exit = record["recovery"]["worker_exit"]
        assert (worker_exit["pid"], worker_exit["birth"], worker_exit["reason"]) == (123, "worker-birth", reason)
        assert (worker_exit["trace_id"], worker_exit["request_id"]) == ("trc_owned", "req-owned")
        assert worker_exit["stack_log"]["path"] == "worker.log"
        assert record["is_live"] is False
    assert state["sessions"]["session-a"]["recovery"]["status"] == "ready"
    exited = daemon.state["worker_lifecycle"][-1]
    assert (exited["event"], exited["reason"], exited["code"], exited["exit_confirmed"]) == ("exited", reason, code, True)
    assert (exited["pid"], exited["start_generation"], exited["request_id"]) == (123, "worker-birth", "req-owned")


def test_unconfirmed_exit_keeps_no_worker_exit_receipt(monkeypatch):
    saved = []
    state = {"sessions": {"owned": {"session_id": "owned", "is_live": True, "recovery": {"status": "ready"}}}}
    identity = ProcessIdentity(123, "worker-birth")
    def request(*args, **kwargs):
        raise WorkerFailure("worker_stuck", "no_progress", "silent", worker=identity, stack_log={"path": "w.log"})
    worker = SimpleNamespace(request=request, stop=lambda: None, log_path="w.log", previous_identity=lambda: identity)
    daemon = _bare_daemon()
    monkeypatch.setattr(daemon, "_ensure_worker", lambda: worker)
    monkeypatch.setattr(daemon_server.process, "probe", lambda identity: Liveness.UNKNOWN)
    monkeypatch.setattr(daemon_server, "load_context_state", lambda context: copy.deepcopy(state))
    monkeypatch.setattr(daemon_server, "save_context_state", lambda value, context: saved.append(copy.deepcopy(value)))
    with pytest.raises(WorkerFailure) as raised:
        daemon._request_worker("exec", {"operation": "rd.debug.run_to"}, no_progress_s=1)
    assert raised.value.exit_confirmed is False
    record = saved[0]["sessions"]["owned"]
    assert record["recovery"]["status"] == "requires_restart"
    assert record["recovery"]["worker_exit"] is None


def test_worker_request_success_keeps_state_and_controller(monkeypatch):
    response = {"ok": True, "result": {"reverted": True}}
    calls = []
    def request(*args, **kwargs):
        calls.append((args, kwargs))
        return response
    worker = SimpleNamespace(request=request,
        stop=lambda: pytest.fail("successful worker must not stop"))
    daemon = object.__new__(daemon_server.DaemonRuntime)
    monkeypatch.setattr(daemon, "_ensure_worker", lambda: worker)
    monkeypatch.setattr(daemon_server, "load_context_state", lambda *args: pytest.fail("success must not quarantine"))
    assert daemon._request_worker("exec", {"operation": "rd.shader.revert_replacement"}, no_progress_s=1) == response
    assert len(calls) == 1
    assert calls[0][1]["frame_sink"] is daemon


@pytest.mark.parametrize("code, reason", [("worker_stuck", "no_progress"), ("worker_lost", "worker_exited"),
                                          ("worker_request_failed", "invalid_frame")])
def test_exec_failure_is_one_canonical_operation_error(monkeypatch, code, reason):
    daemon = daemon_server.DaemonRuntime(endpoint=Endpoint("fixture"), token="fixture", daemon_context="owned-context")
    monkeypatch.setattr(daemon, "_persist_state", lambda: None)
    monkeypatch.setattr(daemon, "_refresh_state_from_runtime_locked", lambda: None)

    def request_worker(method, params, *, no_progress_s, frames):
        with daemon._state_lock:
            daemon.state["active_operation"].update(stage="opening", native_call={"name": "OpenCapture", "phase": "enter",
                                                                                   "at_ms": 1700000000000})
        failure = WorkerFailure(code, reason, "worker failed", worker=ProcessIdentity(321, "birth-321"),
                                exit_confirmed=True, stack_log={"path": "/logs/worker.log", "tail": "Timeout (0:00:27)!"},
                                trace_id=params["trace_id"])
        failure.replay_requires_restart = True
        raise failure

    monkeypatch.setattr(daemon, "_request_worker", request_worker)
    channel = daemon_server._ClientChannel(None, "req-owned", stream=False)
    response = daemon._run_exec("rd.capture.open_replay", {}, transport="cli", remote=False, request_id="req-owned",
                                no_progress_ms=45000, channel=channel)
    assert response["ok"] is True
    envelope = response["result"]
    assert (envelope["result_kind"], envelope["ok"]) == ("rd.capture.open_replay", False)
    assert (envelope["error"]["code"], envelope["error"]["category"]) == (code, "runtime")
    details = envelope["error"]["details"]
    assert details == {
        "failure_stage": "worker_exec", "reason": reason, "outcome": "unknown",
        "worker": {"pid": 321, "start_generation": "birth-321"}, "worker_exit_confirmed": True,
        "replay_requires_restart": True, "stack_log": {"path": "/logs/worker.log", "tail": "Timeout (0:00:27)!"},
        "trace_id": details["trace_id"], "request_id": "req-owned",
        "last_progress": {"stage": "opening", "native_call": {"name": "OpenCapture", "phase": "enter", "at_ms": 1700000000000},
                          "at_ms": details["last_progress"]["at_ms"]},
        "no_progress_ms": 45000,
    }
    assert details["trace_id"].startswith("trc_") and envelope["meta"]["trace_id"] == details["trace_id"]
    assert daemon.state["active_operation"] == {}


def test_worker_lifecycle_history_is_bounded():
    daemon = _bare_daemon()
    for index in range(daemon_server.WORKER_LIFECYCLE_LIMIT + 4):
        daemon._record_worker_lifecycle("started", ProcessIdentity(index + 1, f"birth-{index}"))
    history = daemon.state["worker_lifecycle"]
    assert len(history) == daemon_server.WORKER_LIFECYCLE_LIMIT
    assert history[0]["pid"] == 5 and history[-1]["pid"] == daemon_server.WORKER_LIFECYCLE_LIMIT + 4


@pytest.mark.parametrize("existing_worker", [False, True])
def test_new_worker_marks_persisted_replay_for_controlled_recovery(monkeypatch, existing_worker):
    saved, started = [], []
    state = {"sessions": {"owned": {"session_id": "owned", "capture_file_id": "capture-a", "is_live": True,
        "recovery": {"status": "ready"}, "shader_replacements": [{"replacement_id": "owned-patch"}]}},
        "captures": {"capture-a": {"file_path": "owned.rdc"}}}
    identities = [ProcessIdentity(123, 'worker-birth')]
    worker = SimpleNamespace(is_running=lambda: False,
                             ensure_started=lambda: started.append(True) or identities.append(ProcessIdentity(456, "new")),
                             previous_identity=lambda: identities[-1])
    daemon = _bare_daemon()
    daemon._worker = worker if existing_worker else None
    monkeypatch.setattr(daemon_server, "RuntimeWorkerProcess", lambda **kwargs: worker)
    monkeypatch.setattr(daemon_server.process, "probe", lambda identity: Liveness.EXITED)
    monkeypatch.setattr(daemon_server, "load_context_state", lambda context: copy.deepcopy(state))
    monkeypatch.setattr(daemon_server, "save_context_state", lambda value, context: saved.append(copy.deepcopy(value)))
    assert daemon._ensure_worker() is worker
    assert started == [True]
    assert len(saved) == 1
    record = saved[0]["sessions"]["owned"]
    assert record["recovery"]["status"] == "requires_restart"
    assert record["recovery"]["worker_exit"]["pid"] == 123
    assert record["recovery"]["worker_exit"]["birth"] == "worker-birth"
    assert record["recovery"]["worker_exit"]["reason"] == "previous_worker_exited"
    assert record["is_live"] is False
    assert record["shader_replacements"] == [{"replacement_id": "owned-patch"}]
    assert saved[0]["captures"] == state["captures"]
    assert saved[0]["recovery"]["deferred_session_ids"] == []
    assert state["sessions"]["owned"]["is_live"] is True
    assert daemon.state["worker_lifecycle"][-1]["event"] == "started"
    assert daemon.state["worker_lifecycle"][-1]["pid"] == 456


def test_live_worker_is_not_reclassified_on_normal_request(monkeypatch):
    worker = SimpleNamespace(is_running=lambda: True, ensure_started=lambda: None)
    daemon = _bare_daemon()
    daemon._worker = worker
    monkeypatch.setattr(daemon_server, "load_context_state", lambda context: pytest.fail("live worker must retain its controller"))
    assert daemon._ensure_worker() is worker


@pytest.mark.parametrize('liveness', [Liveness.ALIVE, Liveness.UNKNOWN])
def test_unconfirmed_previous_worker_is_not_replaced(monkeypatch, liveness):
    worker = SimpleNamespace(is_running=lambda: False, previous_identity=lambda: ProcessIdentity(123, 'worker-birth'),
                             ensure_started=lambda: pytest.fail('must not start replacement'))
    daemon = _bare_daemon()
    daemon._worker = worker
    monkeypatch.setattr(daemon_server.process, 'probe', lambda identity: liveness)
    with pytest.raises(RuntimeError, match='Previous worker identity'):
        daemon._ensure_worker()


def test_worker_exit_identity_survives_persistent_state_roundtrip(monkeypatch, tmp_path):
    from rdc_tool.runtime_state import load_context_state, save_context_state
    monkeypatch.setenv('RDC_TOOL_INTERMEDIATE_ROOT', str(tmp_path))
    state = {'sessions': {'owned': {'session_id': 'owned', 'backend_type': 'remote', 'is_live': True}},
             'captures': {}}
    save_context_state(state, 'owned-context')
    daemon = _bare_daemon()
    assert daemon._mark_replay_requires_restart('worker exited', ProcessIdentity(123, 'worker-birth'), reason='no_progress',
                                                trace_id='trc_1', request_id='req_1',
                                                stack_log={'path': '/w.log', 'tail': 'x' * 5000}) is True
    record = load_context_state('owned-context')['sessions']['owned']
    worker_exit = record['recovery']['worker_exit']
    assert {key: worker_exit[key] for key in ('pid', 'birth', 'reason', 'trace_id', 'request_id')} == {
        'pid': 123, 'birth': 'worker-birth', 'reason': 'no_progress', 'trace_id': 'trc_1', 'request_id': 'req_1'}
    assert worker_exit['stack_log'] == {'path': '/w.log', 'tail': 'x' * 2048}
    assert record['state'] == 'degraded'
    assert record['is_live'] is False


def test_daemon_clear_preserves_registration_when_worker_reports_cleanup_failure(monkeypatch):
    daemon = daemon_server.DaemonRuntime(endpoint=Endpoint('fixture-endpoint'), token='fixture-token', daemon_context='owned')
    daemon.state['session_id'] = 'session-owned'
    monkeypatch.setattr(daemon, '_persist_state', lambda: None)
    monkeypatch.setattr(daemon, '_refresh_state_from_runtime_locked', lambda: None)
    monkeypatch.setattr(daemon, '_request_worker', lambda *a, **k: {'ok': True, 'result': {
        'ok': False, 'error': {'code': 'context_cleanup_failed', 'message': 'remote release unconfirmed'}}})
    result = daemon._run_clear_context()
    assert not result['ok']
    assert result['error']['code'] == 'context_cleanup_failed'
    assert daemon.state['session_id'] == 'session-owned'


@pytest.mark.skipif(host.IS_WINDOWS, reason="the descendant walk and /proc identities are POSIX")
def test_worker_blocked_while_holding_the_gil_is_dumped_killed_and_quarantined(monkeypatch):
    """A real worker subprocess whose operation never releases the GIL.

    No Python thread in it can run, yet faulthandler's C thread dumps every
    stack before the daemon watchdog fires; the daemon then kills the worker
    tree, confirms the exit, quarantines replay and returns one structured error.
    """
    from rdc_tool.runtime_state import load_context_state, save_context_state
    context = "gil-holding-worker"
    save_context_state({"sessions": {"owned": {"session_id": "owned", "is_live": True}}, "captures": {}}, context)
    monkeypatch.setattr(daemon_worker, "child_python_argv",
                        lambda module, *args: [sys.executable, str(FAKES / "gil_holding_worker.py"), *args])
    monkeypatch.setattr(daemon_worker, "native_manifest_status", lambda root: {"status": "absent"})
    daemon = daemon_server.DaemonRuntime(endpoint=Endpoint("fixture"), token="fixture", daemon_context=context)
    monkeypatch.setattr(daemon, "_persist_state", lambda: None)
    channel = daemon_server._ClientChannel(None, "req-gil", stream=False)
    try:
        response = daemon._run_exec("rd.test.block", {}, transport="cli", remote=False, request_id="req-gil",
                                    no_progress_ms=4000, channel=channel)
        envelope = response["result"]
        assert (envelope["result_kind"], envelope["error"]["code"]) == ("rd.test.block", "worker_stuck")
        details = envelope["error"]["details"]
        assert (details["reason"], details["outcome"], details["request_id"]) == ("no_progress", "unknown", "req-gil")
        assert details["worker_exit_confirmed"] is True
        assert details["replay_requires_restart"] is True
        assert details["last_progress"]["stage"] == "blocking"
        assert details["stack_log"]["path"].endswith(f"worker_{context}.log")
        tail = details["stack_log"]["tail"]
        assert tail.startswith("Timeout (")
        assert "gil_holding_worker.py" in tail and "blocking_operation" in tail
        worker = ProcessIdentity(details["worker"]["pid"], details["worker"]["start_generation"])
        assert process.probe(worker) is Liveness.EXITED
        log = Path(details["stack_log"]["path"]).read_text(encoding="utf-8")
        descendant_line = next(line for line in log.splitlines() if line.startswith("descendant "))
        _, pid, birth = descendant_line.split(" ", 2)
        assert process.wait_exit(ProcessIdentity(int(pid), birth), 5)
        worker_exit = load_context_state(context)["sessions"]["owned"]["recovery"]["worker_exit"]
        assert (worker_exit["pid"], worker_exit["reason"], worker_exit["request_id"]) == (worker.pid, "no_progress", "req-gil")
        assert [entry["event"] for entry in daemon.state["worker_lifecycle"]] == ["started", "exited"]
    finally:
        if daemon._worker is not None:
            daemon._worker.stop()
            for path in Path(daemon._worker.log_path).parent.glob(f"worker_{context}.log*"):
                path.unlink(missing_ok=True)
