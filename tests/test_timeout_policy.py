from __future__ import annotations

import asyncio
import time

import pytest

from rdc_tool import cli, progress, remote_bootstrap, timeout_policy
from rdc_tool.operation_definitions import OPERATIONS
from rdc_tool.remote_bootstrap import AndroidBootstrapResult
from rdc_tool.context_snapshot import clear_context_snapshot, save_context_snapshot
from rdc_tool.runtime import dispatch, live_state, oplog, remote_target, renderdoc_api
from rdc_tool.runtime.operations import remote as remote_ops

pytestmark = pytest.mark.usefixtures("fake_renderdoc")


class DummyRemoteServer:
    def Ping(self):
        return type("PingStatus", (), {"OK": lambda self: True, "Message": lambda self: "Succeeded"})()

    def DriverName(self):
        return "Android Vulkan"

    def RemoteSupportedReplays(self):
        return ["Vulkan"]

    def ShutdownConnection(self):
        return None


def test_every_operation_publishes_the_single_no_progress_budget():
    expected = {"rule": "no_progress", "default_no_progress_ms": 300000,
                "min_no_progress_ms": 30000, "max_no_progress_ms": 3600000}
    assert timeout_policy.execution_budget() == expected
    assert all(operation["execution_budget"] == expected for operation in OPERATIONS)


def test_remote_connect_has_no_private_deadline():
    connect = next(operation for operation in OPERATIONS if operation["name"] == "rd.remote.connect")
    assert "timeout_policy" not in connect
    assert "timeout_ms" not in connect["param_names"]
    assert "timeout_ms" not in connect["input_schema"]["properties"]


@pytest.mark.parametrize("value", [None, 30000, 300000, 3600000])
def test_budget_within_the_published_range_is_accepted(value):
    assert timeout_policy.validate_no_progress_ms(value) == (300000 if value is None else value)


@pytest.mark.parametrize("value", [29999, 3600001, 0, -1, True, 1.5, "300000"])
def test_budget_outside_the_published_range_is_rejected(value):
    with pytest.raises(timeout_policy.NoProgressBudgetError) as raised:
        timeout_policy.validate_no_progress_ms(value)
    assert raised.value.code == "invalid_no_progress_ms"
    assert raised.value.details["no_progress_ms"] == value


@pytest.mark.parametrize("budget_ms", [30000, 300000, 3600000])
def test_cooperative_deadline_fires_before_the_stack_dump_and_the_dump_before_the_kill(budget_ms):
    cooperative = timeout_policy.cooperative_no_progress_s(budget_ms)
    dump = timeout_policy.stack_dump_after_s(budget_ms)
    kill = timeout_policy.watchdog_s(budget_ms)
    assert 0 < cooperative < dump < kill == budget_ms / 1000
    assert kill - dump == min(5.0, budget_ms / 10000)


def test_cli_exec_sends_the_request_budget_without_a_total_deadline(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def _fake_daemon_request(method: str, **kwargs):
        captured.update(method=method, **kwargs)
        return {"ok": True, "result": {"ok": True}}

    monkeypatch.setattr(cli, "daemon_request", _fake_daemon_request)
    monkeypatch.setattr(cli, "_ensure_daemon_state", lambda context: {"context_id": context})

    payload = cli._daemon_exec("rd.remote.connect", {"host": "127.0.0.1"}, context="ctx-demo",
                               request_id="req-owned", no_progress_ms=45000)

    assert payload == {"ok": True}
    assert captured["method"] == "exec"
    assert "timeout" not in captured
    params = captured["params"]
    assert params["request_id"] == "req-owned"
    assert params["no_progress_ms"] == 45000
    assert params["stream"] is False
    defaulted = cli._daemon_exec("rd.core.get_version", {}, context="ctx-demo")
    assert defaulted == {"ok": True}
    assert captured["params"]["no_progress_ms"] == 300000
    assert captured["params"]["request_id"].startswith("req_")


@pytest.mark.parametrize("flags, code", [(["--no-progress-ms", "1000"], "invalid_no_progress_ms"),
                                         (["--request-id", "has space"], "invalid_request_id")])
def test_cli_call_rejects_invalid_execution_options_before_contacting_the_daemon(monkeypatch, capsys, flags, code):
    import json
    monkeypatch.setattr(cli, "_ensure_daemon_state", lambda context: pytest.fail("daemon contacted"))
    args = cli._build_parser().parse_args(["call", "rd.core.get_version", *flags])
    assert asyncio.run(cli._cmd_call(args)) == cli.EXIT_RUNTIME_ERR
    payload = json.loads(capsys.readouterr().out)
    assert payload["result_kind"] == "rd.core.get_version"
    assert payload["error"]["code"] == code
    assert payload["error"]["category"] == "validation"


def test_connection_budget_moves_forward_on_reported_progress(monkeypatch):
    clock = {"now": 100.0}
    monkeypatch.setattr(remote_bootstrap.time, "monotonic", lambda: clock["now"])
    budget = remote_bootstrap.ConnectionBudget(10000)
    token = remote_bootstrap._connection_budget.set(budget)
    try:
        clock["now"] = 108.0
        oplog._progress("installing", "Installing helper")
        clock["now"] = 117.0
        assert budget.remaining() == pytest.approx(1.0)
        clock["now"] = 118.5
        with pytest.raises(remote_bootstrap.AndroidRemoteBootstrapError) as raised:
            budget.remaining()
        assert raised.value.code == "remote_connect_timeout"
    finally:
        remote_bootstrap._connection_budget.reset(token)


def test_remote_connect_waits_within_the_requests_cooperative_window(monkeypatch) -> None:
    # Freeze the clock so this assertion checks the budget, not scheduler time.
    monkeypatch.setattr("rdc_tool.remote_bootstrap.time.monotonic", lambda: 100.0)
    original_remotes = dict(live_state._runtime.remotes)
    original_enable_remote = live_state._runtime.enable_remote
    captured: dict[str, object] = {}

    async def _inline_offload(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    def _capture_wait(url: str, timeout_ms: int) -> None:
        captured["url"] = url
        captured["timeout_ms"] = timeout_ms

    monkeypatch.setattr(renderdoc_api, "_offload", _inline_offload)
    monkeypatch.setattr(remote_target, "_wait_for_remote_endpoint", _capture_wait)
    monkeypatch.setattr(remote_target, "_create_remote_server_connection", lambda url: DummyRemoteServer())

    async def scenario():
        scope = progress.RequestScope(request_id="req", trace_id="trc", no_progress_ms=60000)
        token = progress._CURRENT_REQUEST.set(scope)
        try:
            return await remote_ops.dispatch("connect", {"host": "127.0.0.1", "port": 38920})
        finally:
            progress._CURRENT_REQUEST.reset(token)

    live_state._runtime.remotes.clear()
    live_state._runtime.enable_remote = True
    try:
        payload = asyncio.run(scenario())
        assert payload.ok is True
        assert captured["url"] == "127.0.0.1:38920"
        assert captured["timeout_ms"] == int(timeout_policy.cooperative_no_progress_s(60000) * 1000)
    finally:
        live_state._runtime.remotes.clear()
        live_state._runtime.remotes.update(original_remotes)
        live_state._runtime.enable_remote = original_enable_remote


def test_remote_ping_rehydrates_handle_from_context_snapshot(monkeypatch) -> None:
    original_remotes = dict(live_state._runtime.remotes)
    context_id = "remote-rehydrate-test"
    retired_forwards: list[str] = []

    async def _inline_offload(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    monkeypatch.setattr(renderdoc_api, "_offload", _inline_offload)
    monkeypatch.setattr(remote_target, "_create_remote_server_connection", lambda url: DummyRemoteServer())
    monkeypatch.setattr(remote_target, "_wait_for_remote_endpoint", lambda url, timeout_ms: None)
    monkeypatch.setattr(remote_bootstrap, "resolve_adb_path", lambda: "adb-test")
    monkeypatch.setattr(
        remote_bootstrap,
        "cleanup_android_remote",
        lambda result: retired_forwards.append(result.forward_spec) or [],
    )
    monkeypatch.setattr(
        remote_bootstrap,
        "bootstrap_android_remote",
        lambda remote_port, options: AndroidBootstrapResult(
            adb_path="adb-test",
            device_serial=options.device_serial,
            package_name="org.renderdoc.renderdoccmd.arm64",
            activity_name="org.renderdoc.renderdoccmd.arm64.Loader",
            abi="arm64-v8a",
            apk_path="demo.apk",
            host="127.0.0.1",
            port=45678,
            remote_port=remote_port,
            forward_spec="tcp:45678",
            config_remote_path="/sdcard/renderdoc.conf",
            installed_apk=True,
            pushed_config=True,
            started_activity=True,
            owned_pids=[123],
            created_forward=True,
            install_mode="update",
            install_reason="test",
            uninstalled_existing=False,
            cleanup_actions=["adb-forward"],
        ),
    )

    live_state._runtime.remotes.clear()
    save_context_snapshot(
        {
            "context_id": context_id,
            "backend": "remote",
            "remote": {
                "state": "live_handle",
                "remote_id": "remote_demo",
                "origin_remote_id": "remote_demo",
                "endpoint": "127.0.0.1:45678",
                "origin_context_id": context_id,
                "context_locality": "strict",
                "reuse_policy": "must_reconnect",
                "transport": "adb_android",
                "device_serial": "serial-1",
                "options": {"device_serial": "serial-1", "local_port": 45678, "remote_port": 38920},
                "bootstrap": {
                    "device_serial": "serial-1",
                    "package_name": "org.renderdoc.renderdoccmd.arm64",
                    "port": 45678,
                    "remote_port": 38920,
                    "forward_spec": "tcp:45678",
                    "created_forward": True,
                    "started_activity": False,
                    "owned_pids": [],
                },
            },
        },
        context_id,
    )
    try:
        payload = asyncio.run(
            dispatch.dispatch_operation(
                "rd.remote.ping",
                {"remote_id": "remote_demo"},
                transport="test",
                context_id=context_id,
            )
        )
        assert payload["ok"] is True
        assert payload["data"]["detail"]["remote_id"] == "remote_demo"
        assert live_state._runtime.remotes["remote_demo"].host == "127.0.0.1"
        assert live_state._runtime.remotes["remote_demo"].device_serial == "serial-1"
        assert retired_forwards == ["tcp:45678"]
    finally:
        clear_context_snapshot(context_id)
        live_state._runtime.context_snapshots.pop(context_id, None)
        live_state._runtime.remotes.clear()
        live_state._runtime.remotes.update(original_remotes)


def test_request_scope_carries_the_budget_and_defaults_outside_a_request():
    assert progress.current_no_progress_ms() == timeout_policy.DEFAULT_NO_PROGRESS_MS
    token = progress._CURRENT_REQUEST.set(progress.RequestScope(request_id="r", trace_id="t", no_progress_ms=45000))
    try:
        assert progress.current_no_progress_ms() == 45000
        budget = remote_bootstrap._request_budget()
        assert budget.window_s == pytest.approx(timeout_policy.cooperative_no_progress_s(45000))
        assert budget.deadline == pytest.approx(time.monotonic() + budget.window_s, abs=1.0)
    finally:
        progress._CURRENT_REQUEST.reset(token)
