from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import asyncio
import threading

import pytest

from rdc_tool import remote_bootstrap as rb
from rdc_tool import server
from rdc_tool.android_apk_identity import read_apk_identity
from rdc_tool.core.errors import CoreError


@pytest.fixture(autouse=True)
def no_pending_package_manager(monkeypatch):
    # These tests isolate helper repair and cancellation. Active-session parsing
    # and its actual install boundary are exercised in test_android_install_state.
    monkeypatch.setattr(rb, "_preflight_android_install", lambda result: None)
    monkeypatch.setattr(rb, "DEFAULT_ANDROID_TIMEOUT_MS", 5)


def result(tmp_path):
    apk = tmp_path / "helper.apk"
    apk.write_bytes(b"fixture")
    return rb.AndroidBootstrapResult("adb", "device", "org.renderdoc.renderdoccmd.arm64", "", "arm64-v8a", "127.0.0.1", 1234, 38920, str(apk), "tcp:1234", expected_version="v1.45")


def facts(**changes):
    return {"package_name": "org.renderdoc.renderdoccmd.arm64", "device_serial": "device", "apk_sha256": "a" * 64,
            "installed_identity": "b" * 64, "service_identity": [], "expected_version": "v1.45", "actual_version": "commit-sha",
            "target_version_code": 145, "installed_version_code": 136, **changes}


def identity(monkeypatch):
    monkeypatch.setattr(rb, "read_apk_identity", lambda _: {"package_name": "org.renderdoc.renderdoccmd.arm64", "version_code": 145, "apk_sha256": "a" * 64})


def test_same_install_apk_manifest_identity():
    root = Path(__file__).resolve().parents[1] / "binaries/android"
    for arch in ("arm32", "arm64"):
        info = read_apk_identity(str(root / arch / f"org.renderdoc.renderdoccmd.{arch}.apk"))
        assert info["package_name"] == f"org.renderdoc.renderdoccmd.{arch}"
        assert isinstance(info["version_code"], int) and info["version_code"] > 0
        assert len(info["apk_sha256"]) == 64


def test_invalid_apk_never_reaches_installer(monkeypatch, tmp_path):
    current = result(tmp_path)
    commands = []
    monkeypatch.setattr(rb, "_run_process", lambda *a, **k: commands.append(a))
    with pytest.raises(rb.AndroidRemoteBootstrapError) as error:
        rb._install_android_helper(current, rb.AndroidBootstrapOptions())
    assert error.value.code == "android_apk_invalid"
    assert not commands


@pytest.mark.parametrize("installed,target", [(136, 145), (145, 145), (146, 145)])
def test_version_difference_automatically_updates_or_downgrades(monkeypatch, tmp_path, installed, target):
    current = result(tmp_path)
    monkeypatch.setattr(rb, "_adb_shell", lambda *a, **k: SimpleNamespace(stdout=f"package:{current.package_name}", stderr=""))
    monkeypatch.setattr(rb, "_helper_snapshot", lambda _: facts(installed_version_code=installed, target_version_code=target))
    installs = []
    monkeypatch.setattr(rb, "_install_android_helper", lambda *a, **k: installs.append(k))
    rb._ensure_android_helper_installed(current, rb.AndroidBootstrapOptions())
    assert installs == ([] if installed == target else [{"update": True, "downgrade": installed > target}])


@pytest.mark.parametrize("kind", ["signature", "downgrade"])
def test_incompatible_package_is_replaced_in_one_attempt(monkeypatch, tmp_path, kind):
    current = result(tmp_path)
    identity(monkeypatch)
    monkeypatch.setattr(rb, "_helper_snapshot", lambda _: facts())
    commands = []
    def install(command, **kwargs):
        commands.append(command)
        failure = "INSTALL_FAILED_UPDATE_INCOMPATIBLE" if kind == "signature" else "INSTALL_FAILED_VERSION_DOWNGRADE"
        return SimpleNamespace(returncode=1, stdout="", stderr=failure) if len(commands) == 1 else SimpleNamespace(returncode=0, stdout="Success", stderr="")
    def shell(adb, serial, *args, **kwargs):
        assert args == ("pm", "uninstall", current.package_name)
        return SimpleNamespace(stdout="Success", stderr="")
    monkeypatch.setattr(rb, "_run_process", install)
    monkeypatch.setattr(rb, "_adb_shell", shell)
    rb._install_android_helper(current, rb.AndroidBootstrapOptions(), update=True)
    assert len(commands) == 2 and current.installed_apk
    assert current.uninstalled_existing == (kind == "signature")
    assert ("-d" in commands[-1]) == (kind == "downgrade")


def test_unidentified_running_helper_is_not_stopped(monkeypatch, tmp_path):
    current = result(tmp_path)
    monkeypatch.setattr(rb, "_helper_snapshot", lambda _: facts(installed_identity=""))
    monkeypatch.setattr(rb, "_adb_shell", lambda *a, **k: pytest.fail("unknown identity cannot be stopped"))
    with pytest.raises(rb.AndroidRemoteBootstrapError) as error:
        rb.repair_incompatible_android_helper(current, rb.AndroidBootstrapOptions())
    assert error.value.code == "android_helper_state_unknown"


def test_cancel_after_package_commit_retains_installation_fact(monkeypatch, tmp_path):
    current = result(tmp_path)
    identity(monkeypatch)
    budget = rb.ConnectionBudget(3000)
    def run(*args, **kwargs):
        budget.cancelled.set()
        return SimpleNamespace(returncode=0, stdout="Success", stderr="")
    monkeypatch.setattr(rb, "_run_process", run)
    token = rb._connection_budget.set(budget)
    try:
        with pytest.raises(rb.AndroidRemoteBootstrapError) as error:
            rb._install_android_helper(current, rb.AndroidBootstrapOptions())
        assert error.value.code == "remote_connect_cancelled"
        assert current.installed_apk and current.install_mode == "install"
    finally:
        rb._connection_budget.reset(token)


def test_native_busy_does_not_enter_repair(monkeypatch):
    runtime = server.server_runtime
    bootstrap = SimpleNamespace(host="127.0.0.1", port=1234)
    monkeypatch.setattr(runtime, "bootstrap_android_remote", lambda **k: bootstrap)
    monkeypatch.setattr(runtime, "describe_android_remote", lambda _: {})
    monkeypatch.setattr(runtime, "_renderdoc_version_value", lambda: "v1.45")
    monkeypatch.setattr(runtime, "_wait_for_remote_endpoint", lambda *a: (_ for _ in ()).throw(CoreError("remote_busy", "busy", "runtime")))
    monkeypatch.setattr(runtime, "repair_incompatible_android_helper", lambda *a: pytest.fail("busy cannot repair"))
    monkeypatch.setattr(runtime, "cleanup_android_remote", lambda _: [])
    with pytest.raises(CoreError) as error:
        asyncio.run(runtime._connect_remote_endpoint("host", 38920, "adb_android", {"device_serial": "device"}, 3000))
    assert error.value.code == "remote_busy"


def test_progress_comes_from_actual_install_step(monkeypatch, tmp_path):
    current = result(tmp_path)
    identity(monkeypatch)
    stages = []
    monkeypatch.setattr(rb, "_run_process", lambda *a, **k: SimpleNamespace(returncode=0, stdout="Success", stderr=""))
    rb._install_android_helper(current, rb.AndroidBootstrapOptions(progress=stages.append), update=True)
    assert stages == ["installing"] and current.install_mode == "update"


def test_install_requires_positive_package_manager_result(monkeypatch, tmp_path):
    current = result(tmp_path)
    identity(monkeypatch)
    monkeypatch.setattr(rb, "_run_process", lambda *a, **k: SimpleNamespace(returncode=0, stdout="Failure [unknown]", stderr=""))
    with pytest.raises(rb.AndroidRemoteBootstrapError) as error:
        rb._install_android_helper(current, rb.AndroidBootstrapOptions())
    assert error.value.code == "android_apk_install_failed"
    assert not current.installed_apk


def test_native_mismatch_refreshes_owned_helper_once_and_pings(monkeypatch):
    runtime = server.server_runtime
    remote = SimpleNamespace(Ping=lambda: SimpleNamespace(OK=lambda: True), ShutdownConnection=lambda: None)
    bootstrap = SimpleNamespace(host="127.0.0.1", port=1234, package_name="helper")
    observed = []
    monkeypatch.setattr(runtime, "bootstrap_android_remote", lambda **k: bootstrap)
    monkeypatch.setattr(runtime, "describe_android_remote", lambda _: {})
    monkeypatch.setattr(runtime, "_renderdoc_version_value", lambda: "v1.45")
    def wait(*args):
        observed.append("verify")
        if observed.count("verify") == 1:
            raise CoreError("remote_version_mismatch", "mismatch", "runtime")
    monkeypatch.setattr(runtime, "_wait_for_remote_endpoint", wait)
    monkeypatch.setattr(runtime, "repair_incompatible_android_helper", lambda *a: observed.append("repair"))
    monkeypatch.setattr(runtime, "_prepare_android_service", lambda *a: bootstrap)
    monkeypatch.setattr(runtime, "_create_remote_server_connection", lambda *a: remote)
    monkeypatch.setattr(runtime, "_status_ok", lambda _: True)
    monkeypatch.setattr(runtime, "_collect_remote_server_info", lambda *a, **k: {})
    assert asyncio.run(runtime._connect_remote_endpoint("host", 38920, "adb_android", {}, 3000))[1] is remote
    assert observed == ["verify", "repair", "verify"]


@pytest.mark.parametrize("install_timeout", [False, True])
def test_connect_cancel_after_package_commit_publishes_joined_installation_receipt(monkeypatch, tmp_path, install_timeout):
    from rdc_tool.progress import ProgressReporter
    runtime = server.server_runtime
    current = result(tmp_path)
    current.uninstalled_existing = install_timeout
    identity(monkeypatch)
    entered, release = threading.Event(), threading.Event()
    receipts, cleaned = [], []
    class Sink:
        def publish(self, event):
            receipts.append(event)
    def install(*args, **kwargs):
        entered.set()
        assert release.wait(2)
        if install_timeout:
            raise rb.subprocess.TimeoutExpired(args[0], kwargs["timeout"])
        return SimpleNamespace(returncode=0, stdout="Success", stderr="")
    def bootstrap(remote_port, options):
        return rb._prepare_android_service(current, options, False, "helper/.Loader")
    monkeypatch.setattr(rb, "_run_process", install)
    monkeypatch.setattr(rb, "_list_renderdoc_socket_ports", lambda *a: [])
    monkeypatch.setattr(rb, "_adb_shell", lambda *a, **k: SimpleNamespace(stdout="", stderr=""))
    monkeypatch.setattr(rb, "cleanup_android_remote", lambda item: cleaned.append(item) or [])
    monkeypatch.setattr(runtime, "bootstrap_android_remote", bootstrap)
    monkeypatch.setattr(runtime, "_create_remote_server_connection", lambda *a: pytest.fail("cancelled install cannot connect"))
    # Exercise the actual install and bootstrap error receipt through the full
    # async connect boundary, including cancellation while PackageManager runs.
    async def run():
        await server.runtime_startup()
        runtime._record_operation_start(runtime._runtime_context_id(), trace_id="cancel-install", operation="rd.remote.connect", transport="test", args={})
        reporter = ProgressReporter(trace_id="cancel-install", operation="rd.remote.connect", sink=Sink())
        token = runtime._CURRENT_PROGRESS_REPORTER.set(reporter)
        try:
            task = asyncio.create_task(runtime._connect_remote_endpoint("host", 1, "adb_android", {"device_serial": "device"}, 3000))
            while not entered.is_set():
                await asyncio.sleep(0)
            task.cancel()
            await asyncio.sleep(0)
            assert not task.done()
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await task
            receipt = receipts[-1]
            assert receipt.stage == "cancelled"
            assert receipt.details["installation"] == {"installed_apk": not install_timeout,
                "uninstalled_existing": install_timeout, "install_mode": "" if install_timeout else "install"}
            assert receipt.details["remote"]["code"] == ("remote_install_unconfirmed" if install_timeout else "remote_connect_cancelled")
            if install_timeout:
                assert receipt.details["device_action"]["state"] == "unconfirmed"
            assert cleaned == [current]
            assert current.installed_apk is not install_timeout
            history = await server.dispatch_operation("rd.core.get_operation_history", {"operation": "rd.remote.connect"}, transport="test")
            assert history["ok"] is True
            entry = next(item for item in history["data"]["operations"] if item["trace_id"] == "cancel-install")
            final = entry["stages"][-1]
            assert final["stage"] == "cancelled"
            assert final["details"]["installation"] == receipt.details["installation"]
            if install_timeout:
                assert final["details"]["device_action"] == receipt.details["device_action"]
        finally:
            release.set()
            runtime._CURRENT_PROGRESS_REPORTER.reset(token)
    asyncio.run(run())


@pytest.mark.parametrize("uninstalled", [False, True])
def test_install_timeout_is_typed_and_preserves_confirmed_mutation_facts(monkeypatch, tmp_path, uninstalled):
    current = result(tmp_path)
    current.uninstalled_existing = uninstalled
    identity(monkeypatch)
    monkeypatch.setattr(rb, "_list_renderdoc_socket_ports", lambda *args: [])
    monkeypatch.setattr(rb, "_adb_shell", lambda *args, **kwargs: SimpleNamespace(stdout="", stderr=""))
    cleaned = []
    monkeypatch.setattr(rb, "cleanup_android_remote", lambda item: cleaned.append(item) or [])
    def timeout(command, **kwargs):
        raise rb.subprocess.TimeoutExpired(command, kwargs["timeout"], output=b"Performing Streamed Install\n", stderr=b"pending")
    monkeypatch.setattr(rb, "_run_process", timeout)
    with pytest.raises(rb.AndroidRemoteBootstrapError) as error:
        rb._prepare_android_service(current, rb.AndroidBootstrapOptions(), False, "helper/.Loader")
    assert error.value.code == "remote_install_unconfirmed"
    assert error.value.details["remote"]["stage"] == "installing"
    assert error.value.details["device_action"]["state"] == "unconfirmed"
    assert error.value.details["device_action"]["kind"] == "android_install"
    assert error.value.details["installation"] == {"installed_apk": False, "uninstalled_existing": uninstalled, "install_mode": ""}
    assert error.value.details["stdout"] == "Performing Streamed Install\n"
    assert error.value.details["stderr"] == "pending"
    assert cleaned == [current]


def test_missing_receipt_verifies_target_bytes_and_continues_without_reinstall(monkeypatch, tmp_path):
    current = result(tmp_path)
    identity(monkeypatch)
    installs = []
    monkeypatch.setattr(rb, "_run_process", lambda command, **kwargs: installs.append(command) or SimpleNamespace(returncode=0, stdout="", stderr=""))
    monkeypatch.setattr(rb, "_inspect_android_install_state", lambda _: {"installation_state": "clear", "observation": "verified", "sessions": []})
    monkeypatch.setattr(rb, "_observe_installed_apk", lambda item: setattr(item, "apk_identity_status", "matched"))
    rb._install_android_helper(current, rb.AndroidBootstrapOptions())
    assert len(installs) == 1 and current.installed_apk


def test_pending_install_resolves_in_original_budget_without_second_install(monkeypatch, tmp_path):
    current = result(tmp_path)
    identity(monkeypatch)
    observations = iter([{"installation_state": "pending", "observation": "pending", "sessions": []},
                         {"installation_state": "clear", "observation": "verified", "sessions": []}])
    monkeypatch.setattr(rb, "_inspect_android_install_state", lambda _: next(observations))
    monkeypatch.setattr(rb.time, "sleep", lambda _: None)
    monkeypatch.setattr(rb, "_observe_installed_apk", lambda item: setattr(item, "apk_identity_status", "matched"))
    budget = rb.ConnectionBudget(5000)
    token = rb._connection_budget.set(budget)
    try:
        rb._wait_for_android_install(current, require_target=True)
        assert rb._connection_budget.get() is budget
    finally:
        rb._connection_budget.reset(token)


def test_clear_session_alone_never_proves_installation(monkeypatch, tmp_path):
    current = result(tmp_path)
    monkeypatch.setattr(rb, "_inspect_android_install_state", lambda _: {"installation_state": "clear", "observation": "verified", "sessions": []})
    monkeypatch.setattr(rb, "_observe_installed_apk", lambda item: setattr(item, "apk_identity_status", "different"))
    with pytest.raises(rb.AndroidRemoteBootstrapError) as error:
        rb._wait_for_android_install(current, require_target=True, receipt={"stdout": "missing terminal result"})
    assert error.value.code == "remote_install_unconfirmed"
    assert error.value.details["stdout"] == "missing terminal result"
    assert not current.installed_apk


def test_accepted_launch_waits_for_phone_permission_with_original_budget(monkeypatch, tmp_path):
    current = result(tmp_path)
    clock = [0.0]
    commands = []
    monkeypatch.setattr(rb.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(rb.time, "sleep", lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    monkeypatch.setattr(rb, "_adb_shell", lambda *args, **kwargs: commands.append(args[2:]) or SimpleNamespace(stdout="Activity: com.smartisanos.security/.permission.SpecialRadioPermissionsActivity", stderr=""))
    monkeypatch.setattr(rb, "_package_pids", lambda *args: [321] if clock[0] >= 20 else [])
    budget = rb.ConnectionBudget(30000)
    token = rb._connection_budget.set(budget)
    try:
        rb._start_android_helper(current, current.package_name + '/.Loader', rb.AndroidBootstrapOptions())
        assert clock[0] == 20 and current.owned_pids == [321]
        assert len(commands) == 1 and commands[0][:2] == ('am', 'start')
        assert rb._connection_budget.get() is budget
    finally:
        rb._connection_budget.reset(token)


def test_permission_wait_cancellation_does_not_launch_an_alternate_activity(monkeypatch, tmp_path):
    current = result(tmp_path)
    budget = rb.ConnectionBudget(30000)
    commands = []
    monkeypatch.setattr(rb, "_adb_shell", lambda *args, **kwargs: commands.append(args[2:]) or SimpleNamespace(stdout="Status: ok", stderr=""))
    monkeypatch.setattr(rb, "_package_pids", lambda *args: [])
    monkeypatch.setattr(rb.time, "sleep", lambda _: budget.cancelled.set())
    token = rb._connection_budget.set(budget)
    try:
        with pytest.raises(rb.AndroidRemoteBootstrapError) as error:
            rb._start_android_helper(current, current.package_name + '/.Loader', rb.AndroidBootstrapOptions())
        assert error.value.code == 'remote_connect_cancelled'
        assert len(commands) == 1 and not current.started_activity
    finally:
        rb._connection_budget.reset(token)
