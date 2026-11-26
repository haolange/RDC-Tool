from __future__ import annotations

import copy
from types import SimpleNamespace

import pytest

from rdc_tool.daemon import server as daemon_server
from rdc_tool.platform.process import Liveness, ProcessIdentity


@pytest.mark.parametrize("method", ["exec", "clear_context"])
@pytest.mark.parametrize("failure", ["lost_reply", "error_reply"])
def test_worker_request_failure_is_not_replayed(monkeypatch, method, failure):
    calls = []
    stops = []
    saved = []
    state = {"sessions": {"session-a": {"capture_file_id": "capture-a", "is_live": True,
        "recovery": {"status": "ready"}, "shader_replacements": [{"replacement_id": "patch-a"}]},
        "session-b": {"capture_file_id": "capture-b", "is_live": True, "recovery": {"status": "ready"}}}}
    def request(*args, **kwargs):
        calls.append((args, kwargs))
        if len(calls) == 1:
            if failure == "lost_reply":
                raise TimeoutError("reply lost after native execution")
            return {"ok": False, "error": {"message": "unexpected worker exception"}}
        return {"ok": True, "result": {"reverted": True}}
    worker = SimpleNamespace(request=request, stop=lambda: stops.append(True),
                             previous_identity=lambda: ProcessIdentity(123, 'worker-birth'))
    daemon = object.__new__(daemon_server.DaemonRuntime)
    daemon.daemon_context = "owned-context"
    monkeypatch.setattr(daemon, "_ensure_worker", lambda: worker)
    monkeypatch.setattr(daemon_server.process, "probe", lambda identity: Liveness.EXITED)
    monkeypatch.setattr(daemon_server, "load_context_state", lambda context: copy.deepcopy(state))
    monkeypatch.setattr(daemon_server, "save_context_state", lambda value, context: saved.append((copy.deepcopy(value), context)), raising=False)
    with pytest.raises(RuntimeError, match="outcome unknown"):
        daemon._request_worker(method, {"operation": "rd.shader.revert_replacement"}, timeout=1)
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
        assert record["recovery"]["worker_exit"] == {"pid": 123, "birth": "worker-birth"}
        assert record["is_live"] is False
    assert state["sessions"]["session-a"]["recovery"]["status"] == "ready"


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
    assert daemon._request_worker("exec", {"operation": "rd.shader.revert_replacement"}) == response
    assert len(calls) == 1
    assert calls[0][1]["frame_sink"] is daemon


@pytest.mark.parametrize("existing_worker", [False, True])
def test_new_worker_marks_persisted_replay_for_controlled_recovery(monkeypatch, existing_worker):
    saved, started = [], []
    state = {"sessions": {"owned": {"session_id": "owned", "capture_file_id": "capture-a", "is_live": True,
        "recovery": {"status": "ready"}, "shader_replacements": [{"replacement_id": "owned-patch"}]}},
        "captures": {"capture-a": {"file_path": "owned.rdc"}}}
    worker = SimpleNamespace(is_running=lambda: False, ensure_started=lambda: started.append(True),
                             previous_identity=lambda: ProcessIdentity(123, 'worker-birth'))
    daemon = object.__new__(daemon_server.DaemonRuntime)
    daemon.daemon_context = "owned-context"
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
    assert record["recovery"]["worker_exit"] == {"pid": 123, "birth": "worker-birth"}
    assert record["is_live"] is False
    assert record["shader_replacements"] == [{"replacement_id": "owned-patch"}]
    assert saved[0]["captures"] == state["captures"]
    assert saved[0]["recovery"]["deferred_session_ids"] == []
    assert state["sessions"]["owned"]["is_live"] is True


def test_live_worker_is_not_reclassified_on_normal_request(monkeypatch):
    worker = SimpleNamespace(is_running=lambda: True, ensure_started=lambda: None)
    daemon = object.__new__(daemon_server.DaemonRuntime)
    daemon.daemon_context = "owned-context"
    daemon._worker = worker
    monkeypatch.setattr(daemon_server, "load_context_state", lambda context: pytest.fail("live worker must retain its controller"))
    assert daemon._ensure_worker() is worker


@pytest.mark.parametrize('liveness', [Liveness.ALIVE, Liveness.UNKNOWN])
def test_unconfirmed_previous_worker_is_not_replaced(monkeypatch, liveness):
    worker = SimpleNamespace(is_running=lambda: False, previous_identity=lambda: ProcessIdentity(123, 'worker-birth'),
                             ensure_started=lambda: pytest.fail('must not start replacement'))
    daemon = object.__new__(daemon_server.DaemonRuntime)
    daemon.daemon_context = 'owned-context'
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
    daemon = object.__new__(daemon_server.DaemonRuntime)
    daemon.daemon_context = 'owned-context'
    daemon._mark_replay_requires_restart('worker exited', ProcessIdentity(123, 'worker-birth'))
    record = load_context_state('owned-context')['sessions']['owned']
    assert record['recovery']['worker_exit'] == {'pid': 123, 'birth': 'worker-birth'}
    assert record['state'] == 'degraded'
    assert record['is_live'] is False


def test_daemon_clear_preserves_registration_when_worker_reports_cleanup_failure(monkeypatch):
    from rdc_tool.platform.ipc import Endpoint
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
