from pathlib import Path
import pytest
from rdc_tool import stdio_host, runtime_worker
from rdc_tool.daemon.ownership import OwnerLease, DaemonOwnerUnavailable


def test_stdio_reuses_worker_and_releases_owner(monkeypatch,tmp_path):
    state=tmp_path/'state.json';called=[]
    monkeypatch.setattr(stdio_host,'_daemon_state_path',lambda context:state)
    monkeypatch.setattr(stdio_host,'host_native_manifest_status',lambda root:{'status':'verified'})
    def main(args):
        called.append(args)
        with pytest.raises(DaemonOwnerUnavailable):OwnerLease(state,'test')
        return 0
    monkeypatch.setattr(runtime_worker,'main',main)
    assert stdio_host.run_stdio('test')==0
    assert called==[['--context-id','test']]
    lease=OwnerLease(state,'test');lease.close()


def test_stdio_releases_owner_on_failure(monkeypatch,tmp_path):
    state=tmp_path/'state.json'
    monkeypatch.setattr(stdio_host,'_daemon_state_path',lambda context:state)
    monkeypatch.setattr(stdio_host,'host_native_manifest_status',lambda root:{'status':'verified'})
    monkeypatch.setattr(runtime_worker,'main',lambda args:(_ for _ in ()).throw(ValueError('failure')))
    with pytest.raises(ValueError,match='failure'):stdio_host.run_stdio('test')
    lease=OwnerLease(state,'test');lease.close()


def test_stdio_rejects_bad_native_receipt(monkeypatch):
    monkeypatch.setattr(stdio_host,'host_native_manifest_status',lambda root:{'status':'invalid','reason':'mismatch'})
    monkeypatch.setattr(runtime_worker,'main',lambda args:pytest.fail('invalid runtime started'))
    with pytest.raises(RuntimeError,match='integrity failed'):stdio_host.run_stdio('test')


def test_stdio_restart_quarantines_persisted_sessions(monkeypatch, tmp_path):
    import asyncio
    from rdc_tool import server_runtime
    from rdc_tool.runtime_state import save_context_state, load_context_state
    state = tmp_path / 'owner.json'
    monkeypatch.setattr(stdio_host, '_daemon_state_path', lambda context: state)
    monkeypatch.setattr(stdio_host, 'host_native_manifest_status', lambda root: {'status': 'verified'})
    context = 'stdio-restart'
    calls = []
    async def recover(*args, **kwargs):
        pytest.fail('persisted native session was automatically recovered')
    monkeypatch.setattr(server_runtime, '_recover_single_session_from_state', recover)
    monkeypatch.setattr(server_runtime, '_runtime_context_id', lambda: context)
    monkeypatch.setattr(server_runtime, '_session_manager', object())
    def main(args):
        if not calls:
            save_context_state({'sessions': {'old': {'session_id': 'old', 'backend_type': 'local',
                'is_live': True, 'state': 'ready', 'recovery': {'status': 'ready'}}}}, context)
        else:
            assert load_context_state(context)['sessions']['old']['recovery']['status'] == 'requires_restart'
            asyncio.run(server_runtime._recover_context_sessions(context))
            with pytest.raises(Exception) as error:
                asyncio.run(server_runtime._ensure_live_session('old'))
            assert error.value.code == 'session_requires_restart'
        calls.append(args)
        return 0
    monkeypatch.setattr(runtime_worker, 'main', main)
    assert stdio_host.run_stdio(context) == 0
    assert stdio_host.run_stdio(context) == 0
    assert len(calls) == 2
