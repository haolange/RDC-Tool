"""Local daemon addresses: Windows pipes or private POSIX domain sockets.

Socket creation errors are propagated; there is no network/unauthenticated fallback.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import stat
import tempfile

from rdc_tool.runtime_paths import cli_runtime_dir


def _private_directory(path: Path) -> Path:
    try:
        path.mkdir(mode=0o700)
    except FileExistsError:
        pass
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
        raise PermissionError(f"IPC directory must be owned by this user with mode 0700: {path}")
    return path


def address(pipe_name: str) -> str:
    if os.name == "nt":
        return rf"\\.\pipe\{pipe_name}"
    # A fixed-size digest avoids sun_path limits even for long checkout/context names.
    namespace = hashlib.sha256(str(cli_runtime_dir().resolve()).encode()).hexdigest()[:16]
    root = _private_directory(Path(tempfile.gettempdir()) / f"rdc-tool-{os.getuid()}")
    directory = _private_directory(root / namespace)
    name = hashlib.sha256(pipe_name.encode()).hexdigest()[:32]
    result = str(directory / f"{name}.sock")
    if len(os.fsencode(result)) >= 104:
        raise ValueError("IPC socket path is too long; use a shorter TMPDIR")
    return result


def connection_options(token: str) -> dict:
    if os.name == "nt":
        return {"family": "AF_PIPE"}
    # Authenticate before multiprocessing unpickles the first message.
    if not token:
        raise ValueError("A daemon authentication token is required")
    return {"family": "AF_UNIX", "authkey": token.encode("utf-8")}
