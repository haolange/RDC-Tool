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
