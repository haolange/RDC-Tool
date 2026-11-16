"""The Python interpreter bundled with each host runtime.

Where the interpreter's files live is the host layout's contract; the host
manifest's ``bundled_python`` records only what was bundled (version and
provenance). Missing files or provenance are failures, never filled in.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from rdc_tool.runtime_paths import PYTHON_DIRECTORIES, binaries_root, host_layout

PROVENANCE_FIELDS = ("python_version", "package", "source_url", "source_sha256")
_STDLIB_MARKERS = ("os.py", "site.py", "encodings/__init__.py")


def _bundled_python_metadata() -> dict[str, Any]:
    path = binaries_root() / "manifest.runtime.json"
    if not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    metadata = payload.get("bundled_python") if isinstance(payload, dict) else None
    return dict(metadata) if isinstance(metadata, dict) else {}


def bundled_python_executable() -> Path | None:
    """This host's bundled interpreter, or ``None`` when it is not installed."""
    path = binaries_root() / host_layout().python["executable"]
    return path if path.is_file() else None


def current_python_runtime_details() -> dict[str, str]:
    return {
        "executable": str(Path(sys.executable).resolve()),
        "version": sys.version.split()[0],
        "prefix": str(Path(sys.prefix).resolve()),
        "base_prefix": str(Path(sys.base_prefix).resolve()),
    }


def validate_bundled_python_layout() -> tuple[bool, list[str], dict[str, Any]]:
    root = binaries_root()
    failures: list[str] = []
    try:
        metadata = _bundled_python_metadata()
    except (OSError, ValueError) as exc:
        metadata = {}
        failures.append(f"unreadable runtime manifest: {exc}")
    failures += [f"bundled_python metadata missing {key}" for key in PROVENANCE_FIELDS
                 if not str(metadata.get(key) or "").strip()]
    resolved: dict[str, str] = {}
    for role, relative in host_layout().python.items():
        path = root / relative
        resolved[role] = str(path)
        if role in PYTHON_DIRECTORIES and not path.is_dir():
            failures.append(f"missing bundled python directory: {role}={path}")
        elif role not in PYTHON_DIRECTORIES and not path.is_file():
            failures.append(f"missing bundled python file: {role}={path}")
    stdlib = root / host_layout().python["stdlib"]
    if stdlib.is_dir():
        failures += [f"missing stdlib marker: {stdlib / marker}" for marker in _STDLIB_MARKERS
                     if not (stdlib / marker).is_file()]
    details = {
        "bundled_python": {**{key: str(metadata.get(key) or "") for key in PROVENANCE_FIELDS}, **resolved},
        "current_python": current_python_runtime_details(),
    }
    return not failures, failures, details
