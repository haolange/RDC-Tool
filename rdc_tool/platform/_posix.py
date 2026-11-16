"""POSIX primitives behind the platform contracts."""

from __future__ import annotations

import errno
import fcntl

_LOCK_BUSY = frozenset({errno.EWOULDBLOCK, errno.EAGAIN, errno.EACCES})


def try_lock(fd: int) -> bool:
    # flock is per open file description, matching per-handle Windows locks.
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        if exc.errno in _LOCK_BUSY:
            return False
        raise
    return True


def unlock(fd: int) -> None:
    fcntl.flock(fd, fcntl.LOCK_UN)
