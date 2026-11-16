from __future__ import annotations

import json
from pathlib import Path

import pytest

from rdc_tool import python_runtime
from rdc_tool.runtime_paths import HOST_LAYOUTS

BUNDLES = {
    "windows-x64": {
        "files": ["python/python.exe", "python/pythonw.exe", "python/python3.dll", "python/python314.dll", "python/python314._pth",
                  "python/DLLs/_socket.pyd"],
        "metadata": {"python_entry": "python/python.exe", "pythonw_entry": "python/pythonw.exe", "python3_dll": "python/python3.dll",
                     "python_dll": "python/python314.dll", "stdlib_layout": "python/Lib", "site_packages": "python/Lib/site-packages",
                     "dll_dir": "python/DLLs", "pth_file": "python/python314._pth"},
        "stdlib": "python/Lib",
    },
    "linux-x64": {
        "files": ["python/bin/python3.14"],
        "metadata": {"python_entry": "python/bin/python3.14", "stdlib_layout": "python/lib/python3.14",
                     "site_packages": "python/lib/python3.14/site-packages"},
        "stdlib": "python/lib/python3.14",
    },
}


def _bundle(root: Path, target: str, *, metadata_overrides: dict | None = None) -> None:
    spec = BUNDLES[target]
    for relative in spec["files"]:
        (root / relative).parent.mkdir(parents=True, exist_ok=True)
        (root / relative).write_bytes(b"x")
    for marker in ("os.py", "site.py", "encodings/__init__.py"):
        (root / spec["stdlib"] / marker).parent.mkdir(parents=True, exist_ok=True)
        (root / spec["stdlib"] / marker).write_text("#\n", encoding="utf-8")
    (root / spec["metadata"]["site_packages"]).mkdir(parents=True, exist_ok=True)
    metadata = {"python_version": "3.14.3", **spec["metadata"], **(metadata_overrides or {})}
    (root / "manifest.runtime.json").write_text(json.dumps({"files": [], "bundled_python": metadata}), encoding="utf-8")


@pytest.fixture(params=sorted(BUNDLES))
def host(request, tmp_path, monkeypatch):
    monkeypatch.setattr(python_runtime, "host_layout", lambda: HOST_LAYOUTS[request.param])
    monkeypatch.setattr(python_runtime, "binaries_root", lambda: tmp_path)
    return request.param, tmp_path


def test_complete_bundle_validates(host):
    target, root = host
    _bundle(root, target)
    ok, failures, details = python_runtime.validate_bundled_python_layout()
    assert ok, failures
    assert details["bundled_python"]["python_version"] == "3.14.3"
    assert python_runtime.bundled_python_executable() == (root / BUNDLES[target]["metadata"]["python_entry"]).resolve()


def test_missing_metadata_is_a_failure_not_a_default(host):
    target, root = host
    _bundle(root, target, metadata_overrides={"python_entry": ""})
    ok, failures, _ = python_runtime.validate_bundled_python_layout()
    assert not ok
    assert "bundled_python metadata missing python_entry" in failures
    assert python_runtime.bundled_python_executable() is None


def test_metadata_cannot_escape_the_runtime_directory(host):
    target, root = host
    _bundle(root, target, metadata_overrides={"python_entry": "../../outside"})
    ok, failures, _ = python_runtime.validate_bundled_python_layout()
    assert not ok
    assert any("escapes the runtime directory" in failure for failure in failures)


def test_missing_stdlib_marker_is_reported(host):
    target, root = host
    _bundle(root, target)
    (root / BUNDLES[target]["stdlib"] / "encodings" / "__init__.py").unlink()
    ok, failures, _ = python_runtime.validate_bundled_python_layout()
    assert not ok
    assert any(failure.startswith("missing stdlib marker") for failure in failures)
