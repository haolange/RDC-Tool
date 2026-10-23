from __future__ import annotations

import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor
from enum import IntEnum
from types import SimpleNamespace as NS

import pytest

from rdc_tool import server_runtime, tool_router
from rdc_tool.core.engine import CoreEngine
from rdc_tool.core import pipeline_service as pipeline


class Code(IntEnum):
    Succeeded = 0
    RemoteServerConnectionLost = 1


class Status:
    def __init__(self, code=Code.Succeeded):
        self.code = code

    def OK(self):
        return self.code == Code.Succeeded

    def Message(self):
        return 'Connection lost to remote server' if not self.OK() else ''


class Controller:
    def __init__(self):
        self.status = Status()
        self.probes = 0

    def GetFatalErrorStatus(self):
        self.probes += 1
        return self.status


@pytest.fixture
def runtime(monkeypatch):
    controller = Controller()
    updates = []

    async def ensure_live_session(session_id):
        assert session_id == 'native-session'

    monkeypatch.setattr(server_runtime, '_ensure_live_session', ensure_live_session)
    monkeypatch.setattr(server_runtime, '_context_snapshot', lambda: {'runtime': {'session_id': 'native-session'}})
    monkeypatch.setattr(server_runtime, '_session_manager', NS(get_controller=lambda session_id: controller))
    monkeypatch.setattr(server_runtime, '_update_context_session_record',
                        lambda session_id, **fields: updates.append((session_id, fields)))
    return controller, updates


def execute(monkeypatch, operation, handler):
    domain = operation.split('.')[1]
    monkeypatch.setitem(tool_router._DOMAIN_HANDLERS, domain, handler)
    engine = CoreEngine(registry=tool_router.build_operation_registry())
    args = {'session_id': 'native-session'}
    if operation == 'rd.texture.get_pixel_value':
        args.update(texture_id='ResourceId::187074', x=685, y=70, event_id=1716)
    elif operation == 'rd.session.observe':
        args = {'out_path': '/qa/observation.png'}
    elif operation == 'rd.pipeline.get_state':
        args.update(event_id=1716, detail='summary', sections=['blend'])
    return asyncio.run(engine.execute(operation, args))


@pytest.mark.parametrize('operation', ['rd.texture.get_pixel_value', 'rd.pipeline.get_state', 'rd.session.observe'])
def test_existing_native_fatal_rejects_before_read(monkeypatch, runtime, operation):
    controller, updates = runtime
    controller.status = Status(Code.RemoteServerConnectionLost)
    called = []

    async def handler(action, args, env):
        await server_runtime._get_controller(args.get("session_id", "native-session"))
        called.append(action)
        return {'success': True, 'r': 0}

    result = execute(monkeypatch, operation, handler)
    assert result['ok'] is False
    assert result['error']['code'] == 'replay_fatal_error'
    assert result['error']['details']['renderdoc_status']['result_code_name'] == 'RemoteServerConnectionLost'
    assert result['data'] == {} and result['artifacts'] == []
    assert called == []
    assert updates[-1][1]['recovery_status'] == 'requires_restart'


@pytest.mark.parametrize('operation', ['rd.texture.get_pixel_value', 'rd.pipeline.get_state', 'rd.session.observe'])
def test_native_fatal_during_call_rejects_default_success(monkeypatch, runtime, operation):
    controller, updates = runtime

    async def handler(action, args, env):
        await server_runtime._get_controller(args.get("session_id", "native-session"))
        controller.status = Status(Code.RemoteServerConnectionLost)
        return {'success': True, 'r': 0, 'g': 0, 'b': 0, 'a': 0}

    result = execute(monkeypatch, operation, handler)
    assert result['ok'] is False
    assert result['error']['code'] == 'replay_fatal_error'
    assert result['data'] == {} and result['artifacts'] == []
    assert updates[-1][1]['recovery_status'] == 'requires_restart'


def test_native_fatal_explains_secondary_projection_exception(monkeypatch, runtime):
    controller, _ = runtime

    async def handler(action, args, env):
        await server_runtime._get_controller(args.get("session_id", "native-session"))
        controller.status = Status(Code.RemoteServerConnectionLost)
        raise AttributeError("'NoneType' object has no attribute 'outputMerger'")

    result = execute(monkeypatch, 'rd.pipeline.get_state', handler)
    assert result['error']['code'] == 'replay_fatal_error'
    assert 'Connection lost' in result['error']['message']


def test_healthy_native_zero_is_valid_readback(monkeypatch, runtime):
    controller, updates = runtime

    async def handler(action, args, env):
        await server_runtime._get_controller(args.get("session_id", "native-session"))
        return {'success': True, 'r': 0, 'g': 0, 'b': 0, 'a': 0}

    result = execute(monkeypatch, 'rd.texture.get_pixel_value', handler)
    assert result['ok'] is True and result['data']['r'] == 0
    assert controller.probes >= 2 and updates == []


@pytest.mark.parametrize('probe', [None, lambda: None])
def test_missing_or_unknown_health_is_not_assumed_success(monkeypatch, runtime, probe):
    controller, _ = runtime
    controller.GetFatalErrorStatus = probe
    called = []

    async def handler(action, args, env):
        await server_runtime._get_controller(args.get("session_id", "native-session"))
        called.append(action)
        return {'success': True, 'r': 0}

    result = execute(monkeypatch, 'rd.texture.get_pixel_value', handler)
    assert result['ok'] is False
    assert result['error']['code'] == 'replay_health_unavailable'
    assert called == []


def test_non_native_projection_error_keeps_original_error(monkeypatch, runtime):
    async def handler(action, args, env):
        await server_runtime._get_controller(args.get("session_id", "native-session"))
        raise AttributeError('independent projection failure')

    result = execute(monkeypatch, 'rd.pipeline.get_state', handler)
    assert result['error']['code'] == 'internal_error'
    assert result['error']['message'] == 'independent projection failure'


def test_global_capture_close_remains_available_after_native_fatal(monkeypatch, runtime):
    controller, _ = runtime
    controller.status = Status(Code.RemoteServerConnectionLost)
    called = []

    async def handler(action, args, env):
        called.append(action)
        return {'success': True, 'released': True}

    result = execute(monkeypatch, 'rd.capture.close_replay', handler)
    assert result['ok'] is True and called == ['close_replay']
    assert controller.probes == 0


def test_pipeline_shader_resources_use_owning_replay_executor(monkeypatch):
    graphics = NS(D3D11=0, D3D12=1, Vulkan=2, OpenGL=3)
    monkeypatch.setattr(pipeline, '_get_rd', lambda: NS(GraphicsAPI=graphics))
    monkeypatch.setattr(pipeline, '_rd_shader_stages', lambda: [])

    class ThreadBoundController:
        def __init__(self):
            self.owner = threading.get_ident()

        def SetFrameEvent(self, event_id, force):
            assert threading.get_ident() == self.owner

        def GetPipelineState(self):
            assert threading.get_ident() == self.owner
            return NS()

        def GetAPIProperties(self):
            assert threading.get_ident() == self.owner
            return NS(pipelineType=graphics.Vulkan)

        def GetResources(self):
            assert threading.get_ident() == self.owner
            return []

    async def run():
        executor = ThreadPoolExecutor(max_workers=1)
        asyncio.get_running_loop().set_default_executor(executor)
        controller = await asyncio.to_thread(ThreadBoundController)
        manager = NS(get_controller=lambda session_id: controller)
        result = await pipeline.PipelineService().snapshot_pipeline(
            'native-session', 1716, manager, sections=['shaders'])
        assert result.shaders == []

    asyncio.run(run())

def test_concurrent_health_scopes_do_not_mix_controllers(monkeypatch):
    controllers = {'broken': Controller(), 'healthy': Controller()}

    async def ensure_live(session_id):
        assert session_id in controllers

    monkeypatch.setattr(server_runtime, '_ensure_live_session', ensure_live)
    monkeypatch.setattr(server_runtime, '_session_manager', NS(get_controller=lambda key: controllers[key]))
    monkeypatch.setattr(server_runtime, '_update_context_session_record', lambda *args, **fields: None)

    async def run():
        reached = asyncio.Event()

        async def handler(action, args, env):
            controller = await server_runtime._get_controller(args['session_id'])
            if args['session_id'] == 'broken':
                await asyncio.sleep(0)
                controller.status = Status(Code.RemoteServerConnectionLost)
                reached.set()
            else:
                await reached.wait()
            return {'success': True, 'r': 0}

        monkeypatch.setitem(tool_router._DOMAIN_HANDLERS, 'texture', handler)
        engine = CoreEngine(registry=tool_router.build_operation_registry())
        async def query(key):
            return await engine.execute('rd.texture.get_pixel_value', {
                'session_id': key, 'texture_id': 'ResourceId::187074', 'x': 0, 'y': 0})
        broken, healthy = await asyncio.gather(query('broken'), query('healthy'))
        assert broken['error']['code'] == 'replay_fatal_error'
        assert healthy['ok'] is True and healthy['data']['r'] == 0

    asyncio.run(run())

def test_debug_start_capability_probe_uses_owning_replay_executor(monkeypatch):
    import json

    async def run():
        executor = ThreadPoolExecutor(max_workers=1)
        asyncio.get_running_loop().set_default_executor(executor)
        owner = await asyncio.to_thread(threading.get_ident)

        class NativeController:
            def GetPipelineState(self):
                assert threading.get_ident() == owner
                return NS()

            def GetTargetShaderEncodings(self):
                assert threading.get_ident() == owner
                return []

        controller = NativeController()

        async def get_controller(session_id):
            return controller

        async def ensure_event(session_id, event):
            return event

        def capabilities(session_id, *, controller, context_id):
            assert context_id == 'native-caps-context'
            controller.GetPipelineState()
            controller.GetTargetShaderEncodings()
            return {'shader_debug': {'status': 'unsupported', 'reason': 'fixture boundary'}}

        monkeypatch.setattr(server_runtime, '_get_controller', get_controller)
        monkeypatch.setattr(server_runtime, '_ensure_event', ensure_event)
        monkeypatch.setattr(server_runtime, '_get_rd', lambda: NS())
        monkeypatch.setattr(server_runtime, '_session_remote_capability_matrix', capabilities)
        monkeypatch.setattr(server_runtime, '_runtime_context_id', lambda: 'native-caps-context')
        result = json.loads(await server_runtime._dispatch_shader('debug_start', {
            'session_id': 'native-session', 'event_id': 1716, 'params': {'x': 685, 'y': 70}}))
        assert result['code'] == 'shader_debug_backend_unsupported'

    asyncio.run(run())