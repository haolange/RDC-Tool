"""Experimental read-only D3D11 v20 container inspection. Never opens replay."""
from __future__ import annotations
import hashlib
import json
import mmap
import struct
import tempfile
from pathlib import Path
from rdc_tool.d3d11_chunk_names import NAMES

MAX_SECTION_BYTES = 1024 * 1024 * 1024
MAX_CHUNKS = 100_000


def scan_chunks(data):
    rows = []; pos = 0
    def read(fmt, offset):
        if offset < 0 or offset + struct.calcsize(fmt) > len(data):
            raise ValueError(f'Truncated chunk header at {offset}')
        return struct.unpack_from(fmt, data, offset)[0]
    while pos < len(data):
        if len(rows) >= MAX_CHUNKS: raise ValueError("Chunk count exceeds inspection limit")
        start = pos; header = read('<I', pos); pos += 4
        if not header & 0xffff or header & ~0x1fffff:
            raise ValueError(f'Unsupported chunk header at {start}')
        if header & 0x10000:
            count = read('<I', pos); pos += 4 + count * 8
        for flag in (0x20000, 0x40000, 0x80000):
            if header & flag: pos += 8
        wide = bool(header & 0x100000)
        size = read('<Q' if wide else '<I', pos); pos += 8 if wide else 4
        end = pos + size
        if end > len(data): raise ValueError(f'Chunk payload exceeds section at {start}')
        chunk_id = header & 0xffff
        method = NAMES[chunk_id-1000] if 1000 <= chunk_id < 1000+len(NAMES) else f'UnknownOrSystemChunk_{chunk_id}'
        rows.append(dict(index=len(rows), header=start, id=chunk_id, flags=header & ~0xffff,
                         data=pos, size=size, end=end, method=method))
        pos = (end + 63) & ~63
        if pos > len(data): raise ValueError('Incomplete final chunk alignment')
    return rows


def _validate_dxbc(code):
    """Check container bounds, not shader semantics or authenticity."""
    n = len(code)
    if n < 32 or code[:4] != b'DXBC' or struct.unpack_from('<I', code, 24)[0] != n:
        raise ValueError('Invalid DXBC container')
    count = struct.unpack_from('<I', code, 28)[0]
    table_end = 32 + 4 * count
    if table_end > n:
        raise ValueError('Invalid DXBC part table')
    parts = []
    spans = []
    for i in range(count):
        offset = struct.unpack_from('<I', code, 32 + 4 * i)[0]
        if offset < table_end or offset + 8 > n:
            raise ValueError('Invalid DXBC part offset')
        size = struct.unpack_from('<I', code, offset + 4)[0]
        end = offset + 8 + size
        if end > n:
            raise ValueError('Invalid DXBC part length')
        try:
            tag = code[offset:offset + 4].decode('ascii')
        except UnicodeError as exc:
            raise ValueError('Invalid DXBC part tag') from exc
        spans.append((offset, end))
        parts.append(dict(tag=tag, offset=offset, size=size))
    spans.sort()
    if any(left[1] > right[0] for left, right in zip(spans, spans[1:])):
        raise ValueError('Overlapping DXBC parts')
    return parts


class _PayloadReader:
    """Bound every field to its chunk, including absolute 64-byte alignment."""
    def __init__(self, data, chunk):
        self.data = data
        self.pos = chunk['data']
        self.end = chunk['end']
        if not 0 <= self.pos <= self.end <= len(data):
            raise ValueError('Invalid shader payload bounds')

    def read(self, fmt):
        size = struct.calcsize(fmt)
        if self.pos + size > self.end:
            raise ValueError('Truncated shader payload')
        values = struct.unpack_from(fmt, self.data, self.pos)
        self.pos += size
        return values

    def bytes(self, size):
        if size < 0 or self.pos + size > self.end:
            raise ValueError('Truncated shader payload')
        value = self.data[self.pos:self.pos + size]
        self.pos += size
        return value

    def align(self):
        self.pos = (self.pos + 63) & ~63
        if self.pos > self.end:
            raise ValueError('Truncated shader alignment')


def _read_stream_output(reader):
    # RenderDoc v1.47 Serialise_CreateGeometryShaderWithStreamOutput and
    # DoSerialise(D3D11_SO_DECLARATION_ENTRY); const char* uses signed length,
    # -1 denotes a null semantic (a stream-output gap).
    entries, = reader.read('<Q')
    if entries > 128:
        raise ValueError('SO declaration count exceeds D3D11 limit')
    declarations = []
    for _ in range(entries):
        stream, length = reader.read('<Ii')
        if length < -1:
            raise ValueError('Invalid SO semantic string length')
        if length == -1:
            semantic = None
        else:
            try:
                semantic = reader.bytes(length).decode('ascii')
            except UnicodeError as exc:
                raise ValueError('Invalid SO semantic string') from exc
            if '\0' in semantic:
                raise ValueError('Embedded null in SO semantic string')
        index, start, count, slot = reader.read('<IBBB')
        if stream > 3 or slot > 3 or start > 3 or count == 0:
            raise ValueError('Invalid SO declaration')
        if semantic is not None and (count > 4 or start + count > 4):
            raise ValueError('Invalid SO component range')
        declarations.append(dict(stream=stream, semantic=semantic, index=index,
                                 start_component=start, component_count=count,
                                 output_slot=slot))
    duplicate, num_strides = reader.read('<IQ')
    if duplicate != entries or num_strides > 4:
        raise ValueError('Invalid SO declaration or stride count')
    strides = [reader.read('<I')[0] for _ in range(num_strides)]
    duplicate, rasterized_stream = reader.read('<II')
    if duplicate != num_strides or rasterized_stream not in (0, 1, 2, 3, 0xffffffff):
        raise ValueError('Invalid SO stride count or rasterized stream')
    return dict(declarations=declarations, strides=strides,
                rasterized_stream=rasterized_stream)


def export_shaders(data, chunks, output):
    stages = {1007: 'vs', 1008: 'hs', 1009: 'ds', 1010: 'gs',
              1011: 'gs', 1012: 'ps', 1013: 'cs'}
    results = []
    output.mkdir()
    for chunk in chunks:
        if chunk['id'] not in stages:
            continue
        reader = _PayloadReader(data, chunk)
        n, = reader.read('<Q')
        reader.align()
        start = reader.pos
        code = reader.bytes(n)
        parts = _validate_dxbc(code)
        duplicate, = reader.read('<Q')
        if duplicate != n:
            raise ValueError('Shader bytecode length mismatch')
        stream_output = _read_stream_output(reader) if chunk['id'] == 1011 else None
        linkage, rid = reader.read('<QQ')
        if reader.pos != reader.end:
            raise ValueError('Unsupported shader payload schema')
        file = f'{rid}_{stages[chunk["id"]]}.dxbc'
        with (output / file).open('xb') as dst:
            dst.write(code)
        result = dict(resource_id=rid, stage=stages[chunk['id']], byte_size=n,
                      sha256=hashlib.sha256(code).hexdigest(), file=file, parts=parts,
                      class_linkage=linkage, chunk_index=chunk['index'],
                      section_byte_offset=start, replay_verified=False)
        if stream_output is not None:
            result['stream_output'] = stream_output
        results.append(result)
    return results


def inspect_capture(capture_path, output_dir):
    from rdc_tool.runtime_bootstrap import bootstrap_renderdoc_runtime
    from rdc_tool.runtime_identity import host_native_manifest_status
    from rdc_tool.runtime_paths import tools_root
    if host_native_manifest_status(tools_root())['status'] == 'invalid':
        raise RuntimeError('Native runtime integrity failed')
    runtime = bootstrap_renderdoc_runtime(probe_import=True)
    if not runtime.import_ok:
        raise RuntimeError(f"Native runtime import failed: {runtime.import_error}")
    import renderdoc as rd
    output = Path(output_dir); output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()): raise ValueError('Output directory must be empty; existing results are never overwritten')
    capture = rd.OpenCaptureFile()
    try:
        status = capture.OpenFile(str(Path(capture_path).resolve()), '', None)
        if status != rd.ResultCode.Succeeded: raise RuntimeError(f'OpenFile: {status}')
        if capture.DriverName() != 'D3D11': raise ValueError('Static chunk parser supports D3D11 only')
        index = capture.FindSectionByType(rd.SectionType.FrameCapture)
        if index < 0: raise ValueError('No FrameCapture section')
        props = capture.GetSectionProperties(index)
        if props.version != 20: raise ValueError(f'Unsupported D3D11 section version {props.version}; expected 20')
        if props.uncompressedSize > MAX_SECTION_BYTES: raise ValueError('Section exceeds experimental 1 GiB inspection limit')
        data = capture.GetSectionContents(index)
        if not data: raise ValueError('Empty FrameCapture section')
        if len(data) != props.uncompressedSize: raise ValueError('Section decompression size mismatch')
        # A temporary file avoids retaining a second full Python copy during inspection.
        with tempfile.TemporaryFile() as tmp:
            tmp.write(data); del data; tmp.flush()
            with mmap.mmap(tmp.fileno(), 0, access=mmap.ACCESS_READ) as buf:
                chunks = scan_chunks(buf)
                shaders = export_shaders(buf, chunks, output/'shaders')
                names = read_resource_names(buf, chunks)
                for shader in shaders:
                    shader['resource_name'] = names.get(str(shader['resource_id']), '')
                buffers = export_buffers(buf, chunks, output/'buffers', names)
        (output/'chunks.json').write_text(json.dumps(chunks), encoding='utf-8')
        (output/'buffers.json').write_text(json.dumps(buffers,indent=2), encoding='utf-8')
        (output/'resource-names.json').write_text(json.dumps(names,indent=2), encoding='utf-8')
        (output/'shaders.json').write_text(json.dumps(shaders,indent=2), encoding='utf-8')
        thumbnail = capture.GetThumbnail(rd.FileType.PNG,2048)
        if thumbnail.data: (output/'embedded-thumbnail.png').write_bytes(bytes(thumbnail.data))
        result = dict(ok=True, scope='experimental_static_d3d11_inspection', replay_verified=False,
            capture_path=str(Path(capture_path).resolve()), section_version=20,
            chunk_count=len(chunks), shader_count=len(shaders), buffer_count=len(buffers), output_dir=str(output.resolve()),
            limitations=['No draw-state reconstruction or frame rendering',
                        'Chunk indices are not replay event IDs',
                        'Buffer bytes are serialized initial contents, not draw-event state',
                        'Stream-output metadata is static; no output buffers are executed',
                        'DXBC structural validation is not an authenticity or semantic proof'])
        (output/'inspection.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
        return result
    finally:
        capture.Shutdown()


def read_resource_names(data, chunks):
    names = {}
    for c in chunks:
        if c['id'] != 1001: continue
        if c['size'] < 12: raise ValueError('Truncated resource name')
        rid, size = struct.unpack_from('<QI', data, c['data'])
        if size + 12 != c['size']: raise ValueError('Unsupported resource name layout')
        names[str(rid)] = data[c['data']+12:c['end']].decode('utf-8', errors='replace')
    return names


def export_buffers(data, chunks, output, names):
    output.mkdir(); results = []
    for c in chunks:
        if c['id'] != 1006: continue
        p = c['data']
        def read(fmt):
            nonlocal p
            size = struct.calcsize(fmt)
            if p + size > c['end']: raise ValueError('Truncated buffer record')
            values = struct.unpack_from(fmt, data, p); p += size
            return values
        desc = read('<6I'); present, = read('<B')
        if present not in (0, 1): raise ValueError('Invalid initial buffer flag')
        if present:
            empty, = read('<Q')
            if empty != 0: raise ValueError('Unsupported initial buffer pointer')
            p = (p + 63) & ~63
            read('<Q')  # serialized row/depth pitch
        rid, n = read('<QQ'); p = (p + 63) & ~63
        if p+n+8 != c['end'] or n != desc[0]: raise ValueError('Unsupported buffer data layout')
        duplicate = struct.unpack_from('<Q', data, p+n)[0]
        if duplicate != n: raise ValueError('Buffer length mismatch')
        code = data[p:p+n]; file = f'{rid}.bin'
        with (output/file).open('xb') as dst: dst.write(code)
        results.append(dict(resource_id=rid, resource_name=names.get(str(rid),''), file=file,
            descriptor=dict(zip(['ByteWidth','Usage','BindFlags','CPUAccessFlags','MiscFlags','StructureByteStride'],desc)),
            sha256=hashlib.sha256(code).hexdigest(), byte_size=n, section_byte_offset=p,
            chunk_index=c['index'], initial_data_supplied=bool(present),
            content_scope='serialized_initial_contents', replay_verified=False))
    return results
