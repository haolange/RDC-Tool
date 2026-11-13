#!/usr/bin/env python3
"""Stage a matching, user-built Linux RenderDoc pair; never download or overwrite.

Run with the SAME Python interpreter used to run RDC-Tool. Provenance is supplied
by the builder; byte identity and actual loader paths are independently checked.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import sysconfig
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def identity(path: Path) -> dict:
    with path.open('rb') as stream:
        return {'size': path.stat().st_size,
                'sha256': hashlib.file_digest(stream, 'sha256').hexdigest()}


def validate_inputs(library: Path, binding: Path) -> None:
    if not sys.platform.startswith('linux') or platform.machine().lower() not in ('x86_64', 'amd64'):
        raise ValueError('Only Linux x86-64 is supported by this installer')
    if binding.name not in ('renderdoc.so', 'renderdoc' + sysconfig.get_config_var('EXT_SUFFIX')):
        raise ValueError('Binding must be upstream renderdoc.so or match this interpreter EXT_SUFFIX; do not rename an incompatible binding')
    for path in (library, binding):
        with path.open('rb') as stream:
            header = stream.read(20)
        if len(header) < 20 or header[:6] != b'\x7fELF\x02\x01' or header[18:20] != b'\x3e\x00':
            raise ValueError(f'Expected a little-endian ELF64 x86-64 object: {path}')


def probe_runtime(directory: Path) -> dict:
    code = '''import json, pathlib, sys
sys.path.insert(0, sys.argv[1] + '/pymodules')
import renderdoc
paths = sorted({line.split(maxsplit=5)[5].strip() for line in pathlib.Path('/proc/self/maps').read_text().splitlines() if len(line.split(maxsplit=5)) == 6 and pathlib.Path(line.split(maxsplit=5)[5].strip()).name.startswith('librenderdoc.so')})
print(json.dumps({'binding': str(pathlib.Path(renderdoc.__file__).resolve()), 'libraries': paths, 'version': renderdoc.GetVersionString()}))
'''
    env = os.environ.copy()
    env.pop('PYTHONPATH', None)
    env.pop('LD_PRELOAD', None)
    env['LD_LIBRARY_PATH'] = str(directory)
    proc = subprocess.run([sys.executable, '-I', '-c', code, str(directory)],
                          env=env, text=True, capture_output=True, timeout=30)
    if proc.returncode:
        raise ValueError('RenderDoc import probe failed: ' + proc.stderr[-4000:])
    result = json.loads(proc.stdout.strip().splitlines()[-1])
    expected_binding = directory / 'pymodules' / ('renderdoc' + sysconfig.get_config_var('EXT_SUFFIX'))
    expected_library = directory / 'librenderdoc.so'
    if Path(result['binding']).resolve() != expected_binding.resolve():
        raise ValueError('Probe loaded a different Python binding')
    if {Path(p).resolve() for p in result['libraries']} != {expected_library.resolve()}:
        raise ValueError('Probe did not load exactly the paired native library')
    return result


def install(library: Path, binding: Path, destination: Path, source_url: str,
            source_revision: str, version: str) -> dict:
    validate_inputs(library, binding)
    if not source_url.startswith('https://') or not re.fullmatch(r'[0-9a-fA-F]{40}', source_revision):
        raise ValueError('Supply an HTTPS source URL and full 40-character source revision')
    if not version.strip():
        raise ValueError('Version is required')
    destination = destination.absolute()
    if destination.exists() or destination.is_symlink():
        raise ValueError('Destination already exists; choose a new directory')
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.rdc-runtime-', dir=destination.parent) as temporary:
        stage = Path(temporary)
        (stage / 'pymodules').mkdir()
        shutil.copy2(library, stage / 'librenderdoc.so')
        binding_name = 'renderdoc' + sysconfig.get_config_var('EXT_SUFFIX')
        shutil.copy2(binding, stage / 'pymodules' / binding_name)
        observed = probe_runtime(stage)
        if observed['version'] != version:
            raise ValueError(f"Observed version {observed['version']!r} differs from requested {version!r}")
        manifest = {'native_build': {'target': 'linux-x64', 'source_url': source_url,
                    'source_revision': source_revision.lower(), 'version': version,
                    'python_abi': sysconfig.get_config_var('SOABI'),
                    'provenance_scope': 'builder_supplied; not source-build attestation'},
                    'files': [{'path': p.relative_to(stage).as_posix(), **identity(p)}
                              for p in (stage / 'librenderdoc.so', stage / 'pymodules' / binding_name)]}
        (stage / 'manifest.runtime.json').write_text(json.dumps(manifest, indent=2) + '\n')
        # rename does not overwrite a nonempty destination, and no destination is
        # removed on failure. TemporaryDirectory cleans only its owned stage.
        stage.rename(destination)
    return {'destination': str(destination), 'version': version,
            'replay_verified': False, 'manifest': str(destination / 'manifest.runtime.json')}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--library', type=Path, required=True)
    parser.add_argument('--binding', type=Path, required=True)
    parser.add_argument('--source-url', required=True)
    parser.add_argument('--source-revision', required=True)
    parser.add_argument('--version', required=True)
    parser.add_argument('--destination', type=Path, default=ROOT / 'binaries/linux/x64')
    args = parser.parse_args()
    try:
        result = install(**vars(args))
    except (OSError, ValueError, subprocess.SubprocessError, KeyError, IndexError) as exc:
        print(f'Linux runtime installation failed: {exc}', file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
