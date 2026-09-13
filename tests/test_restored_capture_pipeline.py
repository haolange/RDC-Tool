from types import SimpleNamespace as NS

import pytest

from rdx.core import pipeline_service as pipeline
from rdx.core.capture_queries import query_calls, read_thumbnail, structured_object
from rdx.core.native_values import native_value
from rdx.models import GraphicsAPI, ShaderStage


def test_all_viewports_and_scissors_preserve_enabled_and_index():
    first = NS(x=0, y=0, width=64, height=64, enabled=True, minDepth=0, maxDepth=1)
    second = NS(x=64, y=0, width=32, height=64, enabled=False, minDepth=0.2, maxDepth=0.8)
    state = NS(rasterizer=NS(viewports=[first, second], scissors=[first, second]))
    before = pipeline._extract_viewport(state, GraphicsAPI.D3D12)
    second.width = 16
    after = pipeline._extract_viewport(state, GraphicsAPI.D3D12)
    assert before != after
    assert after[1]['width'] == 16 and after[1]['index'] == 1 and after[1]['enabled'] is False
    assert pipeline._extract_scissor(state, GraphicsAPI.D3D12)[1]['width'] == 16
    with pytest.raises(AttributeError):
        pipeline._extract_viewport(NS(), GraphicsAPI.D3D12)


def test_blend_write_mask_and_logic_are_not_discarded():
    equation = NS(source='One', destination='Zero', operation='Add')
    blend = NS(enabled=True, colorBlend=equation, alphaBlend=equation,
               writeMask=15, logicOperation='Copy', logicOperationEnabled=True)
    state = NS(outputMerger=NS(blendState=NS(blends=[blend])))
    before = pipeline._extract_blend_state(state, GraphicsAPI.D3D12)[0]
    blend.writeMask = 0
    after = pipeline._extract_blend_state(state, GraphicsAPI.D3D12)[0]
    assert before != after
    assert after.write_mask == 0 and after.logic_op_enabled and after.logic_op == 'Copy'


def test_stencil_front_and_back_masks_operations_and_reference_are_retained():
    face = NS(function='Equal', reference=3, compareMask=255, writeMask=0,
              failOperation='Keep', depthFailOperation='Replace', passOperation='Increment')
    raw = NS(depthEnable=True, depthWrites=False, depthFunction='Less', stencilEnable=True,
             frontFace=face, backFace=NS(**vars(face)))
    state = NS(outputMerger=NS(depthStencilState=raw))
    before = pipeline._extract_depth_stencil(state, GraphicsAPI.D3D12)
    raw.backFace.reference = 7
    after = pipeline._extract_depth_stencil(state, GraphicsAPI.D3D12)
    assert before != after and after.back['reference'] == 7
    assert after.front['writeMask'] == 0 and after.front['depthFailOperation'] == 'Replace'
    with pytest.raises(AttributeError):
        pipeline._extract_depth_stencil(NS(), GraphicsAPI.D3D12)


def test_sampler_collector_uses_native_sampler_and_access(monkeypatch):
    monkeypatch.setattr(pipeline, '_get_rd', lambda: NS(ResourceId=lambda: None))
    access = NS(index=0, arrayElement=2, descriptorStore='store', byteOffset=48)
    sampler = NS(addressU='Clamp', minLOD=2, maxLOD=5, maxAnisotropy=8)
    reflected = NS(fixedBindNumber=3, fixedBindSetOrSpace=1, name='surfaceSampler')
    pipe = NS(GetShaderReflection=lambda _: NS(samplers=[reflected]),
              GetReadOnlyResources=lambda _: [], GetReadWriteResources=lambda _: [],
              GetConstantBlocks=lambda _: [], GetSamplers=lambda _: [
                  NS(access=access, descriptor=NS(resource=None), sampler=sampler)])
    result = pipeline._collect_bindings_for_stage(pipe, 'pixel', ShaderStage.PS)
    assert len(result) == 1 and result[0].type == 'Sampler'
    assert result[0].sampler['addressU'] == 'Clamp'
    assert result[0].access['byteOffset'] == 48 and result[0].array_index == 2


def test_native_value_does_not_swallow_failed_properties():
    class Broken:
        @property
        def resource(self):
            raise RuntimeError('readback failed')
    with pytest.raises(RuntimeError, match='readback failed'):
        native_value(Broken())


def test_thumbnail_shutdown_on_success_and_failed_open():
    closed = []
    capture = NS(OpenFile=lambda *_: 0, GetThumbnail=lambda *_: NS(data=b'png', type=1, width=64, height=32),
                 Shutdown=lambda: closed.append(True))
    rd = NS(OpenCaptureFile=lambda: capture, ResultCode=NS(Succeeded=0), FileType=NS(PNG=1))
    assert read_thumbnail(rd, 'capture', 'png', 64) == b'png'
    capture.OpenFile = lambda *_: 5
    with pytest.raises(RuntimeError, match='OpenFile'):
        read_thumbnail(rd, 'capture', 'png', 64)
    assert len(closed) == 2


def test_structured_calls_paginate_and_reject_invalid_chunks():
    base = NS(Chunk=1, Struct=2, Array=3, Resource=4, Boolean=5, Float=6, String=7,
              Character=8, Buffer=9, Null=10)
    rd = NS(SDBasic=base)
    child = NS(name='count', type=NS(basetype=11, name='uint32', byteSize=4), AsInt=lambda: 32)
    chunk = NS(name='Draw', type=NS(basetype=1, name='API', byteSize=4),
               NumChildren=lambda: 2, GetChild=lambda _: child)
    controller = NS(GetStructuredFile=lambda: NS(chunks=[chunk, chunk]))
    result = query_calls(rd, controller, event_id=None, chunk_indices=[0, 1], offset=0, limit=1, max_nodes=2)
    assert result['next_offset'] == 1 and result['node_budget_exhausted']
    call = result['calls'][0]['call']
    assert call['children'][0]['value'] == 32 and call['omitted_children'] == 1
    continued = query_calls(rd, controller, event_id=None, chunk_indices=[0], offset=0, limit=1,
                            max_nodes=2, child_offset=call['next_child_offset'])['calls'][0]['call']
    assert continued['children'][0]['object_path'] == [1]
    assert continued['next_child_offset'] is None
    scalar = query_calls(rd, controller, event_id=None, chunk_indices=[0], offset=0, limit=1,
                         max_nodes=1, object_path=[1])['calls'][0]['call']
    assert scalar['value'] == 32 and scalar['object_path'] == [1]
    with pytest.raises(ValueError, match='Chunk index'):
        query_calls(rd, controller, event_id=None, chunk_indices=[2], offset=0, limit=1, max_nodes=2)
