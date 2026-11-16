from __future__ import annotations

import sys
from pathlib import Path

import pytest

from rdc_tool.runtime_bootstrap import bootstrap_renderdoc_runtime
from rdc_tool.runtime_paths import binaries_root, binding_module_path, pymodules_dir


def test_bootstrap_uses_only_this_installations_runtime() -> None:
    report = bootstrap_renderdoc_runtime(probe_import=False)

    assert report.binaries_dir == binaries_root().resolve()
    assert report.pymodules_dir == pymodules_dir().resolve()
    assert str(report.pymodules_dir) in sys.path


def test_bootstrap_probe_import_renderdoc() -> None:
    if not binding_module_path().is_file():
        pytest.skip(f"this host's RenderDoc binding is not installed: {binding_module_path()}")

    report = bootstrap_renderdoc_runtime(probe_import=True)

    assert report.import_ok, report.import_error
    assert Path(report.import_module_path).resolve() == binding_module_path().resolve()
