from __future__ import annotations

import asyncio
import inspect
import json
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from rdc_tool import remote_bootstrap as android
from rdc_tool import server_runtime as runtime


HEADER = "Num       RefCount Protocol Flags    Type St Inode Path\n"


class Control:
    def __init__(self, *, busy="", fail_shutdown=False):
        self.busy = busy
        self.fail_shutdown = fail_shutdown
        self.shutdowns = 0
        self.triggers = []
        self.queues = []

    def GetTarget(self): return "test-app"
    def GetAPI(self): return "Vulkan"
    def GetPID(self): return 42
    def GetBusyClient(self): return self.busy
    def Connected(self): return not self.busy
    def TriggerCapture(self, frames): self.triggers.append(frames)
    def QueueCapture(self, frame, frames): self.queues.append((frame, frames))
    def Shutdown(self):
        self.shutdowns += 1
        if self.fail_shutdown:
            raise OSError("socket close failed")


def handle(**kwargs):
    return runtime.RemoteHandle("remote-target-test", "127.0.0.1", 60656, True, **kwargs)


@pytest.fixture
def native(monkeypatch):
    controls = []
    creates = []
    enumerates = []
    ids = iter([38920, 0])
    def create(*args):
        creates.append(args)
        control = Control()
        controls.append(control)
        return control
    def enumerate_targets(*args):
        enumerates.append(args)
        return next(ids)
    monkeypatch.setattr(runtime, "_get_rd", lambda: SimpleNamespace(
        CreateTargetControl=create, EnumerateRemoteTargets=enumerate_targets))
    monkeypatch.setattr(runtime, "_drain_target_control_messages_sync", lambda *a, **kw: [])
    return controls, creates, enumerates


def test_tcp_scan_and_control_use_host_only_and_release(native):
    remote = handle()
    targets = runtime._remote_list_targets_sync(remote)
    controls, creates, enumerates = native
    assert enumerates == [("127.0.0.1", 0), ("127.0.0.1", 38920)]
    assert creates == [("127.0.0.1", 38920, "rdc-tool-remote-target-test", False)]
    assert targets[0]["target_id"] == "38920"
    assert controls[0].shutdowns == 1
    assert not remote.target_control_leases


def test_successful_empty_scan_does_not_return_stale_cached_targets(monkeypatch):
    remote = handle(known_targets={"38920": {"target_id": "38920", "ident": 38920}})
    monkeypatch.setattr(runtime, "_get_rd", lambda: SimpleNamespace(EnumerateRemoteTargets=lambda *a: 0))
    assert runtime._remote_list_targets_sync(remote) == []
    assert remote.known_targets == {}


@pytest.mark.parametrize("host", ["", "127.0.0.1:60656", "adb://device", "::1"])
def test_unsupported_host_shape_cannot_succeed_with_empty_scan(host, monkeypatch):
    remote = handle()
    remote.host = host
    monkeypatch.setattr(runtime, "_get_rd", lambda: pytest.fail("native API must not receive unsupported URL"))
    with pytest.raises(runtime.RuntimeToolError, match="hostname"):
        runtime._remote_list_targets_sync(remote)


@pytest.mark.parametrize("stdout,stderr,code", [
    ("", "", 0), ("cat: permission denied", "", 0), (HEADER, "denied", 0),
    (HEADER, "", 1), (HEADER + "malformed\n", "", 0),
])
def test_android_socket_read_failures_are_not_empty_results(monkeypatch, stdout, stderr, code):
    monkeypatch.setattr(android, "_adb_shell", lambda *a, **kw: SimpleNamespace(
        stdout=stdout, stderr=stderr, returncode=code))
    with pytest.raises(android.AndroidRemoteBootstrapError, match="socket"):
        android.list_android_target_idents("canonical-adb", "chosen-serial")


@pytest.mark.parametrize("rows,expected", [
    ("", []),
    ("00000000: 00000002 00000000 00010000 0001 01 12 @renderdoc_39920\n", []),
    ("00000000: 00000002 00000000 00010000 0001 01 12 @renderdoc_38920\n"
     "00000000: 00000002 00000000 00010000 0001 01 13 @renderdoc_38927\n"
     "00000000: 00000002 00000000 00010000 0001 01 14 @renderdoc_38928\n", [38920, 38927]),
])
def test_android_valid_socket_listing_filters_target_abi(monkeypatch, rows, expected):
    calls = []
    def shell(*args, **kwargs):
        calls.append(args)
        return SimpleNamespace(stdout=HEADER + rows, stderr="", returncode=0)
    monkeypatch.setattr(android, "_adb_shell", shell)
    assert android.list_android_target_idents("canonical-adb", "chosen-serial") == expected
    assert calls == [("canonical-adb", "chosen-serial", "cat", "/proc/net/unix")]


def test_android_maps_logical_ident_and_releases_control_before_forward(native, monkeypatch):
    controls, creates, enumerates = native
    remote = handle(transport="adb_android", device_serial="chosen-serial")
    bridge = android.AndroidBootstrapResult("canonical-adb", "chosen-serial", "", "", "", "127.0.0.1",
                                            62001, 38922, "", "tcp:62001", created_forward=True)
    monkeypatch.setattr(runtime, "resolve_adb_path", lambda: "canonical-adb")
    monkeypatch.setattr(runtime, "list_android_target_idents", lambda adb, serial: [38922])
    calls = []
    def forward(*args):
        calls.append(args)
        return bridge
    def cleanup(receipt):
        assert receipt is bridge
        assert controls[0].shutdowns == 1
        receipt.created_forward = False
        return []
    monkeypatch.setattr(runtime, "forward_android_target", forward)
    monkeypatch.setattr(runtime, "cleanup_android_remote", cleanup)
    targets = runtime._remote_list_targets_sync(remote)
    assert targets[0]["ident"] == 38922
    assert targets[0]["target_id"] == "38922"
    assert creates[0][:2] == ("127.0.0.1", 62001)
    assert calls == [("canonical-adb", "chosen-serial", 38922)]
    assert enumerates == []
    assert not remote.target_control_leases


def test_android_target_forward_is_no_rebind_and_has_exact_cleanup_receipt(monkeypatch):
    commands = []
    monkeypatch.setattr(android, "allocate_local_port", lambda: 62001)
    monkeypatch.setattr(android, "_run_subprocess", lambda cmd, **kw: commands.append(cmd))
    bridge = android.forward_android_target("canonical-adb", "chosen-serial", 38922)
    assert commands == [["canonical-adb", "-s", "chosen-serial", "forward", "--no-rebind",
                         "tcp:62001", "localabstract:renderdoc_38922"]]
    assert bridge.created_forward and not bridge.started_activity
    assert bridge.remote_port == 38922


@pytest.mark.parametrize("queued", [False, True])
def test_busy_target_never_forces_or_captures(monkeypatch, queued):
    remote = handle(known_targets={"38920": {"target_id": "38920", "ident": 38920}})
    control = Control(busy="user-client")
    creates = []
    def create(*args):
        creates.append(args)
        return control
    monkeypatch.setattr(runtime, "_get_rd", lambda: SimpleNamespace(CreateTargetControl=create))
    with pytest.raises(runtime.RuntimeToolError, match="busy"):
        runtime._trigger_remote_capture_sync(remote, target_id="38920", num_frames=1, queued=queued)
    assert creates[0][-1] is False
    assert not control.triggers and not control.queues
    assert control.shutdowns == 1


def test_busy_target_scan_preserves_busy_metadata_without_reading_messages(native, monkeypatch):
    control = Control(busy="user-client")
    monkeypatch.setattr(runtime, "_get_rd", lambda: SimpleNamespace(
        EnumerateRemoteTargets=lambda host, prior: 38920 if prior == 0 else 0,
        CreateTargetControl=lambda *a: control))
    monkeypatch.setattr(runtime, "_drain_target_control_messages_sync", lambda *a, **kw: pytest.fail("busy drain"))
    assert runtime._remote_list_targets_sync(handle())[0]["busy_client"] == "user-client"
    assert control.shutdowns == 1


@pytest.mark.parametrize("failure", [False, True])
def test_scope_shutdown_on_success_and_exception(native, failure):
    remote = handle()
    if failure:
        with pytest.raises(ValueError, match="action failed"):
            with runtime._target_control_scope_sync(remote, 38920):
                raise ValueError("action failed")
    else:
        with runtime._target_control_scope_sync(remote, 38920):
            pass
    assert native[0][0].shutdowns == 1
    assert not remote.target_control_leases


def test_failed_shutdown_retains_control_and_disconnect_retries(monkeypatch):
    control = Control(fail_shutdown=True)
    remote = handle()
    monkeypatch.setattr(runtime, "_get_rd", lambda: SimpleNamespace(CreateTargetControl=lambda *a: control))
    with pytest.raises(runtime.RuntimeToolError, match="cleanup failed"):
        with runtime._target_control_scope_sync(remote, 38920):
            pass
    assert remote.target_control_leases[0]["control"] is control
    assert runtime._disconnect_remote_handle_sync(remote)
    control.fail_shutdown = False
    assert runtime._disconnect_remote_handle_sync(remote) == []
    assert not remote.target_control_leases


def test_failed_forward_cleanup_retains_receipt_after_control_shutdown(native, monkeypatch):
    remote = handle(transport="adb_android", device_serial="chosen-serial")
    bridge = SimpleNamespace(host="127.0.0.1", port=62001, created_forward=True)
    monkeypatch.setattr(runtime, "resolve_adb_path", lambda: "canonical-adb")
    monkeypatch.setattr(runtime, "forward_android_target", lambda *a: bridge)
    monkeypatch.setattr(runtime, "cleanup_android_remote", lambda receipt: ["ownership changed"])
    with pytest.raises(runtime.RuntimeToolError, match="cleanup failed"):
        with runtime._target_control_scope_sync(remote, 38920):
            pass
    assert native[0][0].shutdowns == 1
    assert remote.target_control_leases[0] == {"control": None, "bridge": bridge}
    assert runtime._disconnect_remote_handle_sync(remote) == ["ownership changed"]
    monkeypatch.setattr(runtime, "cleanup_android_remote", lambda receipt: [])
    assert runtime._disconnect_remote_handle_sync(remote) == []
    assert native[0][0].shutdowns == 1


def test_foreign_forward_is_never_removed(monkeypatch):
    bridge = android.AndroidBootstrapResult("adb", "chosen", "", "", "", "127.0.0.1",
                                            62001, 38922, "", "tcp:62001", created_forward=True)
    commands = []
    monkeypatch.setattr(android, "_list_adb_forwards_for_cleanup",
        lambda endpoint: [["foreign", "tcp:62001", "localabstract:renderdoc_38922"]])
    monkeypatch.setattr(android, "_run_subprocess", lambda cmd, **kwargs: commands.append(cmd))
    assert android.cleanup_android_remote(bridge) == ["ADB forward identity changed; refusing to remove it"]
    assert bridge.created_forward
    assert all("--remove" not in command for command in commands)


def test_trigger_uses_one_control_for_capture_and_poll(native):
    remote = handle(known_targets={"38920": {"target_id": "38920", "ident": 38920}})
    runtime._trigger_remote_capture_sync(remote, target_id="38920", num_frames=2)
    assert len(native[0]) == 1
    assert native[0][0].triggers == [2]
    assert native[0][0].shutdowns == 1


@pytest.mark.parametrize("operation", ["poll", "copy", "delete"])
@pytest.mark.parametrize("fail", [False, True])
def test_capture_operations_release_the_control(native, monkeypatch, tmp_path, operation, fail):
    remote = handle()
    destination = tmp_path / "capture.rdc"
    def effect(*args):
        if fail:
            raise OSError("action failed")
        destination.write_bytes(b"capture")
    def create(*args):
        control = Control()
        control.CopyCapture = effect
        control.DeleteCapture = effect
        native[0].append(control)
        return control
    def drain(*args, **kwargs):
        if fail and operation == "poll":
            raise OSError("action failed")
        return [{"type": "CaptureCopied", "capture": {"capture_id": "1"}}]
    monkeypatch.setattr(runtime, "_get_rd", lambda: SimpleNamespace(CreateTargetControl=create))
    monkeypatch.setattr(runtime, "_drain_target_control_messages_sync", drain)
    def invoke():
        if operation == "poll":
            runtime._poll_captures_for_target_sync(remote, target_id="38920")
        elif operation == "copy":
            runtime._copy_remote_capture_sync(remote, 38920, 1, destination)
        else:
            runtime._delete_remote_capture_sync(remote, 38920, 1)
    if fail:
        with pytest.raises(OSError, match="action failed"):
            invoke()
    else:
        invoke()
    assert native[0][0].shutdowns == 1
    assert not remote.target_control_leases


def test_copy_first_capture_completes_through_real_message_drain(monkeypatch, tmp_path):
    remote = handle()
    destination = tmp_path / "first-capture.rdc"
    messages = iter([
        SimpleNamespace(type=1, newCapture=SimpleNamespace(captureId=0, path=str(destination), local=True)),
        SimpleNamespace(type=2),
    ])
    control = Control()
    copies = []
    def copy(capture_id, path):
        copies.append((capture_id, path))
        Path(path).write_bytes(b"capture-zero")
    control.CopyCapture = copy
    control.ReceiveMessage = lambda progress: next(messages)
    monkeypatch.setattr(runtime, "_get_rd", lambda: SimpleNamespace(
        CreateTargetControl=lambda *args: control,
        TargetControlMessageType=SimpleNamespace(Noop=0, CaptureCopied=1, Disconnected=2),
    ))
    runtime._copy_remote_capture_sync(remote, 38920, 0, destination)
    assert copies == [(0, str(destination))]
    assert remote.known_captures["0"]["capture_id"] == "0"
    assert remote.known_captures["0"]["message_type"] == "CaptureCopied"
    assert remote.known_captures["0"]["target_id"] == "38920"
    assert control.shutdowns == 1
    assert not remote.target_control_leases


@pytest.mark.parametrize("message_type", ["NewCapture", "CaptureCopied"])
def test_registry_preserves_explicit_capture_zero(message_type):
    remote = handle()
    record = runtime._update_remote_capture_registry_from_message(
        remote, target_id="38920", message_type=message_type,
        message=SimpleNamespace(newCapture=SimpleNamespace(captureId=0)),
    )
    assert record["capture_id"] == "0"
    assert remote.known_captures["0"] is record


@pytest.mark.parametrize("capture", [None, SimpleNamespace(), SimpleNamespace(captureId=-1),
                                     SimpleNamespace(captureId=None), SimpleNamespace(captureId=""),
                                     SimpleNamespace(captureId=False)])
def test_registry_rejects_missing_negative_or_malformed_capture_ids(capture):
    remote = handle()
    assert runtime._update_remote_capture_registry_from_message(
        remote, target_id="38920", message_type="CaptureCopied",
        message=SimpleNamespace(newCapture=capture),
    ) is None
    assert remote.known_captures == {}


def test_disconnect_failure_keeps_handle_and_context_ownership(monkeypatch):
    remote = handle(remote_server=object())
    monkeypatch.setattr(runtime._runtime, "remotes", {remote.remote_id: remote})
    monkeypatch.setattr(runtime, "_remote_consumed_payload", lambda remote_id: None)
    monkeypatch.setattr(runtime, "_assert_remote_handle_context", lambda remote: None)
    monkeypatch.setattr(runtime, "_remote_active_session_ids", lambda remote: [])
    monkeypatch.setattr(runtime, "_clear_context_remote_live", lambda remote_id: pytest.fail("ownership cleared"))
    monkeypatch.setattr(runtime, "_disconnect_remote_handle_sync", lambda remote: ["owned forward removal failed"])
    result = json.loads(asyncio.run(runtime._dispatch_remote("disconnect", {"remote_id": remote.remote_id})))
    assert not result["success"]
    assert result["code"] == "remote_disconnect_failed"
    assert runtime._runtime.remotes[remote.remote_id] is remote


def test_disconnect_retry_does_not_reuse_a_closed_native_remote(monkeypatch):
    shutdowns = []
    remote = handle(transport="adb_android", remote_server=SimpleNamespace(
        ShutdownConnection=lambda: shutdowns.append("shutdown")), bootstrap_result=object())
    monkeypatch.setattr(runtime, "cleanup_android_remote", lambda receipt: ["forward remove failed"])
    assert runtime._disconnect_remote_handle_sync(remote) == ["forward remove failed"]
    assert remote.remote_server is None and not remote.connected
    monkeypatch.setattr(runtime, "cleanup_android_remote", lambda receipt: [])
    assert runtime._disconnect_remote_handle_sync(remote) == []
    assert shutdowns == ["shutdown"]


def test_scan_cleanup_failure_cannot_be_reported_as_successful_target(monkeypatch):
    remote = handle()
    control = Control(fail_shutdown=True)
    monkeypatch.setattr(runtime, "_get_rd", lambda: SimpleNamespace(
        EnumerateRemoteTargets=lambda host, prior: 38920 if prior == 0 else 0,
        CreateTargetControl=lambda *a: control))
    monkeypatch.setattr(runtime, "_drain_target_control_messages_sync", lambda *a, **kw: [])
    with pytest.raises(runtime.RuntimeToolError, match="cleanup failed"):
        runtime._remote_list_targets_sync(remote)
    assert len(remote.target_control_leases) == 1


def test_cancel_joins_native_target_cleanup_before_returning():
    entered = threading.Event()
    release = threading.Event()
    cleaned = threading.Event()
    def work():
        entered.set()
        try:
            assert release.wait(5)
        finally:
            cleaned.set()
    async def scenario():
        task = asyncio.create_task(runtime._offload_target_operation(work))
        while not entered.is_set():
            await asyncio.sleep(0.01)
        task.cancel()
        await asyncio.sleep(0.02)
        assert not task.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert cleaned.is_set()
    asyncio.run(scenario())


def test_native_control_creation_has_one_scoped_call_site():
    source = inspect.getsource(runtime)
    assert source.count(".CreateTargetControl(") == 1
    assert "_create_target_control_sync" not in source
    assert ".CreateTargetControl(" in inspect.getsource(runtime._target_control_scope_sync)


@pytest.fixture
def capture_options_binding(monkeypatch):
    # The current same-source 1.48 PYD exposes this constructor, not the old
    # GetDefaultCaptureOptions free function. Defaults match capture_options.h.
    instances = []

    class CaptureOptions:
        def __init__(self):
            self.allowVSync = True
            self.allowFullscreen = True
            self.apiValidation = False
            self.captureCallstacks = False
            self.captureCallstacksOnlyActions = False
            self.delayForDebugger = 0
            self.verifyBufferAccess = False
            self.hookIntoChildren = False
            self.refAllResources = False
            self.captureAllCmdLists = False
            self.debugOutputMute = True
            self.softMemoryLimit = 0
            instances.append(self)

    binding = SimpleNamespace(CaptureOptions=CaptureOptions)
    monkeypatch.setattr(runtime, "_get_rd", lambda: binding)
    return binding, instances


def test_capture_options_use_current_binding_constructor_and_fresh_defaults(capture_options_binding):
    options, applied = runtime._capture_options_from_dict({
        "allow_vsync": "false", "api_validation": "true", "delay_for_debugger": "7",
    })
    assert applied == {"allow_vsync": False, "api_validation": True, "delay_for_debugger": 7}
    assert options.allowVSync is False and options.apiValidation is True
    assert options.delayForDebugger == 7
    assert options.allowFullscreen is True and options.debugOutputMute is True
    fresh, applied = runtime._capture_options_from_dict({})
    assert fresh is not options and applied == {}
    assert fresh.allowVSync is True and fresh.apiValidation is False
    assert fresh.delayForDebugger == 0


def test_set_capture_options_uses_current_binding_without_target(capture_options_binding, monkeypatch):
    remote = handle(remote_server=object(), default_capture_options={"allow_fullscreen": False})
    monkeypatch.setattr(runtime._runtime, "remotes", {remote.remote_id: remote})
    monkeypatch.setattr(runtime, "_remote_consumed_payload", lambda remote_id: None)
    monkeypatch.setattr(runtime, "_assert_remote_handle_context", lambda remote: None)
    result = json.loads(asyncio.run(runtime._dispatch_remote("set_capture_options", {
        "remote_id": remote.remote_id, "options": {"api_validation": True, "delay_for_debugger": 3},
    })))
    assert result["success"] is True
    assert result["applied"] == {"api_validation": True, "delay_for_debugger": 3}
    assert remote.default_capture_options == {
        "allow_fullscreen": False, "api_validation": True, "delay_for_debugger": 3,
    }
    assert not remote.known_targets and not remote.target_control_leases


def test_launch_passes_current_capture_options_with_explicit_override(capture_options_binding, monkeypatch):
    binding, instances = capture_options_binding
    executed = []
    control = Control()
    binding.CreateTargetControl = lambda *args: control
    monkeypatch.setattr(runtime, "_drain_target_control_messages_sync", lambda *args, **kwargs: [])

    def execute(*args):
        executed.append(args)
        return SimpleNamespace(ident=38920, result=SimpleNamespace(OK=lambda: True))

    remote = handle(remote_server=SimpleNamespace(ExecuteAndInject=execute),
                    default_capture_options={"allow_vsync": False, "api_validation": True})
    target = runtime._launch_remote_app_sync(
        remote, exe_path="test-app", working_dir="", cmdline="", env={},
        capture_options={"allow_vsync": True, "delay_for_debugger": 5},
    )
    assert executed[0][4] is instances[0]
    assert instances[0].allowVSync is True and instances[0].apiValidation is True
    assert instances[0].delayForDebugger == 5
    assert target["capture_options"] == {
        "allow_vsync": True, "api_validation": True, "delay_for_debugger": 5,
    }
    assert remote.default_capture_options == {"allow_vsync": False, "api_validation": True}
    assert control.shutdowns == 1 and not remote.target_control_leases
