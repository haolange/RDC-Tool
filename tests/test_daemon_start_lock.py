from __future__ import annotations

import errno
import json
import os
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from rdc_tool import cli, environment
from rdc_tool.daemon import client


@pytest.fixture(autouse=True)
def lock_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(client, 'STATE_DIR', tmp_path / 'locks')


def test_nonblocking_retry_and_unlock(monkeypatch):
    clock = [0.0]
    modes = []
    monkeypatch.setattr(client.time, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(client.time, 'sleep', lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    def locking(fd, mode, size):
        modes.append(mode)
        assert size == 1
        if mode == client.msvcrt.LK_NBLCK and len(modes) <= 2:
            raise OSError(errno.EACCES, 'locked')
    monkeypatch.setattr(client.msvcrt, 'locking', locking)
    with client._locked_daemon_start('retry'):
        assert clock[0] == pytest.approx(.1)
    assert modes == [client.msvcrt.LK_NBLCK] * 3 + [client.msvcrt.LK_UNLCK]


@pytest.mark.parametrize('failure', [OSError(errno.EBADF, 'bad descriptor'), OSError(errno.EINVAL, 'bad argument'), OSError(errno.EIO, 'I/O'), KeyboardInterrupt()])
def test_non_contention_and_interrupt_release_mutex(monkeypatch, failure):
    real_locking = client.msvcrt.locking
    def fail(*args):
        raise failure
    monkeypatch.setattr(client.msvcrt, 'locking', fail)
    monkeypatch.setattr(client.time, 'sleep', lambda _: pytest.fail('must not retry'))
    with pytest.raises(type(failure)):
        with client._locked_daemon_start('failed'):
            pytest.fail('entered')
    monkeypatch.setattr(client.msvcrt, 'locking', real_locking)
    with client._locked_daemon_start('failed'):
        pass


def test_explicit_access_denied_is_not_contention(monkeypatch):
    failure = OSError(errno.EACCES, 'denied')
    failure.winerror = 5
    monkeypatch.setattr(client.msvcrt, 'locking', lambda *args: (_ for _ in ()).throw(failure))
    monkeypatch.setattr(client.time, 'sleep', lambda _: pytest.fail('must not retry'))
    with pytest.raises(OSError) as caught:
        with client._locked_daemon_start('denied'):
            pytest.fail('entered')
    assert caught.value is failure


def test_timeout_never_enters_startup_or_unlocks(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(client, 'DAEMON_START_LOCK_TIMEOUT_S', .125)
    monkeypatch.setattr(client.time, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(client.time, 'sleep', lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    modes = []
    def busy(fd, mode, size):
        modes.append(mode)
        raise OSError(errno.EACCES, 'locked')
    monkeypatch.setattr(client.msvcrt, 'locking', busy)
    monkeypatch.setattr(client, '_ensure_daemon_locked', lambda **kw: pytest.fail('startup entered'))
    with pytest.raises(client.DaemonStartLockTimeout) as caught:
        client.ensure_daemon(context='busy')
    assert clock[0] == pytest.approx(.125)
    assert set(modes) == {client.msvcrt.LK_NBLCK}
    payload = cli._exception_error_payload('rdc_tool.cli', caught.value)
    assert payload['error']['code'] == 'daemon_start_lock_timeout'
    assert caught.value.details['waiting_for'] == 'file_lock'
    assert caught.value.details['elapsed_seconds'] == pytest.approx(.125)


def test_thread_mutex_and_file_retry_share_one_deadline(monkeypatch):
    clock = [0.0]
    class Mutex:
        def acquire(self, *, timeout):
            assert timeout == pytest.approx(.2)
            clock[0] += .15
            return True
        def release(self):
            clock.append('released')
    path = client._daemon_state_path('deadline').with_suffix('.start.lock')
    key = os.path.normcase(str(path.resolve()))
    monkeypatch.setattr(client, '_START_MUTEXES', {key: Mutex()})
    monkeypatch.setattr(client, 'DAEMON_START_LOCK_TIMEOUT_S', .2)
    monkeypatch.setattr(client.time, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(client.time, 'sleep', lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    monkeypatch.setattr(client.msvcrt, 'locking', lambda *args: (_ for _ in ()).throw(OSError(errno.EACCES, 'locked')))
    with pytest.raises(client.DaemonStartLockTimeout):
        with client._locked_daemon_start('deadline'):
            pytest.fail('entered')
    assert clock == [pytest.approx(.2), 'released']


def test_thread_wait_is_bounded_and_other_context_is_independent(monkeypatch):
    entered, release = threading.Event(), threading.Event()
    def hold():
        with client._locked_daemon_start('thread'):
            entered.set()
            assert release.wait(5)
    owner = threading.Thread(target=hold)
    owner.start()
    try:
        assert entered.wait(5)
        monkeypatch.setattr(client, 'DAEMON_START_LOCK_TIMEOUT_S', .1)
        with pytest.raises(client.DaemonStartLockTimeout) as caught:
            with client._locked_daemon_start('thread'):
                pytest.fail('entered')
        assert caught.value.details['waiting_for'] == 'thread_mutex'
        with client._locked_daemon_start('other'):
            pass
    finally:
        release.set()
        owner.join(5)
    assert not owner.is_alive()


def test_file_open_failure_releases_thread_mutex(monkeypatch):
    real_open = Path.open
    def fail(path, *args, **kwargs):
        if path.suffix == '.lock':
            raise PermissionError('fixture denied')
        return real_open(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'open', fail)
    with pytest.raises(PermissionError):
        with client._locked_daemon_start('open'):
            pytest.fail('entered')
    monkeypatch.setattr(Path, 'open', real_open)
    with client._locked_daemon_start('open'):
        pass


def test_body_failure_unlocks(monkeypatch):
    with pytest.raises(RuntimeError, match='body'):
        with client._locked_daemon_start('body'):
            raise RuntimeError('body')
    with client._locked_daemon_start('body'):
        pass


def test_cli_start_timeout_does_not_clean_state(monkeypatch, capsys):
    cleaned = []
    monkeypatch.setattr(environment, 'validate_environment', lambda: None)
    monkeypatch.setattr(cli, 'cleanup_stale_daemon_states', lambda **kw: cleaned.append(kw))
    def timeout(**kw):
        raise client.DaemonStartLockTimeout('cli-busy', 'file_lock', time.monotonic(), 30)
    monkeypatch.setattr(cli, 'ensure_daemon', timeout)
    monkeypatch.setattr(sys, 'argv', ['rdc-tool', '--daemon-context', 'cli-busy', 'daemon', 'start'])
    with pytest.raises(SystemExit) as caught:
        cli.main()
    assert caught.value.code == cli.EXIT_RUNTIME_ERR
    assert json.loads(capsys.readouterr().out)['error']['code'] == 'daemon_start_lock_timeout'
    assert cleaned == []


_CHILD = r'''
import json,os,sys,time
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from rdc_tool.daemon import client
from rdc_tool.runtime_process_identity import _process_birth
client.STATE_DIR=Path(sys.argv[2])
mode=sys.argv[3]
if mode=='hold':
 with client._locked_daemon_start('shared'):
  print('locked',flush=True)
  sys.stdin.readline()
elif mode=='wait':
 print('waiting',flush=True)
 start=time.monotonic()
 with client._locked_daemon_start('shared'):
  print(json.dumps({'elapsed':time.monotonic()-start}),flush=True)
else:
 if mode=='slow':
  real_wait=client._wait_for_daemon_ready
  def wait(state):
   print('spawned',flush=True)
   sys.stdin.readline()
   return real_wait(state)
  client._wait_for_daemon_ready=wait
 print('starting',flush=True)
 started=time.monotonic()
 try:
  ok,message,state=client.ensure_daemon(context='shared',owner_pid=int(sys.argv[4]))
 except client.DaemonStartLockTimeout as exc:
  if mode!='bounded':raise
  print(json.dumps({'code':exc.code,'elapsed':time.monotonic()-started}),flush=True)
  sys.exit(0)
 print(json.dumps({'ok':ok,'pid':state.get('pid'),'birth':_process_birth(state['pid']),'elapsed':time.monotonic()-started}),flush=True)
'''


def _spawn(tmp_path, mode):
    root = Path(__file__).resolve().parents[1]
    env = dict(os.environ, RDC_TOOL_INTERMEDIATE_ROOT=str(tmp_path), RDC_TOOL_ROOT=str(root))
    state = tmp_path / 'runtime' / 'rdc_tool_cli'
    return subprocess.Popen([sys.executable, '-u', '-c', _CHILD, str(root), str(state), mode, str(os.getpid())],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)


def _line(process, timeout=20):
    result = queue.Queue()
    reader = threading.Thread(target=lambda: result.put(process.stdout.readline()), daemon=True)
    reader.start()
    try:
        text = result.get(timeout=timeout)
    except queue.Empty:
        process.kill()
        process.wait(timeout=5)
        reader.join(5)
        pytest.fail('child did not publish its barrier')
    reader.join(5)
    assert text, process.stderr.read()
    return text.strip()


def _close(*processes):
    for process in processes:
        if process:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)
            for stream in (process.stdin, process.stdout, process.stderr):
                stream.close()


def test_process_wait_survives_old_crt_retry_window(tmp_path):
    owner = _spawn(tmp_path, 'hold')
    waiter = None
    try:
        assert _line(owner) == 'locked'
        waiter = _spawn(tmp_path, 'wait')
        assert _line(waiter) == 'waiting'
        time.sleep(15)
        assert waiter.poll() is None
        owner.stdin.write('release\n')
        owner.stdin.flush()
        result = json.loads(_line(waiter))
        assert 14 <= result['elapsed'] < 30
        owner.wait(timeout=5)
        waiter.wait(timeout=5)
        assert owner.returncode == waiter.returncode == 0
    finally:
        _close(waiter, owner)


def test_process_owner_exit_releases_lock(tmp_path):
    owner = _spawn(tmp_path, 'hold')
    try:
        assert _line(owner) == 'locked'
        owner.kill()
        owner.wait(timeout=5)
        waiter = _spawn(tmp_path, 'wait')
        try:
            assert _line(waiter) == 'waiting'
            assert json.loads(_line(waiter))['elapsed'] < 5
            waiter.wait(timeout=5)
        finally:
            _close(waiter)
    finally:
        _close(owner)


def test_slow_real_daemon_is_reused_across_processes(monkeypatch, tmp_path):
    monkeypatch.setenv('RDC_TOOL_INTERMEDIATE_ROOT', str(tmp_path))
    monkeypatch.setattr(client, 'STATE_DIR', tmp_path / 'runtime' / 'rdc_tool_cli')
    owner = _spawn(tmp_path, 'slow')
    waiter = None
    try:
        assert _line(owner) == 'starting'
        assert _line(owner) == 'spawned'
        waiter = _spawn(tmp_path, 'normal')
        assert _line(waiter) == 'starting'
        time.sleep(15)
        assert waiter.poll() is None
        owner.stdin.write('release\n')
        owner.stdin.flush()
        one, two = json.loads(_line(owner)), json.loads(_line(waiter))
        assert one['ok'] and two['ok']
        assert one['pid'] == two['pid']
        assert one['birth'] == two['birth']
        assert 14 <= two['elapsed'] < 30
        owner.wait(timeout=5)
        waiter.wait(timeout=5)
    finally:
        _close(waiter, owner)
        assert client.clear_context('shared')[0]
        assert client.stop_daemon('shared')[0]


def test_process_default_deadline_preserves_slow_live_owner(monkeypatch, tmp_path):
    from rdc_tool.runtime_process_identity import _process_birth
    monkeypatch.setenv('RDC_TOOL_INTERMEDIATE_ROOT', str(tmp_path))
    monkeypatch.setattr(client, 'STATE_DIR', tmp_path / 'runtime' / 'rdc_tool_cli')
    owner = _spawn(tmp_path, 'slow')
    waiter = None
    try:
        assert _line(owner) == 'starting'
        assert _line(owner) == 'spawned'
        # Readiness publication is blocked only in the test-side caller.
        deadline = time.monotonic() + 10
        state = {}
        while not state and time.monotonic() < deadline:
            state = client.load_daemon_state('shared')
            time.sleep(.05)
        assert state
        birth = _process_birth(state['pid'])
        waiter = _spawn(tmp_path, 'bounded')
        assert _line(waiter) == 'starting'
        result = json.loads(_line(waiter, timeout=40))
        assert result['code'] == 'daemon_start_lock_timeout'
        assert 29 <= result['elapsed'] < 35
        assert owner.poll() is None
        # Assert the original live owner through its authenticated connection,
        # not a single unqualified read of a concurrently published state file.
        response = client.daemon_request('status', params={}, state=state, context='shared', timeout=2)
        assert response['ok']
        current = response['result']['state']
        assert (current['pid'], current['pipe_name']) == (state['pid'], state['pipe_name'])
        assert _process_birth(current['pid']) == birth
        owner.stdin.write('release\n')
        owner.stdin.flush()
        published = json.loads(_line(owner))
        assert published['ok'] and published['pid'] == state['pid']
        owner.wait(timeout=5)
        waiter.wait(timeout=5)
    finally:
        _close(waiter, owner)
        assert client.clear_context('shared')[0]
        assert client.stop_daemon('shared')[0]


def test_mutex_registry_wait_also_uses_acquisition_deadline(monkeypatch):
    registry = threading.Lock()
    registry.acquire()
    monkeypatch.setattr(client, '_START_MUTEXES_LOCK', registry)
    monkeypatch.setattr(client, 'DAEMON_START_LOCK_TIMEOUT_S', .05)
    try:
        with pytest.raises(client.DaemonStartLockTimeout) as caught:
            with client._locked_daemon_start('registry'):
                pytest.fail('entered')
        assert caught.value.details['waiting_for'] == 'thread_mutex'
    finally:
        registry.release()
