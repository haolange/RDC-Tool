"""Exclusive file locks.

``path_lock`` serializes a critical section across threads and processes with
one monotonic deadline: a process-local mutex keyed by the lock path is taken
first, then the OS file lock is retried non-blockingly. Only documented lock
contention is retried; any other OS error propagates at once. ``HeldLock``
holds a lock for a process lifetime and is released by the OS on exit.
"""

from __future__ import annotations

import os
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO, Iterator, Literal

from rdc_tool.platform import host

_os = host.backend()
_MUTEXES: dict[str, threading.Lock] = {}
_MUTEXES_GUARD = threading.Lock()

LockStage = Literal["thread_mutex", "file_lock"]


class LockTimeout(TimeoutError):
    def __init__(self, path: Path, stage: LockStage, elapsed: float, timeout: float) -> None:
        super().__init__(f"Timed out acquiring {stage} for {path}")
        self.path = path
        self.stage = stage
        self.elapsed = elapsed
        self.timeout = timeout


def _remaining(deadline: float) -> float:
    return max(0.0, deadline - time.monotonic())


def _path_mutex(key: str, path: Path, started: float, deadline: float, timeout: float) -> threading.Lock:
    if not _MUTEXES_GUARD.acquire(timeout=_remaining(deadline)):
        raise LockTimeout(path, "thread_mutex", time.monotonic() - started, timeout)
    try:
        return _MUTEXES.setdefault(key, threading.Lock())
    finally:
        _MUTEXES_GUARD.release()


@contextmanager
def path_lock(path: Path, *, timeout: float, poll_interval: float = 0.05) -> Iterator[None]:
    """Hold ``path`` exclusively; ``timeout=0`` makes exactly one attempt."""
    started = time.monotonic()
    deadline = started + timeout
    path.parent.mkdir(parents=True, exist_ok=True)
    key = os.path.normcase(str(path.resolve()))
    mutex = _path_mutex(key, path, started, deadline, timeout)
    if not mutex.acquire(timeout=_remaining(deadline)):
        raise LockTimeout(path, "thread_mutex", time.monotonic() - started, timeout)
    try:
        with path.open("a+b") as handle:
            while not _os.try_lock(handle.fileno()):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise LockTimeout(path, "file_lock", time.monotonic() - started, timeout)
                time.sleep(min(poll_interval, remaining))
            try:
                yield
            finally:
                _os.unlock(handle.fileno())
    finally:
        mutex.release()


class HeldLock:
    """A lock owned until ``release()`` or process exit."""

    def __init__(self, handle: BinaryIO) -> None:
        self._handle = handle

    @classmethod
    def try_open(cls, path: Path) -> HeldLock | None:
        """Make one non-blocking attempt; ``None`` means the lock is held elsewhere."""
        path.parent.mkdir(parents=True, exist_ok=True)
        handle = path.open("a+b")
        try:
            acquired = _os.try_lock(handle.fileno())
        except BaseException:
            handle.close()
            raise
        if not acquired:
            handle.close()
            return None
        return cls(handle)

    @property
    def released(self) -> bool:
        return self._handle.closed

    def release(self) -> None:
        if not self._handle.closed:
            try:
                _os.unlock(self._handle.fileno())
            finally:
                self._handle.close()
