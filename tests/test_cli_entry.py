from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from rdc_tool import cli

ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "cli" / "run_cli.py"


def _run(*args, code=None):
    command = [sys.executable, "-c", code, *args] if code else [sys.executable, str(LAUNCHER), *args]
    return subprocess.run(command, capture_output=True, text=True, timeout=60, cwd=ROOT)


def test_launcher_and_package_entry_share_one_version_payload():
    result = _run("version", "--json")
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    expected = cli._version_payload()
    assert payload["data"] == expected["data"]
    assert payload["schema_version"] == expected["schema_version"]


def test_version_reports_the_served_catalog_identity():
    payload = json.loads(_run("version", "--json").stdout)
    listed = json.loads(_run("tools", "list", "--json").stdout)["data"]
    assert payload["data"]["catalog"] == {
        "schema_version": listed["schema_version"],
        "fingerprint": listed["fingerprint"],
        "tool_count": listed["tool_count"],
    }


def test_launcher_has_no_private_options():
    result = _run("--context-id", "x", "version")
    assert result.returncode != 0
    assert "unrecognized arguments" in result.stderr or "invalid choice" in result.stderr


def test_subcommand_help_is_reachable():
    result = _run("daemon", "--help")
    assert result.returncode == 0
    assert "start" in result.stdout and "stop" in result.stdout


def test_completion_covers_every_subcommand_and_long_option():
    words = set(cli._completion_words())
    assert {"batch", "describe", "update", "--namespace", "--owner-pid", "--daemon-context"} <= words
    assert "rd.pipeline.get_state" in words


def test_doctor_reports_missing_dependencies_without_crashing():
    # -S skips site-packages, so every third-party dependency is genuinely absent.
    code = f"import sys; sys.path.insert(0, {str(ROOT)!r}); sys.argv = ['rdc-tool', '--json', 'doctor']; from rdc_tool.cli import main; main()"
    result = subprocess.run([sys.executable, "-S", "-c", code], capture_output=True, text=True, timeout=60, cwd=ROOT)
    payload = json.loads(result.stdout)
    assert payload["result_kind"] == "rdc_tool.doctor"
    assert payload["ok"] is False
    missing = set(payload["error"]["details"]["dependencies"]["missing"])
    assert {"numpy", "Pillow", "pydantic", "aiofiles"} <= missing
