"""Build relocatable metadata for the source package in the bundled distribution."""
from __future__ import annotations

import base64
import csv
import hashlib
import shutil
import tomllib
from pathlib import Path


def write_distribution_metadata(root: Path, site_packages: Path) -> None:
    project = tomllib.loads((root / 'pyproject.toml').read_text(encoding='utf-8'))['project']
    name, version = project['name'], project['version']
    directory = site_packages / f"{name.replace('-', '_')}-{version}.dist-info"
    # Runtime packaging owns these generated metadata directories, not third-party packages.
    for previous in site_packages.glob(f"{name.replace('-', '_')}-*.dist-info"):
        if previous == directory:
            continue
        if previous.is_symlink() or previous.resolve().parent != site_packages.resolve():
            raise RuntimeError(f'Unsafe distribution metadata path: {previous}')
        if (previous / 'INSTALLER').read_text(encoding='utf-8').strip() != 'rdc-tool-runtime':
            raise RuntimeError(f'Refusing to replace non-generated metadata: {previous}')
        shutil.rmtree(previous)
    directory.mkdir(parents=True, exist_ok=True)
    fields = ['Metadata-Version: 2.3', f'Name: {name}', f'Version: {version}',
              f"Summary: {project['description']}", 'License: Apache-2.0',
              f"Requires-Python: {project['requires-python']}"]
    fields.extend(f'Requires-Dist: {dependency}' for dependency in project['dependencies'])
    files = {
        'METADATA': '\n'.join(fields) + '\n',
        'WHEEL': 'Wheel-Version: 1.0\nGenerator: RDC-Tool runtime packaging\nRoot-Is-Purelib: true\nTag: py3-none-any\n',
        'INSTALLER': 'rdc-tool-runtime\n',
        'top_level.txt': 'rdc_tool\n',
        'entry_points.txt': '[console_scripts]\nrdc-tool = rdc_tool.cli:main\n',
    }
    rows = []
    for filename, text in files.items():
        payload = text.encode('utf-8')
        (directory / filename).write_bytes(payload)
        digest = base64.urlsafe_b64encode(hashlib.sha256(payload).digest()).decode().rstrip('=')
        rows.append([f'{directory.name}/{filename}', f'sha256={digest}', str(len(payload))])
    rows.append([f'{directory.name}/RECORD', '', ''])
    with (directory / 'RECORD').open('w', encoding='utf-8', newline='') as stream:
        csv.writer(stream).writerows(rows)
