"""The native loader contract: the binding resolves the exact library; nothing is preloaded on POSIX."""

from __future__ import annotations

import os
from pathlib import PurePosixPath

import pytest

from rdc_tool.platform.native import LoaderReport
from rdc_tool.runtime_paths import HOST_LAYOUTS


def test_linux_library_sits_where_the_binding_runpath_resolves():
    # RenderDoc links the binding with RUNPATH "$ORIGIN/:$ORIGIN/../lib/".
    layout = HOST_LAYOUTS["linux-x64"]
    binding_dir = PurePosixPath(layout.binding_module).parent
    assert PurePosixPath(layout.native_library).parent == PurePosixPath("lib")
    assert binding_dir.parent / "lib" == PurePosixPath(layout.native_library).parent


@pytest.mark.skipif(os.name == "nt", reason="POSIX loader primitive")
def test_posix_loader_validates_without_mapping_the_library(tmp_path):
    from rdc_tool.platform import _posix

    library = tmp_path / "lib" / "librenderdoc-probe.so"
    library.parent.mkdir()
    library.write_bytes(b"not loaded")
    (tmp_path / "pymodules").mkdir()
    report = LoaderReport()
    _posix.prepare_loader(library, tmp_path / "pymodules", report)
    assert report.errors == [] and report.prepared == [str(library.resolve())]
    assert _posix.loaded_library_path(library.name) is None

    missing = LoaderReport()
    _posix.prepare_loader(tmp_path / "lib" / "absent.so", tmp_path / "pymodules", missing)
    assert missing.prepared == [] and "missing native library" in missing.errors[0]
