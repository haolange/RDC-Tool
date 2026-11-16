from __future__ import annotations

import hashlib
import json

import pytest

from rdc_tool import host_tools
from rdc_tool.runtime_paths import HOST_LAYOUTS


@pytest.fixture(params=sorted(HOST_LAYOUTS))
def layout(request, tmp_path, monkeypatch):
    host_layout = HOST_LAYOUTS[request.param]
    monkeypatch.setattr(host_tools, "host_layout", lambda: host_layout)
    monkeypatch.setattr(host_tools, "binaries_root", lambda: tmp_path)
    for variable in set(host_tools.OVERRIDE_VARIABLES.values()):
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setenv("PATH", "")
    files = []
    for relative in host_tools.bundled_host_files(host_layout):
        file = tmp_path / relative
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(b"fixture")
        files.append({"path": relative, "size": 7, "sha256": hashlib.sha256(b"fixture").hexdigest()})
    (tmp_path / "manifest.runtime.json").write_text(json.dumps({"files": files, "bundled_tools": {
        name: {"version": "test", "source_url": "https://example.test/source", "license": "MIT"}
        for name in host_tools.OVERRIDE_VARIABLES
    }}))
    return tmp_path, host_layout


def test_bundled_tools_work_without_path_or_sdk(layout, monkeypatch):
    root, host_layout = layout
    monkeypatch.setenv("ANDROID_HOME", "/nonexistent")
    assert host_tools.resolve_host_tool("adb") == (root / host_layout.host_tools["adb"]).resolve()
    assert all(row["source"] == "bundled" and row["available"] for row in host_tools.host_tools_status().values())
    assert host_tools.validate_bundled_host_tools() == (True, [])


def test_explicit_override_is_used_and_invalid_override_never_falls_back(layout, monkeypatch):
    root, _ = layout
    custom = root / "explicit-adb"
    custom.write_bytes(b"custom")
    monkeypatch.setenv("RDC_TOOL_ANDROID_ADB_PATH", str(custom))
    assert host_tools.resolve_host_tool("adb") == custom.resolve()
    custom.unlink()
    with pytest.raises(host_tools.HostToolUnavailableError, match="RDC_TOOL_ANDROID_ADB_PATH"):
        host_tools.resolve_host_tool("adb")
    assert not host_tools.host_tools_status()["adb"]["available"]


def test_missing_or_corrupt_required_file_fails_layout(layout):
    root, host_layout = layout
    for relative in host_tools.bundled_host_files(host_layout):
        file = root / relative
        original = file.read_bytes()
        file.write_bytes(b"tampered")
        assert host_tools.validate_bundled_host_tools()[0] is False, relative
        file.unlink()
        assert host_tools.validate_bundled_host_tools()[0] is False, relative
        file.write_bytes(original)


def test_missing_provenance_fails(layout):
    root, _ = layout
    (root / "manifest.runtime.json").write_text('{"files":[]}')
    assert host_tools.validate_bundled_host_tools()[0] is False
