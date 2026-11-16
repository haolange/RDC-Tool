from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from rdc_tool import cli, runtime_paths
from rdc_tool.runtime_paths import HOST_LAYOUTS, UnsupportedHost

ROOT = Path(__file__).resolve().parents[1]


def test_tools_root_is_the_installation():
    assert runtime_paths.tools_root() == ROOT


@pytest.mark.parametrize("target", sorted(HOST_LAYOUTS))
def test_runtime_paths_follow_the_host_layout(monkeypatch, target):
    monkeypatch.setattr(runtime_paths, "host_target", lambda: target)
    layout = HOST_LAYOUTS[target]
    assert runtime_paths.binaries_root() == ROOT / layout.runtime_dir
    assert runtime_paths.native_library_path() == ROOT / layout.runtime_dir / layout.native_library
    assert runtime_paths.binding_module_path() == ROOT / layout.runtime_dir / layout.binding_module
    assert set(layout.host_tools) == {"adb", "spirv_as", "spirv_dis"}


def test_unknown_host_is_rejected_by_name(monkeypatch):
    monkeypatch.setattr(runtime_paths, "host_target", lambda: "plan9-mips")
    with pytest.raises(UnsupportedHost, match="plan9-mips"):
        runtime_paths.binaries_root()


def test_doctor_reports_unsupported_host(monkeypatch, capsys):
    monkeypatch.setattr(cli, "host_layout", lambda: (_ for _ in ()).throw(UnsupportedHost("plan9-mips")))
    code = cli._cmd_doctor(argparse.Namespace(daemon_context="default"))
    payload = json.loads(capsys.readouterr().out)
    assert code == cli.EXIT_RUNTIME_ERR
    assert payload["error"]["code"] == "unsupported_host"
    assert payload["error"]["details"]["supported_hosts"] == sorted(HOST_LAYOUTS)
