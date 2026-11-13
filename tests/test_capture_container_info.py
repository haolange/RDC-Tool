from types import SimpleNamespace
import pytest
from rdc_tool.core.capture_queries import read_container_info


def test_container_info_never_opens_replay():
    calls = []
    props = SimpleNamespace(name='frame', type=1, version=20, flags=2, compressedSize=10, uncompressedSize=40)
    capture = SimpleNamespace(OpenFile=lambda *a: 0, Shutdown=lambda: calls.append('close'),
        DriverName=lambda: 'D3D11', GetSectionCount=lambda: 1, GetSectionProperties=lambda i: props)
    rd = SimpleNamespace(OpenCaptureFile=lambda: capture, ResultCode=SimpleNamespace(Succeeded=0))
    result = read_container_info(rd, 'file.rdc')
    assert result['replay_verified'] is False
    assert result['driver'] == 'D3D11'
    assert result['sections'][0]['version'] == 20
    assert calls == ['close']


def test_container_read_failure_closes_capture():
    calls = []
    capture = SimpleNamespace(OpenFile=lambda *a: 'corrupt', Shutdown=lambda: calls.append('close'))
    rd = SimpleNamespace(OpenCaptureFile=lambda: capture, ResultCode=SimpleNamespace(Succeeded=0))
    with pytest.raises(RuntimeError, match='corrupt'):
        read_container_info(rd, 'bad.rdc')
    assert calls == ['close']
