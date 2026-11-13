from __future__ import annotations

import errno
import os
from pathlib import Path
import socket
import stat

import pytest

from rdc_tool import file_lock
from rdc_tool.daemon import client, transport


def test_lock_contention_and_release(tmp_path):
    with (tmp_path / 'lock').open('a+b') as first, (tmp_path / 'lock').open('a+b') as second:
        assert file_lock.lock(first, blocking=False)
        assert not file_lock.lock(second, blocking=False)
        file_lock.unlock(first)
        assert file_lock.lock(second, blocking=False)
        file_lock.unlock(second)


@pytest.mark.skipif(os.name == 'nt', reason='POSIX-specific transport')
def test_socket_address_is_private_and_namespaced(monkeypatch, tmp_path):
    monkeypatch.setattr(transport.tempfile, 'gettempdir', lambda: str(tmp_path))
    monkeypatch.setattr(transport, 'cli_runtime_dir', lambda: Path('/a/long/root'))
    # The pytest path can itself exceed sun_path, so this test checks the directory
    # independently rather than making an unportable long socket address.
    private = transport._private_directory(tmp_path / 'private')
    assert stat.S_IMODE(private.stat().st_mode) == 0o700
    assert private.stat().st_uid == os.getuid()
    public = tmp_path / 'public'; public.mkdir(mode=0o755)
    with pytest.raises(PermissionError):
        transport._private_directory(public)
    assert transport.connection_options('test-token') == {'family':'AF_UNIX', 'authkey':b'test-token'}


@pytest.mark.skipif(os.name == 'nt', reason='POSIX-specific transport')
def test_socket_directory_rejects_symlink(tmp_path):
    target = tmp_path / 'target'; target.mkdir(mode=0o700)
    link = tmp_path / 'link'; link.symlink_to(target, target_is_directory=True)
    with pytest.raises(PermissionError):
        transport._private_directory(link)


def test_socket_permission_error_is_not_hidden(monkeypatch):
    def denied(**kwargs):
        raise PermissionError(errno.EPERM, 'fixture socket denied')
    monkeypatch.setattr(client, 'Client', denied)
    monkeypatch.setattr(client, '_pipe_address', lambda name: 'fixture-address')
    with pytest.raises(PermissionError) as caught:
        client.daemon_request('ping', state={'pipe_name':'test', 'token':'test'})
    assert caught.value.errno == errno.EPERM


def test_socket_address_is_bounded_and_context_specific(monkeypatch):
    if os.name == 'nt':
        pytest.skip('POSIX socket path')
    import tempfile
    with tempfile.TemporaryDirectory(prefix='rdci-', dir='/tmp') as directory:
        monkeypatch.setattr(transport.tempfile, 'gettempdir', lambda: directory)
        monkeypatch.setattr(transport, 'cli_runtime_dir', lambda: Path('/long/' + 'x' * 300))
        a = transport.address('context/' + 'a' * 300)
        b = transport.address('context-b')
        assert a != b and len(os.fsencode(a)) < 104
        assert stat.S_IMODE(Path(a).parent.stat().st_mode) == 0o700


def test_windows_lock_errors_and_named_pipe_contract(monkeypatch, tmp_path):
    from types import SimpleNamespace
    calls = []
    def locking(fd, mode, length):
        calls.append((mode, length))
    fake_crt = SimpleNamespace(LK_LOCK=1, LK_NBLCK=2, LK_UNLCK=0, locking=locking)
    monkeypatch.setattr(file_lock, 'os', SimpleNamespace(name='nt'))
    monkeypatch.setattr(file_lock, 'msvcrt', fake_crt, raising=False)
    with (tmp_path / 'lock').open('a+b') as handle:
        assert file_lock.lock(handle, blocking=False)
        file_lock.unlock(handle)
        assert calls == [(2, 1), (0, 1)]
        failure = OSError(errno.EACCES, 'fixture access denied'); failure.winerror = 5
        fake_crt.locking = lambda *args: (_ for _ in ()).throw(failure)
        with pytest.raises(OSError) as caught:
            file_lock.lock(handle, blocking=False)
        assert caught.value is failure
    monkeypatch.setattr(transport, 'os', SimpleNamespace(name='nt'))
    assert transport.address('name') == r'\\.\pipe\name'
    assert transport.connection_options('token') == {'family':'AF_PIPE'}
