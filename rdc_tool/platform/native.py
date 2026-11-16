"""Native library loading for the RenderDoc runtime.

``prepare_loader`` makes one exact native library resolvable before the Python
binding is imported; ``loaded_library_path`` observes which file the process
actually mapped, so identity checks compare real loads, not configuration.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from rdc_tool.platform import host

_os = host.backend()


@dataclass
class LoaderReport:
    prepared: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def prepare_loader(native_library: Path, binding_dir: Path) -> LoaderReport:
    report = LoaderReport()
    _os.prepare_loader(native_library, binding_dir, report)
    return report


def loaded_library_path(file_name: str) -> Path | None:
    """Return the mapped path of ``file_name``; raise ``OSError`` when unobservable or ambiguous."""
    return _os.loaded_library_path(file_name)
