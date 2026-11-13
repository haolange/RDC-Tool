import importlib.util
import json
from pathlib import Path
import sys
import sysconfig

import pytest

spec = importlib.util.spec_from_file_location('install_linux_runtime', Path(__file__).parents[1] / 'scripts/install_linux_runtime.py')
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)
pytestmark = pytest.mark.skipif(not sys.platform.startswith('linux'), reason='Linux installer')


def inputs(tmp_path):
    header = b'\x7fELF\x02\x01' + bytes(12) + b'\x3e\x00'
    library = tmp_path / 'lib.so'; library.write_bytes(header)
    binding = tmp_path / ('renderdoc' + sysconfig.get_config_var('EXT_SUFFIX')); binding.write_bytes(header)
    return library, binding


def test_install_records_pair_and_refuses_overwrite(tmp_path, monkeypatch):
    library, binding = inputs(tmp_path)
    destination = tmp_path / 'runtime'
    monkeypatch.setattr(installer, 'probe_runtime', lambda _: {'version': '1.47'})
    result = installer.install(library, binding, destination, 'https://github.com/baldurk/renderdoc', 'a' * 40, '1.47')
    assert result['replay_verified'] is False
    manifest = json.loads((destination / 'manifest.runtime.json').read_text())
    assert len(manifest['files']) == 2
    assert manifest['native_build']['python_abi'] == sysconfig.get_config_var('SOABI')
    for item in manifest['files']:
        assert installer.identity(destination / item['path']) == {k: item[k] for k in ('size', 'sha256')}
    with pytest.raises(ValueError, match='already exists'):
        installer.install(library, binding, destination, 'https://github.com/baldurk/renderdoc', 'a' * 40, '1.47')


def test_probe_failure_does_not_publish_partial_runtime(tmp_path, monkeypatch):
    library, binding = inputs(tmp_path)
    monkeypatch.setattr(installer, 'probe_runtime', lambda _: {'version': '1.46'})
    with pytest.raises(ValueError, match='differs'):
        installer.install(library, binding, tmp_path / 'runtime', 'https://github.com/baldurk/renderdoc', 'a' * 40, '1.47')
    assert not (tmp_path / 'runtime').exists()
    assert not list(tmp_path.glob('.rdc-runtime-*'))


def test_rejects_abi_name_and_non_elf(tmp_path):
    library, binding = inputs(tmp_path)
    renamed = tmp_path / 'renderdoc.cpython-999-x86_64-linux-gnu.so'; renamed.write_bytes(binding.read_bytes())
    with pytest.raises(ValueError, match='EXT_SUFFIX'):
        installer.validate_inputs(library, renamed)
    library.write_bytes(b'not an ELF file')
    with pytest.raises(ValueError, match='ELF64'):
        installer.validate_inputs(library, binding)


def test_upstream_generic_binding_is_installed_with_current_abi(tmp_path, monkeypatch):
    library, binding = inputs(tmp_path)
    generic = tmp_path / 'renderdoc.so'
    generic.write_bytes(binding.read_bytes())
    monkeypatch.setattr(installer, 'probe_runtime', lambda _: {'version': '1.47'})
    destination = tmp_path / 'runtime'
    installer.install(library, generic, destination, 'https://github.com/baldurk/renderdoc', 'a' * 40, '1.47')
    assert (destination / 'pymodules' / binding.name).is_file()
