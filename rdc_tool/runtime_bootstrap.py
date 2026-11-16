"""RenderDoc runtime bootstrap helpers for standalone rdc-tool."""

from __future__ import annotations

import importlib
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from rdc_tool.platform import native as platform_native
from rdc_tool.runtime_paths import binaries_root, native_library_name, pymodules_dir
from rdc_tool.runtime_identity import loaded_runtime_identity


@dataclass
class RuntimeBootstrapResult:
    binaries_dir: Path
    pymodules_dir: Path
    sys_path_added: bool = False
    loader_prepared: list[str] = field(default_factory=list)
    loader_errors: list[str] = field(default_factory=list)
    import_ok: bool = False
    import_module_path: str = ""
    import_error: str = ""
    loaded_runtime: dict[str, Any] = field(default_factory=dict)


def _probe_renderdoc_import(report: RuntimeBootstrapResult) -> None:
    try:
        importlib.invalidate_caches()
        import renderdoc as rd  # type: ignore[import-not-found]

        report.import_ok = True
        report.import_module_path = str(getattr(rd, "__file__", ""))
        report.loaded_runtime = loaded_runtime_identity(report.binaries_dir, report.pymodules_dir)
        if report.loaded_runtime.get("status") == "mismatch":
            raise ImportError("Loaded RenderDoc paths differ from the configured runtime")
    except Exception as exc:  # noqa: BLE001
        report.import_ok = False
        report.import_error = f"{exc.__class__.__name__}: {exc}"


def bootstrap_renderdoc_runtime(*, probe_import: bool = False) -> RuntimeBootstrapResult:
    """Make the configured RenderDoc native library and binding importable."""

    bin_dir, pymod_dir = binaries_root().resolve(), pymodules_dir().resolve()
    report = RuntimeBootstrapResult(
        binaries_dir=bin_dir,
        pymodules_dir=pymod_dir,
    )

    pymod_text = str(pymod_dir)
    if pymod_text not in sys.path:
        sys.path.insert(0, pymod_text)
        report.sys_path_added = True

    loader = platform_native.prepare_loader(bin_dir / native_library_name(), pymod_dir)
    report.loader_prepared = loader.prepared
    report.loader_errors = loader.errors

    if probe_import:
        _probe_renderdoc_import(report)

    return report
