from types import SimpleNamespace

import pytest

from rdc_tool import remote_bootstrap as rb
from rdc_tool.android_install_state import parse_active_install_sessions


PACKAGE = "org.renderdoc.renderdoccmd.arm64"


def session(package="null", *, destroyed="false", in_use="true", applied="false", failed="false", final="0"):
    return ("  Active Session 1443114869:\n"
        f"    appPackageName={package} mCommitted=true mSealed=true mStageDirInUse={in_use}\n"
        f"    mDestroyed={destroyed} mSessionApplied={applied} mSessionFailed={failed} mFinalStatus={final}\n")


def output(block=""):
    return "Active install sessions:\n" + block + "\nFinalized install sessions:\n  PRIVATE_OTHER_APP_HISTORY\n"


def result(tmp_path):
    apk = tmp_path / "helper.apk"
    apk.write_bytes(b"fixture")
    return rb.AndroidBootstrapResult("adb", "serial", PACKAGE, "", "arm64-v8a", "127.0.0.1", 1, 2, str(apk), "tcp:1")


@pytest.mark.parametrize("package", ["null", PACKAGE])
def test_pending_target_or_unknown_session_blocks_actual_install(monkeypatch, tmp_path, package):
    current = result(tmp_path)
    monkeypatch.setattr(rb, "read_apk_identity", lambda path: {"package_name": PACKAGE, "apk_sha256": "a" * 64})
    monkeypatch.setattr(rb, "_adb_shell", lambda *args, **kwargs: SimpleNamespace(stdout=output(session(package)), stderr=""))
    monkeypatch.setattr(rb, "_run_process", lambda *args, **kwargs: pytest.fail("pending session cannot trigger another install"))
    with pytest.raises(rb.AndroidRemoteBootstrapError) as error:
        rb._install_android_helper(current, rb.AndroidBootstrapOptions())
    assert error.value.code == "remote_install_unconfirmed"
    action = error.value.details["device_action"]
    assert action["kind"] == "android_install" and action["state"] == "unconfirmed"
    assert action["device_serial"] == "serial" and action["apk_sha256"] == "a" * 64
    assert action["observation"] == "pending"
    assert action["sessions"][0]["session_id"] == "1443114869"
    assert "PRIVATE_OTHER_APP_HISTORY" not in str(error.value.details)


@pytest.mark.parametrize("text,stderr", [("", ""), ("vendor unknown", ""), (output("  Unknown session layout"), ""),
    (output(), "permission denied"), (output("  Active Session 1:\n appPackageName=null"), "")])
def test_unreadable_pm_state_fails_closed_without_install(monkeypatch, tmp_path, text, stderr):
    current = result(tmp_path)
    monkeypatch.setattr(rb, "_adb_shell", lambda *args, **kwargs: SimpleNamespace(stdout=text, stderr=stderr))
    with pytest.raises(rb.AndroidRemoteBootstrapError) as error:
        rb._preflight_android_install(current)
    assert error.value.code == "remote_install_unconfirmed"
    assert error.value.details["device_action"]["observation"] == "unreadable"
    assert error.value.details["device_action"]["sessions"] == []
    assert text not in str(error.value.details) if text else True


@pytest.mark.parametrize("block", ["", session("com.example.other"), session(PACKAGE, in_use="false", applied="true", final="1"),
    session(PACKAGE, destroyed="true", in_use="false", failed="true", final="-110")])
def test_absent_unrelated_or_proven_terminal_sessions_allow_install(monkeypatch, tmp_path, block):
    current = result(tmp_path)
    monkeypatch.setattr(rb, "read_apk_identity", lambda path: {"package_name": PACKAGE, "apk_sha256": "a" * 64})
    calls = []
    def shell(adb, serial, *args, **kwargs):
        calls.append(args)
        assert args == ("dumpsys", "package", "installs")
        return SimpleNamespace(stdout=output(block), stderr="")
    monkeypatch.setattr(rb, "_adb_shell", shell)
    installs = []
    monkeypatch.setattr(rb, "_run_process", lambda command, **kwargs: installs.append(command) or SimpleNamespace(returncode=0, stdout="Success", stderr=""))
    rb._install_android_helper(current, rb.AndroidBootstrapOptions())
    assert len(installs) == 1 and current.installed_apk
    assert calls == [("dumpsys", "package", "installs")]


@pytest.mark.parametrize("destroyed,in_use,failed,final", [("true", "true", "false", "0"),
    ("true", "false", "false", "0"), ("true", "true", "true", "-110")])
def test_abandoned_or_in_use_session_is_not_assumed_terminal(destroyed, in_use, failed, final):
    pending = parse_active_install_sessions(output(session(PACKAGE, destroyed=destroyed, in_use=in_use, failed=failed, final=final)))
    assert len(pending) == 1
    assert pending[0]["session_id"] == "1443114869"


def test_compatible_existing_helper_does_not_query_unrelated_installs(monkeypatch, tmp_path):
    current = result(tmp_path)
    monkeypatch.setattr(rb, "_adb_shell", lambda *args, **kwargs: SimpleNamespace(stdout=f"package:{PACKAGE}", stderr=""))
    monkeypatch.setattr(rb, "_preflight_android_install", lambda *args: pytest.fail("compatible installation does not need PM mutation"))
    rb._ensure_android_helper_installed(current, rb.AndroidBootstrapOptions())
    assert not current.installed_apk


@pytest.mark.parametrize("code", ["remote_connect_cancelled", "remote_connect_timeout"])
def test_cancelled_read_only_preflight_does_not_claim_install_started(monkeypatch, tmp_path, code):
    def cancelled(*args, **kwargs):
        raise rb.AndroidRemoteBootstrapError(code, "read cancelled")
    monkeypatch.setattr(rb, "_adb_shell", cancelled)
    with pytest.raises(rb.AndroidRemoteBootstrapError) as error:
        rb._preflight_android_install(result(tmp_path))
    assert error.value.code == code
    assert "device_action" not in error.value.details


def test_confirmed_reinstall_rechecks_pending_state_before_uninstall(monkeypatch, tmp_path):
    current = result(tmp_path)
    monkeypatch.setattr(rb, "read_apk_identity", lambda path: {"package_name": PACKAGE, "apk_sha256": "a" * 64})
    observations = iter([output(), output(session(PACKAGE))])
    def shell(adb, serial, *args, **kwargs):
        assert args == ("dumpsys", "package", "installs"), "pending session must prevent uninstall"
        return SimpleNamespace(stdout=next(observations), stderr="")
    monkeypatch.setattr(rb, "_adb_shell", shell)
    monkeypatch.setattr(rb, "_require_repair_confirmation", lambda *args: {})
    installs = []
    monkeypatch.setattr(rb, "_run_process", lambda command, **kwargs: installs.append(command) or SimpleNamespace(
        returncode=1, stdout="", stderr="INSTALL_FAILED_UPDATE_INCOMPATIBLE"))
    with pytest.raises(rb.AndroidRemoteBootstrapError) as error:
        rb._install_android_helper(current, rb.AndroidBootstrapOptions(repair_policy="confirmed"), update=True)
    assert error.value.code == "remote_install_unconfirmed"
    assert len(installs) == 1 and not current.uninstalled_existing


@pytest.mark.parametrize("returncode,stdout,stderr", [
    (0, "", ""),
    (1, "", "device offline"),
    (0, "Performing Streamed Install\n", ""),
    (1, "Success\n", "transport lost"),
    (0, "Success\n", "Failure [INSTALL_FAILED_INTERNAL_ERROR]"),
])
def test_ambiguous_install_receipt_retains_device_action_without_retry(monkeypatch, tmp_path, returncode, stdout, stderr):
    current = result(tmp_path)
    current.uninstalled_existing = True
    monkeypatch.setattr(rb, "read_apk_identity", lambda path: {"package_name": PACKAGE, "apk_sha256": "a" * 64})
    queries = []
    def shell(adb, serial, *args, **kwargs):
        queries.append(args)
        assert args == ("dumpsys", "package", "installs"), "an ambiguous receipt cannot trigger repair or another probe"
        return SimpleNamespace(stdout=output(), stderr="")
    monkeypatch.setattr(rb, "_adb_shell", shell)
    installs = []
    def install(command, **kwargs):
        installs.append(command)
        return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)
    monkeypatch.setattr(rb, "_run_process", install)
    with pytest.raises(rb.AndroidRemoteBootstrapError) as error:
        rb._install_android_helper(current, rb.AndroidBootstrapOptions(repair_policy="confirmed"), update=True)
    assert error.value.code == "remote_install_unconfirmed"
    assert error.value.details == {"returncode": returncode, "stdout": stdout, "stderr": stderr,
        "device_action": {"kind": "android_install", "state": "unconfirmed", "device_serial": "serial",
            "package_name": PACKAGE, "apk_sha256": "a" * 64, "sessions": [], "observation": "unreadable"}}
    assert len(installs) == 1
    assert queries == [("dumpsys", "package", "installs")]
    assert current.uninstalled_existing and not current.installed_apk
    assert current.cleanup_actions == []


@pytest.mark.parametrize("returncode,stdout,stderr", [
    (0, "Failure [INSTALL_FAILED_INVALID_APK]\n", ""),
    (1, "", "INSTALL_PARSE_FAILED_MANIFEST_MALFORMED"),
    (1, "", "Failure [vendor-specific rejection]"),
])
def test_explicit_install_failure_stays_definitive_without_device_action(monkeypatch, tmp_path, returncode, stdout, stderr):
    current = result(tmp_path)
    monkeypatch.setattr(rb, "read_apk_identity", lambda path: {"package_name": PACKAGE, "apk_sha256": "a" * 64})
    monkeypatch.setattr(rb, "_adb_shell", lambda *args, **kwargs: SimpleNamespace(stdout=output(), stderr=""))
    installs = []
    monkeypatch.setattr(rb, "_run_process", lambda command, **kwargs: installs.append(command) or SimpleNamespace(
        returncode=returncode, stdout=stdout, stderr=stderr))
    with pytest.raises(rb.AndroidRemoteBootstrapError) as error:
        rb._install_android_helper(current, rb.AndroidBootstrapOptions())
    assert error.value.code == "android_apk_install_failed"
    assert error.value.details == {"returncode": returncode}
    assert (stderr or stdout).strip() in error.value.message
    assert len(installs) == 1 and not current.installed_apk


@pytest.mark.parametrize("body,state,observation", [(output(), "clear", "verified"),
    (output(session()), "pending", "pending"), ("unrecognized vendor state", "unknown", "unreadable")])
def test_readonly_inspection_reuses_device_apk_and_pending_checks_without_mutation(monkeypatch, tmp_path, body, state, observation):
    current = result(tmp_path)
    commands = []
    monkeypatch.setattr(rb, "resolve_adb_path", lambda: "same-install-adb")
    monkeypatch.setattr(rb, "detect_device_arch", lambda adb, serial: ("arm64", "arm64-v8a"))
    monkeypatch.setattr(rb, "select_android_package", lambda arch: (PACKAGE, current.apk_path))
    monkeypatch.setattr(rb, "read_apk_identity", lambda path: {"package_name": PACKAGE, "apk_sha256": "a" * 64})
    def query(command, **kwargs):
        commands.append(command)
        assert command == ["same-install-adb", "-s", "serial", "get-state"]
        return SimpleNamespace(returncode=0, stdout="device", stderr="")
    monkeypatch.setattr(rb, "_run_subprocess", query)
    def shell(adb, serial, *args, **kwargs):
        commands.append([adb, "-s", serial, *args])
        assert args == ("dumpsys", "package", "installs")
        return SimpleNamespace(stdout=body, stderr="")
    monkeypatch.setattr(rb, "_adb_shell", shell)
    monkeypatch.setattr(rb, "_run_process", lambda *args, **kwargs: pytest.fail("inspection cannot mutate"))
    facts = rb.inspect_android_installation("serial")
    assert facts["device_serial"] == "serial" and facts["package_name"] == PACKAGE
    assert facts["apk_sha256"] == "a" * 64
    assert facts["installation_state"] == state and facts["observation"] == observation
    assert len(commands) == 2
    assert "PRIVATE_OTHER_APP_HISTORY" not in str(facts)


@pytest.mark.parametrize("serial", ["", " ", "other device"])
def test_inspection_requires_exact_serial_before_queries(monkeypatch, serial):
    monkeypatch.setattr(rb, "resolve_adb_path", lambda: pytest.fail("invalid serial cannot query"))
    with pytest.raises(rb.AndroidRemoteBootstrapError) as error:
        rb.inspect_android_installation(serial)
    assert error.value.code == "adb_device_serial_invalid"


def test_inspection_operation_is_canonical_readonly_and_context_bound(monkeypatch):
    import asyncio
    from rdc_tool import server
    from rdc_tool.runtime_catalog import describe_operation
    definition = describe_operation("rd.remote.inspect_installation")
    assert definition["scope"] == "global" and definition["effects"] == []
    assert definition["input_schema"]["required"] == ["device_serial"]
    runtime = server.server_runtime
    monkeypatch.setattr(runtime._runtime, "enable_remote", True)
    observed = []
    def inspect(serial):
        observed.append(serial)
        return {"device_serial": serial, "package_name": PACKAGE, "apk_sha256": "a" * 64,
            "installation_state": "clear", "observation": "verified", "sessions": []}
    monkeypatch.setattr(runtime, "inspect_android_installation", inspect)
    async def run():
        denied = await server.dispatch_operation("rd.remote.inspect_installation", {"device_serial": "serial"}, context_id="default", transport="test")
        assert denied["ok"] is False and denied["error"]["code"] == "remote_context_required"
        assert not observed
        result = await server.dispatch_operation("rd.remote.inspect_installation", {"device_serial": "serial"}, context_id="inspection-owned", transport="test")
        assert result["ok"] is True and result["data"]["context_id"] == "inspection-owned"
        assert result["data"]["installation_state"] == "clear"
        assert observed == ["serial"]
    asyncio.run(run())
