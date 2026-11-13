"""Cross-platform exclusive locks for runtime state and ownership handles."""
from __future__ import annotations

import errno
import os
from typing import BinaryIO

if os.name == "nt":
    import msvcrt
else:
    import fcntl


def _lock_fd(fd: int, blocking: bool) -> None:
    if os.name == "nt":
        msvcrt.locking(fd, msvcrt.LK_LOCK if blocking else msvcrt.LK_NBLCK, 1)
    else:
        fcntl.flock(fd, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))


def lock(handle: BinaryIO, *, blocking: bool = True) -> bool:
    """Acquire an exclusive lock; return False only for nonblocking contention."""
    handle.seek(0)
    try:
        _lock_fd(handle.fileno(), blocking)
    except OSError as exc:
        busy = (exc.errno == errno.EACCES and getattr(exc, "winerror", None) in (None, 33)) if os.name == "nt" else exc.errno in (errno.EACCES, errno.EAGAIN)
        if not blocking and busy:
            return False
        raise
    return True


def unlock(handle: BinaryIO) -> None:
    handle.seek(0)
    if os.name == "nt":
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
