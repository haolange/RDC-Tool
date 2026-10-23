from types import SimpleNamespace

import pytest

from rdc_tool import remote_bootstrap as rb


def result():
    return rb.AndroidBootstrapResult(adb_path="adb", device_serial="device", package_name="org.renderdoc.renderdoccmd.arm64",
        activity_name="helper.Loader", abi="arm64-v8a", host="127.0.0.1", port=1, remote_port=2,
        apk_path="unused.apk", forward_spec="tcp:1")


def runner(monkeypatch, package_output, *, probe_code=0, install_code=0, install_error=""):
    commands = []
    def run(cmd, **kwargs):
        commands.append(cmd)
        if "shell" in cmd and "pm" in cmd:
            return SimpleNamespace(returncode=probe_code, stdout=package_output, stderr="probe denied" if probe_code else "")
        return SimpleNamespace(returncode=install_code, stdout="Success" if not install_code else "", stderr=install_error)
    monkeypatch.setattr(rb.subprocess, "run", run)
    return commands


def test_installed_stopped_helper_is_reused_without_install_or_local_apk(monkeypatch):
    commands = runner(monkeypatch, "package:org.renderdoc.renderdoccmd.arm64\n")
    value = result()
    rb._ensure_android_helper_installed("adb", "device", value.package_name, "does-not-exist.apk", value)
    assert not any("install" in cmd or "uninstall" in cmd for cmd in commands)
    assert value.installed_apk is False
    assert value.uninstalled_existing is False
    assert value.install_mode == "existing"
    assert value.cleanup_actions == []


@pytest.mark.parametrize("output,code", [("", 1), ("Error: inaccessible", 0), ("unrecognized output", 0)])
def test_unknown_package_state_fails_before_any_install(monkeypatch, output, code):
    commands = runner(monkeypatch, output, probe_code=code)
    with pytest.raises(rb.AndroidRemoteBootstrapError) as caught:
        rb._ensure_android_helper_installed("adb", "device", result().package_name, "unused.apk", result())
    assert caught.value.code == "android_package_probe_failed"
    assert not any("install" in cmd or "uninstall" in cmd for cmd in commands)


def test_absent_helper_is_installed_once_without_replace_flag(monkeypatch, tmp_path):
    apk = tmp_path / "helper.apk"
    apk.write_bytes(b"fixture")
    commands = runner(monkeypatch, "")
    value = result()
    rb._ensure_android_helper_installed("adb", "device", value.package_name, str(apk), value)
    installs = [cmd for cmd in commands if "install" in cmd]
    assert len(installs) == 1
    assert "-r" not in installs[0]
    assert not any("uninstall" in cmd for cmd in commands)
    assert value.installed_apk is True
    assert value.uninstalled_existing is False


@pytest.mark.parametrize("failure", ["INSTALL_FAILED_UPDATE_INCOMPATIBLE", "INSTALL_FAILED_VERSION_DOWNGRADE", "INSTALL_FAILED_ALREADY_EXISTS"])
def test_install_failure_or_package_race_never_uninstalls_or_retries(monkeypatch, tmp_path, failure):
    apk = tmp_path / "helper.apk"
    apk.write_bytes(b"fixture")
    commands = runner(monkeypatch, "", install_code=1, install_error=failure)
    with pytest.raises(rb.AndroidRemoteBootstrapError) as caught:
        rb._ensure_android_helper_installed("adb", "device", result().package_name, str(apk), result())
    assert caught.value.code == "android_apk_install_failed"
    assert len([cmd for cmd in commands if "install" in cmd]) == 1
    assert not any("uninstall" in cmd or "-r" in cmd for cmd in commands)


def test_package_probe_stderr_cannot_be_treated_as_absent(monkeypatch):
    commands = []
    def run(cmd, **kwargs):
        commands.append(cmd)
        return SimpleNamespace(returncode=0, stdout="", stderr="permission denied")
    monkeypatch.setattr(rb.subprocess, "run", run)
    with pytest.raises(rb.AndroidRemoteBootstrapError) as caught:
        rb._ensure_android_helper_installed("adb", "device", result().package_name, "unused.apk", result())
    assert caught.value.code == "android_package_probe_failed"
    assert not any("install" in cmd for cmd in commands)


@pytest.mark.parametrize("fresh_install", [False, True])
def test_starting_process_does_not_acquire_existing_installation_config(monkeypatch, fresh_install):
    value = result()
    config_writes = []
    shell_commands = []
    def ensure(*args):
        args[-1].installed_apk = fresh_install
    monkeypatch.setattr(rb, "_ensure_android_helper_installed", ensure)
    monkeypatch.setattr(rb, "_ensure_renderdoc_conf", lambda item: config_writes.append(item.package_name))
    monkeypatch.setattr(rb, "_list_renderdoc_socket_ports", lambda *args: [2])
    monkeypatch.setattr(rb, "_package_pids", lambda *args: [91])
    monkeypatch.setattr(rb, "_is_package_running", lambda *args: True)
    monkeypatch.setattr(rb, "_adb_shell", lambda *args, **kwargs: shell_commands.append(args[2:]))
    monkeypatch.setattr(rb, "_run_subprocess", lambda *args, **kwargs: SimpleNamespace(stdout=""))
    observed = rb._prepare_android_service_steps(value, rb.AndroidBootstrapOptions(), False, "helper/.Loader")
    assert observed.started_activity is True
    assert observed.owned_pids == [91]
    assert observed.created_forward is True
    assert bool(config_writes) is fresh_install
    assert any(command[:2] == ("am", "start") for command in shell_commands)
