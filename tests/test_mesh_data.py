from types import SimpleNamespace as NS
import struct
import pytest
from rdc_tool.core.mesh_data import decode_format, vertex_input, input_obj
from rdc_tool.core.replay_facts import post_transform_outputs


def fmt(kind='Float', width=4, count=3):
    return NS(type='Regular', compType=kind, compByteWidth=width, compCount=count)


def test_component_formats_and_bounds():
    assert decode_format(fmt('UNorm',1,2), b'\x00\xff', 0) == [0,1]
    assert decode_format(fmt('SNorm',1,2), b'\x80\x7f', 0) == [-1,1]
    assert decode_format(fmt('Float',2,2), struct.pack('<ee',.5,-1), 0) == [.5,-1]
    for f, raw in [(fmt(), bytes(2)),(fmt(),struct.pack('<fff',float('nan'),0,0)),(NS(type='R10G10B10A2',compType='UNorm',compByteWidth=4,compCount=4),bytes(16))]:
        with pytest.raises(ValueError): decode_format(f,raw,0)


def fixture():
    attrs=[NS(name=name, used=True, format=fmt(count=n), byteOffset=offset, vertexBuffer=0, perInstance=False,instanceRate=0,genericEnabled=False,floatCastWrong=False) for name,n,offset in [('POSITION',3,0),('NORMAL',3,12),('TEXCOORD0',2,24)]]
    raw=b''.join(struct.pack('<8f',i,2,3,0,1,0,.25,.75) for i in range(3))
    binding=NS(resourceId='vb',byteOffset=0,byteSize=len(raw),byteStride=32)
    action=NS(eventId=10,children=[],flags=3,numIndices=3,numInstances=1,instanceOffset=0,indexOffset=0,baseVertex=0,vertexOffset=0)
    pipe=NS(GetVBuffers=lambda:[binding],GetVertexInputs=lambda:attrs,GetIBuffer=lambda:NS(resourceId='ib',byteOffset=0,byteSize=6,byteStride=2),GetPrimitiveTopology=lambda:'TriangleList')
    ctl=NS(GetRootActions=lambda:[action],GetPipelineState=lambda:pipe,GetBufferData=lambda rid,offset,size:(struct.pack('<3H',2,0,1) if rid=='ib' else raw)[offset:offset+size])
    rd=NS(ActionFlags=NS(Drawcall=1,Indexed=2))
    return ctl,rd,attrs,binding,action


def test_indexed_input_and_obj_share_correct_values():
    ctl,rd,*_=fixture(); result=vertex_input(ctl,rd,10)
    assert result['vertex_rows'][0]['position']==[2,2,3]
    assert result['vertex_rows'][0]['normal']==[0,1,0]
    assert result['vertex_rows'][0]['uv']==[.25,.75]
    obj,count=input_obj(result,True)
    assert count==1 and 'vn 0 1 0' in obj and 'vt 0.25 0.75' in obj and 'f 1/1/1 2/2/2 3/3/3' in obj
    assert result['source']=='vs_input' and not result['truncated']


def test_unbound_ambiguous_invalid_and_truncated_inputs():
    ctl,rd,attrs,binding,action=fixture();attrs[1].vertexBuffer=2
    assert vertex_input(ctl,rd,10)['attributes']['normal']['status']=='unsupported'
    attrs[1].vertexBuffer=0;attrs.append(attrs[1])
    assert vertex_input(ctl,rd,10)['attributes']['normal']['status']=='unsupported'
    with pytest.raises(ValueError): input_obj(vertex_input(ctl,rd,10,max_vertices=1),True)
    action.baseVertex=-4
    with pytest.raises(ValueError): vertex_input(ctl,rd,10)


def test_instance_rate_and_original_indices():
    ctl,rd,attrs,binding,action=fixture();action.numInstances=4;action.instanceOffset=1
    attrs[0].perInstance=True;attrs[0].instanceRate=2
    result=vertex_input(ctl,rd,10,instance=2)
    assert all(row['position']==[2,2,3] for row in result['vertex_rows'])
    with pytest.raises(ValueError): input_obj(result,True)
    with pytest.raises(ValueError): vertex_input(ctl,rd,10,instance=4)


def test_output_signature_never_guesses_normal_from_texcoord():
    sig=[NS(stream=0,varType='Float',systemValue='Position',semanticIdxName='SV_POSITION',compCount=4),NS(stream=0,varType='Float',systemValue='Undefined',semanticIdxName='TEXCOORD0',compCount=2)]
    rows=[{'vertex_index':0}];raw=struct.pack('<6f',1,2,3,1,.5,.25)
    result=post_transform_outputs(NS(outputSignature=sig),'D3D12',24,raw,rows)
    assert result['status']=='present' and rows[0]['outputs']['TEXCOORD0']==[.5,.25]
    assert 'normal' not in rows[0]
    assert post_transform_outputs(NS(outputSignature=sig),'D3D12',32,raw,[])['status']=='unsupported'
    assert post_transform_outputs(NS(outputSignature=sig),'Vulkan',24,raw,[])['status']=='unsupported'


def test_regular_bgra_and_read_failures_are_not_unsupported():
    f=fmt('UNorm',1,4);f.BGRAOrder=lambda:True
    assert decode_format(f,bytes([0,127,255,255]),0)==[1,127/255,0,1]
    ctl,rd,attrs,binding,action=fixture();binding.byteSize=32
    with pytest.raises(ValueError, match='outside bound buffer'): vertex_input(ctl,rd,10)
    ctl,rd,*_=fixture();read=ctl.GetBufferData
    ctl.GetBufferData=lambda rid,off,size:read(rid,off,size)[:-1] if rid=='vb' else read(rid,off,size)
    with pytest.raises(ValueError, match='Incomplete vertex readback'): vertex_input(ctl,rd,10)


def test_obj_handler_preserves_buffer_failure(monkeypatch, tmp_path):
    import asyncio,json
    from rdc_tool import server_runtime as server
    from rdc_tool.core import mesh_data
    monkeypatch.setattr(server,'_get_controller',lambda _:asyncio.sleep(0,result=object()))
    monkeypatch.setattr(server,'_ensure_event',lambda *_:asyncio.sleep(0,result=10))
    monkeypatch.setattr(server,'_get_rd',lambda:object())
    def fail(*_): raise mesh_data.MeshReadError('Incomplete vertex readback')
    monkeypatch.setattr(mesh_data,'vertex_input',fail)
    target=tmp_path/'missing.obj'
    result=json.loads(asyncio.run(server._export_mesh_file({'session_id':'s','event_id':10,'output_path':str(target),'space':'vs_input','include_attributes':True})))
    assert result['success'] is False and result['code']=='mesh_input_failed'
    assert not target.exists()


def vulkan_output_signature():
    def field(builtin, location, count, name):
        return NS(stream=0, varType='Float', systemValue=builtin, regIndex=location,
                  compCount=count, varName=name, semanticIdxName='', regChannelMask=(1 << count) - 1, perPrimitiveRate=False)
    return [field('Position', 0xffffffff, 4, 'gl_Position'),
            field('Undefined', 2, 1, 'scalar'),
            field('Undefined', 7, 3, 'varying'),
            field('Undefined', 8, 2, 'uv')]


def test_vulkan_vs_output_uses_native_std430_signature_order_and_alignment():
    sig = vulkan_output_signature()
    raw = bytearray([0xa5] * 128)
    for vertex in range(2):
        start = vertex * 64
        struct.pack_into('<4f', raw, start, 1 + vertex, 2, 3, 1)
        struct.pack_into('<f', raw, start + 16, 9 + vertex)
        struct.pack_into('<3f', raw, start + 32, 4 + vertex, 5, 6)
        struct.pack_into('<2f', raw, start + 48, .25, .75)
    rows = [{'vertex_index': 0}, {'vertex_index': 1}]
    result = post_transform_outputs(NS(outputSignature=sig), 'Vulkan', 64, bytes(raw), rows)
    assert result['status'] == 'present'
    assert result['packing'] == 'vulkan-vs-std430'
    assert result['api'] == 'Vulkan' and result['stage'] == 'VS'
    assert result['layout'][2]['component_mask'] == 7
    assert result['layout'][2]['scalar_type'] == 'float32'
    assert [item['byte_offset'] for item in result['layout']] == [0, 16, 32, 48]
    assert result['layout'][2]['location'] == 7
    assert result['layout'][2]['variable_name'] == 'varying'
    assert result['layout'][0]['system_value'] == 'Position'
    assert result['layout'][0]['location'] is None
    assert rows[1]['outputs']['location:7'] == [5, 5, 6]
    assert rows[0]['outputs']['builtin:Position'] == [1, 2, 3, 1]
    assert 'normal' not in rows[0]


@pytest.mark.parametrize('change', ['stride', 'type', 'stream', 'duplicate', 'position', 'rate', 'location'])
def test_vulkan_vs_output_rejects_unproven_layout_without_partial_projection(change):
    sig = vulkan_output_signature()
    stride = 64
    if change == 'stride': stride = 60
    elif change == 'type': sig[2].varType = 'Half'
    elif change == 'stream': sig[2].stream = 1
    elif change == 'duplicate': sig[2].regIndex = 2
    elif change == 'position': sig[0], sig[1] = sig[1], sig[0]
    elif change == 'rate': sig[2].perPrimitiveRate = True
    elif change == 'location': sig[2].regIndex = 0xffffffff
    rows = [{'vertex_index': 0}]
    result = post_transform_outputs(NS(outputSignature=sig), 'Vulkan', stride, bytes(64), rows)
    assert result['status'] == 'unsupported'
    assert 'outputs' not in rows[0]


def test_vulkan_vs_output_preserves_nonfinite_and_rejects_incomplete_raw_bytes():
    sig = vulkan_output_signature()
    raw = bytearray(64)
    struct.pack_into('<3f', raw, 32, float('nan'), 1, 2)
    rows = [{'vertex_index': 0}]
    result = post_transform_outputs(NS(outputSignature=sig), 'Vulkan', 64, bytes(raw), rows)
    assert result['status'] == 'present' and rows[0]['outputs']['location:7'] is None
    with pytest.raises(ValueError, match='Incomplete post-transform'):
        post_transform_outputs(NS(outputSignature=sig), 'Vulkan', 64, bytes(raw[:-1]), [{'vertex_index': 0}])


@pytest.mark.parametrize('stage', ['vs', 'gs'])
def test_post_transform_runtime_routes_only_vulkan_vs_to_proven_layout(monkeypatch, stage):
    import asyncio, json
    from rdc_tool import server_runtime as server
    from rdc_tool.core import replay_facts
    sig = vulkan_output_signature()
    mesh = NS(vertexResourceId='post-vs-buffer', vertexByteOffset=0, vertexByteSize=64, vertexByteStride=64)
    pipe = NS(GetShaderReflection=lambda _: NS(outputSignature=sig))
    controller = NS(GetPostVSData=lambda *_: mesh, GetBufferData=lambda *_: bytes(64),
                    GetPipelineState=lambda: pipe, GetAPIProperties=lambda: NS(pipelineType=3))
    async def inline(fn, *args, **kwargs): return fn(*args, **kwargs)
    monkeypatch.setattr(server, '_offload', inline)
    monkeypatch.setattr(server, '_get_controller', lambda _: asyncio.sleep(0, result=controller))
    monkeypatch.setattr(server, '_ensure_event', lambda *_: asyncio.sleep(0, result=10))
    monkeypatch.setattr(server, '_get_rd', lambda: NS(MeshDataStage=NS(VSOut='vs', GSOut='gs'), GraphicsAPI=NS(D3D11=1, D3D12=2, Vulkan=3)))
    monkeypatch.setattr(server, '_rd_stage', lambda value: value)
    monkeypatch.setattr(server, '_mesh_format_payload', lambda _: {})
    monkeypatch.setattr(replay_facts, 'mesh_attributes', lambda *_: {})
    response = json.loads(asyncio.run(server._dispatch_mesh('get_post_transform_data', {
        'session_id': 's', 'event_id': 10, 'stage': stage, 'max_vertices': 1,
    })))
    assert response['success'] is True
    data = response['mesh_data']
    assert data['outputs']['status'] == ('present' if stage == 'vs' else 'unsupported')
    if stage == 'vs': assert data['vertex_rows'][0]['outputs']['location:7'] == [0, 0, 0]
    else: assert 'outputs' not in data['vertex_rows'][0]


def post_transform_window_fixture():
    mesh = NS(vertexResourceId='internal-vb', vertexByteOffset=24, vertexByteSize=(1 << 64)-1,
              vertexByteStride=32, indexResourceId='internal-ib', indexByteOffset=12,
              indexByteSize=(1 << 64)-1, indexByteStride=2, numIndices=100000,
              baseVertex=-5, allowRestart=False, restartIndex=0xffffffff)
    calls = []
    def read(resource, offset, size):
        calls.append((resource, offset, size))
        if resource == 'internal-ib': return struct.pack('<3H', 1005, 7, 1005)
        vertex = (offset - 24) // 32
        return struct.pack('<8f', vertex, 2, 3, 1, 4, 5, 6, 7)
    return mesh, NS(GetBufferData=read), calls


def test_post_transform_index_window_reads_only_corresponding_sparse_rows_and_native_bases():
    from rdc_tool.core.mesh_data import read_post_transform_window
    mesh, controller, calls = post_transform_window_fixture()
    result = read_post_transform_window(controller, mesh, first_index=4097, index_count=3, max_vertices=2, indexed=True)
    assert calls == [('internal-ib', 8206, 6), ('internal-vb', 32024, 32), ('internal-vb', 88, 32)]
    assert result['vertex_indices'] == [1000, 2]
    assert len(result['raw']) == 64
    window = result['window']
    assert window['complete'] is True and window['vertex_mapping_complete'] is True
    assert window['first_index'] == 4097 and window['index_unit'] == 'element'
    assert window['base_vertex'] == -5 and window['index_byte_offset'] == 8206
    assert [row['index_value'] for row in window['index_rows']] == [1005, 7, 1005]
    assert [row['vertex_index'] for row in window['index_rows']] == [1000, 2, 1000]
    assert window['index_bytes_hex'] == struct.pack('<3H', 1005, 7, 1005).hex()


@pytest.mark.parametrize('first,count,maximum', [(-1, 3, 3), (0, 0, 3), (0, 4097, 3), (0, 3, 0), (0, 3, 257)])
def test_post_transform_window_limits_are_rejected_before_buffer_access(first, count, maximum):
    from rdc_tool.core.mesh_data import read_post_transform_window
    mesh, controller, calls = post_transform_window_fixture()
    with pytest.raises(ValueError):
        read_post_transform_window(controller, mesh, first_index=first, index_count=count, max_vertices=maximum, indexed=True)
    assert calls == []


@pytest.mark.parametrize('failure', ['index_short', 'vertex_short', 'negative_vertex', 'unique_budget', 'range'])
def test_post_transform_window_never_zero_fills_or_truncates_failed_reads(failure):
    from rdc_tool.core.mesh_data import read_post_transform_window, MeshReadError
    mesh, controller, calls = post_transform_window_fixture()
    read = controller.GetBufferData
    if failure == 'index_short': controller.GetBufferData = lambda *args: b'\x00'
    elif failure == 'vertex_short': controller.GetBufferData = lambda *args: read(*args) if args[0] == 'internal-ib' else bytes(31)
    elif failure == 'negative_vertex': mesh.baseVertex = -1006
    elif failure == 'range': mesh.numIndices = 2
    with pytest.raises(MeshReadError):
        read_post_transform_window(controller, mesh, first_index=0, index_count=3,
                                   max_vertices=1 if failure == 'unique_budget' else 3, indexed=True)


def test_post_transform_restart_candidate_and_nonindexed_rows_are_explicit():
    from rdc_tool.core.mesh_data import read_post_transform_window
    mesh, controller, calls = post_transform_window_fixture()
    read = controller.GetBufferData
    mesh.baseVertex = 0
    mesh.allowRestart = True
    controller.GetBufferData = lambda *args: struct.pack('<3H', 3, 65535, 5) if args[0] == 'internal-ib' else read(*args)
    result = read_post_transform_window(controller, mesh, first_index=0, index_count=3, max_vertices=3, indexed=True)
    assert result['vertex_indices'] == [3, 5]
    assert result['window']['vertex_mapping_complete'] is False
    assert result['window']['index_rows'][1]['restart_candidate'] is True
    assert result['window']['index_rows'][1]['vertex_index'] is None
    calls.clear()
    result = read_post_transform_window(controller, mesh, first_index=10, index_count=2, max_vertices=2, indexed=False)
    assert result['vertex_indices'] == [10, 11]
    assert result['window']['index_bytes_hex'] is None
    assert all(call[0] == 'internal-vb' for call in calls)


def test_buffer_missing_resource_reports_proven_pre_effect_rejection(monkeypatch):
    import asyncio, json
    from rdc_tool import server_runtime as server
    def forbidden(*_): raise AssertionError('No frame mutation or data read before resource resolution')
    controller = NS(GetTextures=lambda: [], GetBuffers=lambda: [], GetResources=lambda: [],
                    GetBufferData=forbidden, SetFrameEvent=forbidden)
    async def inline(fn, *args, **kwargs): return fn(*args, **kwargs)
    monkeypatch.setattr(server, '_offload', inline)
    monkeypatch.setattr(server, '_get_controller', lambda _: asyncio.sleep(0, result=controller))
    response = json.loads(asyncio.run(server._dispatch_mesh('decode_index_data', {
        'session_id': 's', 'index_buffer_id': 'not-in-inventory', 'format': 'u16', 'index_count': 3,
    })))
    assert response['success'] is False and response['category'] == 'validation'
    assert response['details'] == {'session_id': 's', 'failure_stage': 'resolve_buffer',
                                   'effects_attempted': False, 'context_preserved': True}


def test_native_inventory_failure_is_not_blessed_as_pre_effect_validation(monkeypatch):
    import asyncio
    from rdc_tool import server_runtime as server
    def fail(): raise ValueError('native inventory failed')
    controller = NS(GetTextures=fail)
    async def inline(fn, *args, **kwargs): return fn(*args, **kwargs)
    monkeypatch.setattr(server, '_offload', inline)
    monkeypatch.setattr(server, '_get_controller', lambda _: asyncio.sleep(0, result=controller))
    with pytest.raises(ValueError, match='native inventory failed'):
        asyncio.run(server._dispatch_buffer('get_data', {'session_id': 's', 'buffer_id': 'id', 'size': 4}))


def test_post_transform_runtime_window_keeps_raw_mapping_and_absolute_vertex_identity(monkeypatch):
    import asyncio, json
    from rdc_tool import server_runtime as server
    from rdc_tool.core import replay_facts
    mesh, controller, calls = post_transform_window_fixture()
    sig = [NS(stream=0, varType='Float', systemValue='Position', regIndex=0xffffffff, compCount=4, varName='p', regChannelMask=15, perPrimitiveRate=False),
           NS(stream=0, varType='Float', systemValue='Undefined', regIndex=7, compCount=4, varName='v', regChannelMask=15, perPrimitiveRate=False)]
    controller.GetPostVSData = lambda *_: mesh
    controller.GetPipelineState = lambda: NS(GetShaderReflection=lambda _: NS(outputSignature=sig))
    controller.GetAPIProperties = lambda: NS(pipelineType=3)
    async def inline(fn, *args, **kwargs): return fn(*args, **kwargs)
    async def forbidden(*_): raise AssertionError('No generic resource lookup for a native mesh window')
    monkeypatch.setattr(server, '_offload', inline)
    monkeypatch.setattr(server, '_get_controller', lambda _: asyncio.sleep(0, result=controller))
    monkeypatch.setattr(server, '_ensure_event', lambda *_: asyncio.sleep(0, result=10))
    monkeypatch.setattr(server, '_resolve_resource_id', forbidden)
    monkeypatch.setattr(server, '_get_rd', lambda: NS(MeshDataStage=NS(VSOut='vs', GSOut='gs'), GraphicsAPI=NS(D3D11=1, D3D12=2, Vulkan=3)))
    monkeypatch.setattr(server, '_rd_stage', lambda value: value)
    monkeypatch.setattr(replay_facts, 'mesh_attributes', lambda *_: {})
    response = json.loads(asyncio.run(server._dispatch_mesh('get_post_transform_data', {
        'session_id': 's', 'stage': 'vs', 'max_vertices': 2, 'first_index': 4097, 'index_count': 3,
    })))
    assert response['success'] is True
    data = response['mesh_data']
    assert data['mesh_format']['base_vertex'] == -5
    assert data['index_window']['first_index'] == 4097
    assert data['index_window']['complete'] is True and data['truncated'] is True
    assert [row['vertex_index'] for row in data['vertex_rows']] == [1000, 2]
    assert [row['source_byte_offset'] for row in data['vertex_rows']] == [32024, 88]
    assert data['vertex_rows'][0]['outputs']['builtin:Position'][0] == 1000
    assert data['vertex_rows'][1]['outputs']['location:7'] == [4, 5, 6, 7]


def test_post_transform_invalid_window_is_rejected_before_replay_effects(monkeypatch):
    import asyncio, json
    from rdc_tool import server_runtime as server
    async def forbidden(*_): raise AssertionError('Invalid window must not acquire or move replay')
    monkeypatch.setattr(server, '_get_controller', forbidden)
    monkeypatch.setattr(server, '_ensure_event', forbidden)
    response = json.loads(asyncio.run(server._dispatch_mesh('get_post_transform_data', {
        'session_id': 's', 'stage': 'vs', 'max_vertices': 0, 'first_index': 0, 'index_count': 3,
    })))
    assert response['success'] is False and response['category'] == 'validation'
    assert response['details']['effects_attempted'] is False
    assert response['details']['context_preserved'] is True


@pytest.mark.parametrize('failure,stage', [('not_buffer','resolve_buffer'), ('range','validate_buffer_range'), ('budget','validate_buffer_read_budget')])
def test_buffer_pre_read_rejections_preserve_context_without_data_read(monkeypatch, failure, stage):
    import asyncio, json
    from rdc_tool import server_runtime as server
    def forbidden(*_): raise AssertionError('No data read or event mutation on pre-read rejection')
    length = 2097152 if failure == 'budget' else 16
    controller = NS(GetBuffers=lambda: [] if failure == 'not_buffer' else [NS(resourceId='rid',length=length)], GetBufferData=forbidden, SetFrameEvent=forbidden)
    async def inline(fn, *args, **kwargs): return fn(*args, **kwargs)
    monkeypatch.setattr(server, '_offload', inline)
    monkeypatch.setattr(server, '_get_controller', lambda _: asyncio.sleep(0, result=controller))
    monkeypatch.setattr(server, '_resolve_resource_id', lambda *_: asyncio.sleep(0, result='rid'))
    monkeypatch.setattr(server, '_read_at_capture_state', forbidden)
    response = json.loads(asyncio.run(server._dispatch_buffer('get_data', {'session_id':'s', 'buffer_id':'rid', 'size':length+1 if failure == 'range' else length, 'as_base64':True})))
    assert response['success'] is False and response['category'] == 'validation'
    assert response['details'] == {'session_id':'s', 'failure_stage':stage, 'effects_attempted':False, 'context_preserved':True}
