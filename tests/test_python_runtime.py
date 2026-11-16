from __future__ import annotations

import json
from pathlib import Path

import pytest

from rdc_tool import python_runtime
from rdc_tool.runtime_paths import HOST_LAYOUTS, PYTHON_DIRECTORIES

PROVENANCE = {"python_version": "3.14.3", "package": "fixture interpreter", "source_url": "https://example.test/python.zip",
              "source_sha256": "a" * 64}


def _bundle(root: Path, target: str, *, provenance: dict | None = None) -> None:
    layout = HOST_LAYOUTS[target]
    for role, relative in layout.python.items():
        path = root / relative
        if role in PYTHON_DIRECTORIES:
            path.mkdir(parents=True, exist_ok=True)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"x")
    for marker in ("os.py", "site.py", "encodings/__init__.py"):
        (root / layout.python["stdlib"] / marker).parent.mkdir(parents=True, exist_ok=True)
        (root / layout.python["stdlib"] / marker).write_text("#\n", encoding="utf-8")
    metadata = PROVENANCE if provenance is None else provenance
    (root / "manifest.runtime.json").write_text(json.dumps({"files": [], "bundled_python": metadata}), encoding="utf-8")


@pytest.fixture(params=sorted(HOST_LAYOUTS))
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
    assert python_runtime.bundled_python_executable() == root / HOST_LAYOUTS[target].python["executable"]


@pytest.mark.parametrize("field", sorted(python_runtime.PROVENANCE_FIELDS))
def test_missing_provenance_is_a_failure_not_a_default(host, field):
    target, root = host
    _bundle(root, target, provenance={**PROVENANCE, field: ""})
    ok, failures, _ = python_runtime.validate_bundled_python_layout()
    assert not ok
    assert f"bundled_python metadata missing {field}" in failures


def test_missing_interpreter_is_reported_and_not_returned(host):
    target, root = host
    _bundle(root, target)
    (root / HOST_LAYOUTS[target].python["executable"]).unlink()
    ok, failures, _ = python_runtime.validate_bundled_python_layout()
    assert not ok
    assert any(failure.startswith("missing bundled python file: executable") for failure in failures)
    assert python_runtime.bundled_python_executable() is None


def test_missing_stdlib_marker_is_reported(host):
    target, root = host
    _bundle(root, target)
    (root / HOST_LAYOUTS[target].python["stdlib"] / "encodings" / "__init__.py").unlink()
    ok, failures, _ = python_runtime.validate_bundled_python_layout()
    assert not ok
    assert any(failure.startswith("missing stdlib marker") for failure in failures)


def test_every_layout_keeps_the_interpreter_inside_its_python_directory():
    for layout in HOST_LAYOUTS.values():
        assert all(Path(relative).parts[0] == "python" and ".." not in Path(relative).parts for relative in layout.python.values())
        assert PYTHON_DIRECTORIES <= set(layout.python) and {"executable", "path_config"} <= set(layout.python)
