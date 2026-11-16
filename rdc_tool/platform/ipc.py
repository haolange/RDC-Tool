"""Authenticated local IPC endpoints.

Windows uses named pipes; POSIX uses Unix sockets inside a private 0700
directory owned by the current user. Both run the multiprocessing HMAC
challenge with the per-daemon key during ``accept``/``connect``, before any
request is unpickled. There is no network or unauthenticated fallback.
"""

from __future__ import annotations

import os
import secrets
import stat
import tempfile
from dataclasses import dataclass
from multiprocessing.connection import Client, Connection, Listener
from pathlib import Path

from rdc_tool.platform import host

_FAMILY = "AF_PIPE" if host.IS_WINDOWS else "AF_UNIX"
_MAX_SOCKET_PATH_BYTES = 104


@dataclass(frozen=True)
class Endpoint:
    address: str


def private_runtime_dir() -> Path:
    """POSIX directory for sockets: owned by this user, mode 0700, not a link."""
    base = os.environ.get("XDG_RUNTIME_DIR", "").strip()
    path = Path(base) / "rdc-tool" if base else Path(tempfile.gettempdir()) / f"rdc-tool-{os.getuid()}"
    try:
        path.mkdir(mode=0o700)
    except FileExistsError:
        pass
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
        raise PermissionError(f"IPC directory must be a 0700 directory owned by this user: {path}")
    return path


def new_endpoint() -> Endpoint:
    if host.IS_WINDOWS:
        return Endpoint(rf"\\.\pipe\rdc-tool-{os.getpid()}-{secrets.token_hex(8)}")
    address = str(private_runtime_dir() / f"{secrets.token_hex(16)}.sock")
    if len(os.fsencode(address)) >= _MAX_SOCKET_PATH_BYTES:
        raise OSError(f"IPC socket path exceeds the Unix socket limit; use a shorter TMPDIR: {address}")
    return Endpoint(address)


def listen(endpoint: Endpoint, *, authkey: bytes) -> Listener:
    return Listener(address=endpoint.address, family=_FAMILY, authkey=authkey)


def connect(endpoint: Endpoint, *, authkey: bytes) -> Connection:
    return Client(address=endpoint.address, family=_FAMILY, authkey=authkey)


def discard(endpoint: Endpoint) -> None:
    """Remove a dead owner's socket file; named pipes vanish with their owner."""
    if host.IS_WINDOWS or not endpoint.address:
        return
    path = Path(endpoint.address)
    if path.parent == private_runtime_dir() and path.is_socket():
        path.unlink(missing_ok=True)
