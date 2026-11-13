"""Pure byte-parser boundary tests; these do not claim native replay coverage."""
import struct
import pytest
from rdc_tool.static_inspect import scan_chunks, export_shaders


def padded(value):
    return value + bytes((-len(value)) % 64)


@pytest.mark.parametrize('value', [b'\x01', struct.pack('<II', 0, 0),
    struct.pack('<II', 0x200001, 0), struct.pack('<II', 1, 65),
    struct.pack('<II', 0x10001, 0xffffffff),
    struct.pack('<I', 0x20001), struct.pack('<II', 0x100001, 0)])
def test_invalid_chunk_headers_reject(value):
    with pytest.raises(ValueError):
        scan_chunks(value)


def test_final_alignment_must_be_present():
    with pytest.raises(ValueError, match='alignment'):
        scan_chunks(struct.pack('<II', 1, 0))


def test_all_metadata_flags_and_wide_size():
    value = struct.pack('<IIQ', 0x1f0000 | 1007, 1, 123) + bytes(24) + struct.pack('<Q', 0)
    chunks = scan_chunks(padded(value))
    assert len(chunks) == 1
    assert chunks[0]['method'] == 'CreateVertexShader'
    assert chunks[0]['data'] == 48
    assert chunks[0]['size'] == 0


def shader_section(code):
    # Chunk begins at zero; serialised byte buffer is aligned to byte 64.
    payload = struct.pack('<Q', len(code)) + bytes(48) + code + struct.pack('<QQQ', len(code), 0, 7)
    return padded(struct.pack('<II', 1007, len(payload)) + payload)


def test_minimal_structural_shader_export(tmp_path):
    code = b'DXBC' + bytes(20) + struct.pack('<II', 32, 0)
    section = shader_section(code)
    rows = export_shaders(section, scan_chunks(section), tmp_path / 'shaders')
    assert rows[0]['replay_verified'] is False
    assert (tmp_path / 'shaders' / '7_vs.dxbc').read_bytes() == code


def test_invalid_dxbc_part_offset_rejects(tmp_path):
    code = b'DXBC' + bytes(20) + struct.pack('<III', 36, 1, 0xffffffff)
    section = shader_section(code)
    with pytest.raises(ValueError, match='part offset'):
        export_shaders(section, scan_chunks(section), tmp_path / 'shaders')
    assert not list((tmp_path / 'shaders').iterdir())


def test_chunk_count_limit(monkeypatch):
    from rdc_tool import static_inspect
    monkeypatch.setattr(static_inspect, 'MAX_CHUNKS', 1)
    section = padded(struct.pack('<II', 1, 0)) * 2
    with pytest.raises(ValueError, match='count'):
        scan_chunks(section)


def test_resource_names_exact_length_and_decode():
    from rdc_tool.static_inspect import read_resource_names
    payload = struct.pack('<QI', 9, 3) + b'a\xffb'
    section = padded(struct.pack('<II', 1001, len(payload)) + payload)
    assert read_resource_names(section, scan_chunks(section)) == {'9': 'a\ufffdb'}
    bad = padded(struct.pack('<II', 1001, len(payload) - 1) + payload)
    with pytest.raises(ValueError, match='layout'):
        read_resource_names(bad, scan_chunks(bad))


def buffer_section(present=0, flag=None, duplicate=4):
    buf = bytearray(struct.pack('<II', 1006, 0))
    buf += struct.pack('<6IB', 4, 0, 1, 0, 0, 0, present if flag is None else flag)
    if present:
        buf += struct.pack('<Q', 0)
        buf += bytes((-len(buf)) % 64)
        buf += struct.pack('<II', 4, 4)
    buf += struct.pack('<QQ', 19, 4)
    buf += bytes((-len(buf)) % 64)
    buf += b'abcd' + struct.pack('<Q', duplicate)
    struct.pack_into('<I', buf, 4, len(buf)-8)
    return padded(bytes(buf))


@pytest.mark.parametrize('present', [0, 1])
def test_buffer_exports_serialized_contents_only(tmp_path, present):
    from rdc_tool.static_inspect import export_buffers
    section = buffer_section(present)
    results = export_buffers(section, scan_chunks(section), tmp_path/'buffers', {'19': 'vertices'})
    assert results[0]['content_scope'] == 'serialized_initial_contents'
    assert results[0]['replay_verified'] is False
    assert results[0]['resource_name'] == 'vertices'
    assert (tmp_path/'buffers'/'19.bin').read_bytes() == b'abcd'


@pytest.mark.parametrize('kwargs,match', [({'flag': 2}, 'flag'), ({'duplicate': 9}, 'length mismatch')])
def test_buffer_invalid_input_rejects_without_export(tmp_path, kwargs, match):
    from rdc_tool.static_inspect import export_buffers
    section = buffer_section(**kwargs)
    with pytest.raises(ValueError, match=match):
        export_buffers(section, scan_chunks(section), tmp_path/'buffers', {})
    assert not list((tmp_path/'buffers').iterdir())


def so_shader_section(*, semantic=b'POSITION', entries=1, num_entries=None,
                      strides=(12,), num_strides=None, raster=0xffffffff,
                      stream=0, start=0, count=3, slot=0, prefix=b''):
    code = b'DXBC' + bytes(20) + struct.pack('<II', 32, 0)
    section = bytearray(prefix + struct.pack('<IIQ', 1011, 0, len(code)))
    section += bytes((-len(section)) % 64)
    section += code + struct.pack('<QQ', len(code), entries)
    for _ in range(entries):
        section += struct.pack('<Ii', stream, -1 if semantic is None else len(semantic))
        if semantic is not None:
            section += semantic
        section += struct.pack('<IBBB', 0, start, count, slot)
    section += struct.pack('<IQ', entries if num_entries is None else num_entries, len(strides))
    for stride in strides:
        section += struct.pack('<I', stride)
    section += struct.pack('<IIQQ', len(strides) if num_strides is None else num_strides,
                           raster, 17, 23)
    struct.pack_into('<I', section, len(prefix) + 4, len(section) - len(prefix) - 8)
    return padded(bytes(section))


def test_stream_output_export_preserves_layout_and_linkage(tmp_path):
    section = so_shader_section(prefix=padded(struct.pack('<II', 1, 0)))
    rows = export_shaders(section, scan_chunks(section), tmp_path/'shaders')
    assert len(rows) == 1
    row = rows[0]
    assert row['resource_id'] == 23 and row['stage'] == 'gs'
    assert row['class_linkage'] == 17
    assert row['replay_verified'] is False
    assert row['stream_output'] == {
        'declarations': [{'stream': 0, 'semantic': 'POSITION', 'index': 0,
                          'start_component': 0, 'component_count': 3, 'output_slot': 0}],
        'strides': [12], 'rasterized_stream': 0xffffffff,
    }
    assert (tmp_path/'shaders'/'23_gs.dxbc').read_bytes()[:4] == b'DXBC'


def test_stream_output_null_semantic_gap_and_implicit_stride(tmp_path):
    section = so_shader_section(semantic=None, count=8, strides=())
    row, = export_shaders(section, scan_chunks(section), tmp_path/'shaders')
    assert row['stream_output']['declarations'][0]['semantic'] is None
    assert row['stream_output']['declarations'][0]['component_count'] == 8
    assert row['stream_output']['strides'] == []  # Not invented/computed by this parser.


@pytest.mark.parametrize('kwargs', [
    {'num_entries': 2}, {'num_strides': 2}, {'raster': 4}, {'stream': 4},
    {'slot': 4}, {'start': 3, 'count': 2}, {'count': 0}, {'semantic': b'P\xff'},
    {'semantic': b'P\x00'}, {'strides': (4, 4, 4, 4, 4)}, {'entries': 129},
])
def test_invalid_stream_output_rejects_without_export(tmp_path, kwargs):
    section = so_shader_section(**kwargs)
    with pytest.raises(ValueError):
        export_shaders(section, scan_chunks(section), tmp_path/'shaders')
    assert not list((tmp_path/'shaders').iterdir())


def test_every_stream_output_payload_truncation_rejects(tmp_path):
    section = so_shader_section()
    chunk, = scan_chunks(section)
    for end in range(chunk['data'], chunk['end']):
        truncated = {**chunk, 'end': end, 'size': end - chunk['data']}
        output = tmp_path / str(end)
        with pytest.raises(ValueError):
            export_shaders(section[:end], [truncated], output)
        assert not list(output.iterdir())


def test_stream_output_unknown_tail_rejects(tmp_path):
    section = so_shader_section()
    chunk, = scan_chunks(section)
    chunk = {**chunk, 'end': chunk['end'] + 1, 'size': chunk['size'] + 1}
    with pytest.raises(ValueError, match='schema'):
        export_shaders(section, [chunk], tmp_path/'shaders')


def test_overlapping_dxbc_parts_reject(tmp_path):
    code = b'DXBC' + bytes(20) + struct.pack('<IIII', 48, 2, 40, 40) + b'SHDR' + struct.pack('<I', 0)
    section = shader_section(code)
    with pytest.raises(ValueError, match='Overlapping'):
        export_shaders(section, scan_chunks(section), tmp_path/'shaders')
