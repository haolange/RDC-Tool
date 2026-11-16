"""Windows primitives behind the platform contracts."""

from __future__ import annotations

import errno
import msvcrt
import os

_ERROR_LOCK_VIOLATION = 33


def try_lock(fd: int) -> bool:
    # LK_LOCK silently gives up after ~10 s, so only non-blocking attempts are used.
    os.lseek(fd, 0, os.SEEK_SET)
    try:
        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
    except OSError as exc:
        if exc.errno == errno.EACCES and getattr(exc, "winerror", None) in (None, _ERROR_LOCK_VIOLATION):
            return False
        raise
    return True


def unlock(fd: int) -> None:
    os.lseek(fd, 0, os.SEEK_SET)
    msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
