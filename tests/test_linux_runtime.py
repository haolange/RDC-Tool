from pathlib import Path
import json
import sys
import sysconfig
from types import SimpleNamespace
import pytest
from rdc_tool import native_platform, runtime_paths, runtime_identity, python_runtime

pytestmark = pytest.mark.skipif(not sys.platform.startswith('linux'), reason='Linux host tests')

@pytest.fixture(autouse=True)
def isolate(monkeypatch, tmp_path):
    monkeypatch.setenv('RDC_TOOL_ROOT', str(tmp_path))
    monkeypatch.delenv('RDC_TOOL_RUNTIME_DLL_DIR', raising=False)
    monkeypatch.delenv('RDC_TOOL_RENDERDOC_PATH', raising=False)


def test_native_paths_are_not_windows(tmp_path):
    assert runtime_paths.binaries_root() == tmp_path/'binaries/linux/x64'
    assert native_platform.native_library_path(tmp_path).name == 'librenderdoc.so'
    assert python_runtime.bundled_python_executable() == Path(sys.executable).resolve()
    ok, failures, details = python_runtime.validate_bundled_python_layout()
    assert ok and not failures and details['mode'] == 'host_python'


def test_extension_binding_requires_compatible_suffix(tmp_path):
    import importlib.machinery
    native = tmp_path/('renderdoc'+importlib.machinery.EXTENSION_SUFFIXES[0])
    native.touch()
    (tmp_path/'renderdoc.pyd').touch()
    assert native_platform.native_binding_path(tmp_path) == native


def test_linux_receipt_checks_all_bytes(tmp_path, monkeypatch):
    root = runtime_paths.binaries_root(); (root/'pymodules').mkdir(parents=True)
    library = root/'librenderdoc.so';library.write_bytes(b'library')
    binding = native_platform.native_binding_path(root/'pymodules');binding.write_bytes(b'binding')
    files = [{'path':p.relative_to(root).as_posix(),**runtime_identity.file_identity(p)} for p in [library,binding]]
    manifest={'native_build':{'target':'linux-x64','source_url':'https://renderdoc.org','version':'test','python_abi':sysconfig.get_config_var('SOABI')},'files':files}
    (root/'manifest.runtime.json').write_text(json.dumps(manifest))
    assert runtime_identity.host_native_manifest_status(tmp_path)['status']=='verified'
    monkeypatch.setenv('RDC_TOOL_RENDERDOC_PATH',str(tmp_path/'outside'))
    assert runtime_identity.host_native_manifest_status(tmp_path)['status']=='invalid'
    monkeypatch.delenv('RDC_TOOL_RENDERDOC_PATH')
    binding.write_bytes(b'modified')
    assert runtime_identity.host_native_manifest_status(tmp_path)['status']=='invalid'
    binding.unlink()
    assert runtime_identity.host_native_manifest_status(tmp_path)['status']=='invalid'


def test_linux_receipt_rejects_escape(tmp_path):
    root=runtime_paths.binaries_root(); root.mkdir(parents=True)
    (root/'manifest.runtime.json').write_text(json.dumps({'native_build':{'target':'linux-x64','source_url':'https://renderdoc.org','version':'test','python_abi':sysconfig.get_config_var('SOABI')},'files':[{'path':'../../../escape','size':1,'sha256':'x'}]}))
    assert runtime_identity.host_native_manifest_status(tmp_path)['status']=='invalid'


def test_preview_module_is_importable_but_does_not_fake_window():
    from rdc_tool import preview_window
    assert preview_window.PreviewWindowHost is None
    assert preview_window.fit_size_within_bounds(100,100,50,50)==(50,50)
