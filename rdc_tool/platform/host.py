"""Host identification: the only module that inspects the running OS."""

from __future__ import annotations

import os
import platform
import sys
from functools import cache
from types import ModuleType

IS_WINDOWS = os.name == "nt"

_ARCH_NAMES = {"amd64": "x64", "x86_64": "x64", "aarch64": "arm64", "arm64": "arm64"}


def host_target() -> str:
    """Return the runtime target name, for example ``windows-x64`` or ``linux-x64``."""
    system = "windows" if IS_WINDOWS else sys.platform
    machine = platform.machine().lower()
    return f"{system}-{_ARCH_NAMES.get(machine, machine)}"


@cache
def backend() -> ModuleType:
    """Return the OS primitive module shared by the platform contracts."""
    if IS_WINDOWS:
        from rdc_tool.platform import _windows

        return _windows
    from rdc_tool.platform import _posix

    return _posix
