"""The Android capture transfer runs under a no-progress budget: growth, stall and cancel."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from fakes.android_device import FakeAndroidDevice
from rdc_tool import progress, remote_bootstrap
from rdc_tool.core.session_manager import TransferInterrupted
from rdc_tool.runtime import context_records, live_state, remote_session
from rdc_tool.runtime.operations import session as session_ops


def test_growing_transfers_report_progress_and_finish_without_a_fixed_deadline(monkeypatch, tmp_path):
    device = FakeAndroidDevice(monkeypatch, tmp_path, window_s=0.2)
    device.sync_mode = device.writer_mode = "slow"
    assert device.transfer() == device.destination
    fractions = [fraction for stage, fraction in device.progress if stage == "capture_transfer_progress"]
    assert fractions == sorted(fractions) and fractions[0] < 0.5 < fractions[-1] <= 1.0
    assert device.shell_source in device.size_polls and device.destination in device.size_polls
    assert device.owned == [device.destination] and device.files == {device.destination: device.content}
    assert device.killed == [] and device.state.retained_transfer_dirs == []


def test_stalled_push_kills_the_adb_client_and_retains_the_recovery_path(monkeypatch, tmp_path):
    device = FakeAndroidDevice(monkeypatch, tmp_path, window_s=0.1)
    device.sync_mode = "stall"
    with pytest.raises(RuntimeError, match="sync outcome unconfirmed; retain .*no progress") as error:
        device.transfer()
    assert isinstance(error.value.__cause__, TransferInterrupted) and error.value.__cause__.reason == "stalled"
    assert device.killed == [device.commands[-1]] and device.commands[-1][3] == "push"
    assert device.state.retained_transfer_dirs == [device.shell_dir]
    assert device.shell_directories == {device.shell_dir} and not device.owned


def test_cancelled_request_stops_the_writer_and_keeps_both_recovery_paths(monkeypatch, tmp_path):
    device = FakeAndroidDevice(monkeypatch, tmp_path, window_s=30.0)
    device.writer_mode = "slow"
    scope = progress.RequestScope(request_id="req-transfer", trace_id="trc_transfer")
    device.on_growth = lambda fraction: scope.cancelled.set() if fraction > 0.5 else None
    token = progress._CURRENT_REQUEST.set(scope)
    try:
        with pytest.raises(RuntimeError, match="device writer completion is unknown") as error:
            device.transfer()
    finally:
        progress._CURRENT_REQUEST.reset(token)
    assert isinstance(error.value.__cause__, TransferInterrupted) and error.value.__cause__.reason == "cancelled"
    assert device.destination in str(error.value) and device.shell_dir in str(error.value)
    assert device.killed == [device.commands[-1]]
    assert device.state.retained_transfer_dirs == [device.shell_dir]
    assert not device.owned


@pytest.fixture
def owned_context(monkeypatch):
    context = "android-transfer-cleanup"
    monkeypatch.setattr(live_state, "_runtime_context_id", lambda: context)
    yield context
    context_records._reset_context_snapshot(context)


def test_retained_directories_move_into_the_context_and_clear_context_releases_them(monkeypatch, owned_context, tmp_path):
    device = FakeAndroidDevice(monkeypatch, tmp_path)
    device.state.retained_transfer_dirs.append(device.shell_dir)
    monkeypatch.setattr(live_state, "_session_manager", SimpleNamespace(get_state=lambda session_id: device.state))
    remote_session._record_device_transfers("copy")
    assert device.state.retained_transfer_dirs == []
    assert context_records._context_snapshot(owned_context)["device_transfers"] == [
        {"device_serial": "device", "shell_dir": device.shell_dir}]
    removed = []
    monkeypatch.setattr(remote_bootstrap, "resolve_adb_path", lambda: "adb")
    def remove(adb_path, serial, shell_dir):
        removed.append((adb_path, serial, shell_dir))
        return ["device offline"] if len(removed) == 1 else []
    monkeypatch.setattr(remote_bootstrap, "remove_android_transfer_dir", remove)
    failed = asyncio.run(session_ops.dispatch("clear_context", {"context_id": owned_context}))
    assert failed.ok is False and failed.details["cleanup_reason_code"] == "device_transfer_cleanup_failed"
    assert context_records._context_snapshot(owned_context)["device_transfers"]  # Kept for the next attempt.
    cleared = asyncio.run(session_ops.dispatch("clear_context", {"context_id": owned_context}))
    assert cleared.ok is True
    assert removed == [("adb", "device", device.shell_dir)] * 2
    assert context_records._context_snapshot(owned_context)["device_transfers"] == []


def test_device_transfer_removal_only_touches_its_own_directory(monkeypatch):
    commands = []
    def run(cmd, **kwargs):
        commands.append(cmd)
        token = cmd[-1].rsplit("printf '", 1)[1].split(":", 1)[0]
        return type("Done", (), {"returncode": 0, "stdout": f"{token}:REMOVED\n", "stderr": ""})()
    monkeypatch.setattr(remote_bootstrap, "_run_process", run)
    shell_dir = "/data/local/tmp/rdc-tool-transfer-" + "a" * 32
    assert remote_bootstrap.remove_android_transfer_dir("adb", "serial", shell_dir) == []
    assert commands[0][:4] == ["adb", "-s", "serial", "shell"]
    assert "rm -f " + shell_dir + "/source.rdc && rmdir " + shell_dir in commands[0][4]
    for foreign in ("/data/local/tmp", "/sdcard/rdc-tool-transfer-" + "a" * 32, shell_dir + "/../x"):
        assert remote_bootstrap.remove_android_transfer_dir("adb", "serial", foreign)
    assert len(commands) == 1
