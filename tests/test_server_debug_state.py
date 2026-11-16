import asyncio
from types import SimpleNamespace

import pytest
from rdc_tool.runtime import live_state, renderdoc_api, replay_access
from rdc_tool.runtime.operations import debug as debug_ops
from rdc_tool.runtime.operations import shader as shader_ops


@pytest.fixture
def native_debug(monkeypatch):
    def var(name, value, kind='Float', members=None):
        return SimpleNamespace(name=name, type=kind, rows=1, columns=1, members=members or [],
                               value=SimpleNamespace(**{('f32v' if kind == 'Float' else 'u32v'): [value]}))
    empty, x1, x3, y2 = var('', 0), var('x', 1.0), var('x', 3.0), var('y', 2, 'UInt')
    def state(pc, before, after):
        return SimpleNamespace(stepIndex=pc, changes=[SimpleNamespace(before=before, after=after)], callstack=['main', 'lighting'])
    batches = [[state(1, empty, x1), state(2, empty, y2), state(3, x1, x3)], [state(4, y2, empty)], []]
    advances, freed = [], []
    def advance(debugger):
        advances.append(debugger)
        return batches.pop(0)
    controller = SimpleNamespace(ContinueDebug=advance, FreeTrace=lambda trace: freed.append(trace), GetPipelineState=lambda: None)
    async def get_controller(_):
        return controller
    async def ensure_event(session_id, event_id):
        return 42 if event_id is None else event_id
    monkeypatch.setattr(replay_access, '_ensure_event', ensure_event)
    async def offload(fn, *args):
        return fn(*args)
    handle = live_state.ShaderDebugHandle('trace', 'replay', 'pixel', 42, SimpleNamespace(inputs=[]), object())
    monkeypatch.setattr(live_state._runtime, 'shader_debugs', {'trace': handle})
    monkeypatch.setattr(replay_access, '_get_controller', get_controller)
    monkeypatch.setattr(renderdoc_api, '_offload', offload)
    def call(action, **args):
        return asyncio.run(debug_ops.dispatch(action, {'session_id': 'replay', 'shader_debug_id': 'trace', **args}))
    return SimpleNamespace(call=call, handle=handle, advances=advances, freed=freed, controller=controller)


def test_native_batches_and_before_after_are_preserved(native_debug):
    d = native_debug
    assert d.call('get_variables').data['variables'] == []
    assert not d.advances
    assert d.call('step').data['state']['pc'] == 1
    assert d.call('get_variables').data['variables'][0]['value'] == {'f32v': [1.0]}
    assert d.call('step').data['state']['pc'] == 2
    assert len(d.advances) == 1
    assert {v['name']: v['value'] for v in d.call('get_variables').data['variables']} == {'x': {'f32v': [1.0]}, 'y': {'u32v': [2]}}
    assert d.call('run_to', target={'pc': 3}).data['state']['pc'] == 3
    assert len(d.advances) == 1
    assert d.call('evaluate_expression', expression='x').data['value'] == {'f32v': [3.0]}
    d.call('set_breakpoints', breakpoints=[{'pc': 4}])
    stopped = d.call('continue')
    assert stopped.data['stopped_reason'] == 'breakpoint'
    assert stopped.data['state']['pc'] == 4
    assert [v['name'] for v in d.call('get_variables').data['variables']] == ['x']
    assert d.call('get_callstack').data['callstack'] == [{'function': name, 'file': None, 'line': None, 'pc': 4} for name in ['main', 'lighting']]
    assert d.call('continue').data['stopped_reason'] == 'finished'
    assert d.call('get_variables', name_filter='y').data['variables'] == []
    d.call('finish')
    assert d.freed == [d.handle.trace]
    assert 'trace' not in live_state._runtime.shader_debugs


def test_unknown_expression_keeps_live_debugger_and_replay(monkeypatch, native_debug):
    replay = live_state.ReplayHandle(session_id='replay', capture_file_id='capture', frame_index=0, active_event_id=42)
    monkeypatch.setattr(live_state._runtime, 'replays', {'replay': replay})
    result = native_debug.call('evaluate_expression', expression='missing_variable')
    assert not result.ok
    assert result.code == 'expression_not_found'
    assert result.category == 'validation'
    assert result.details['effects_attempted'] is False
    assert result.details['context_preserved'] is True
    assert live_state._runtime.replays['replay'] is replay
    assert not native_debug.advances


@pytest.mark.parametrize('action,args', [
    ('step', {'step_mode': 'line'}), ('run_to', {'target': {'texture_id': 'not-pc'}}),
    ('run_to', {'target': {'pc': -1}}), ('run_to', {'target': {'pc': 3}}),
    ('set_breakpoints', {'breakpoints': [{'file': 'shader', 'line': 1}]}),
    ('get_variables', {'expand_depth': -1}), ('get_variables', {'max_variables': 0}),
])
def test_invalid_requests_do_not_touch_controller(monkeypatch, native_debug, action, args):
    native_debug.handle.current_state = SimpleNamespace(stepIndex=4)
    async def forbidden(_):
        raise AssertionError('invalid request must precede native access')
    monkeypatch.setattr(replay_access, '_get_controller', forbidden)
    result = native_debug.call(action, **args)
    assert result.ok is False
    assert result.code == 'validation_error'
    assert result.details['effects_attempted'] is False
    assert result.details['context_preserved'] is True


def test_typed_members_and_truncation_do_not_mutate_snapshot(native_debug):
    d = native_debug
    d.handle.variables = {'material': {'name': 'material', 'type': 'Struct', 'members': [
        {'name': 'albedo', 'type': 'Float', 'value': {'f32v': [0.5]}, 'members': []}]},
        'other': {'name': 'other', 'type': 'UInt', 'value': {'u32v': [7]}, 'members': []}}
    bounded = d.call('get_variables', max_variables=1, expand_depth=0)
    assert bounded.data['truncated'] is True
    assert bounded.data['variables'][0]['members_truncated'] is True
    assert bounded.data['variables'][0]['members'] == []
    expanded = d.call('get_variables', name_filter='material', expand_depth=1)
    assert expanded.data['truncated'] is False
    assert expanded.data['variables'][0]['members'][0]['value'] == {'f32v': [0.5]}
    assert len(d.handle.variables['material']['members']) == 1


def test_release_failure_keeps_handle(native_debug):
    def fail(_):
        raise RuntimeError('trace release failed')
    native_debug.controller.FreeTrace = fail
    with pytest.raises(RuntimeError, match='trace release failed'):
        native_debug.call('finish')
    assert live_state._runtime.shader_debugs['trace'] is native_debug.handle


def test_current_catalog_admits_trace_pc_and_rejects_unimplemented_modes():
    from rdc_tool.runtime_catalog import validate_operation_arguments
    identity = {'session_id': 'replay', 'shader_debug_id': 'trace'}
    validate_operation_arguments('rd.debug.run_to', {**identity, 'target': {'pc': 17}})
    validate_operation_arguments('rd.debug.set_breakpoints', {**identity, 'breakpoints': [{'pc': 17}]})
    validate_operation_arguments('rd.debug.step', {**identity, 'step_mode': 'instruction'})
    for operation, args in [
        ('rd.debug.run_to', {'target': {'texture_id': 'wrong-target'}}),
        ('rd.debug.run_to', {'target': {'pc': -1}}),
        ('rd.debug.set_breakpoints', {'breakpoints': [{'file': 'shader', 'line': 1}]}),
        ('rd.debug.step', {'step_mode': 'line'}),
    ]:
        with pytest.raises(ValueError):
            validate_operation_arguments(operation, {**identity, **args})


def shader_state(d, **args):
    return asyncio.run(shader_ops.dispatch('get_debug_state', {
        'session_id': 'replay', 'shader_debug_id': 'trace', **args}))


def test_sparse_native_instruction_map_is_not_trace_pc_or_array_index(native_debug):
    d = native_debug
    def info(instruction, line, file_index=-1):
        return SimpleNamespace(instruction=instruction, lineInfo=SimpleNamespace(
            disassemblyLine=line, fileIndex=file_index, lineStart=9, lineEnd=10, colStart=0, colEnd=4))
    d.handle.trace = SimpleNamespace(inputs=[], instInfo=[info(5, 12), info(100, 20, 2)])
    for pc, instruction, mapped in [(300, 99, 5), (301, 100, 100), (302, 6, 5)]:
        d.handle.current_state = SimpleNamespace(stepIndex=pc, nextInstruction=instruction)
        result = shader_state(d, detail_level='summary').data['state']
        assert result['pc'] == pc and result['next_instruction'] == instruction
        assert result['has_native_state'] is True
        location = result['source_location']
        assert location['mapping_instruction'] == mapped
        assert location['disassembly_source'] == 'renderdoc_native_debug_disassembly'
        if mapped == 5:
            assert location['mapping_end_instruction_exclusive'] == 100
            assert location['disassembly_line'] == 12
            assert location['file_index'] is None and location['line_start'] is None
        else:
            assert location['mapping_end_instruction_exclusive'] is None
            assert location['file_index'] == 2 and location['line_start'] == 9
            assert location['column_start'] is None and location['column_end'] == 4
        assert 'variables' not in result
    d.handle.current_state.nextInstruction = 4
    assert shader_state(d).data['state']['source_location'] is None
    assert not d.advances


def test_initial_missing_metadata_and_native_pc_zero_are_distinct(native_debug):
    d = native_debug
    initial = shader_state(d).data['state']
    assert initial['pc'] == 0 and initial['has_native_state'] is False
    assert initial['next_instruction'] is None and initial['source_location'] is None
    assert initial['variables'] == [] and initial['callstack'] == []
    d.handle.current_state = SimpleNamespace(stepIndex=0)
    observed = shader_state(d).data['state']
    assert observed['has_native_state'] is True and observed['next_instruction'] is None
    d.handle.trace = SimpleNamespace(inputs=[], instInfo=[SimpleNamespace(instruction=0, lineInfo=SimpleNamespace())])
    d.handle.current_state.nextInstruction = 0
    location = shader_state(d).data['state']['source_location']
    assert location['disassembly_line'] is None and location['file_index'] is None


def test_full_state_is_bounded_and_snapshot_is_not_mutated(native_debug):
    d = native_debug
    nested = {'name': 'leaf', 'members': []}
    for index in range(4):
        nested = {'name': str(index), 'members': [nested]}
    d.handle.variables = {'first': nested, **{str(i): {'name': str(i)} for i in range(70)}}
    d.handle.current_state = SimpleNamespace(stepIndex=8, nextInstruction=90, callstack=[str(i) for i in range(70)])
    result = shader_state(d).data['state']
    assert len(result['variables']) == 64 and result['variable_count'] == 71 and result['variables_truncated']
    assert result['variable_member_depth'] == 2
    bounded_leaf = result['variables'][0]['members'][0]['members'][0]
    assert bounded_leaf['members'] == [] and bounded_leaf['members_truncated']
    assert d.handle.variables['first']['members'][0]['members'][0]['members']
    assert len(result['callstack']) == 64 and result['callstack_count'] == 70 and result['callstack_truncated']


@pytest.mark.parametrize('detail', ['registers', None, [], {}])
def test_bad_state_detail_rejected_before_native(monkeypatch, native_debug, detail):
    async def forbidden(_):
        raise AssertionError('invalid detail must precede controller access')
    monkeypatch.setattr(replay_access, '_get_controller', forbidden)
    result = shader_state(native_debug, detail_level=detail)
    assert not result.ok and result.code == 'validation_error'
    assert result.details['effects_attempted'] is False
    assert result.details['context_preserved'] is True


def test_step_state_exposes_location_without_changing_pc_target(native_debug):
    d = native_debug
    result = d.call('step').data['state']
    assert result['pc'] == 1 and result['has_native_state'] is True
    assert result['next_instruction'] is None
    d.handle.current_state.nextInstruction = 490
    result = d.call('run_to', target={'pc': 1}).data['state']
    assert result['pc'] == 1 and result['next_instruction'] == 490
    assert len(d.advances) == 1


def test_catalog_rejects_unknown_state_detail():
    from rdc_tool.runtime_catalog import validate_operation_arguments
    identity = {'session_id': 'replay', 'shader_debug_id': 'trace'}
    for detail in ['summary', 'full']:
        validate_operation_arguments('rd.shader.get_debug_state', {**identity, 'detail_level': detail})
    with pytest.raises(ValueError):
        validate_operation_arguments('rd.shader.get_debug_state', {**identity, 'detail_level': 'registers'})


def test_debug_variable_snapshots_include_immutable_native_inputs(native_debug):
    d = native_debug
    member = SimpleNamespace(name="SV_Position", type="Float", rows=1, columns=4, members=[],
                             value=SimpleNamespace(f32v=[10.5, 20.5, 0.3, 1.0]))
    d.handle.trace.inputs = [SimpleNamespace(name="_IN", type="Struct", rows=0, columns=0,
                                             members=[member], value=None)]
    first = d.call('get_variables', name_filter='_IN', expand_depth=2).data
    assert first['truncated'] is False
    assert first['variables'][0]['variable_origin'] == 'trace_input'
    assert first['variables'][0]['members'][0]['value']['f32v'] == [10.5, 20.5, 0.3, 1.0]
    assert shader_state(d).data['state']['variables'][0] == first['variables'][0]
    assert d.call('continue').data['stopped_reason'] == 'finished'
    assert d.call('get_variables', name_filter='_IN').data['variables'] == first['variables']
    assert d.call('get_variables', name_filter='x').data['variables'][0]['value']['f32v'] == [3.0]
