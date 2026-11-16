from __future__ import annotations

import errno
import threading

import pytest

from rdc_tool.platform import host, locks


def test_held_lock_excludes_second_handle_until_release(tmp_path):
    path = tmp_path / 'owner.lock'
    first = locks.HeldLock.try_open(path)
    assert first is not None
    assert locks.HeldLock.try_open(path) is None
    first.release()
    assert first.released
    second = locks.HeldLock.try_open(path)
    assert second is not None
    second.release()


def test_path_lock_zero_timeout_is_one_attempt(tmp_path):
    path = tmp_path / 'state.lock'
    held = locks.HeldLock.try_open(path)
    try:
        with pytest.raises(locks.LockTimeout) as caught:
            with locks.path_lock(path, timeout=0):
                pytest.fail('entered')
        assert caught.value.stage == 'file_lock'
        assert caught.value.timeout == 0
    finally:
        held.release()
    with locks.path_lock(path, timeout=0):
        pass


def test_path_lock_serializes_threads(tmp_path):
    path = tmp_path / 'shared.lock'
    inside = []
    def worker():
        with locks.path_lock(path, timeout=5):
            inside.append(1)
            assert len(inside) == 1
            inside.pop()
    threads = [threading.Thread(target=worker) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(10)
    assert not any(thread.is_alive() for thread in threads)


def test_host_target_names_os_and_arch():
    system, _, arch = host.host_target().partition('-')
    assert system in {'windows', 'linux', 'darwin'}
    assert arch


@pytest.mark.skipif(host.IS_WINDOWS, reason='POSIX lock primitive')
def test_posix_non_contention_error_propagates(tmp_path):
    import os

    from rdc_tool.platform import _posix

    fd = os.open(tmp_path / 'closed.lock', os.O_CREAT | os.O_RDWR)
    os.close(fd)
    with pytest.raises(OSError) as caught:
        _posix.try_lock(fd)
    assert caught.value.errno == errno.EBADF


@pytest.mark.skipif(not host.IS_WINDOWS, reason='Windows lock primitive')
def test_windows_access_denied_is_not_contention(monkeypatch, tmp_path):
    from rdc_tool.platform import _windows

    failure = OSError(errno.EACCES, 'denied')
    failure.winerror = 5
    monkeypatch.setattr(_windows.msvcrt, 'locking', lambda *args: (_ for _ in ()).throw(failure))
    with (tmp_path / 'denied.lock').open('a+b') as handle:
        with pytest.raises(OSError) as caught:
            _windows.try_lock(handle.fileno())
    assert caught.value is failure


@pytest.mark.skipif(not host.IS_WINDOWS, reason='Windows lock primitive')
def test_windows_lock_violation_is_contention(monkeypatch, tmp_path):
    from rdc_tool.platform import _windows

    failure = OSError(errno.EACCES, 'locked')
    failure.winerror = 33
    monkeypatch.setattr(_windows.msvcrt, 'locking', lambda *args: (_ for _ in ()).throw(failure))
    with (tmp_path / 'busy.lock').open('a+b') as handle:
        assert _windows.try_lock(handle.fileno()) is False
