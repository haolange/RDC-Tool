from pathlib import Path
import hashlib
import json
import pytest
from rdc_tool import host_tools

@pytest.fixture
def layout(tmp_path, monkeypatch):
    monkeypatch.setattr(host_tools, "binaries_root", lambda: tmp_path)
    for variable in {item[1] for item in host_tools.HOST_TOOLS.values()}:
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setenv("PATH", "")
    files = []
    for relative in host_tools.BUNDLED_HOST_FILES:
        file = tmp_path / relative
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(b"fixture")
        files.append({"path": relative, "size": 7, "sha256": hashlib.sha256(b"fixture").hexdigest()})
    (tmp_path / "manifest.runtime.json").write_text(json.dumps({"files": files, "bundled_tools": {
        name: {"version": "test", "source_url": "https://example.test/source", "license": "MIT"} for name in host_tools.HOST_TOOLS
    }}))
    return tmp_path

def test_bundled_tools_work_without_path_or_sdk(layout, monkeypatch):
    monkeypatch.setenv("ANDROID_HOME", "/nonexistent")
    assert host_tools.resolve_host_tool("adb") == (layout / "adb/adb.exe").resolve()
    assert all(row["source"] == "bundled" and row["available"] for row in host_tools.host_tools_status().values())
    assert host_tools.validate_bundled_host_tools() == (True, [])

def test_explicit_override_is_used_and_invalid_override_never_falls_back(layout, monkeypatch):
    custom = layout / "explicit.exe"
    custom.write_bytes(b"custom")
    monkeypatch.setenv("RDC_TOOL_ANDROID_ADB_PATH", str(custom))
    assert host_tools.resolve_host_tool("adb") == custom.resolve()
    custom.unlink()
    with pytest.raises(host_tools.HostToolUnavailableError, match="RDC_TOOL_ANDROID_ADB_PATH"):
        host_tools.resolve_host_tool("adb")
    assert not host_tools.host_tools_status()["adb"]["available"]

@pytest.mark.parametrize("relative", host_tools.BUNDLED_HOST_FILES)
def test_missing_or_corrupt_required_file_fails_layout(layout, relative):
    file = layout / relative
    file.write_bytes(b"tampered")
    assert host_tools.validate_bundled_host_tools()[0] is False
    file.unlink()
    assert host_tools.validate_bundled_host_tools()[0] is False

def test_missing_provenance_fails(layout):
    (layout / "manifest.runtime.json").write_text('{"files":[]}')
    assert host_tools.validate_bundled_host_tools()[0] is False
