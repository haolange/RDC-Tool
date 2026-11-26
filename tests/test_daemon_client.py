from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pytest

from rdc_tool import cli
from rdc_tool.context_snapshot import normalize_context_id
from rdc_tool.daemon import client as daemon_client
from rdc_tool.daemon import state as daemon_state
from rdc_tool.runtime_paths import cli_runtime_dir


def test_idle_daemon_retains_context_with_owned_replay_or_remote(monkeypatch, tmp_path: Path) -> None:
    from rdc_tool.context_snapshot import save_context_snapshot
    from rdc_tool.daemon.client import context_has_unreleased_resources
    from rdc_tool.runtime_state import save_context_state

    monkeypatch.setenv("RDC_TOOL_INTERMEDIATE_ROOT", str(tmp_path / "intermediate"))
    context = "ctx-idle-owner"
    assert context_has_unreleased_resources(context) is False

    save_context_state({"sessions": {"sess-owned": {"session_id": "sess-owned", "backend_type": "remote"}}}, context)
    assert context_has_unreleased_resources(context) is True

    save_context_state({}, context)
    save_context_snapshot({"remote": {"state": "live_handle", "remote_id": "remote-owned"}}, context)
    assert context_has_unreleased_resources(context) is True

    save_context_snapshot({}, context)
    assert context_has_unreleased_resources(context) is False


def _configure_runtime_dir(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("RDC_TOOL_INTERMEDIATE_ROOT", str(tmp_path))
    cli_runtime_dir().mkdir(parents=True, exist_ok=True)


def _configure_context_artifact_paths(monkeypatch, tmp_path: Path) -> Path:
    state_dir = cli_runtime_dir()
    state_dir.mkdir(parents=True, exist_ok=True)

    def _ctx_path(prefix: str, suffix: str, context: str = "default") -> Path:
        ctx = normalize_context_id(context)
        if ctx == "default":
            return state_dir / f"{prefix}{suffix}"
        token = "".join(ch if ch.isalnum() or ch in ("-", "_", ".") else "_" for ch in ctx)
        return state_dir / f"{prefix}_{token}{suffix}"

    monkeypatch.setattr(daemon_client, "context_state_path", lambda context="default": _ctx_path("runtime_state", ".json", context))
    monkeypatch.setattr(daemon_client, "context_snapshot_path", lambda context="default": _ctx_path("context_snapshot", ".json", context))
    monkeypatch.setattr(daemon_client, "context_log_path", lambda context="default": _ctx_path("runtime_logs", ".jsonl", context))
    monkeypatch.setattr(daemon_client, "worker_state_path", lambda context="default": _ctx_path("worker_state", ".json", context))
    return state_dir


def _legacy_state(context: str) -> dict:
    return {"context_id": context, "daemon_context": context, "pid": 101, "owner_pid": 102,
            "worker": {"pid": 103, "running": True}, "pipe_name": "fixture-pipe", "token": "fixture-secret",
            "session_count": 0, "capture_count": 0, "session_id": "", "capture_file_id": "",
            "active_request_count": 0, "active_operation": {}, "attached_clients": [], "backend": "local"}


def test_capacity_retires_only_proven_inactive_legacy_state(monkeypatch, tmp_path: Path) -> None:
    from rdc_tool.platform.process import Liveness
    _configure_runtime_dir(monkeypatch, tmp_path)
    context = "old-inactive"
    path = daemon_client.state_path(context)
    path.write_text(json.dumps(_legacy_state(context)), encoding="utf-8")
    monkeypatch.setattr(daemon_client.process, "probe", lambda identity: Liveness.EXITED)
    assert context not in daemon_client.list_occupying_context_ids()
    assert not path.exists()


@pytest.mark.parametrize("obstruction", ["live", "unknown", "resources", "bad_worker", "wrong_context", "corrupt"])
def test_capacity_preserves_unverifiable_legacy_state(monkeypatch, tmp_path: Path, obstruction: str) -> None:
    from rdc_tool.daemon.ownership import DaemonOwnerUnavailable
    from rdc_tool.platform.process import Liveness
    _configure_runtime_dir(monkeypatch, tmp_path)
    context = "old-uncertain"
    path = daemon_client.state_path(context)
    payload = _legacy_state(context)
    if obstruction == "resources":
        payload["capture_count"] = 1
    if obstruction == "bad_worker":
        payload["worker"] = {"running": True}
    if obstruction == "wrong_context":
        payload["context_id"] = "another-context"
    path.write_text("{" if obstruction == "corrupt" else json.dumps(payload), encoding="utf-8")
    before = path.read_bytes()
    monkeypatch.setattr(daemon_client.process, "probe", lambda identity:
        Liveness.ALIVE if obstruction == "live" else Liveness.UNKNOWN if obstruction == "unknown" else Liveness.EXITED)
    with pytest.raises(DaemonOwnerUnavailable) as exc:
        daemon_client.list_occupying_context_ids()
    assert "fixture-secret" not in str(exc.value)
    assert path.read_bytes() == before


def test_capacity_preserves_legacy_snapshot_with_remote_ownership(monkeypatch, tmp_path: Path) -> None:
    from rdc_tool.context_snapshot import save_context_snapshot
    from rdc_tool.daemon.ownership import DaemonOwnerUnavailable
    from rdc_tool.platform.process import Liveness
    _configure_runtime_dir(monkeypatch, tmp_path)
    context = 'old-owned-remote'
    path = daemon_client.state_path(context)
    path.write_text(json.dumps(_legacy_state(context)), encoding='utf-8')
    save_context_snapshot({'remote': {'state': 'live_handle', 'remote_id': 'owned'}}, context)
    monkeypatch.setattr(daemon_client.process, 'probe', lambda identity: Liveness.EXITED)
    with pytest.raises(DaemonOwnerUnavailable, match='resources_unconfirmed'):
        daemon_client.list_occupying_context_ids()
    assert path.is_file()


@pytest.mark.parametrize('kind', ['dangling_session', 'live_preview'])
def test_capacity_preserves_inconsistent_or_active_legacy_records(monkeypatch, tmp_path: Path, kind: str) -> None:
    from rdc_tool.daemon.ownership import DaemonOwnerUnavailable
    from rdc_tool.platform.process import Liveness
    _configure_runtime_dir(monkeypatch, tmp_path)
    context = 'old-inconsistent'
    path = daemon_client.state_path(context)
    path.write_text(json.dumps(_legacy_state(context)), encoding='utf-8')
    runtime = {'context_id': context, 'sessions': {}, 'captures': {},
               'current_session_id': 'unknown-session' if kind == 'dangling_session' else '',
               'preview': {'enabled': kind == 'live_preview'}}
    daemon_client.context_state_path(context).write_text(json.dumps(runtime), encoding='utf-8')
    monkeypatch.setattr(daemon_client.process, 'probe', lambda identity: Liveness.EXITED)
    with pytest.raises(DaemonOwnerUnavailable, match='resources_unconfirmed'):
        daemon_client.list_occupying_context_ids()
    assert path.is_file()


def test_capacity_never_retires_legacy_state_with_busy_owner(monkeypatch, tmp_path: Path) -> None:
    from rdc_tool.daemon.ownership import OwnerLease
    _configure_runtime_dir(monkeypatch, tmp_path)
    context = 'old-busy'
    path = daemon_client.state_path(context)
    path.write_text(json.dumps(_legacy_state(context)), encoding='utf-8')
    lease = OwnerLease(path, context)
    try:
        assert context in daemon_client.list_occupying_context_ids()
        assert path.is_file()
    finally:
        lease.close()


def test_cleanup_stale_daemon_state_removes_dead_pid(monkeypatch, tmp_path: Path) -> None:
    _configure_runtime_dir(monkeypatch, tmp_path)

    state_path = cli_runtime_dir() / "daemon_state_dead.json"
    state_path.write_text(
        json.dumps(
            {
                "context_id": "dead",
                "endpoint": "pipe-dead",
                "token": "token-dead",
                "pid": 99999,
                "started_at": "2026-03-06T00:00:00+00:00",
                "last_activity_at": "2026-03-06T00:00:00+00:00",
                "owner_pid": 0,
                "lease_timeout_seconds": 120,
                "idle_timeout_seconds": 900,
                "attached_clients": [],
            },
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(daemon_client.process, "is_alive", lambda identity: False)

    cleaned = daemon_client.cleanup_stale_daemon_states()

    assert "daemon_state_dead.json" in cleaned["state_files"]
    assert not state_path.exists()


@pytest.mark.parametrize("worker_alive", [True, False])
def test_dead_daemon_replacement_waits_for_recorded_worker_exit(monkeypatch, tmp_path: Path, worker_alive: bool) -> None:
    _configure_runtime_dir(monkeypatch, tmp_path)
    _configure_context_artifact_paths(monkeypatch, tmp_path)
    context = "dead-daemon-worker"
    daemon_state.save_state({
        "pid": 100, "endpoint": "isolated", "token": "test",
        "worker": {"pid": 200, "running": True},
    }, context)
    state_path = daemon_client.state_path(context)
    state_bytes = state_path.read_bytes()
    monkeypatch.setattr(daemon_client.process, "is_alive", lambda identity: worker_alive and identity.pid == 200)
    monkeypatch.setattr(daemon_client.process, "kill_tree", lambda identity: False)
    monkeypatch.setattr(daemon_client.process, "wait_exit", lambda *args, **kwargs: False)
    monkeypatch.setattr(daemon_client, "owner_is_busy", lambda *args: False)
    def spawn(*args, **kwargs):
        if worker_alive:
            pytest.fail("replacement must not spawn while the old worker is live")
        raise RuntimeError("replacement_spawn_permitted")
    monkeypatch.setattr(daemon_client.subprocess, "Popen", spawn)
    if worker_alive:
        with pytest.raises(daemon_client.DaemonOwnerUnavailable) as exc:
            daemon_client.ensure_daemon(context=context)
        assert exc.value.code == "daemon_owner_unavailable"
        assert exc.value.details["reason"] == "worker_exit_unconfirmed"
        assert state_path.read_bytes() == state_bytes
    else:
        # A nonzero PID in the receipt does not block replacement once that
        # process is confirmed gone. This intercepts spawning before execution.
        with pytest.raises(RuntimeError, match="replacement_spawn_permitted"):
            daemon_client.ensure_daemon(context=context)
        assert not state_path.exists()


def test_dead_daemon_replacement_preserves_state_retained_by_cleanup(monkeypatch, tmp_path: Path) -> None:
    _configure_runtime_dir(monkeypatch, tmp_path)
    context = "retained-owner"
    daemon_state.save_state({"pid": 100, "endpoint": "isolated", "token": "test"}, context)
    state_path = daemon_client.state_path(context)
    state_bytes = state_path.read_bytes()
    monkeypatch.setattr(daemon_client.process, "is_alive", lambda identity: False)
    monkeypatch.setattr(daemon_client, "owner_is_busy", lambda *args: False)
    monkeypatch.setattr(daemon_client, "cleanup_stale_daemon_states", lambda context=None: {})
    monkeypatch.setattr(daemon_client.subprocess, "Popen", lambda *a, **kw: pytest.fail("retained owner must not be replaced"))
    with pytest.raises(daemon_client.DaemonOwnerUnavailable, match="owner_exit_unconfirmed"):
        daemon_client.ensure_daemon(context=context)
    assert state_path.read_bytes() == state_bytes


def test_clear_context_without_daemon_clears_context_files(monkeypatch, tmp_path: Path) -> None:
    _configure_runtime_dir(monkeypatch, tmp_path)

    ok, message, details = daemon_client.clear_context("ctx-x")

    assert ok is True
    assert "context cleared" in message
    assert details["state"] == {}



def test_cleanup_stale_daemon_state_skips_invalid_json(monkeypatch, tmp_path: Path) -> None:
    _configure_runtime_dir(monkeypatch, tmp_path)

    state_path = cli_runtime_dir() / "daemon_state_busy.json"
    state_path.write_text('{"context_id":', encoding="utf-8")

    cleaned = daemon_client.cleanup_stale_daemon_states()

    assert cleaned["state_files"] == []
    assert state_path.exists()


def test_cleanup_stale_daemon_states_clears_orphan_context_artifacts(monkeypatch, tmp_path: Path) -> None:
    _configure_runtime_dir(monkeypatch, tmp_path)
    state_dir = _configure_context_artifact_paths(monkeypatch, tmp_path)

    orphan_paths = [
        state_dir / "runtime_state_orphan.json",
        state_dir / "context_snapshot_orphan.json",
        state_dir / "runtime_logs_orphan.jsonl",
        state_dir / "worker_state_orphan.json",
    ]
    for path in orphan_paths:
        path.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(daemon_client, "list_context_ids", lambda: ["orphan"])

    cleaned = daemon_client.cleanup_stale_daemon_states()

    assert "runtime_state_orphan.json" in cleaned["context_files"]
    assert "context_snapshot_orphan.json" in cleaned["snapshot_files"]
    assert "runtime_logs_orphan.jsonl" in cleaned["log_files"]
    assert "worker_state_orphan.json" in cleaned["worker_files"]
    assert all(not path.exists() for path in orphan_paths)


def test_dead_daemon_preserves_unreleased_replay_and_refuses_false_clear(monkeypatch, tmp_path: Path) -> None:
    _configure_runtime_dir(monkeypatch, tmp_path)
    state_dir = _configure_context_artifact_paths(monkeypatch, tmp_path)
    context = "owned"
    daemon_path = state_dir / "daemon_state_owned.json"
    daemon_path.write_text(json.dumps({"context_id": context, "pid": 99999, "endpoint": "dead-owned", "token": "test-nonce"}), encoding="utf-8")
    runtime_path = state_dir / "runtime_state_owned.json"
    runtime_path.write_text(json.dumps({"sessions": {"sess-owned": {"session_id": "sess-owned"}}}), encoding="utf-8")
    snapshot_path = state_dir / "context_snapshot_owned.json"
    snapshot_path.write_text(json.dumps({"remote": {"state": "expired", "remote_id": "remote-owned",
                                                    "bootstrap": {"started_activity": True, "created_forward": True}}}), encoding="utf-8")
    monkeypatch.setattr(daemon_client.process, "is_alive", lambda identity: False)
    monkeypatch.setattr(daemon_client, "list_context_ids", lambda: [context])

    cleaned = daemon_client.cleanup_stale_daemon_states()
    assert daemon_path.name in cleaned["state_files"]
    assert not daemon_path.exists()
    assert runtime_path.exists() and snapshot_path.exists()
    assert cleaned["context_files"] == cleaned["snapshot_files"] == []

    ok, message, details = daemon_client.clear_context(context)
    assert ok is False
    assert "still owns resources" in message
    assert details["context_id"] == context
    assert runtime_path.exists() and snapshot_path.exists()
    stopped, message = daemon_client.stop_daemon(context)
    assert stopped is False
    assert "clear it before stopping" in message


def test_orphan_cleanup_preserves_unreadable_context_state(monkeypatch, tmp_path: Path) -> None:
    _configure_runtime_dir(monkeypatch, tmp_path)
    state_dir = _configure_context_artifact_paths(monkeypatch, tmp_path)
    runtime_path = state_dir / "runtime_state_unknown.json"
    runtime_path.write_text("{invalid", encoding="utf-8")
    monkeypatch.setattr(daemon_client, "list_context_ids", lambda: ["unknown"])

    cleaned = daemon_client.cleanup_stale_daemon_states()
    assert runtime_path.exists()
    assert cleaned["context_files"] == []


def test_save_daemon_state_uses_atomic_replace(monkeypatch, tmp_path: Path) -> None:
    _configure_runtime_dir(monkeypatch, tmp_path)

    calls: list[tuple[str, str]] = []
    real_replace = daemon_client.os.replace

    def _spy_replace(src: str | Path, dst: str | Path) -> None:
        calls.append((Path(src).name, Path(dst).name))
        real_replace(src, dst)

    monkeypatch.setattr(daemon_client.os, "replace", _spy_replace)

    daemon_state.save_state({"pid": 42, "token": "tok", "endpoint": "pipe", "context_id": "ctx"}, context="ctx")

    state = daemon_client.load_state(context="ctx")
    assert state["pid"] == 42
    assert calls
    assert not list(cli_runtime_dir().glob("*.tmp"))


def test_stop_daemon_uses_loaded_state_before_cleanup(monkeypatch, tmp_path: Path) -> None:
    _configure_runtime_dir(monkeypatch, tmp_path)

    calls: list[tuple[int, str]] = []
    cleared: list[str] = []
    state = {"pid": 321, "context_id": "ctx-live", "token": "tok", "endpoint": "pipe-live"}

    monkeypatch.setattr(daemon_client, "load_state", lambda context="default": dict(state) if context == "ctx-live" else {})
    monkeypatch.setattr(daemon_client, "cleanup_stale_daemon_states", lambda context=None: (_ for _ in ()).throw(AssertionError("cleanup should not run before stop uses loaded state")))
    monkeypatch.setattr(daemon_client, "_shutdown_stateful_daemon", lambda daemon, loaded, context: calls.append((daemon.pid, context)) or True)
    monkeypatch.setattr(daemon_client.process, "is_alive", lambda identity: False)
    monkeypatch.setattr(daemon_client, "clear_state", lambda context="default", **kwargs: cleared.append(f"daemon:{context}"))

    ok, message = daemon_client.stop_daemon("ctx-live")

    assert ok is True
    assert message == "daemon stopped"
    assert calls == [(321, "ctx-live")]
    assert cleared == ["daemon:ctx-live"]


def test_daemon_stop_cli_confirms_exact_context_and_completion(monkeypatch, capsys) -> None:
    monkeypatch.setattr(cli, "stop_daemon", lambda context="default": (True, "daemon stopped"))
    monkeypatch.setattr(sys, "argv", ["rdc-tool", "--json", "--daemon-context", "ctx-live", "daemon", "stop"])

    with pytest.raises(SystemExit) as exit_info:
        cli.main()

    assert exit_info.value.code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["result_kind"] == "rdc_tool.daemon.stop"
    assert payload["data"] == {
        "message": "daemon stopped",
        "context_id": "ctx-live",
        "stopped": True,
    }


def test_owner_lost_stops_even_when_request_count_would_have_blocked_idle() -> None:
    now = 1_000_000
    assert daemon_client.owner_lost_should_stop(
        owner_pid=44,
        owner_running=False,
        has_live_clients=False,
        last_activity_ms=now - 120_000,
        now_ms=now,
        lease_timeout_seconds=120,
    )
    assert not daemon_client.owner_lost_should_stop(
        owner_pid=44,
        owner_running=False,
        has_live_clients=True,
        last_activity_ms=now - 120_000,
        now_ms=now,
        lease_timeout_seconds=120,
    )


def test_attach_client_forwards_owner_pid(monkeypatch, tmp_path: Path) -> None:
    _configure_runtime_dir(monkeypatch, tmp_path)
    captured: dict[str, object] = {}

    def _ensure(**kwargs):
        captured.update(kwargs)
        return True, "ok", {"pid": 1, "token": "tok", "endpoint": "pipe", "context_id": kwargs["context"]}

    monkeypatch.setattr(daemon_client, "ensure_daemon", _ensure)
    monkeypatch.setattr(
        daemon_client,
        "daemon_request",
        lambda *args, **kwargs: {"ok": True, "result": {"state": {**kwargs['state'], "owner_pid": 4321}}},
    )
    ok, _message, _state = daemon_client.attach_client(
        context="ctx-a",
        client_id="client-a",
        client_type="app",
        pid=9,
        owner_pid=4321,
    )
    assert ok is True
    assert captured["owner_pid"] == 4321
    assert captured["context"] == "ctx-a"


def test_stop_daemon_kills_recorded_worker_for_same_context(monkeypatch, tmp_path: Path) -> None:
    _configure_runtime_dir(monkeypatch, tmp_path)
    killed: list[int] = []
    state = {
        "pid": 11,
        "context_id": "ctx-live",
        "token": "tok",
        "endpoint": "pipe-live",
        "worker": {"pid": 22},
    }
    monkeypatch.setattr(daemon_client, "load_state", lambda context="default": dict(state) if context == "ctx-live" else {})
    monkeypatch.setattr(daemon_client, "cleanup_stale_daemon_states", lambda context=None: {})
    monkeypatch.setattr(daemon_client, "_shutdown_stateful_daemon", lambda *args, **kwargs: True)
    monkeypatch.setattr(daemon_client.process, "is_alive", lambda identity: identity.pid == 22)
    monkeypatch.setattr(daemon_client.process, "kill_tree", lambda identity: killed.append(identity.pid) or True)
    monkeypatch.setattr(daemon_client.process, "wait_exit", lambda identity, timeout: True)
    monkeypatch.setattr(daemon_client, "clear_state", lambda context="default", **kwargs: None)
    monkeypatch.setattr(daemon_client, "clear_worker_state", lambda context="default": None)

    ok, message = daemon_client.stop_daemon("ctx-live")
    assert ok is True
    assert message == "daemon stopped"
    assert killed == [22]


def test_clear_context_does_not_stop_daemon(monkeypatch, tmp_path: Path) -> None:
    _configure_runtime_dir(monkeypatch, tmp_path)
    stopped: list[str] = []
    monkeypatch.setattr(
        daemon_client,
        "load_state",
        lambda context="default": {"pid": 1, "token": "tok", "endpoint": "pipe", "context_id": context},
    )
    monkeypatch.setattr(
        daemon_client,
        "daemon_request",
        lambda method, **kwargs: {"ok": True, "result": {"released": {}}} if method == "clear_context" else (_ for _ in ()).throw(AssertionError(method)),
    )
    monkeypatch.setattr(daemon_client, "stop_daemon", lambda context="default": stopped.append(context) or (True, "no"))
    monkeypatch.setattr(daemon_client, "clear_context_snapshot", lambda context="default": None)
    monkeypatch.setattr(daemon_client, "clear_context_state", lambda context="default": None)
    ok, message, _details = daemon_client.clear_context("ctx-keep")
    assert ok is True
    assert "cleared" in message
    assert stopped == []


def test_stop_daemon_does_not_kill_other_context_worker(monkeypatch, tmp_path: Path) -> None:
    _configure_runtime_dir(monkeypatch, tmp_path)
    killed: list[int] = []
    states = {
        "ctx-live": {"pid": 11, "context_id": "ctx-live", "token": "tok", "endpoint": "pipe-live", "worker": {"pid": 22}},
        "ctx-other": {"pid": 33, "context_id": "ctx-other", "token": "tok", "endpoint": "pipe-other", "worker": {"pid": 44}},
    }
    monkeypatch.setattr(daemon_client, "load_state", lambda context="default": dict(states.get(context, {})))
    monkeypatch.setattr(daemon_client, "cleanup_stale_daemon_states", lambda context=None: {})
    monkeypatch.setattr(daemon_client, "_shutdown_stateful_daemon", lambda *args, **kwargs: True)
    monkeypatch.setattr(daemon_client.process, "is_alive", lambda identity: identity.pid in {22, 44})
    monkeypatch.setattr(daemon_client.process, "kill_tree", lambda identity: killed.append(identity.pid) or True)
    monkeypatch.setattr(daemon_client.process, "wait_exit", lambda identity, timeout: True)
    monkeypatch.setattr(daemon_client, "clear_state", lambda context="default", **kwargs: None)
    monkeypatch.setattr(daemon_client, "clear_worker_state", lambda context="default": None)

    ok, message = daemon_client.stop_daemon("ctx-live")
    assert ok is True
    assert message == "daemon stopped"
    assert killed == [22]


def test_ensure_daemon_forwards_owner_pid_to_existing_zero_owner(monkeypatch, tmp_path: Path) -> None:
    _configure_runtime_dir(monkeypatch, tmp_path)
    claimed: dict[str, object] = {}
    existing = {"pid": 77, "token": "tok", "endpoint": "pipe", "context_id": "ctx-a", "owner_pid": 0}
    monkeypatch.setattr(daemon_client, "cleanup_stale_daemon_states", lambda context=None: {})
    monkeypatch.setattr(daemon_client, "load_state", lambda context="default": dict(existing))
    monkeypatch.setattr(daemon_client.process, "is_alive", lambda identity: identity.pid == 77)

    def _request(method, **kwargs):
        if method == "claim_owner":
            claimed.update(kwargs.get("params") or {})
            return {"ok": True, "result": {"state": {**existing, "owner_pid": 4321}}}
        if method == "status":
            return {"ok": True, "result": {"state": {**existing, "owner_pid": 4321}}}
        raise AssertionError(method)

    monkeypatch.setattr(daemon_client, "daemon_request", _request)
    monkeypatch.setattr(daemon_client, "_update_saved_state_from_response", lambda response, context, **kwargs: (response.get("result") or {}).get("state") or {})
    ok, message, state = daemon_client.ensure_daemon(context="ctx-a", owner_pid=4321)
    assert ok is True
    assert "already running" in message
    assert claimed["owner_pid"] == 4321
    assert int(state.get("owner_pid") or 0) == 4321


def test_dead_owner_exits_live_daemon_process(monkeypatch, tmp_path: Path) -> None:
    import subprocess

    try:
        from rdc_tool.daemon import server as _daemon_server
    except Exception as exc:
        pytest.skip(f"daemon server import unavailable: {exc}")
    del _daemon_server

    intermediate = tmp_path / "rdc-tool-intermediate"
    state_dir = intermediate / "runtime" / "rdc_tool_cli"
    state_dir.mkdir(parents=True)
    monkeypatch.setenv("RDC_TOOL_INTERMEDIATE_ROOT", str(intermediate))

    dummy = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(120)"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    owner = int(dummy.pid)
    try:
        ok, _message, state = daemon_client.ensure_daemon(
            context="ctx-owner-reap",
            owner_pid=owner,
            lease_timeout_seconds=1,
            idle_timeout_seconds=900,
        )
        assert ok is True
        daemon = daemon_client.daemon_process(state)
        assert daemon.pid > 0 and daemon.birth
        dummy.kill()
        dummy.wait(timeout=5)
        assert daemon_client.process.wait_exit(daemon, 8)
    finally:
        if dummy.poll() is None:
            dummy.kill()
        daemon_client.stop_daemon("ctx-owner-reap")


def test_parser_accepts_global_owner_pid() -> None:
    args = cli._build_parser().parse_args(["--owner-pid", "77", "--daemon-context", "ctx", "daemon", "start"])
    assert args.owner_pid == 77
    assert args.daemon_context == "ctx"


def test_control_request_timeout_returns_structured_details(monkeypatch, tmp_path: Path) -> None:
    _configure_runtime_dir(monkeypatch, tmp_path)

    class _FakeClient:
        def __init__(self, endpoint, *, authkey: bytes) -> None:
            self.address = endpoint.address
            self.authkey = authkey

        def send(self, payload: dict[str, object]) -> None:
            return None

        def poll(self, timeout: float) -> bool:
            return False

        def close(self) -> None:
            return None

    state = {
        "endpoint": "pipe-demo",
        "token": "tok-demo",
        "context_id": "ctx-demo",
        "active_operation": {"operation": "rd.capture.open_replay", "trace_id": "trace-1", "transport": "cli"},
        "pid": 123,
        "session_id": "sess-demo",
        "capture_file_id": "capf-demo",
        "active_request_count": 1,
    }
    daemon_state.save_state(
        {
            **state,
            "active_operation": {"operation": "rd.capture.open_replay", "trace_id": "trace-2", "transport": "cli"},
            "session_id": "sess-ready",
            "capture_file_id": "capf-ready",
            "active_event_id": 147,
            "active_request_count": 2,
            "recovery_status": "ready",
        },
        context="ctx-demo",
    )

    monkeypatch.setattr(daemon_client.ipc, "connect", _FakeClient)

    try:
        daemon_client.daemon_request(
            "get_state",
            params={},
            timeout=0.01,
            state=state,
            context="ctx-demo",
        )
    except daemon_client.DaemonRequestTimeout as exc:
        assert exc.code == "daemon_timeout"
        assert exc.details["operation"] == "get_state"
        assert exc.details["context_id"] == "ctx-demo"
        assert exc.details["timeout_seconds"] == 0.01
        assert exc.details["active_request_count"] == 2
        assert exc.details["active_operation"]["operation"] == "rd.capture.open_replay"
        assert exc.details["active_operation"]["trace_id"] == "trace-2"
        assert exc.details["daemon_state_excerpt"]["session_id"] == "sess-ready"
        assert exc.details["daemon_state_excerpt"]["capture_file_id"] == "capf-ready"
        assert exc.details["daemon_state_excerpt"]["active_event_id"] == 147
        assert exc.details["daemon_state_excerpt"]["recovery_status"] == "ready"
    else:  # pragma: no cover
        raise AssertionError("expected DaemonRequestTimeout")


@pytest.mark.parametrize("resource", ["session", "capture", "remote", "unreadable", "active_request"])
def test_idle_client_cleanup_preserves_owned_daemon(monkeypatch, tmp_path: Path, resource: str) -> None:
    _configure_runtime_dir(monkeypatch, tmp_path)
    _configure_context_artifact_paths(monkeypatch, tmp_path)
    context = "idle-owned"
    if resource in {"session", "capture"}:
        key = "sessions" if resource == "session" else "captures"
        daemon_client.context_state_path(context).write_text(json.dumps({key: {"owned": {}}}), encoding="utf-8")
    elif resource == "remote":
        daemon_client.context_snapshot_path(context).write_text(json.dumps({"remote": {"state": "live_handle", "remote_id": "owned"}}), encoding="utf-8")
    elif resource == "unreadable":
        daemon_client.context_state_path(context).write_text("{invalid", encoding="utf-8")
    state = {"context_id": context, "pid": 321, "owner_pid": 654, "endpoint": "owned-pipe", "token": "test-only",
        "last_activity_at": "2026-03-06T00:00:00+00:00", "idle_timeout_seconds": 900,
        "active_request_count": int(resource == "active_request")}
    daemon_state.save_state(state, context)
    monkeypatch.setattr(daemon_client.process, "is_alive", lambda identity: identity.pid in {321, 654})
    monkeypatch.setattr(daemon_client.process, "wait_exit", lambda *args, **kwargs: True)
    requests = []
    def request(method, **kwargs):
        requests.append(method)
        return {"ok": True, "result": {"running": True, "state": state}}
    monkeypatch.setattr(daemon_client, "daemon_request", request)
    monkeypatch.setattr(daemon_client.subprocess, "Popen", lambda *args, **kwargs: pytest.fail("must preserve original daemon"))
    assert not daemon_client._state_should_reap(daemon_client.load_state(context))
    cleaned = daemon_client.cleanup_stale_daemon_states(context)
    assert cleaned["state_files"] == cleaned["killed_pids"] == []
    ok, _, current = daemon_client.ensure_daemon(context=context, owner_pid=654)
    assert ok and current["pid"] == 321
    assert requests == ["status"]


@pytest.mark.parametrize("owner_alive,has_resources,expected", [(True, False, True), (False, True, True)])
def test_idle_cleanup_still_reaps_empty_or_orphaned_daemon(monkeypatch, owner_alive, has_resources, expected):
    monkeypatch.setattr(daemon_client.process, "is_alive", lambda identity: identity.pid == 321 or owner_alive)
    monkeypatch.setattr(daemon_client, "context_has_unreleased_resources", lambda context: has_resources)
    state = {"context_id": "test-only", "pid": 321, "owner_pid": 654,
        "last_activity_at": "2026-03-06T00:00:00+00:00", "idle_timeout_seconds": 900, "lease_timeout_seconds": 120}
    assert daemon_client._state_should_reap(state) is expected

def test_concurrent_ensure_daemon_publishes_one_owner(monkeypatch, tmp_path: Path) -> None:
    import threading
    from concurrent.futures import ThreadPoolExecutor

    _configure_runtime_dir(monkeypatch, tmp_path)
    first_spawned = threading.Event()
    release_start = threading.Event()
    spawned = []

    def spawn(*args, **kwargs):
        proc = type('Process', (), {'pid': 7100 + len(spawned), 'stdin': io.StringIO()})()
        spawned.append(proc.pid)
        first_spawned.set()
        return proc

    def ready(state):
        assert release_start.wait(3)
        # Readiness is published by the daemon, never by a client RPC response.
        daemon_state.save_state(state, context='same-context')
        return True

    monkeypatch.setattr(daemon_client.subprocess, 'Popen', spawn)
    monkeypatch.setattr(daemon_client, '_wait_for_daemon_ready', ready)
    monkeypatch.setattr(daemon_client.process, 'is_alive', lambda identity: identity.pid > 0)
    monkeypatch.setattr(daemon_client, 'daemon_request', lambda method, **kw: {'ok': True, 'result': {'state': kw['state']}})
    with ThreadPoolExecutor(max_workers=2) as executor:
        one = executor.submit(daemon_client.ensure_daemon, context='same-context', owner_pid=9000)
        assert first_spawned.wait(3)
        two_entered = threading.Event()
        def second():
            two_entered.set()
            return daemon_client.ensure_daemon(context='same-context', owner_pid=9000)
        two = executor.submit(second)
        assert two_entered.wait(3)
        # First startup has not published readiness; a second caller must wait.
        import time
        time.sleep(.05)
        release_start.set()
        results = [one.result(timeout=5), two.result(timeout=5)]
    assert len(spawned) == 1
    assert all(result[0] for result in results)
    assert results[0][2]['pid'] == results[1][2]['pid'] == spawned[0]

def test_daemon_start_lock_is_process_scoped_and_released(monkeypatch, tmp_path: Path) -> None:
    import subprocess
    import threading
    from concurrent.futures import ThreadPoolExecutor

    _configure_runtime_dir(monkeypatch, tmp_path)
    code = """
import sys
from pathlib import Path
from rdc_tool.daemon import client
with client._locked_daemon_start('shared'):
    print('locked', flush=True)
    sys.stdin.readline()
"""
    child = subprocess.Popen([sys.executable, '-c', code, str(cli_runtime_dir())],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    acquired = threading.Event()
    def acquire():
        with daemon_client._locked_daemon_start('shared'):
            acquired.set()
    try:
        assert child.stdout.readline().strip() == 'locked'
        # Different context does not wait behind this startup.
        with daemon_client._locked_daemon_start('other'):
            pass
        with ThreadPoolExecutor(max_workers=1) as executor:
            pending = executor.submit(acquire)
            assert not acquired.wait(.1)
            child.stdin.write('release\n')
            child.stdin.flush()
            child.wait(timeout=5)
            pending.result(timeout=5)
        assert acquired.is_set()
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=5)
        child.stdin.close()
        child.stdout.close()


def test_daemon_start_lock_releases_on_failure(monkeypatch, tmp_path: Path) -> None:
    _configure_runtime_dir(monkeypatch, tmp_path)
    with pytest.raises(RuntimeError, match='startup failed'):
        with daemon_client._locked_daemon_start('failure'):
            raise RuntimeError('startup failed')
    with daemon_client._locked_daemon_start('failure'):
        pass
