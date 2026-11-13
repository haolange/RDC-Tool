"""Host-native runtime layout. Explicit paths never imply replay support."""
from __future__ import annotations
import importlib.machinery
import os
from pathlib import Path
import platform
import sys


def platform_target() -> str:
    machine = platform.machine().lower()
    arch = {"amd64": "x64", "x86_64": "x64", "aarch64": "arm64"}.get(machine, machine)
    if sys.platform == "win32":
        return f"windows-{arch}"
    if sys.platform.startswith("linux"):
        return f"linux-{arch}"
    raise RuntimeError(f"Unsupported runtime host: {sys.platform}/{machine}")


def native_library_path(directory: Path) -> Path:
    return directory / ("renderdoc.dll" if is_windows() else "librenderdoc.so")


def native_binding_path(directory: Path) -> Path:
    if is_windows():
        return directory / "renderdoc.pyd"
    for suffix in importlib.machinery.EXTENSION_SUFFIXES:
        candidate = directory / ("renderdoc" + suffix)
        if candidate.is_file():
            return candidate
    # A missing file is returned for actionable diagnostics, never imported.
    return directory / ("renderdoc" + importlib.machinery.EXTENSION_SUFFIXES[0])


def is_windows() -> bool:
    return os.name == "nt"
