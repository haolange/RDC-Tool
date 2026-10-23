"""Bounded vertex-input decoding from native bindings, without semantic inference."""
from __future__ import annotations
import math
import re
import struct
from typing import Any
from rdc_tool.core.native_values import native_value


class MeshReadError(ValueError):
    """Bounded buffer read failed; never reported as unsupported."""


def decode_format(fmt: Any, raw: bytes, offset: int) -> list[float | int]:
    width, count = int(fmt.compByteWidth), int(fmt.compCount)
    kind = getattr(fmt.compType, "name", str(fmt.compType))
    if getattr(fmt.type, 'name', str(fmt.type)) != 'Regular' or width not in (1, 2, 4, 8) or not 1 <= count <= 4:
        raise ValueError('Unsupported packed vertex format')
    if offset < 0 or offset + width * count > len(raw):
        raise MeshReadError('Vertex attribute outside buffer readback')
    codes = {'Float': {2: 'e', 4: 'f', 8: 'd'}, 'UInt': {1: 'B', 2: 'H', 4: 'I', 8: 'Q'},
             'SInt': {1: 'b', 2: 'h', 4: 'i', 8: 'q'}, 'UNorm': {1: 'B', 2: 'H', 4: 'I'},
             'SNorm': {1: 'b', 2: 'h', 4: 'i'}}
    code = codes.get(kind, {}).get(width)
    if not code:
        raise ValueError('Unsupported vertex component format')
    values = list(struct.unpack_from('<' + code * count, raw, offset))
    if kind == 'UNorm': values = [v / ((1 << (8 * width)) - 1) for v in values]
    if kind == 'SNorm': values = [max(-1.0, v / ((1 << (8 * width - 1)) - 1)) for v in values]
    if callable(getattr(fmt, 'BGRAOrder', None)) and fmt.BGRAOrder():
        if count < 3: raise ValueError('Invalid BGRA component count')
        values[0], values[2] = values[2], values[0]
    if not all(math.isfinite(v) for v in values):
        raise ValueError('Non-finite vertex attribute')
    return values


def semantic_kind(name: str) -> str | None:
    name = name.upper()
    if re.fullmatch(r'POSITION0?', name): return 'position'
    if re.fullmatch(r'NORMAL0?', name): return 'normal'
    if re.fullmatch(r'TEXCOORD0?|UV0?', name): return 'uv'
    return None


def vertex_input(controller: Any, rd: Any, event_id: int, instance: int = 0, max_vertices: int = 128) -> dict[str, Any]:
    stack = list(controller.GetRootActions())
    action = None
    while stack:
        candidate = stack.pop()
        if int(candidate.eventId) == event_id:
            action = candidate
            break
        stack.extend(candidate.children)
    if action is None or not action.flags & rd.ActionFlags.Drawcall:
        raise ValueError('Vertex input requires a draw event')
    if instance < 0 or instance >= max(1, int(action.numInstances)):
        raise ValueError('Instance outside draw range')
    pipe = controller.GetPipelineState()
    buffers, inputs = list(pipe.GetVBuffers()), list(pipe.GetVertexInputs())
    count = int(action.numIndices)
    limit = min(count, max_vertices) if max_vertices > 0 else count
    indexed = bool(action.flags & rd.ActionFlags.Indexed)
    ib = pipe.GetIBuffer()
    if indexed:
        stride = int(ib.byteStride)
        if stride not in (1, 2, 4): raise ValueError('Unsupported index width')
        offset = int(ib.byteOffset) + int(action.indexOffset) * stride
        if int(ib.byteSize) != (1 << 64) - 1 and int(action.indexOffset) * stride + limit * stride > int(ib.byteSize):
            raise MeshReadError('Index read outside bound range')
        raw = bytes(controller.GetBufferData(ib.resourceId, offset, limit * stride))
        if len(raw) != limit * stride: raise MeshReadError('Incomplete index readback')
        indices = [v[0] + int(action.baseVertex) for v in struct.iter_unpack('<' + {1:'B',2:'H',4:'I'}[stride], raw)]
    else:
        indices = list(range(int(action.vertexOffset), int(action.vertexOffset) + limit))
    if any(v < 0 for v in indices): raise MeshReadError('Negative vertex index')
    rows = [{'vertex_index': index, 'draw_index': n, 'values': {}} for n, index in enumerate(indices)]
    attributes = {k: {'status': 'unsupported', 'reason': 'No unique used input semantic'} for k in ('position','normal','uv')}
    layout = []
    for attr in inputs:
        if not attr.used: continue
        name = str(attr.name)
        item = {'semantic': name, 'source': 'vs_input', 'format': native_value(attr.format),
                'buffer_slot': int(attr.vertexBuffer), 'byte_offset': int(attr.byteOffset),
                'per_instance': bool(attr.perInstance), 'instance_rate': int(attr.instanceRate)}
        try:
            if attr.genericEnabled or attr.floatCastWrong: raise ValueError('Generic or cast vertex inputs are not decoded')
            if attr.vertexBuffer >= len(buffers): raise ValueError('Vertex buffer is not bound')
            binding = buffers[attr.vertexBuffer]
            stride = int(binding.byteStride)
            width = int(attr.format.compByteWidth) * int(attr.format.compCount)
            if stride <= 0 or attr.byteOffset + width > stride: raise ValueError('Attribute exceeds vertex stride')
            item.update(resource_id=str(binding.resourceId), byte_stride=stride, binding_offset=int(binding.byteOffset))
            rate = int(attr.instanceRate)
            if attr.perInstance and rate <= 0: raise ValueError('Invalid instance step rate')
            addresses = [(int(action.instanceOffset) + instance // rate if attr.perInstance else i) * stride + int(attr.byteOffset) for i in indices]
            if addresses:
                start, end = min(addresses), max(addresses) + width
                if end > int(binding.byteSize): raise MeshReadError('Vertex index outside bound buffer')
                raw = bytes(controller.GetBufferData(binding.resourceId, int(binding.byteOffset)+start, end-start))
                if len(raw) != end-start: raise MeshReadError('Incomplete vertex readback')
                for row, address in zip(rows, addresses): row['values'][name] = decode_format(attr.format, raw, address-start)
            item['status'] = 'present'
        except MeshReadError:
            raise
        except ValueError as exc:
            for row in rows: row["values"].pop(name, None)
            item.update(status='unsupported', reason=str(exc))
        layout.append(item)
    for kind in attributes:
        candidates = [item for item in layout if semantic_kind(item['semantic']) == kind]
        if len(candidates) == 1:
            item = candidates[0]
            attributes[kind] = dict(item)
            for row in rows: row[kind] = row['values'].get(item['semantic'])
    return {'source': 'vs_input', 'instance': instance, 'vertex_rows': rows, 'attributes': attributes,
            'layout': layout, 'vertex_count': len(rows), 'draw_index_count': count, 'truncated': limit<count,
            'topology': getattr(pipe.GetPrimitiveTopology(), 'name', str(pipe.GetPrimitiveTopology())), 'indexed': indexed,
            'index_binding': native_value(ib) if indexed else None}

def input_obj(data: dict[str, Any], include_attributes: bool) -> tuple[str, int]:
    rows = data['vertex_rows']
    attrs = data['attributes']
    for key in (('position', 'normal', 'uv') if include_attributes else ('position',)):
        item = attrs[key]
        minimum = 2 if key == 'uv' else 3
        if item['status'] != 'present' or item['format']['compType'] != 'Float' or item['format']['compCount'] < minimum:
            raise ValueError('OBJ requires explicit float position/normal/UV semantics in VS input space')
        if item['per_instance']:
            raise ValueError('OBJ does not combine per-instance attributes with vertex-space geometry')
    count = len(rows)
    if data['truncated']: raise ValueError('OBJ cannot export a truncated vertex input')
    topology = data['topology']
    if topology == 'TriangleList': primitives = [list(range(i,i+3)) for i in range(0,count-2,3)]; kind='f'
    elif topology == 'TriangleStrip': primitives = [[i+i%2,i+1-i%2,i+2] for i in range(count-2)]; kind='f'
    elif topology == 'LineList': primitives = [list(range(i,i+2)) for i in range(0,count-1,2)]; kind='l'
    elif topology == 'PointList': primitives = [[i] for i in range(count)]; kind='p'
    else: raise ValueError('Unsupported OBJ input topology')
    if include_attributes and kind != 'f': raise ValueError('OBJ normal/UV indexing requires triangle topology')
    lines = ['# RDC-Tool VS input attributes; original input coordinate space, no shader transform applied']
    for row in rows: lines.append('v '+' '.join(format(v,'.9g') for v in row['position'][:3]))
    if include_attributes:
        for row in rows: lines.append('vt '+' '.join(format(v,'.9g') for v in row['uv'][:2]))
        for row in rows: lines.append('vn '+' '.join(format(v,'.9g') for v in row['normal'][:3]))
    for primitive in primitives:
        lines.append(kind+' '+' '.join(f'{i+1}/{i+1}/{i+1}' if include_attributes else str(i+1) for i in primitive))
    return '\n'.join(lines)+'\n', len(primitives)


def validate_post_transform_window(first_index: int, index_count: int, max_vertices: int) -> None:
    if type(first_index) is not int or not 0 <= first_index <= 0xffffffff:
        raise ValueError("first_index must be a non-negative uint32 index ordinal")
    if type(index_count) is not int or not 1 <= index_count <= 4096:
        raise ValueError("index_count must be between 1 and 4096")
    if type(max_vertices) is not int or not 1 <= max_vertices <= 256:
        raise ValueError("Index windows require explicit max_vertices between 1 and 256")


def read_post_transform_window(controller: Any, mesh: Any, *, first_index: int,
                               index_count: int, max_vertices: int, indexed: bool) -> dict[str, Any]:
    """Read a native MeshFormat index window and only its referenced output rows.

    Resource objects come exclusively from GetPostVSData in the owning replay;
    this does not resolve arbitrary IDs or infer primitive/raster association.
    """
    validate_post_transform_window(first_index, index_count, max_vertices)
    total = int(mesh.numIndices)
    stride = int(mesh.vertexByteStride)
    vertex_offset = int(mesh.vertexByteOffset)
    vertex_size = int(mesh.vertexByteSize)
    if first_index + index_count > total or stride <= 0 or vertex_offset < 0 or vertex_size < 0:
        raise MeshReadError("Post-transform window is outside native mesh bounds")
    unbounded = (1 << 64) - 1
    index_raw = None
    index_offset = None
    index_stride = None
    index_bound = None
    base = int(mesh.baseVertex) if indexed else 0
    if indexed:
        index_stride = int(mesh.indexByteStride)
        if index_stride not in (1, 2, 4):
            raise MeshReadError("Unsupported native post-transform index width")
        index_size = int(mesh.indexByteSize)
        relative_offset = first_index * index_stride
        read_size = index_count * index_stride
        if index_size != unbounded and relative_offset + read_size > index_size:
            raise MeshReadError("Post-transform index window exceeds native view")
        index_offset = int(mesh.indexByteOffset) + relative_offset
        if index_offset < 0:
            raise MeshReadError("Negative native post-transform index byte offset")
        index_raw = bytes(controller.GetBufferData(mesh.indexResourceId, index_offset, read_size))
        if len(index_raw) != read_size:
            raise MeshReadError("Incomplete post-transform index readback")
        values = list(struct.unpack('<' + {1: 'B', 2: 'H', 4: 'I'}[index_stride] * index_count, index_raw))
        index_bound = None if index_size == unbounded else index_size
    else:
        values = list(range(first_index, first_index + index_count))
    vertex_indices, index_rows = [], []
    allow_restart = bool(mesh.allowRestart) if indexed else False
    restart = int(mesh.restartIndex) & ((1 << (8 * index_stride)) - 1) if indexed else None
    for ordinal, value in enumerate(values, first_index):
        candidate = allow_restart and value == restart
        vertex = None if candidate else value + base
        if vertex is not None and vertex < 0:
            raise MeshReadError("Post-transform base vertex produces a negative row")
        if vertex is not None and vertex not in vertex_indices:
            vertex_indices.append(vertex)
        index_rows.append({"source_index": ordinal, "index_value": value, "vertex_index": vertex,
                           "restart_candidate": candidate})
    if len(vertex_indices) > max_vertices or len(vertex_indices) * stride + len(index_raw or b'') > 1048576:
        raise MeshReadError("Post-transform window exceeds explicit vertex/1 MiB read budget")
    chunks, offsets = [], []
    for vertex in vertex_indices:
        relative_offset = vertex * stride
        offset = vertex_offset + relative_offset
        if offset + stride > (1 << 64) - 1 or (vertex_size != unbounded and relative_offset + stride > vertex_size):
            raise MeshReadError("Post-transform vertex row exceeds native view")
        chunk = bytes(controller.GetBufferData(mesh.vertexResourceId, offset, stride))
        if len(chunk) != stride:
            raise MeshReadError("Incomplete post-transform vertex row readback")
        chunks.append(chunk)
        offsets.append(offset)
    window = {"source": "post_transform", "first_index": first_index, "index_count": index_count,
              "index_unit": "element", "total_indices": total, "indexed": indexed,
              "base_vertex": base if indexed else None, "index_byte_offset": index_offset,
              "index_byte_stride": index_stride, "index_byte_size_bound": index_bound,
              "vertex_byte_size_bound": None if vertex_size == unbounded else vertex_size,
              "index_bytes_hex": index_raw.hex() if index_raw is not None else None,
              "index_rows": index_rows, "complete": True,
              "vertex_mapping_complete": not any(row["restart_candidate"] for row in index_rows)}
    return {"raw": b''.join(chunks), "vertex_indices": vertex_indices, "vertex_byte_offsets": offsets,
            "window": window}
