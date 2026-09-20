from __future__ import annotations

from types import SimpleNamespace

import pytest

from rdc_tool import remote_bootstrap
from rdc_tool.remote_bootstrap import AdbDevice, AndroidBootstrapResult


def test_choose_adb_device_requires_serial_when_multiple() -> None:
    devices = [
        AdbDevice(serial="device-a", state="device"),
        AdbDevice(serial="device-b", state="device"),
    ]

    with pytest.raises(remote_bootstrap.AndroidRemoteBootstrapError) as excinfo:
        remote_bootstrap.choose_adb_device(devices)

    assert excinfo.value.code == "adb_multiple_devices"


def test_select_android_package_matches_packaged_apk() -> None:
    package_name, apk_path = remote_bootstrap.select_android_package("arm64")

    assert package_name == "org.renderdoc.renderdoccmd.arm64"
    assert apk_path.is_file()


def test_resolve_adb_path_uses_env_override(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    adb_path = tmp_path / "adb.exe"
    adb_path.write_text("", encoding="utf-8")

    monkeypatch.setenv("RDC_TOOL_ANDROID_ADB_PATH", str(adb_path))
    monkeypatch.setattr(remote_bootstrap.shutil, "which", lambda _: None)

    assert remote_bootstrap.resolve_adb_path() == str(adb_path.resolve())


def test_describe_android_remote_exposes_bootstrap_flags() -> None:
    result = AndroidBootstrapResult(
        adb_path="adb",
        device_serial="serial-1",
        package_name="org.renderdoc.renderdoccmd.arm64",
        activity_name="org.renderdoc.renderdoccmd.arm64.Loader",
        abi="arm64-v8a",
        host="127.0.0.1",
        port=38960,
        remote_port=38920,
        apk_path="apk",
        forward_spec="tcp:38960",
        config_remote_path="/sdcard/Android/data/org.renderdoc.renderdoccmd.arm64/files/renderdoc.conf",
        installed_apk=True,
        pushed_config=True,
        started_activity=True,
        owned_pids=[123],
        created_forward=True,
        install_mode="force_replace",
        install_reason="signature_mismatch",
        uninstalled_existing=True,
        cleanup_actions=["apk-installed", "adb-forward"],
    )

    payload = remote_bootstrap.describe_android_remote(result)

    assert payload["installed_apk"] is True
    assert payload["pushed_config"] is True
    assert payload["started_activity"] is True
    assert payload["created_forward"] is True
    assert payload["install_mode"] == "force_replace"
    assert payload["install_reason"] == "signature_mismatch"
    assert payload["uninstalled_existing"] is True
    assert payload["cleanup_actions"] == ["apk-installed", "adb-forward"]


def test_install_helper_force_replaces_mismatched_apk(monkeypatch: pytest.MonkeyPatch) -> None:
    commands: list[list[str]] = []

    def _fake_run(cmd: list[str], **_: object) -> SimpleNamespace:
        commands.append(list(cmd))
        if "install" in cmd and "-r" in cmd:
            return SimpleNamespace(returncode=1, stdout="", stderr="INSTALL_FAILED_UPDATE_INCOMPATIBLE")
        return SimpleNamespace(returncode=0, stdout="Success", stderr="")

    monkeypatch.setattr(remote_bootstrap.subprocess, "run", _fake_run)

    result = AndroidBootstrapResult(
        adb_path="adb",
        device_serial="serial-1",
        package_name="org.renderdoc.renderdoccmd.arm64",
        activity_name="org.renderdoc.renderdoccmd.arm64.Loader",
        abi="arm64-v8a",
        host="127.0.0.1",
        port=38960,
        remote_port=38920,
        apk_path="apk",
        forward_spec="tcp:38960",
    )

    remote_bootstrap._ensure_android_helper_installed("adb", "serial-1", result.package_name, "apk", result)

    assert result.installed_apk is True
    assert result.install_mode == "force_replace"
    assert result.install_reason == "signature_mismatch"
    assert result.uninstalled_existing is True
    assert any(cmd[:4] == ["adb", "-s", "serial-1", "uninstall"] for cmd in commands)


def test_install_helper_reports_uninstall_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fake_run(cmd: list[str], **_: object) -> SimpleNamespace:
        if "install" in cmd and "-r" in cmd:
            return SimpleNamespace(returncode=1, stdout="", stderr="INSTALL_FAILED_VERSION_DOWNGRADE")
        if "uninstall" in cmd:
            return SimpleNamespace(returncode=1, stdout="", stderr="DELETE_FAILED_INTERNAL_ERROR")
        return SimpleNamespace(returncode=0, stdout="Success", stderr="")

    monkeypatch.setattr(remote_bootstrap.subprocess, "run", _fake_run)

    result = AndroidBootstrapResult(
        adb_path="adb",
        device_serial="serial-1",
        package_name="org.renderdoc.renderdoccmd.arm64",
        activity_name="org.renderdoc.renderdoccmd.arm64.Loader",
        abi="arm64-v8a",
        host="127.0.0.1",
        port=38960,
        remote_port=38920,
        apk_path="apk",
        forward_spec="tcp:38960",
    )

    with pytest.raises(remote_bootstrap.AndroidRemoteBootstrapError) as excinfo:
        remote_bootstrap._ensure_android_helper_installed("adb", "serial-1", result.package_name, "apk", result)

    assert excinfo.value.code == "android_apk_force_replace_uninstall_failed"


def test_cleanup_android_remote_removes_forward_and_config(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    commands: list[list[str]] = []

    def _fake_run(cmd: list[str], **_: object) -> SimpleNamespace:
        commands.append(list(cmd))
        return SimpleNamespace(returncode=0, stdout="serial-1 tcp:38960 localabstract:renderdoc_38920\n" if "--list" in cmd else "", stderr="")

    def _fake_shell(adb_path: str, device_serial: str, *args: str, **_: object) -> SimpleNamespace:
        commands.append([adb_path, "-s", device_serial, "shell", *args])
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(remote_bootstrap, "_run_subprocess", _fake_run)
    monkeypatch.setattr(remote_bootstrap, "_adb_shell", _fake_shell)

    monkeypatch.setattr(remote_bootstrap, "_package_pids", lambda *a: [123])
    config_path = tmp_path / "renderdoc.conf"
    config_path.write_text("", encoding="utf-8")

    result = AndroidBootstrapResult(
        adb_path="adb",
        device_serial="serial-1",
        package_name="org.renderdoc.renderdoccmd.arm64",
        activity_name="org.renderdoc.renderdoccmd.arm64.Loader",
        abi="arm64-v8a",
        host="127.0.0.1",
        port=38960,
        remote_port=38920,
        apk_path="apk",
        forward_spec="tcp:38960",
        config_local_path=str(config_path),
        config_remote_path="/sdcard/Android/data/org.renderdoc.renderdoccmd.arm64/files/renderdoc.conf",
        started_activity=True,
        owned_pids=[123],
        created_forward=True,
    )

    errors = remote_bootstrap.cleanup_android_remote(result)

    assert errors == []
    assert not config_path.exists()
    assert any(cmd[:3] == ["adb", "-s", "serial-1"] and "forward" in cmd for cmd in commands)
    assert any(cmd[:3] == ["adb", "-s", "serial-1"] and "force-stop" in cmd for cmd in commands)

def test_select_remote_socket_port_prefers_requested_port() -> None:
    assert remote_bootstrap._select_remote_socket_port(38920, [39920], [38920, 39920]) == 38920


def test_select_remote_socket_port_falls_back_to_detected_single_port() -> None:
    assert remote_bootstrap._select_remote_socket_port(38920, [], [39920]) == 39920


@pytest.mark.parametrize('arch', ['arm32', 'arm64'])
def test_bootstrap_reuses_running_helper_without_mutation(monkeypatch, arch):
    commands = []
    monkeypatch.setattr(remote_bootstrap, 'resolve_adb_path', lambda: 'adb')
    def run(cmd, **kwargs):
        commands.append(cmd)
        return SimpleNamespace(stdout='List of devices attached\nserial-1 device\n')
    monkeypatch.setattr(remote_bootstrap, '_run_subprocess', run)
    monkeypatch.setattr(remote_bootstrap, 'detect_device_arch', lambda *a: ('arm64', 'arm64-v8a'))
    monkeypatch.setattr(remote_bootstrap, 'allocate_local_port', lambda *a: 38960)
    monkeypatch.setattr(remote_bootstrap, '_package_pids', lambda adb, serial, package: [123] if package.endswith(arch) else [])
    def forbidden(*args, **kwargs):
        raise AssertionError('must not mutate external helper or require local APK')
    monkeypatch.setattr(remote_bootstrap, 'select_android_package', forbidden)
    monkeypatch.setattr(remote_bootstrap, '_ensure_android_helper_installed', forbidden)
    monkeypatch.setattr(remote_bootstrap, '_adb_shell', forbidden)
    monkeypatch.setattr(remote_bootstrap, '_list_renderdoc_socket_ports', lambda *a: [38920])
    result = remote_bootstrap.bootstrap_android_remote()
    assert result.started_activity is False and result.owned_pids == []
    assert result.installed_apk is False and result.pushed_config is False
    assert result.created_forward is True
    assert result.package_name.endswith(arch)
    assert commands[-1] == ['adb', '-s', 'serial-1', 'forward', '--no-rebind', 'tcp:38960', 'localabstract:renderdoc_38920']


@pytest.mark.parametrize('returncode,stdout,stderr', [(1, '', 'device offline'), (0, '', ''), (2, '', '')])
def test_helper_ownership_probe_fails_closed(monkeypatch, returncode, stdout, stderr):
    monkeypatch.setattr(remote_bootstrap.subprocess, 'run', lambda *a, **k: SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr))
    with pytest.raises(remote_bootstrap.AndroidRemoteBootstrapError) as error:
        remote_bootstrap._package_pids('adb', 'serial', 'helper')
    assert error.value.code == 'android_helper_state_unknown'


def test_helper_cleanup_refuses_replaced_process(monkeypatch):
    monkeypatch.setattr(remote_bootstrap, '_package_pids', lambda *a: [456])
    def forbidden(*a, **k):
        raise AssertionError('must not stop replacement helper')
    monkeypatch.setattr(remote_bootstrap, '_adb_shell', forbidden)
    result = AndroidBootstrapResult(adb_path='adb', device_serial='serial', package_name='helper', activity_name='helper.Loader',
        abi='arm64', host='127.0.0.1', port=1, remote_port=2, apk_path='', forward_spec='', started_activity=True, owned_pids=[123])
    assert remote_bootstrap.cleanup_android_remote(result) == ['Helper process identity changed; refusing to stop it']
@pytest.mark.parametrize('mapping', ['', 'other tcp:38960 localabstract:renderdoc_38920', 'serial-1 tcp:38960 localabstract:renderdoc_40000'])
def test_borrowed_cleanup_never_stops_helper_or_removes_foreign_forward(monkeypatch, mapping):
    commands = []
    def run(cmd, **kwargs):
        commands.append(cmd)
        return SimpleNamespace(stdout=mapping)
    monkeypatch.setattr(remote_bootstrap, '_run_subprocess', run)
    monkeypatch.setattr(remote_bootstrap, '_adb_shell', lambda *a, **k: pytest.fail('borrowed helper must survive'))
    result = AndroidBootstrapResult('adb', 'serial-1', 'helper', '', '', '127.0.0.1', 38960, 38920, '', 'tcp:38960', created_forward=True)
    errors = remote_bootstrap.cleanup_android_remote(result)
    assert bool(errors) == bool(mapping)
    assert all('--remove' not in command for command in commands)
    if not mapping:
        assert remote_bootstrap.cleanup_android_remote(result) == []
        assert len(commands) == 1


def test_socket_query_failure_is_not_reported_as_no_sockets(monkeypatch):
    def fail(*a, **k):
        raise remote_bootstrap.AndroidRemoteBootstrapError('android_socket_probe_failed', 'denied')
    monkeypatch.setattr(remote_bootstrap, '_adb_shell', fail)
    with pytest.raises(remote_bootstrap.AndroidRemoteBootstrapError, match='denied'):
        remote_bootstrap._list_renderdoc_socket_ports('adb', 'serial')


def test_budget_rejects_cancel_and_expiry():
    budget = remote_bootstrap.ConnectionBudget(1000)
    budget.cancelled.set()
    with pytest.raises(remote_bootstrap.AndroidRemoteBootstrapError) as error:
        budget.remaining()
    assert error.value.code == 'remote_connect_cancelled'
    budget.cancelled.clear()
    budget.deadline = 0
    with pytest.raises(remote_bootstrap.AndroidRemoteBootstrapError) as error:
        budget.remaining()
    assert error.value.code == 'remote_connect_timeout'


@pytest.mark.parametrize("ports", [[39920, 40020], [38921, 38922]])
def test_socket_selection_rejects_ambiguity_even_with_one_new_socket(ports):
    with pytest.raises(remote_bootstrap.AndroidRemoteBootstrapError) as error:
        remote_bootstrap._select_remote_socket_port(38920, ports[:1], ports)
    assert error.value.code == "android_remote_socket_ambiguous"


def test_borrowed_delayed_socket_and_cancel_after_forward_roll_back_only_forward(monkeypatch):
    result = AndroidBootstrapResult('adb', 'serial-1', 'helper', '', '', '127.0.0.1', 38960, 38920, '', 'tcp:38960')
    probes = iter([[], [], [38920]])
    monkeypatch.setattr(remote_bootstrap, '_list_renderdoc_socket_ports', lambda *a: next(probes))
    monkeypatch.setattr(remote_bootstrap.time, 'sleep', lambda *a: None)
    monkeypatch.setattr(remote_bootstrap, '_adb_shell', lambda *a, **k: pytest.fail('borrowed helper mutation'))
    budget = remote_bootstrap.ConnectionBudget(10000)
    commands = []
    def run(cmd, **kwargs):
        commands.append(cmd)
        if '--no-rebind' in cmd:
            budget.cancelled.set()
        return SimpleNamespace(stdout='serial-1 tcp:38960 localabstract:renderdoc_38920' if '--list' in cmd else '')
    monkeypatch.setattr(remote_bootstrap, '_run_subprocess', run)
    token = remote_bootstrap._connection_budget.set(budget)
    try:
        with pytest.raises(remote_bootstrap.AndroidRemoteBootstrapError) as error:
            remote_bootstrap._prepare_android_service(result, remote_bootstrap.AndroidBootstrapOptions(), True, '')
        assert error.value.code == 'remote_connect_cancelled'
    finally:
        remote_bootstrap._connection_budget.reset(token)
    assert any('--remove' in cmd for cmd in commands)
    assert result.created_forward is False
    assert not result.started_activity and result.owned_pids == []


def test_forward_conflict_does_not_clean_existing_mapping(monkeypatch):
    result = AndroidBootstrapResult('adb', 'serial-1', 'helper', '', '', '127.0.0.1', 38960, 38920, '', 'tcp:38960')
    monkeypatch.setattr(remote_bootstrap, '_list_renderdoc_socket_ports', lambda *a: [38920])
    def run(cmd, **kwargs):
        assert '--no-rebind' in cmd
        raise remote_bootstrap.AndroidRemoteBootstrapError('adb_forward_failed', 'cannot rebind')
    monkeypatch.setattr(remote_bootstrap, '_run_subprocess', run)
    with pytest.raises(remote_bootstrap.AndroidRemoteBootstrapError, match='cannot rebind'):
        remote_bootstrap._prepare_android_service(result, remote_bootstrap.AndroidBootstrapOptions(), True, '')
    assert result.created_forward is False



def test_cancel_during_owned_launch_records_and_stops_only_created_process(monkeypatch):
    result = AndroidBootstrapResult('adb', 'serial-1', 'helper', '', '', '127.0.0.1', 38960, 38920, '', 'tcp:38960')
    budget = remote_bootstrap.ConnectionBudget(10000)
    commands = []
    monkeypatch.setattr(remote_bootstrap, '_list_renderdoc_socket_ports', lambda *a: [])
    monkeypatch.setattr(remote_bootstrap, '_package_pids', lambda *a: [321])
    def shell(adb, serial, *args, **kwargs):
        commands.append(args)
        if args[:2] == ('am', 'start'):
            budget.cancelled.set()
            raise remote_bootstrap.AndroidRemoteBootstrapError('remote_connect_cancelled', 'cancelled while starting')
        assert args == ('am', 'force-stop', 'helper')
    monkeypatch.setattr(remote_bootstrap, '_adb_shell', shell)
    token = remote_bootstrap._connection_budget.set(budget)
    try:
        with pytest.raises(remote_bootstrap.AndroidRemoteBootstrapError) as error:
            remote_bootstrap._prepare_android_service(result, remote_bootstrap.AndroidBootstrapOptions(install_apk=False, push_config=False), False, 'helper/.Loader')
        assert error.value.code == 'remote_connect_cancelled'
    finally:
        remote_bootstrap._connection_budget.reset(token)
    assert commands[-1] == ('am', 'force-stop', 'helper')
    assert result.started_activity is False and result.owned_pids == []
