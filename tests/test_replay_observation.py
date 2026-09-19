from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from pathlib import Path

import pytest

from rdx import replay_observation as observation


@pytest.fixture
def replay(monkeypatch):
    runtime = observation.runtime
    applied = []
    flat = [SimpleNamespace(eventId=i, customName=f'event {i}', flags=1) for i in range(1, 2502)]
    async def nothing(*args, **kwargs):
        return None
    async def index(*args, **kwargs):
        return flat, flat, {a.eventId: a for a in flat}
    async def controller(*args):
        return SimpleNamespace(SetFrameEvent=lambda event, force: applied.append(event))
    async def offload(fn, *args):
        return fn(*args)
    async def outputs(*args):
        return [('resource-7', 3)]
    async def descriptor(*args, **kwargs):
        return 'resource-7', SimpleNamespace(width=1920, height=1080)
    async def save(**kwargs):
        assert kwargs['artifact_store'] is None
        Path(kwargs['output_path']).write_bytes(b'PNG-test')
        return {'saved_path': kwargs['output_path']}
    monkeypatch.setattr(runtime, '_runtime_context_id', lambda: 'isolated')
    monkeypatch.setattr(runtime, '_context_state', lambda _: {'current_session_id': 'sess', 'backend': 'remote'})
    monkeypatch.setattr(runtime, '_ensure_live_session', nothing)
    monkeypatch.setattr(runtime, '_load_action_index', index)
    monkeypatch.setattr(runtime, '_active_event', lambda _: 42)
    monkeypatch.setattr(runtime, '_store_active_event', lambda *a, **k: None)
    monkeypatch.setattr(runtime, '_get_controller', controller)
    monkeypatch.setattr(runtime, '_offload', offload)
    monkeypatch.setattr(runtime, '_output_target_resource_ids', outputs)
    monkeypatch.setattr(runtime, '_get_texture_descriptor', descriptor)
    monkeypatch.setattr(runtime, '_render_service', SimpleNamespace(save_texture_file=save))
    monkeypatch.setattr(runtime, '_get_rd', lambda: SimpleNamespace(ActionFlags=SimpleNamespace(Present=2)))
    async def present(session, event, resource):
        return len(applied)
    monkeypatch.setattr(runtime, '_session_manager', SimpleNamespace(present_remote=present))
    observation._revisions.clear()
    return applied


def call(action, args):
    return json.loads(asyncio.run(observation.handle(action, args)))


def test_complete_events_do_not_apply_or_truncate(replay):
    result = call('get_replay_events', {})
    assert result['complete'] and len(result['events']) == 2501
    assert replay == []


def test_current_event_observation_and_real_attachment_slot(replay, tmp_path):
    result = call('observe', {'out_path': str(tmp_path / 'a.png'), 'target': {'rt_index': 3}})
    assert result['image_event_id'] == result['event_id'] == 42
    assert replay == [42]
    assert result['target']['output_slot'] == 3
    assert result['remote_display'] == {'status': 'presented', 'event_id': 42, 'texture_id': 'resource-7', 'sequence': 1, 'reason': None}
    second = call('observe', {'out_path': str(tmp_path / 'b.png'), 'event_id': 12})
    assert second['revision'] == result['revision'] + 1
    assert second['image_event_id'] == 12


def test_missing_target_clears_image_but_preserves_applied_event(replay, tmp_path):
    result = call('observe', {'out_path': str(tmp_path / 'a.png'), 'event_id': 18, 'target': {'rt_index': 0}})
    assert result['success']
    assert result['event_id'] == 18 and result['image_event_id'] is None
    assert result['image_path'] is None and result['image_error']['code'] == 'missing_target'


def test_final_without_evidence_is_not_claimed(replay, tmp_path, monkeypatch):
    async def unavailable(*args):
        raise ValueError('No unique Present')
    monkeypatch.setattr(observation, '_final_target', unavailable)
    result = call('observe', {'out_path': str(tmp_path / 'a.png'), 'final_output': True})
    assert not result['is_final_output'] and result['final_output_error']
    assert result['event_id'] == 42


def test_invalid_event_and_existing_path_never_apply(replay, tmp_path):
    destination = tmp_path / 'existing.png'
    destination.write_bytes(b'original')
    assert not call('observe', {'out_path': str(destination)})['success']
    assert not call('observe', {'out_path': str(tmp_path / 'new.png'), 'event_id': 9999})['success']
    assert replay == [] and destination.read_bytes() == b'original'


def test_export_failure_removes_partial_file(replay, tmp_path, monkeypatch):
    async def broken(**kwargs):
        Path(kwargs['output_path']).write_bytes(b'partial')
        raise RuntimeError('device disconnected')
    monkeypatch.setattr(observation.runtime, '_render_service', SimpleNamespace(save_texture_file=broken))
    destination = tmp_path / 'a.png'
    result = call('observe', {'out_path': str(destination)})
    assert result['image_path'] is None and result['image_error']
    assert result['image_error']['code'] == 'export_failure'
    assert not destination.exists()


def test_final_target_rejects_pass_boundary_and_ambiguous_resources(monkeypatch):
    runtime = observation.runtime
    monkeypatch.setattr(runtime, '_get_rd', lambda: SimpleNamespace(ActionFlags=SimpleNamespace(Present=2), TextureCategory=SimpleNamespace(SwapBuffer=4)))
    with pytest.raises(ValueError, match='explicit Present'):
        asyncio.run(observation._final_target('sess', [SimpleNamespace(eventId=9, flags=1)]))
    async def controller(*args):
        return SimpleNamespace(GetTextures=lambda: [SimpleNamespace(resourceId='a', creationFlags=4), SimpleNamespace(resourceId='a', creationFlags=4)],
                               GetUsage=lambda rid: [SimpleNamespace(eventId=9, usage='Present')])
    async def offload(fn, *args):
        return fn(*args)
    monkeypatch.setattr(runtime, '_get_controller', controller)
    monkeypatch.setattr(runtime, '_offload', offload)
    with pytest.raises(ValueError, match='exactly one'):
        asyncio.run(observation._final_target('sess', [SimpleNamespace(eventId=9, flags=2, copyDestination='a')]))


def test_no_output_is_distinct_from_missing_target(replay, tmp_path, monkeypatch):
    async def outputs(*args):
        return []
    monkeypatch.setattr(observation.runtime, '_output_target_resource_ids', outputs)
    result = call('observe', {'out_path': str(tmp_path / 'empty.png'), 'event_id': 5})
    assert result['event_id'] == 5 and result['image_path'] is None
    assert result['image_error']['code'] == 'no_color_output'


def test_manual_present_uses_same_verified_target_as_open(replay, tmp_path, monkeypatch):
    async def index(*args):
        action = SimpleNamespace(eventId=14, flags=2)
        return [], [action], {14: action}
    async def final(*args):
        return 14, 'swap-buffer', SimpleNamespace(width=640, height=480)
    async def outputs(*args):
        return []
    monkeypatch.setattr(observation.runtime, '_load_action_index', index)
    monkeypatch.setattr(observation.runtime, '_active_event', lambda _: 14)
    monkeypatch.setattr(observation.runtime, '_output_target_resource_ids', outputs)
    monkeypatch.setattr(observation, '_final_target', final)
    opened = call('observe', {'out_path': str(tmp_path / 'open.png'), 'final_output': True})
    selected = call('observe', {'out_path': str(tmp_path / 'manual.png'), 'event_id': 14})
    explicit = call('observe', {'out_path': str(tmp_path / 'target.png'), 'event_id': 14, 'target': {'texture_id': 'swap-buffer'}})
    assert explicit['image_event_id'] == 14
    assert opened['target'] == selected['target']
    assert selected['is_final_output'] and selected['image_event_id'] == 14
    assert Path(opened['image_path']).read_bytes() == Path(selected['image_path']).read_bytes()

def test_observation_reports_actual_replacement_state(replay, tmp_path, monkeypatch):
    monkeypatch.setattr(observation.runtime, '_replacement_metadata_entries', lambda session: [])
    monkeypatch.setattr(observation.runtime._runtime, 'restored_shader_sessions', set())
    baseline = call('observe', {'out_path': str(tmp_path / 'baseline.png')})
    assert baseline['modification_state'] == 'baseline'
    assert baseline['display_parameters'] == {'mip': 0, 'slice': 0, 'sample': 0, 'range_min': 0.0, 'range_max': 1.0}
    monkeypatch.setattr(observation.runtime, '_replacement_metadata_entries', lambda session: [{'replacement_id': 'patch'}])
    assert call('observe', {'out_path': str(tmp_path / 'modified.png')})['modification_state'] == 'intervention'
    monkeypatch.setattr(observation.runtime, '_replacement_metadata_entries', lambda session: [])
    observation.runtime._runtime.restored_shader_sessions.add('sess')
    assert call('observe', {'out_path': str(tmp_path / 'restored.png')})['modification_state'] == 'restored'

def test_remote_failure_does_not_reuse_previous_receipt(replay, tmp_path, monkeypatch):
    first = call('observe', {'out_path': str(tmp_path / 'first.png')})
    assert first['remote_display']['status'] == 'presented'
    async def failed(*args):
        raise RuntimeError('surface lost')
    monkeypatch.setattr(observation.runtime, '_session_manager', SimpleNamespace(present_remote=failed))
    result = call('observe', {'out_path': str(tmp_path / 'second.png'), 'event_id': 12})
    assert result['remote_display'] == {'status': 'unavailable', 'event_id': 12,
        'texture_id': 'resource-7', 'sequence': None, 'reason': 'surface lost'}
    assert result['image_event_id'] == 12


def test_no_color_sends_native_clear(replay, tmp_path, monkeypatch):
    calls = []
    async def outputs(*args):
        return []
    async def present(*args):
        calls.append(args)
        return 9
    monkeypatch.setattr(observation.runtime, '_output_target_resource_ids', outputs)
    monkeypatch.setattr(observation.runtime, '_session_manager', SimpleNamespace(present_remote=present))
    result = call('observe', {'out_path': str(tmp_path / 'clear.png'), 'event_id': 5})
    assert calls == [('sess', 5, None)]
    assert result['remote_display'] == {'status': 'unavailable', 'event_id': 5,
        'texture_id': None, 'sequence': 9, 'reason': 'no_color_output'}


def test_local_receipt_is_explicitly_not_applicable(replay, tmp_path, monkeypatch):
    monkeypatch.setattr(observation.runtime, '_context_state', lambda _: {'current_session_id': 'sess', 'backend': 'local'})
    result = call('observe', {'out_path': str(tmp_path / 'local.png')})
    assert result['remote_display'] == {'status': 'not_applicable', 'event_id': 42,
        'texture_id': None, 'sequence': None, 'reason': None}
