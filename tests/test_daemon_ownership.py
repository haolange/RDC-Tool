from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from rdc_tool import cli
from rdc_tool.daemon import client
from rdc_tool.daemon.ownership import DaemonOwnerUnavailable, owner_is_busy


_CHILD = r'''
import json,os,sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from rdc_tool.daemon import client,server
from rdc_tool.daemon.ownership import OwnerLease,DaemonOwnerUnavailable
client.STATE_DIR=Path(sys.argv[2])
path=client._daemon_state_path('isolated-owner')
mode=sys.argv[3]
if mode=='owner':
 lease=OwnerLease(path,'isolated-owner')
 state={'pid':os.getpid(),'pipe_name':'test-owner','token':'test-nonce'}
 client.save_daemon_state(state,'isolated-owner',lease=lease)
 print('owned',flush=True)
 sys.stdin.readline()
elif mode=='late-writer':
 old=client.load_daemon_state('isolated-owner')
 print('read',flush=True)
 sys.stdin.readline()
 try:client.save_daemon_state(old,'isolated-owner')
 except DaemonOwnerUnavailable as exc:print(exc.code,flush=True)
 else:raise AssertionError('late writer replaced successor')
elif mode=='teardown':
 server._daemon_state_path=lambda context:path
 class Listener:
  def __init__(self,**kwargs):pass
  def accept(self):raise OSError('test listener closed')
  def close(self):pass
 server.Listener=Listener
 runtime=server.DaemonRuntime(pipe_name='teardown',token='test-nonce',daemon_context='isolated-owner')
 runtime._stop=lambda:None
 runtime.serve_forever()
 print('returned',flush=True)
 sys.stdin.readline()
'''


@pytest.fixture
def isolated(monkeypatch, tmp_path):
    state_dir = tmp_path / 'runtime' / 'rdc_tool_cli'
    monkeypatch.setattr(client, 'STATE_DIR', state_dir)
    monkeypatch.setenv('RDC_TOOL_INTERMEDIATE_ROOT', str(tmp_path))
    return tmp_path


def _spawn(tmp_path, mode, *, popen=subprocess.Popen):
    root = Path(__file__).resolve().parents[1]
    env = dict(os.environ, RDC_TOOL_ROOT=str(root), RDC_TOOL_INTERMEDIATE_ROOT=str(tmp_path))
    return popen(
        [sys.executable, '-u', '-c', _CHILD, str(root), str(client.STATE_DIR), mode],
        env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )


def _line(proc):
    received = queue.Queue()
    reader = threading.Thread(target=lambda: received.put(proc.stdout.readline()), daemon=True)
    reader.start()
    try:
        line = received.get(timeout=10)
    except queue.Empty:
        pytest.fail('isolated child did not reach its barrier within 10 seconds')
    assert line, proc.stderr.read()
    return line.strip()


def _finish(proc):
    try:
        if proc.poll() is None:
            try:
                proc.stdin.write('exit\n')
                proc.stdin.flush()
            except BrokenPipeError:
                pass
            proc.wait(timeout=5)
        assert proc.returncode == 0, proc.stderr.read()
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)
        for stream in (proc.stdin, proc.stdout, proc.stderr):
            stream.close()


@pytest.mark.parametrize('state_kind', ['invalid', 'invalid_shape', 'missing'])
def test_live_process_owner_blocks_start_and_clear_without_readable_state(monkeypatch, isolated, state_kind):
    proc = _spawn(isolated, 'owner')
    try:
        assert _line(proc) == 'owned'
        path = client._daemon_state_path('isolated-owner')
        if state_kind == 'invalid':
            path.write_text('{broken', encoding='utf-8')
        elif state_kind == 'invalid_shape':
            path.write_text('{"pid":"broken"}', encoding='utf-8')
        else:
            path.unlink()
        artifact = client.context_state_path('isolated-owner')
        artifact.parent.mkdir(parents=True, exist_ok=True)
        artifact.write_text('{"note":"protected live context"}', encoding='utf-8')
        monkeypatch.setattr(client, 'list_context_ids', lambda: ['isolated-owner'])
        client.cleanup_stale_daemon_states()
        assert artifact.exists()
        monkeypatch.setattr(client.subprocess, 'Popen', lambda *a, **kw: pytest.fail('must not fork a live owner'))
        for operation in (lambda: client.ensure_daemon(context='isolated-owner'), lambda: client.clear_context('isolated-owner')):
            with pytest.raises(DaemonOwnerUnavailable) as caught:
                operation()
            payload = cli._exception_error_payload('rdc_tool.cli', caught.value)
            assert payload['error']['code'] == 'daemon_owner_unavailable'
            assert 'token' not in caught.value.details
        assert proc.poll() is None
        assert owner_is_busy(path, 'isolated-owner')
        assert client.context_occupies_capacity('isolated-owner')
        if state_kind == 'invalid':
            assert path.read_text(encoding='utf-8') == '{broken'
        elif state_kind == 'invalid_shape':
            assert path.read_text(encoding='utf-8') == '{"pid":"broken"}'
        else:
            assert not path.exists()
    finally:
        _finish(proc)
    assert not owner_is_busy(client._daemon_state_path('isolated-owner'), 'isolated-owner')


def test_live_status_failure_preserves_owner_and_state(monkeypatch, isolated):
    proc = _spawn(isolated, 'owner')
    try:
        assert _line(proc) == 'owned'
        path = client._daemon_state_path('isolated-owner')
        before = path.read_bytes()
        monkeypatch.setattr(client, 'daemon_request', lambda *a, **kw: (_ for _ in ()).throw(TimeoutError('probe failed')))
        monkeypatch.setattr(client.subprocess, 'Popen', lambda *a, **kw: pytest.fail('status failure must not fork'))
        monkeypatch.setattr(client, '_shutdown_stateful_daemon', lambda *a: pytest.fail('status failure must not stop owner'))
        with pytest.raises(DaemonOwnerUnavailable, match='live_owner_status_failed'):
            client.ensure_daemon(context='isolated-owner')
        assert proc.poll() is None
        assert path.read_bytes() == before
    finally:
        _finish(proc)


@pytest.mark.parametrize('changed', ['pid', 'pipe_name', 'token'])
def test_delayed_process_publication_and_response_cannot_replace_successor(isolated, changed):
    context = 'isolated-owner'
    old = {'pid': 123, 'pipe_name': 'old', 'token': 'old-test-nonce'}
    client.save_daemon_state(old, context)
    proc = _spawn(isolated, 'late-writer')
    try:
        assert _line(proc) == 'read'
        client.clear_daemon_state(context, expected=old)
        successor = {**old, changed: {'pid': os.getpid(), 'pipe_name': 'successor', 'token': 'successor-test-nonce'}[changed]}
        client.save_daemon_state(successor, context)
        before = client._daemon_state_path(context).read_bytes()
        proc.stdin.write('publish\n')
        proc.stdin.flush()
        assert _line(proc) == 'daemon_owner_unavailable'
        with pytest.raises(DaemonOwnerUnavailable, match='response_owner_changed'):
            client._update_saved_state_from_response({'result': {'state': old}}, context, expected=old)
        with pytest.raises(DaemonOwnerUnavailable, match='state_owner_changed'):
            client.clear_daemon_state(context, expected=old)
        assert client._daemon_state_path(context).read_bytes() == before
    finally:
        _finish(proc)


def test_server_keeps_owner_after_listener_teardown_until_process_exit(isolated):
    proc = _spawn(isolated, 'teardown')
    path = client._daemon_state_path('isolated-owner')
    try:
        assert _line(proc) == 'returned'
        assert proc.poll() is None
        assert owner_is_busy(path, 'isolated-owner')
    finally:
        _finish(proc)
    assert not owner_is_busy(path, 'isolated-owner')


def test_unconfirmed_stop_retains_state_and_prevents_replacement(monkeypatch, isolated):
    proc = _spawn(isolated, 'owner')
    try:
        assert _line(proc) == 'owned'
        path = client._daemon_state_path('isolated-owner')
        before = path.read_bytes()
        monkeypatch.setattr(client, '_context_has_unreleased_resources', lambda ctx: False)
        monkeypatch.setattr(client, '_shutdown_stateful_daemon', lambda *a: False)
        assert client.stop_daemon('isolated-owner') == (False, 'daemon stop timed out')
        assert path.read_bytes() == before
        assert owner_is_busy(path, 'isolated-owner')
        monkeypatch.setattr(client, 'daemon_request', lambda *a, **kw: (_ for _ in ()).throw(TimeoutError('stopping')))
        monkeypatch.setattr(client.subprocess, 'Popen', lambda *a, **kw: pytest.fail('unconfirmed stop must not fork'))
        with pytest.raises(DaemonOwnerUnavailable):
            client.ensure_daemon(context='isolated-owner')
    finally:
        _finish(proc)


@pytest.mark.parametrize('failure', ['status', 'ready_timeout'])
def test_failed_startup_never_clears_an_unconfirmed_live_child(monkeypatch, isolated, failure):
    children = []

    def spawn(*args, **kwargs):
        proc = _spawn(isolated, 'owner')
        children.append(proc)
        assert _line(proc) == 'owned'
        return proc

    monkeypatch.setattr(client.subprocess, 'Popen', spawn)
    monkeypatch.setattr(client, '_wait_for_daemon_ready', lambda state: failure != 'ready_timeout')
    monkeypatch.setattr(client, 'daemon_request', lambda *a, **kw: (_ for _ in ()).throw(TimeoutError('startup status failed')))
    monkeypatch.setattr(client, '_kill_process', lambda pid: False)
    monkeypatch.setattr(client, '_wait_for_pid_exit', lambda *a: False)
    try:
        expected = 'started_owner_status_failed' if failure == 'status' else 'startup_exit_unconfirmed'
        with pytest.raises(DaemonOwnerUnavailable, match=expected):
            client.ensure_daemon(context='isolated-owner')
        assert len(children) == 1 and children[0].poll() is None
        state = client.load_daemon_state('isolated-owner')
        assert state['pid'] == children[0].pid
        assert state['pipe_name'] == 'test-owner'
        assert owner_is_busy(client._daemon_state_path('isolated-owner'), 'isolated-owner')
    finally:
        for proc in children:
            _finish(proc)
