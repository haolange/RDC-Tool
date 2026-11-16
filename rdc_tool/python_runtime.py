"""The Python interpreter bundled with each host runtime.

The host manifest's ``bundled_python`` metadata names the interpreter and its
layout; which entries must be files or directories comes from the host
layout. Missing metadata is a failure, never filled in with defaults.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from rdc_tool.runtime_paths import binaries_root, host_layout

_STDLIB_MARKERS = ("os.py", "site.py", "encodings/__init__.py")


def _bundled_python_metadata() -> dict[str, Any]:
    path = (binaries_root() / "manifest.runtime.json")
    if not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    metadata = payload.get("bundled_python") if isinstance(payload, dict) else None
    return dict(metadata) if isinstance(metadata, dict) else {}


def _runtime_path(raw: Any, key: str) -> Path:
    root = binaries_root().resolve()
    path = (root / str(raw)).resolve()
    if not path.is_relative_to(root):
        raise ValueError(f"bundled_python {key} escapes the runtime directory: {raw}")
    return path


def bundled_python_executable() -> Path | None:
    """The bundled interpreter named by the host manifest, or ``None`` when unrecorded."""
    entry = str(_bundled_python_metadata().get("python_entry") or "").strip()
    return _runtime_path(entry, "python_entry") if entry else None


def current_python_runtime_details() -> dict[str, str]:
    return {
        "executable": str(Path(sys.executable).resolve()),
        "version": sys.version.split()[0],
        "prefix": str(Path(sys.prefix).resolve()),
        "base_prefix": str(Path(sys.base_prefix).resolve()),
    }


def validate_bundled_python_layout() -> tuple[bool, list[str], dict[str, Any]]:
    layout = host_layout()
    failures: list[str] = []
    try:
        metadata = _bundled_python_metadata()
    except (OSError, ValueError) as exc:
        metadata = {}
        failures.append(f"unreadable runtime manifest: {exc}")
    resolved: dict[str, str] = {}
    if not str(metadata.get("python_version") or "").strip():
        failures.append("bundled_python metadata missing python_version")
    for key, must_be_dir in [*((key, False) for key in layout.python_files), *((key, True) for key in layout.python_dirs)]:
        raw = str(metadata.get(key) or "").strip()
        if not raw:
            failures.append(f"bundled_python metadata missing {key}")
            continue
        try:
            path = _runtime_path(raw, key)
        except ValueError as exc:
            failures.append(str(exc))
            continue
        resolved[key] = str(path)
        if must_be_dir and not path.is_dir():
            failures.append(f"missing bundled python directory: {key}={path}")
        elif not must_be_dir and not path.is_file():
            failures.append(f"missing bundled python file: {key}={path}")
    stdlib = resolved.get("stdlib_layout")
    if stdlib and Path(stdlib).is_dir():
        failures += [f"missing stdlib marker: {Path(stdlib) / marker}" for marker in _STDLIB_MARKERS
                     if not (Path(stdlib) / marker).is_file()]
    details = {
        "bundled_python": {"python_version": str(metadata.get("python_version") or ""), **resolved},
        "current_python": current_python_runtime_details(),
    }
    return not failures, failures, details
