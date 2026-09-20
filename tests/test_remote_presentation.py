import asyncio
from types import SimpleNamespace
import pytest
from rdc_tool.core import session_manager as module
from rdc_tool.models import BackendType

@pytest.fixture
def manager(monkeypatch):
    value = module.SessionManager()
    value._sessions['owner'] = module.SessionState('owner', BackendType.REMOTE)
    async def offload(fn, *args): return fn(*args)
    monkeypatch.setattr(value, '_offload', offload)
    monkeypatch.setattr(module, '_get_rd', lambda: SimpleNamespace(ResourceId=SimpleNamespace(Null=lambda: 'null')))
    def status(value, *args, **kwargs):
        if not value: raise module.SessionError('renderdoc_error', 'native failed')
    monkeypatch.setattr(module, '_check_status', status)
    return value

def run(manager, resource='texture'):
    return asyncio.run(manager.present_remote('owner', 42, resource))

@pytest.mark.parametrize('sequence', [0, -1, True, 1.5, '1', None])
def test_invalid_receipt_sequence(manager, sequence):
    manager._sessions['owner'].remote_server = SimpleNamespace(PresentReplay=lambda *args: (True, sequence))
    with pytest.raises(module.SessionError, match='not fresh'): run(manager)
    assert manager._sessions['owner'].presentation_sequence == 0

def test_receipt_is_fresh_and_uses_owning_connection(manager):
    calls=[]
    state=manager._sessions['owner']
    state.remote_server=SimpleNamespace(PresentReplay=lambda *args: (calls.append(args) or True, 2))
    assert run(manager) == 2
    assert calls == [(42, 'texture')]
    with pytest.raises(module.SessionError, match='not fresh'): run(manager)
    with pytest.raises(module.SessionError, match='Unknown session'): asyncio.run(manager.present_remote('other',42,'texture'))

def test_failed_native_does_not_advance_sequence(manager):
    state=manager._sessions['owner'];state.presentation_sequence=3
    state.remote_server=SimpleNamespace(PresentReplay=lambda *args: (False, 4))
    with pytest.raises(module.SessionError, match='native failed'): run(manager)
    assert state.presentation_sequence == 3

def test_clear_uses_null_resource(manager):
    calls=[]
    manager._sessions['owner'].remote_server=SimpleNamespace(PresentReplay=lambda *args: (calls.append(args) or True, 1))
    assert run(manager,None) == 1 and calls == [(42,'null')]

def test_missing_connection_and_capability(manager):
    with pytest.raises(module.SessionError, match='No owning'): run(manager)
    manager._sessions['owner'].remote_server=SimpleNamespace()
    with pytest.raises(module.SessionError, match='matching runtime'): run(manager)

def test_new_remote_controller_resets_sequence(manager, monkeypatch):
    state=manager._sessions['owner'];state.remote_server=object();state.presentation_sequence=20
    monkeypatch.setattr(manager, '_open_remote_capture_sync', lambda *args: (state.remote_server,'remote.rdc',object()))
    async def output(*args): pass
    monkeypatch.setattr(manager, '_create_headless_output',output)
    asyncio.run(manager._open_remote_capture(state,'input.rdc'))
    assert state.presentation_sequence == 0
