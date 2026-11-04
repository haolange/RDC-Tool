from __future__ import annotations

from types import SimpleNamespace

import pytest

from rdc_tool import remote_bootstrap
from rdc_tool.remote_bootstrap import AdbDevice, AndroidBootstrapResult


@pytest.fixture(autouse=True)
def _no_real_adb_server_socket(monkeypatch):
    monkeypatch.setattr(remote_bootstrap.socket, 'create_connection',
        lambda *args, **kwargs: pytest.fail('Test must supply a fake ADB server protocol response'))


def _forward_frame(payload=b''):
    return b'OKAY' + f'{len(payload):04x}'.encode('ascii') + payload


@pytest.fixture
def adb_forward_protocol(monkeypatch):
    for name in ('ADB_SERVER_SOCKET', 'ANDROID_ADB_SERVER_ADDRESS', 'ANDROID_ADB_SERVER_PORT'):
        monkeypatch.delenv(name, raising=False)
    state = SimpleNamespace(calls=[], connections=[])

    class Connection:
        def __init__(self, chunks):
            self.chunks = list(chunks) if isinstance(chunks, list) else [chunks]
            self.closed, self.timeouts, self.sent = False, [], []
            self.on_recv = lambda: None
        def __enter__(self): return self
        def __exit__(self, *args): self.closed = True
        def settimeout(self, value): self.timeouts.append(value)
        def sendall(self, data): self.sent.append(data)
        def recv(self, size):
            self.on_recv()
            part = self.chunks.pop(0) if self.chunks else b''
            if isinstance(part, BaseException):
                raise part
            if len(part) > size:
                self.chunks.insert(0, part[size:])
                part = part[:size]
            return part

    def configure(responses):
        packets = iter(responses)
        def connect(endpoint, timeout):
            state.calls.append((endpoint, timeout))
            packet = next(packets)
            if isinstance(packet, BaseException):
                raise packet
            connection = Connection(packet)
            state.connections.append(connection)
            return connection
        monkeypatch.setattr(remote_bootstrap.socket, 'create_connection', connect)
        return state
    return configure


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
    assert payload["owned_pids"] == [123]
    assert payload["pushed_config"] is True
    assert payload["started_activity"] is True
    assert payload["created_forward"] is True
    assert payload["install_mode"] == "force_replace"
    assert payload["install_reason"] == "signature_mismatch"
    assert payload["uninstalled_existing"] is True
    assert payload["cleanup_actions"] == ["apk-installed", "adb-forward"]


def test_install_helper_preserves_existing_apk(monkeypatch: pytest.MonkeyPatch) -> None:
    commands = []
    def fake_run(cmd, **kwargs):
        commands.append(cmd)
        return SimpleNamespace(returncode=0, stdout="package:org.renderdoc.renderdoccmd.arm64\n", stderr="")
    monkeypatch.setattr(remote_bootstrap.subprocess, "run", fake_run)
    result = AndroidBootstrapResult(adb_path="adb", device_serial="serial-1", package_name="org.renderdoc.renderdoccmd.arm64",
        activity_name="helper.Loader", abi="arm64-v8a", host="127.0.0.1", port=38960, remote_port=38920,
        apk_path="apk", forward_spec="tcp:38960")
    remote_bootstrap._ensure_android_helper_installed(result, remote_bootstrap.AndroidBootstrapOptions())
    assert result.installed_apk is False
    assert result.install_mode == "existing"
    assert result.uninstalled_existing is False
    assert not any("install" in cmd or "uninstall" in cmd for cmd in commands)


def test_install_helper_reports_failure_without_destructive_retry(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    commands = []
    apk = tmp_path / "helper.apk"
    apk.write_bytes(b"fixture")
    monkeypatch.setattr(remote_bootstrap, "read_apk_identity", lambda _: {"package_name": "org.renderdoc.renderdoccmd.arm64", "version_code": 145, "apk_sha256": "a" * 64})
    def fake_run(cmd, **kwargs):
        commands.append(cmd)
        if cmd[-3:] == ["dumpsys", "package", "installs"]:
            return SimpleNamespace(returncode=0, stdout="Active install sessions:\n", stderr="")
        if "shell" in cmd:
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        return SimpleNamespace(returncode=1, stdout="", stderr="INSTALL_FAILED_VERSION_DOWNGRADE")
    monkeypatch.setattr(remote_bootstrap.subprocess, "run", fake_run)
    result = AndroidBootstrapResult(adb_path="adb", device_serial="serial-1", package_name="org.renderdoc.renderdoccmd.arm64",
        activity_name="helper.Loader", abi="arm64-v8a", host="127.0.0.1", port=38960, remote_port=38920,
        apk_path=str(apk), forward_spec="tcp:38960")
    with pytest.raises(remote_bootstrap.AndroidRemoteBootstrapError) as excinfo:
        remote_bootstrap._ensure_android_helper_installed(result, remote_bootstrap.AndroidBootstrapOptions())
    assert excinfo.value.code == "android_apk_install_failed"
    assert result.uninstalled_existing is False
    assert not any("uninstall" in cmd or "-r" in cmd for cmd in commands)
    assert len([cmd for cmd in commands if "install" in cmd]) == 1


@pytest.mark.parametrize("sdk_level,storage_dir", [(29, "data"), (30, "media"), (35, "media")])
@pytest.mark.parametrize("remote_state", ["existing", "missing"])
def test_owned_helper_config_preserves_existing_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path, remote_state: str, sdk_level: int, storage_dir: str
) -> None:
    commands: list[list[str]] = []
    local_config = tmp_path / "renderdoc.conf"
    local_config.write_text("", encoding="utf-8")
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

    def fake_shell(adb_path: str, device_serial: str, *args: str, **_: object) -> SimpleNamespace:
        commands.append([adb_path, device_serial, *args])
        if args[:2] == ("getprop", "ro.build.version.sdk"):
            return SimpleNamespace(stdout=str(sdk_level))
        return SimpleNamespace(stdout=remote_state if args[0].startswith("if ") else "")

    def fake_run(cmd: list[str], **_: object) -> SimpleNamespace:
        commands.append(cmd)
        return SimpleNamespace(stdout="")

    monkeypatch.setattr(remote_bootstrap, "_adb_shell", fake_shell)
    monkeypatch.setattr(remote_bootstrap, "_run_subprocess", fake_run)
    monkeypatch.setattr(remote_bootstrap, "_write_renderdoc_conf", lambda _: local_config)

    remote_bootstrap._ensure_renderdoc_conf(result)

    assert result.config_remote_path == (
        f"/sdcard/Android/{storage_dir}/{result.package_name}/files/renderdoc.conf"
    )
    assert result.pushed_config is (remote_state == "missing")
    assert any("push" in cmd for cmd in commands) is (remote_state == "missing")
    assert result.config_local_path == (str(local_config) if remote_state == "missing" else "")


def test_owned_helper_config_rejects_unknown_remote_file_type(monkeypatch: pytest.MonkeyPatch) -> None:
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
    def fake_shell(*args: object, **_: object) -> SimpleNamespace:
        return SimpleNamespace(stdout="30" if args[2:4] == ("getprop", "ro.build.version.sdk") else "invalid")

    monkeypatch.setattr(remote_bootstrap, "_adb_shell", fake_shell)

    with pytest.raises(remote_bootstrap.AndroidRemoteBootstrapError) as excinfo:
        remote_bootstrap._ensure_renderdoc_conf(result)

    assert excinfo.value.code == "android_config_probe_failed"
    assert result.pushed_config is False


@pytest.mark.parametrize("sdk_level", ["", "unknown", "0"])
def test_owned_helper_config_rejects_unknown_sdk(monkeypatch: pytest.MonkeyPatch, sdk_level: str) -> None:
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
    monkeypatch.setattr(remote_bootstrap, "_adb_shell", lambda *a, **k: SimpleNamespace(stdout=sdk_level))

    with pytest.raises(remote_bootstrap.AndroidRemoteBootstrapError) as excinfo:
        remote_bootstrap._ensure_renderdoc_conf(result)

    assert excinfo.value.code == "android_sdk_probe_failed"
    assert result.config_remote_path == ""
    assert result.pushed_config is False


def test_cleanup_android_remote_removes_forward_and_config(monkeypatch: pytest.MonkeyPatch, tmp_path, adb_forward_protocol) -> None:
    commands: list[list[str]] = []
    adb_forward_protocol([_forward_frame(b'serial-1 tcp:38960 localabstract:renderdoc_38920\n'), _forward_frame()])

    def _fake_run(cmd: list[str], **_: object) -> SimpleNamespace:
        commands.append(list(cmd))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

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
    assert any('--remove' in cmd and cmd[cmd.index('-s') + 1] == 'serial-1' for cmd in commands)
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
    def readonly_identity(adb, serial, *args, **kwargs):
        commands.append([adb, '-s', serial, 'shell', *args])
        if args == ('pm', 'path', f'org.renderdoc.renderdoccmd.{arch}'):
            return SimpleNamespace(stdout='package:/data/app/helper/base.apk\n', stderr='')
        if args == ('sha256sum', '/data/app/helper/base.apk'):
            return SimpleNamespace(stdout='b' * 64 + '  /data/app/helper/base.apk\n', stderr='')
        return forbidden()
    monkeypatch.setattr(remote_bootstrap, '_adb_shell', readonly_identity)
    monkeypatch.setattr(remote_bootstrap, 'read_apk_identity', lambda _: {'package_name': f'org.renderdoc.renderdoccmd.{arch}', 'apk_sha256': 'a' * 64})
    monkeypatch.setattr(remote_bootstrap, '_list_renderdoc_socket_ports', lambda *a: [38920])
    result = remote_bootstrap.bootstrap_android_remote()
    assert result.started_activity is False and result.owned_pids == []
    assert result.installed_apk is False and result.pushed_config is False
    assert result.created_forward is True
    assert result.package_name.endswith(arch)
    assert ['adb', '-s', 'serial-1', 'forward', '--no-rebind', 'tcp:38960', 'localabstract:renderdoc_38920'] in commands
    assert result.apk_sha256 == 'a' * 64
    assert result.installed_apk_sha256 == 'b' * 64
    assert result.apk_identity_status == 'different'


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
@pytest.mark.parametrize('mapping', ['\n', 'other tcp:38960 localabstract:renderdoc_38920\n', 'serial-1 tcp:38960 localabstract:renderdoc_40000\n'])
def test_borrowed_cleanup_never_stops_helper_or_removes_foreign_forward(monkeypatch, mapping, adb_forward_protocol):
    commands = []
    state = adb_forward_protocol([_forward_frame(mapping.encode() if mapping.strip() else b'')])
    def run(cmd, **kwargs):
        commands.append(cmd)
        return SimpleNamespace(returncode=0, stdout=mapping, stderr='')
    monkeypatch.setattr(remote_bootstrap, '_run_subprocess', run)
    monkeypatch.setattr(remote_bootstrap, '_adb_shell', lambda *a, **k: pytest.fail('borrowed helper must survive'))
    result = AndroidBootstrapResult('adb', 'serial-1', 'helper', '', '', '127.0.0.1', 38960, 38920, '', 'tcp:38960', created_forward=True)
    errors = remote_bootstrap.cleanup_android_remote(result)
    assert bool(errors) == bool(mapping.strip())
    assert all('--remove' not in command for command in commands)
    if not mapping.strip():
        assert remote_bootstrap.cleanup_android_remote(result) == []
        assert len(state.calls) == 1 and not commands


@pytest.mark.parametrize('packet', [
    b'', b'OK', b'NOPE', b'OKAY00', b'OKAYzzzz', b'OKAY0031short',
    b'FAIL0006denied', b'FAIL0010short',
    _forward_frame(b'\xff\n'), _forward_frame(b'malformed\n'),
    _forward_frame(b'serial-1 tcp:38960 localabstract:renderdoc_38920'),
    _forward_frame(b'serial-1 tcp:38960 localabstract:renderdoc_38920 extra\n'),
    TimeoutError('connect timeout'), [b'OKAY', TimeoutError('read timeout')],
])
def test_forward_cleanup_unreadable_listing_retains_ownership(monkeypatch, packet, adb_forward_protocol):
    commands = []
    state = adb_forward_protocol([packet])
    def run(cmd, **kwargs):
        commands.append(cmd)
        pytest.fail('Unconfirmed query must not issue an ADB mutation')
    monkeypatch.setattr(remote_bootstrap, '_run_subprocess', run)
    result = AndroidBootstrapResult('adb', 'serial-1', '', '', '', '127.0.0.1',
        38960, 38920, '', 'tcp:38960', created_forward=True)
    errors = remote_bootstrap.cleanup_android_remote(result)
    assert errors and 'cleanup unconfirmed' in errors[0]
    assert result.created_forward is True
    assert not commands and len(state.calls) == 1
    assert all(connection.closed for connection in state.connections)


@pytest.mark.parametrize('post_state', ['still_present', 'empty_output', 'truncated', 'bad_status', 'query_failed', 'external_rebind'])
def test_forward_cleanup_requires_confirmed_post_remove_absence(monkeypatch, post_state, adb_forward_protocol):
    owned = b'serial-1 tcp:38960 localabstract:renderdoc_38920\n'
    packet = {
        'still_present': _forward_frame(owned),
        'empty_output': b'',
        'truncated': b'OKAY0031short',
        'bad_status': b'WHAT',
        'query_failed': OSError('query failed'),
        'external_rebind': _forward_frame(b'foreign tcp:38960 localabstract:renderdoc_38920\n'),
    }[post_state]
    state = adb_forward_protocol([_forward_frame(owned), packet])
    commands = []
    def run(cmd, **kwargs):
        commands.append(cmd)
        return SimpleNamespace(returncode=0, stdout='', stderr='')
    monkeypatch.setattr(remote_bootstrap, '_run_subprocess', run)
    result = AndroidBootstrapResult('adb', 'serial-1', '', '', '', '127.0.0.1',
        38960, 38920, '', 'tcp:38960', created_forward=True)
    errors = remote_bootstrap.cleanup_android_remote(result)
    assert errors and result.created_forward is True
    assert commands == [['adb', '-H', 'localhost', '-P', '5037', '-s', 'serial-1', 'forward', '--remove', 'tcp:38960']]
    assert len(state.calls) == 2 and all(connection.closed for connection in state.connections)


def test_forward_cleanup_accepts_confirmed_empty_after_remove(monkeypatch, adb_forward_protocol):
    commands = []
    state = adb_forward_protocol([_forward_frame(b'serial-1 tcp:38960 localabstract:renderdoc_38920\n'), _forward_frame()])
    def run(cmd, **kwargs):
        commands.append(cmd)
        return SimpleNamespace(returncode=0, stdout='', stderr='')
    monkeypatch.setattr(remote_bootstrap, '_run_subprocess', run)
    result = AndroidBootstrapResult('adb', 'serial-1', '', '', '', '127.0.0.1',
        38960, 38920, '', 'tcp:38960', created_forward=True)
    assert remote_bootstrap.cleanup_android_remote(result) == []
    assert result.created_forward is False
    assert len(state.calls) == 2 and all(connection.closed for connection in state.connections)
    assert all(connection.sent == [b'0011host:list-forward'] for connection in state.connections)
    assert sum('--remove' in command for command in commands) == 1
    assert all('--list' not in command for command in commands)


def test_forward_protocol_reads_fragmented_status_length_and_payload(adb_forward_protocol):
    payload = b'serial-1 tcp:38960 localabstract:renderdoc_38920\n'
    state = adb_forward_protocol([[bytes([value]) for value in _forward_frame(payload)]])
    assert remote_bootstrap._list_adb_forwards_for_cleanup(('localhost', 5037)) == [
        ['serial-1', 'tcp:38960', 'localabstract:renderdoc_38920']]
    assert state.connections[0].sent == [b'0011host:list-forward']
    assert state.connections[0].closed


def test_forward_protocol_accepts_exact_maximum_length(adb_forward_protocol):
    payload = b'serial tcp:1 ' + b'x' * (65535 - len(b'serial tcp:1 \n')) + b'\n'
    assert len(payload) == 65535
    state = adb_forward_protocol([_forward_frame(payload)])
    rows = remote_bootstrap._list_adb_forwards_for_cleanup(('localhost', 5037))
    assert len(rows) == 1 and rows[0][:2] == ['serial', 'tcp:1']
    assert state.connections[0].closed


def test_forward_protocol_one_deadline_includes_connect_and_fragment_reads(monkeypatch, adb_forward_protocol):
    payload = b'serial-1 tcp:38960 localabstract:renderdoc_38920\n'
    state = adb_forward_protocol([[bytes([value]) for value in _forward_frame(payload)]])
    clock = [0.0]
    monkeypatch.setattr(remote_bootstrap.time, 'monotonic', lambda: clock[0])
    connect = remote_bootstrap.socket.create_connection
    def delayed_connect(endpoint, timeout):
        assert timeout == 10.0
        clock[0] += 3.0
        connection = connect(endpoint, timeout)
        connection.on_recv = lambda: clock.__setitem__(0, clock[0] + 2.0)
        return connection
    monkeypatch.setattr(remote_bootstrap.socket, 'create_connection', delayed_connect)
    with pytest.raises(remote_bootstrap.AndroidRemoteBootstrapError, match='deadline exceeded'):
        remote_bootstrap._list_adb_forwards_for_cleanup(('localhost', 5037))
    assert len(state.calls) == 1 and state.connections[0].closed
    assert state.connections[0].timeouts == [7.0, 7.0, 5.0, 3.0, 1.0]


@pytest.mark.parametrize('environment,expected', [
    ({}, ('localhost', 5037)),
    ({'ANDROID_ADB_SERVER_ADDRESS':'adb.example', 'ANDROID_ADB_SERVER_PORT':'6200'}, ('adb.example', 6200)),
    ({'ANDROID_ADB_SERVER_PORT':''}, ('localhost', 5037)),
    ({'ADB_SERVER_SOCKET':'tcp:6300', 'ANDROID_ADB_SERVER_ADDRESS':'ignored', 'ANDROID_ADB_SERVER_PORT':'invalid'}, ('localhost', 6300)),
    ({'ADB_SERVER_SOCKET':'tcp:adb.example:6301'}, ('adb.example', 6301)),
    ({'ADB_SERVER_SOCKET':'tcp:adb.example'}, ('adb.example', 5555)),
    ({'ADB_SERVER_SOCKET':'tcp:[::1]:6302'}, ('::1', 6302)),
    ({'ADB_SERVER_SOCKET':'tcp:::1'}, ('::1', 5555)),
    ({'ANDROID_ADB_SERVER_ADDRESS':'[::1]', 'ANDROID_ADB_SERVER_PORT':'6303'}, ('::1', 6303)),
])
def test_adb_server_endpoint_matches_cli_environment_priority(monkeypatch, environment, expected, adb_forward_protocol):
    for name, value in environment.items():
        monkeypatch.setenv(name, value)
    assert remote_bootstrap._adb_server_endpoint() == expected


@pytest.mark.parametrize('environment', [
    {'ADB_SERVER_SOCKET':'localfilesystem:/tmp/adb.sock'},
    {'ADB_SERVER_SOCKET':''}, {'ADB_SERVER_SOCKET':'tcp:'},
    {'ADB_SERVER_SOCKET':'tcp:0'}, {'ADB_SERVER_SOCKET':'tcp:65536'},
    {'ADB_SERVER_SOCKET':'tcp:host:'}, {'ADB_SERVER_SOCKET':'tcp:[::1]'},
    {'ANDROID_ADB_SERVER_ADDRESS':''}, {'ANDROID_ADB_SERVER_PORT':'invalid'},
])
def test_forward_cleanup_unsupported_endpoint_never_falls_back(monkeypatch, environment, adb_forward_protocol):
    state = adb_forward_protocol([])
    for name, value in environment.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(remote_bootstrap, '_run_subprocess', lambda *a, **kw: pytest.fail('No mutation on unknown server'))
    result = AndroidBootstrapResult('adb', 'serial-1', '', '', '', '127.0.0.1',
        38960, 38920, '', 'tcp:38960', created_forward=True)
    assert 'cleanup unconfirmed' in remote_bootstrap.cleanup_android_remote(result)[0]
    assert result.created_forward and not state.calls


@pytest.mark.parametrize('host,command_host', [('adb.example','adb.example'), ('::1','[::1]')])
def test_forward_cleanup_fixes_same_endpoint_for_mutation_and_postquery(monkeypatch, adb_forward_protocol, host, command_host):
    state = adb_forward_protocol([_forward_frame(b'serial-1 tcp:38960 localabstract:renderdoc_38920\n'), _forward_frame()])
    monkeypatch.setenv('ADB_SERVER_SOCKET', f'tcp:{command_host}:6300')
    monkeypatch.setenv('ANDROID_ADB_SERVER_ADDRESS', 'ignored.example')
    monkeypatch.setenv('ANDROID_ADB_SERVER_PORT', 'invalid')
    commands = []
    def remove(cmd, **kwargs):
        commands.append(cmd)
        # A change after the first query cannot redirect removal or confirmation.
        monkeypatch.setenv('ADB_SERVER_SOCKET', 'tcp:other.example:9999')
        return SimpleNamespace(returncode=0, stdout='', stderr='')
    monkeypatch.setattr(remote_bootstrap, '_run_subprocess', remove)
    result = AndroidBootstrapResult('adb', 'serial-1', '', '', '', '127.0.0.1',
        38960, 38920, '', 'tcp:38960', created_forward=True)
    assert remote_bootstrap.cleanup_android_remote(result) == []
    assert not result.created_forward
    assert [call[0] for call in state.calls] == [(host,6300), (host,6300)]
    assert commands == [['adb','-H',command_host,'-P','6300','-s','serial-1','forward','--remove','tcp:38960']]


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


def test_borrowed_delayed_socket_and_cancel_after_forward_roll_back_only_forward(monkeypatch, adb_forward_protocol):
    result = AndroidBootstrapResult('adb', 'serial-1', 'helper', '', '', '127.0.0.1', 38960, 38920, '', 'tcp:38960')
    probes = iter([[], [], [38920]])
    monkeypatch.setattr(remote_bootstrap, '_list_renderdoc_socket_ports', lambda *a: next(probes))
    monkeypatch.setattr(remote_bootstrap.time, 'sleep', lambda *a: None)
    monkeypatch.setattr(remote_bootstrap, '_adb_shell', lambda *a, **k: pytest.fail('borrowed helper mutation'))
    budget = remote_bootstrap.ConnectionBudget(10000)
    commands = []
    adb_forward_protocol([_forward_frame(b'serial-1 tcp:38960 localabstract:renderdoc_38920\n'), _forward_frame()])
    def run(cmd, **kwargs):
        commands.append(cmd)
        if '--no-rebind' in cmd:
            budget.cancelled.set()
        return SimpleNamespace(returncode=0, stdout='', stderr='')
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
    monkeypatch.setattr(remote_bootstrap, '_ensure_android_helper_installed', lambda *a: None)
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
            remote_bootstrap._prepare_android_service(result, remote_bootstrap.AndroidBootstrapOptions(push_config=False), False, 'helper/.Loader')
        assert error.value.code == 'remote_connect_cancelled'
    finally:
        remote_bootstrap._connection_budget.reset(token)
    assert commands[-1] == ('am', 'force-stop', 'helper')
    assert result.started_activity is False and result.owned_pids == []


def test_noninteractive_adb_never_inherits_worker_protocol_stdin(monkeypatch):
    import subprocess
    calls = []
    def run(argv, **kwargs):
        calls.append(kwargs)
        return SimpleNamespace(returncode=0, stdout="List of devices attached\n", stderr="")
    monkeypatch.setattr(remote_bootstrap.subprocess, "run", run)
    remote_bootstrap._run_process(["adb", "devices", "-l"])
    assert calls[0]["stdin"] == subprocess.DEVNULL


@pytest.mark.skipif(remote_bootstrap.os.name != "nt", reason="Windows ADB process creation")
@pytest.mark.parametrize("with_budget", [False, True])
def test_adb_uses_hidden_child_preserving_captured_stdio(monkeypatch, with_budget):
    captured = []
    def check(cmd, **kwargs):
        captured.append(kwargs)
        return SimpleNamespace(returncode=0, stdout="List of devices attached\nserial device\n", stderr="")
    class Process:
        returncode = 0
        def __init__(self, cmd, **kwargs):
            check(cmd, **kwargs)
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def communicate(self, **kwargs): return "List of devices attached\nserial device\n", ""
    monkeypatch.setattr(remote_bootstrap.subprocess, "run", check)
    monkeypatch.setattr(remote_bootstrap.subprocess, "Popen", Process)
    token = remote_bootstrap._connection_budget.set(remote_bootstrap.ConnectionBudget(1000) if with_budget else None)
    try:
        result = remote_bootstrap._run_process(["adb", "devices", "-l"], capture_output=True, text=True, timeout=1)
    finally:
        remote_bootstrap._connection_budget.reset(token)
    assert "serial device" in result.stdout
    assert captured[0]["creationflags"] == remote_bootstrap.subprocess.CREATE_NEW_PROCESS_GROUP
    assert not captured[0]["creationflags"] & (remote_bootstrap.subprocess.DETACHED_PROCESS | remote_bootstrap.subprocess.CREATE_NO_WINDOW)
    assert captured[0]["stdin"] == remote_bootstrap.subprocess.DEVNULL



@pytest.mark.parametrize("output,code", [
    ("", "adb_devices_invalid_response"),
    ("unexpected output", "adb_devices_invalid_response"),
    ("List of devices attached\n\n", "adb_no_device"),
])
def test_bootstrap_ensures_server_once_and_distinguishes_query_failure_from_absence(monkeypatch, output, code):
    calls = []
    monkeypatch.setattr(remote_bootstrap, "resolve_adb_path", lambda: "owned-adb")
    def run(cmd, **kwargs):
        assert remote_bootstrap._connection_budget.get() is not None
        calls.append(cmd)
        return SimpleNamespace(returncode=0, stdout=output if "devices" in cmd else "", stderr="")
    monkeypatch.setattr(remote_bootstrap, "_run_subprocess", run)
    monkeypatch.setattr(remote_bootstrap, "detect_device_arch", lambda *a: pytest.fail("helper preparation before valid device"))
    with pytest.raises(remote_bootstrap.AndroidRemoteBootstrapError) as error:
        remote_bootstrap.bootstrap_android_remote()
    assert error.value.code == code
    assert calls == [["owned-adb", "start-server"], ["owned-adb", "devices", "-l"]]
    assert remote_bootstrap._connection_budget.get() is None


def installed_apk_result():
    return AndroidBootstrapResult('adb', 'serial', 'org.renderdoc.renderdoccmd.arm64', '', 'arm64',
                                  '127.0.0.1', 1, 2, '', '', apk_sha256='a' * 64)


@pytest.mark.parametrize('actual,status', [('a' * 64, 'matched'), ('b' * 64, 'different')])
def test_installed_apk_hash_is_separate_from_the_target_and_uses_shared_budget(monkeypatch, actual, status):
    result = installed_apk_result()
    budget = remote_bootstrap.ConnectionBudget(10000)
    calls = []
    def run(cmd, **kwargs):
        assert remote_bootstrap._connection_budget.get() is budget
        assert 0 < kwargs['timeout'] <= 5.0
        calls.append(cmd)
        if cmd[-3:] == ['pm', 'path', result.package_name]:
            return SimpleNamespace(returncode=0, stdout='package:/data/app/helper/base.apk\n', stderr='')
        assert cmd[-2:] == ['sha256sum', '/data/app/helper/base.apk']
        return SimpleNamespace(returncode=0, stdout=actual.upper() + '  /data/app/helper/base.apk\n', stderr='')
    monkeypatch.setattr(remote_bootstrap, '_run_process', run)
    token = remote_bootstrap._connection_budget.set(budget)
    try:
        remote_bootstrap._observe_installed_apk(result)
    finally:
        remote_bootstrap._connection_budget.reset(token)
    assert len(calls) == 2
    payload = remote_bootstrap.describe_android_remote(result)
    assert payload['apk_sha256'] == 'a' * 64
    assert payload['installed_apk_path'] == '/data/app/helper/base.apk'
    assert payload['installed_apk_sha256'] == actual
    assert payload['apk_identity_status'] == status


@pytest.mark.parametrize('output,reason', [
    ('', 'installed_apk_missing'),
    ('package:/data/app/helper/base.apk\npackage:/data/app/helper/split.apk\n', 'installed_apk_split_or_ambiguous'),
    ('package:relative/base.apk', 'installed_apk_path_invalid'),
    ('package:/data/app/helper/other.apk', 'installed_apk_path_invalid'),
])
def test_installed_apk_missing_split_or_invalid_path_is_not_assumed_matched(monkeypatch, output, reason):
    result = installed_apk_result()
    calls = []
    def shell(*args, **kwargs):
        calls.append(args)
        return SimpleNamespace(stdout=output, stderr='')
    monkeypatch.setattr(remote_bootstrap, '_adb_shell', shell)
    remote_bootstrap._observe_installed_apk(result)
    assert result.apk_identity_status == 'unavailable'
    assert result.apk_identity_reason == reason
    assert not result.installed_apk_path and not result.installed_apk_sha256
    assert result.apk_sha256 == 'a' * 64
    assert len(calls) == 1


@pytest.mark.parametrize('output,stderr', [
    ('truncated-hash  /data/app/helper/base.apk', ''),
    ('a' * 64 + '  /data/app/other/base.apk', ''),
    ('a' * 64 + '  /data/app/helper/base.apk', 'Permission denied'),
])
def test_unreadable_or_wrong_file_digest_is_unavailable(monkeypatch, output, stderr):
    result = installed_apk_result()
    def shell(adb, serial, *args, **kwargs):
        if args[0] == 'pm':
            return SimpleNamespace(stdout='package:/data/app/helper/base.apk', stderr='')
        return SimpleNamespace(stdout=output, stderr=stderr)
    monkeypatch.setattr(remote_bootstrap, '_adb_shell', shell)
    remote_bootstrap._observe_installed_apk(result)
    assert result.apk_identity_status == 'unavailable'
    assert result.apk_identity_reason == 'installed_apk_hash_unreadable'
    assert result.installed_apk_path == '/data/app/helper/base.apk'
    assert not result.installed_apk_sha256


def test_installed_apk_probe_failure_degrades_only_this_diagnostic(monkeypatch):
    result = installed_apk_result()
    def failed(*args, **kwargs):
        raise remote_bootstrap.AndroidRemoteBootstrapError('android_package_probe_failed', 'unreadable')
    monkeypatch.setattr(remote_bootstrap, '_adb_shell', failed)
    remote_bootstrap._observe_installed_apk(result)
    assert result.apk_identity_status == 'unavailable'
    assert result.apk_identity_reason == 'installed_apk_probe_failed'
    assert result.apk_sha256 == 'a' * 64


def test_missing_local_target_preserves_observed_device_hash_without_claiming_a_match(monkeypatch, tmp_path):
    result = installed_apk_result()
    result.apk_sha256 = ''
    def shell(adb, serial, *args, **kwargs):
        return SimpleNamespace(stdout=('package:/data/app/helper/base.apk' if args[0] == 'pm'
                                      else 'b' * 64 + '  /data/app/helper/base.apk'), stderr='')
    monkeypatch.setattr(remote_bootstrap, '_adb_shell', shell)
    monkeypatch.setattr(remote_bootstrap, 'android_binaries_root', lambda: tmp_path)
    remote_bootstrap._observe_installed_apk(result)
    assert result.installed_apk_sha256 == 'b' * 64
    assert result.apk_sha256 == ''
    assert result.apk_identity_status == 'unavailable'
    assert result.apk_identity_reason == 'target_apk_identity_unavailable'


@pytest.mark.parametrize('code', ['remote_connect_cancelled', 'remote_connect_timeout'])
def test_installed_apk_diagnostic_does_not_swallow_connection_terminal_error(monkeypatch, code):
    result = installed_apk_result()
    expected = remote_bootstrap.AndroidRemoteBootstrapError(code, 'connection terminal')
    def terminal(*args, **kwargs):
        raise expected
    monkeypatch.setattr(remote_bootstrap, '_adb_shell', terminal)
    with pytest.raises(remote_bootstrap.AndroidRemoteBootstrapError) as error:
        remote_bootstrap._observe_installed_apk(result)
    assert error.value is expected


def test_installed_apk_diagnostic_observes_cancellation_after_successful_read(monkeypatch):
    budget = remote_bootstrap.ConnectionBudget(10000)
    calls = []
    def cancelled(*args, **kwargs):
        calls.append(args)
        budget.cancelled.set()
        return SimpleNamespace(stdout='package:/data/app/helper/base.apk', stderr='')
    monkeypatch.setattr(remote_bootstrap, '_adb_shell', cancelled)
    token = remote_bootstrap._connection_budget.set(budget)
    try:
        with pytest.raises(remote_bootstrap.AndroidRemoteBootstrapError) as error:
            remote_bootstrap._observe_installed_apk(installed_apk_result())
        assert error.value.code == 'remote_connect_cancelled'
    finally:
        remote_bootstrap._connection_budget.reset(token)
    assert len(calls) == 1


def test_installed_apk_diagnostic_uses_existing_expired_budget_without_a_new_probe(monkeypatch):
    budget = remote_bootstrap.ConnectionBudget(10000)
    budget.deadline = 0
    monkeypatch.setattr(remote_bootstrap, '_adb_shell', lambda *a, **k: pytest.fail('expired budget must not execute adb'))
    token = remote_bootstrap._connection_budget.set(budget)
    try:
        with pytest.raises(remote_bootstrap.AndroidRemoteBootstrapError) as error:
            remote_bootstrap._observe_installed_apk(installed_apk_result())
        assert error.value.code == 'remote_connect_timeout'
    finally:
        remote_bootstrap._connection_budget.reset(token)


def test_current_package_identity_is_sampled_after_owned_preparation(monkeypatch):
    result = installed_apk_result()
    monkeypatch.setattr(remote_bootstrap, '_list_renderdoc_socket_ports', lambda *a: [38920])
    monkeypatch.setattr(remote_bootstrap, '_ensure_android_helper_installed', lambda result, opts: None)
    monkeypatch.setattr(remote_bootstrap, '_package_pids', lambda *a: [123])
    monkeypatch.setattr(remote_bootstrap, '_adb_shell', lambda *a, **k: SimpleNamespace(stdout='', stderr=''))
    monkeypatch.setattr(remote_bootstrap, '_run_subprocess', lambda *a, **k: SimpleNamespace(stdout='', stderr=''))
    observations = []
    monkeypatch.setattr(remote_bootstrap, '_observe_installed_apk', lambda current: observations.append(
        (current is result, current.started_activity, current.created_forward, list(current.owned_pids))))
    assert remote_bootstrap._prepare_android_service_steps(result, remote_bootstrap.AndroidBootstrapOptions(push_config=False), False, 'helper/.Loader') is result
    assert observations == [(True, True, True, [123])]


def test_bootstrap_server_failure_never_queries_or_prepares_device(monkeypatch):
    calls = []
    monkeypatch.setattr(remote_bootstrap, "resolve_adb_path", lambda: "owned-adb")
    def run(cmd, **kwargs):
        calls.append(cmd)
        raise remote_bootstrap.AndroidRemoteBootstrapError(kwargs["error_code"], "server unavailable")
    monkeypatch.setattr(remote_bootstrap, "_run_subprocess", run)
    with pytest.raises(remote_bootstrap.AndroidRemoteBootstrapError) as error:
        remote_bootstrap.bootstrap_android_remote()
    assert error.value.code == "adb_server_start_failed"
    assert calls == [["owned-adb", "start-server"]]



@pytest.mark.parametrize("state", ["device", "offline", "unauthorized", "bootloader", "recovery", "", "device\nunknown"])
def test_selected_device_queries_only_its_frozen_serial_before_helper_preparation(monkeypatch, state):
    calls = []
    monkeypatch.setattr(remote_bootstrap, "resolve_adb_path", lambda: "owned-adb")
    def run(cmd, **kwargs):
        assert remote_bootstrap._connection_budget.get() is not None
        calls.append(cmd)
        return SimpleNamespace(returncode=0, stdout=state if "get-state" in cmd else "", stderr="")
    monkeypatch.setattr(remote_bootstrap, "_run_subprocess", run)
    arch = []
    monkeypatch.setattr(remote_bootstrap, "detect_device_arch", lambda adb, serial: arch.append(serial) or ("arm64", "arm64-v8a"))
    monkeypatch.setattr(remote_bootstrap, "_package_pids", lambda *args: [42])
    monkeypatch.setattr(remote_bootstrap, "allocate_local_port", lambda _: 38960)
    monkeypatch.setattr(remote_bootstrap, "_prepare_android_service", lambda result, *args: result)
    options = remote_bootstrap.AndroidBootstrapOptions(device_serial=" serial ")
    if state == "device":
        result = remote_bootstrap.bootstrap_android_remote(options=options)
        assert result.device_serial == "serial"
        assert arch == ["serial"]
    else:
        with pytest.raises(remote_bootstrap.AndroidRemoteBootstrapError) as error:
            remote_bootstrap.bootstrap_android_remote(options=options)
        assert error.value.code == ("adb_device_invalid_response" if not state or "\n" in state else "adb_device_unavailable")
        if error.value.code == "adb_device_invalid_response":
            assert error.value.details["command"] == ["owned-adb", "-s", "serial", "get-state"]
            assert error.value.details["returncode"] == 0
            assert error.value.details["stdout"] == state
            assert error.value.details["stderr"] == ""
        assert arch == []
    assert calls == [["owned-adb", "start-server"], ["owned-adb", "-s", "serial", "get-state"]]
    assert remote_bootstrap._connection_budget.get() is None


@pytest.fixture(autouse=True)
def short_install_wait_budget(monkeypatch):
    monkeypatch.setattr(remote_bootstrap, "DEFAULT_ANDROID_TIMEOUT_MS", 5)
