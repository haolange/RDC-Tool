from __future__ import annotations

import json
import os
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


def _launcher_env() -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("RDC_TOOL_ROOT", str(ROOT))
    env.pop("RDC_TOOL_PYTHON", None)
    return env


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
        env=_launcher_env(),
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
        env=_launcher_env(),
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
            env=_launcher_env(),
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
        env=_launcher_env(),
        check=False,
    )
    combined = (proc.stdout or "") + (proc.stderr or "")

    assert proc.returncode == 2
    assert "invalid choice" in combined


@pytest.mark.skipif(os.name != "nt", reason="bin/rdc-tool.cmd launcher tests are windows-specific")
def test_launcher_missing_command_returns_usage_error() -> None:
    proc = subprocess.run([_cmd_exe(), "/c", str(ROOT / "bin" / "rdc-tool.cmd")], cwd=ROOT, stdin=subprocess.DEVNULL, capture_output=True, text=True, env=_launcher_env(), timeout=30)
    assert proc.returncode == 2
    assert "missing command" in proc.stderr


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
        env=_launcher_env(),
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
