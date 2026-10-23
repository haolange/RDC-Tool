from __future__ import annotations

import copy
from types import SimpleNamespace

import pytest

from rdc_tool.daemon import server as daemon_server


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
    worker = SimpleNamespace(request=request, stop=lambda: stops.append(True))
    daemon = object.__new__(daemon_server.DaemonRuntime)
    daemon.daemon_context = "owned-context"
    monkeypatch.setattr(daemon, "_ensure_worker", lambda: worker)
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


@pytest.mark.parametrize("existing_worker", [False, True])
def test_new_worker_marks_persisted_replay_for_controlled_recovery(monkeypatch, existing_worker):
    saved, started = [], []
    state = {"sessions": {"owned": {"session_id": "owned", "capture_file_id": "capture-a", "is_live": True,
        "recovery": {"status": "ready"}, "shader_replacements": [{"replacement_id": "owned-patch"}]}},
        "captures": {"capture-a": {"file_path": "owned.rdc"}}}
    worker = SimpleNamespace(is_running=lambda: False, ensure_started=lambda: started.append(True))
    daemon = object.__new__(daemon_server.DaemonRuntime)
    daemon.daemon_context = "owned-context"
    daemon._worker = worker if existing_worker else None
    monkeypatch.setattr(daemon_server, "RuntimeWorkerProcess", lambda **kwargs: worker)
    monkeypatch.setattr(daemon_server, "load_context_state", lambda context: copy.deepcopy(state))
    monkeypatch.setattr(daemon_server, "save_context_state", lambda value, context: saved.append(copy.deepcopy(value)))
    assert daemon._ensure_worker() is worker
    assert started == [True]
    assert len(saved) == 1
    record = saved[0]["sessions"]["owned"]
    assert record["recovery"]["status"] == "requires_restart"
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
