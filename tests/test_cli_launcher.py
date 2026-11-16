from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def _extract_json(text: str) -> dict:
    start = text.find("{")
    end = text.rfind("}")
    assert start >= 0 and end > start, text
    return json.loads(text[start : end + 1])


def _cmd_exe() -> str:
    system_root = str(os.environ.get("SystemRoot") or r"C:\Windows")
    return str(Path(system_root) / "System32" / "cmd.exe")


def _run_cmd(*args: str) -> tuple[int, dict, str]:
    proc = subprocess.run(
        [_cmd_exe(), "/c", str(ROOT / "bin" / "rdc-tool.cmd"), *args],
        cwd=str(ROOT),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=90,
        check=False,
    )
    combined = (proc.stdout or "") + (proc.stderr or "")
    return proc.returncode, _extract_json(combined), combined


def _run_cmd_from_cwd(cwd: Path, *args: str) -> tuple[int, dict, str]:
    proc = subprocess.run(
        [_cmd_exe(), "/c", str(ROOT / str(ROOT / "bin" / "rdc-tool.cmd")), *args],
        cwd=str(cwd),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=90,
        check=False,
    )
    combined = (proc.stdout or "") + (proc.stderr or "")
    return proc.returncode, _extract_json(combined), combined


def _cleanup_context(context_id: str) -> None:
    for command in (("context", "clear"), ("daemon", "stop")):
        subprocess.run(
            [sys.executable, "cli/run_cli.py", "--daemon-context", context_id, *command],
            cwd=str(ROOT),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
            check=False,
        )


@pytest.mark.skipif(os.name != "nt", reason="bin/rdc-tool.cmd launcher tests are windows-specific")
def test_noninteractive_daemon_status_returns_full_payload() -> None:
    context_id = "pytest-cmd-daemon-status"
    try:
        code, payload, _ = _run_cmd( "--daemon-context", context_id, "daemon", "status")
    finally:
        _cleanup_context(context_id)

    assert code == 0
    assert payload["ok"] is True
    assert payload["result_kind"] == "rdc_tool.daemon.status"
    assert isinstance(payload.get("data"), dict)
    assert isinstance(payload["data"].get("state"), dict)


@pytest.mark.skipif(os.name != "nt", reason="bin/rdc-tool.cmd launcher tests are windows-specific")
def test_noninteractive_doctor_returns_cli_only_payload() -> None:
    code, payload, _ = _run_cmd( "--json", "doctor")

    assert code == 0
    assert payload["ok"] is True
    assert payload["result_kind"] == "rdc_tool.doctor"


@pytest.mark.skipif(os.name != "nt", reason="bin/rdc-tool.cmd launcher tests are windows-specific")
def test_noninteractive_unknown_command_uses_cli_usage_error() -> None:
    proc = subprocess.run(
        [_cmd_exe(), "/c", str(ROOT / "bin" / "rdc-tool.cmd"),  "__unknown_command__"],
        cwd=str(ROOT),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=90,
        check=False,
    )
    combined = (proc.stdout or "") + (proc.stderr or "")

    assert proc.returncode == 2
    assert "invalid choice" in combined


@pytest.mark.skipif(os.name != "nt", reason="bin/rdc-tool.cmd launcher tests are windows-specific")
def test_launcher_missing_command_returns_usage_error() -> None:
    proc = subprocess.run([_cmd_exe(), "/c", str(ROOT / "bin" / "rdc-tool.cmd")], cwd=ROOT, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=30)
    assert proc.returncode == 2
    assert "the following arguments are required: command" in proc.stderr


@pytest.mark.skipif(os.name != "nt", reason="bin/rdc-tool.cmd launcher tests are windows-specific")
def test_noninteractive_version_and_completion_are_available() -> None:
    version_code, version_payload, _ = _run_cmd( "version", "--json")
    completion_proc = subprocess.run(
        [_cmd_exe(), "/c", str(ROOT / "bin" / "rdc-tool.cmd"),  "completion", "powershell"],
        cwd=str(ROOT),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=90,
        check=False,
    )

    assert version_code == 0
    assert version_payload["ok"] is True
    assert version_payload["result_kind"] == "rdc_tool.version"
    assert completion_proc.returncode == 0
    assert "Register-ArgumentCompleter" in completion_proc.stdout

@pytest.mark.skipif(os.name != "nt", reason="bin/rdc-tool.cmd launcher tests are windows-specific")
def test_noninteractive_facade_out_argument_is_passed_through() -> None:
    context_id = "pytest-cmd-facade-out"
    try:
        code, payload, output = _run_cmd(

            "--daemon-context",
            context_id,
            "export",
            "screenshot",
            "--out",
            "intermediate/artifacts/pytest-cmd-facade-out.png",
        )
    finally:
        _cleanup_context(context_id)

    assert code == 1
    assert payload["ok"] is False
    assert payload["error"]["code"] == "session_required"
    assert "Parameter cannot be processed" not in output


@pytest.mark.skipif(os.name != "nt", reason="bin/rdc-tool.cmd launcher tests are windows-specific")
def test_noninteractive_tools_list_passthroughs_canonical_payload() -> None:
    code, payload, _ = _run_cmd(

        "tools",
        "list",
        "--json",
        "--limit",
        "3",
    )

    assert code == 0
    assert payload["ok"] is True
    assert payload["result_kind"] == "rdc_tool.tools.list"
    assert payload["data"]["tool_count"] >= 1


@pytest.mark.skipif(os.name != "nt", reason="bin/rdc-tool.cmd launcher tests are windows-specific")
def test_noninteractive_tools_search_runs_from_caller_cwd(tmp_path: Path) -> None:
    code, payload, _ = _run_cmd_from_cwd(
        tmp_path,

        "tools",
        "search",
        "pipeline",
        "--json",
    )

    assert code == 0
    assert payload["ok"] is True
    assert payload["result_kind"] == "rdc_tool.tools.search"
    assert payload["data"]["tool_count"] >= 1


def _posix_launcher(tmp_path: Path, uname_s: str, uname_m: str, *, interpreter: str | None) -> tuple[Path, dict[str, str]]:
    root = tmp_path / "install root"
    (root / "bin").mkdir(parents=True)
    shutil.copy2(ROOT / "bin" / "rdc-tool", root / "bin" / "rdc-tool")
    if interpreter is not None:
        python = root / interpreter
        python.parent.mkdir(parents=True)
        python.write_text('#!/bin/sh\nprintf "%s\\n" "$@"\necho "PYTHONPATH=${PYTHONPATH-unset} PYTHONHOME=${PYTHONHOME-unset}"\nexit 7\n')
        python.chmod(0o755)
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    uname = fake_bin / "uname"
    uname.write_text(f'#!/bin/sh\ncase "$1" in -s) echo {uname_s} ;; -m) echo {uname_m} ;; esac\n')
    uname.chmod(0o755)
    env = {**os.environ, "PATH": f"{fake_bin}{os.pathsep}{os.environ.get('PATH', '')}",
           "PYTHONPATH": "/elsewhere", "PYTHONHOME": "/elsewhere"}
    return root, env


@pytest.mark.skipif(os.name == "nt", reason="POSIX shell launcher")
def test_posix_launcher_runs_this_installations_python_without_inherited_python_env(tmp_path: Path) -> None:
    root, env = _posix_launcher(tmp_path, "Linux", "x86_64", interpreter="binaries/linux/x64/python/bin/python3.14")
    proc = subprocess.run(["sh", str(root / "bin" / "rdc-tool"), "--json", "a b"], cwd=tmp_path, env=env,
                          capture_output=True, text=True, timeout=30, check=False)
    assert proc.returncode == 7, proc.stderr
    assert proc.stdout.splitlines() == ["-s", str(root / "cli" / "run_cli.py"), "--json", "a b",
                                        "PYTHONPATH=unset PYTHONHOME=unset"]


@pytest.mark.skipif(os.name == "nt", reason="POSIX shell launcher")
@pytest.mark.parametrize(("uname_s", "uname_m", "message"), [
    ("Darwin", "arm64", "no runtime for host Darwin-arm64"),
    ("Linux", "x86_64", "Bundled Python is missing"),
])
def test_posix_launcher_refuses_hosts_and_installs_it_cannot_run(tmp_path: Path, uname_s: str, uname_m: str, message: str) -> None:
    root, env = _posix_launcher(tmp_path, uname_s, uname_m, interpreter=None)
    proc = subprocess.run(["sh", str(root / "bin" / "rdc-tool"), "version"], cwd=tmp_path, env=env,
                          capture_output=True, text=True, timeout=30, check=False)
    assert proc.returncode == 2
    assert message in proc.stderr


def test_launchers_export_no_rdc_tool_variables() -> None:
    for name in ("rdc-tool", "rdc-tool.cmd"):
        assert "RDC_TOOL_" not in (ROOT / "bin" / name).read_text(encoding="utf-8")
