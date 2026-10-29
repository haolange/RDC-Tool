from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from scripts import package_release, verify_release_package as verify


def identity_fixture(root: Path) -> Path:
    source = root / 'source'
    package = root / 'package'
    source.mkdir()
    package.mkdir()
    for directory in (source, package):
        (directory / 'LICENSE').write_bytes(b'complete license fixture\n')
    (package / 'CHANGELOG.md').write_text(f'## {verify.TOOL_VERSION}\n', encoding='utf-8')
    for name in ('RELEASE_MANIFEST.json', 'SBOM.json'):
        (package / name).write_text(json.dumps({'version': verify.TOOL_VERSION, 'source_revision': 'a' * 40, 'files': [], 'components': [{'name': 'rdc-tool', 'version': verify.TOOL_VERSION}]}), encoding='utf-8')
    (package / 'pyproject.toml').write_text(f'[project]\nversion = "{verify.TOOL_VERSION}"\n', encoding='utf-8')
    metadata = package / f'binaries/windows/x64/python/Lib/site-packages/rdc_tool-{verify.TOOL_VERSION}.dist-info/METADATA'
    metadata.parent.mkdir(parents=True)
    metadata.write_text(f'Version: {verify.TOOL_VERSION}\n', encoding='utf-8')
    (package / 'LICENSE_INVENTORY.json').write_text(json.dumps([{'name': 'rdc-tool', 'version': verify.TOOL_VERSION}]), encoding='utf-8')
    return package


def test_license_bytes_cannot_be_replaced_by_inventory_claim(tmp_path):
    package = identity_fixture(tmp_path)
    verify._verify_release_identity(package, tmp_path / 'source')
    (package / 'LICENSE').write_bytes(b'Apache-2.0 truncated')
    with pytest.raises(RuntimeError, match='LICENSE bytes'):
        verify._verify_release_identity(package, tmp_path / 'source')


def test_release_version_and_changelog_must_match(tmp_path):
    package = identity_fixture(tmp_path)
    (package / 'CHANGELOG.md').write_text('## Unreleased', encoding='utf-8')
    with pytest.raises(RuntimeError, match='CHANGELOG'):
        verify._verify_release_identity(package, tmp_path / 'source')


def test_replaced_zip_license_fails_even_with_recomputed_manifest_and_checksum(tmp_path):
    package = identity_fixture(tmp_path)
    (package / 'LICENSE').write_bytes(b'replaced license')
    manifest = json.loads((package / 'RELEASE_MANIFEST.json').read_text(encoding='utf-8'))
    manifest['files'] = [{'path': 'LICENSE', 'size': 16, 'sha256': verify._sha256(package / 'LICENSE')}]
    (package / 'RELEASE_MANIFEST.json').write_text(json.dumps(manifest), encoding='utf-8')
    archive = tmp_path / 'candidate.zip'
    with zipfile.ZipFile(archive, 'w') as zipped:
        for file in package.rglob('*'):
            if file.is_file():
                zipped.write(file, file.relative_to(package))
    (tmp_path / 'SHA256SUMS').write_text(f'{verify._sha256(archive)}  candidate.zip\n', encoding='utf-8')
    verify._verify_archive_checksum(archive)
    extracted = tmp_path / 'extracted'
    with zipfile.ZipFile(archive) as zipped:
        zipped.extractall(extracted)
    with pytest.raises(RuntimeError, match='LICENSE bytes'):
        verify._verify_release_identity(extracted, tmp_path / 'source')


def test_checksum_checks_bytes_not_just_filename(tmp_path):
    archive = tmp_path / 'candidate.zip'
    archive.write_bytes(b'archive')
    checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
    (tmp_path / 'SHA256SUMS').write_text(f'{checksum}  candidate.zip\n', encoding='utf-8')
    verify._verify_archive_checksum(archive)
    archive.write_bytes(b'changed')
    with pytest.raises(RuntimeError, match='checksum'):
        verify._verify_archive_checksum(archive)


@pytest.mark.parametrize('filename', ['RELEASE_MANIFEST.json', 'SBOM.json', 'LICENSE_INVENTORY.json', 'pyproject.toml'])
def test_metadata_version_mismatch_fails(tmp_path, filename):
    package = identity_fixture(tmp_path)
    file = package / filename
    file.write_text(file.read_text(encoding='utf-8').replace(verify.TOOL_VERSION, '0.0.0'), encoding='utf-8')
    with pytest.raises(RuntimeError, match='version'):
        verify._verify_release_identity(package, tmp_path / 'source')


def test_staging_is_removed_on_success_and_archive_failure(tmp_path, monkeypatch):
    staging = []
    monkeypatch.setattr(package_release, '_tools_root', lambda: tmp_path)
    monkeypatch.setattr(package_release, '_source_revision', lambda root: 'a' * 40)
    def copy(root, destination):
        staging.append(destination.parent)
        (destination / 'LICENSE').write_bytes(b'fixture')
        runtime = destination / 'binaries/windows/x64/manifest.runtime.json'
        runtime.parent.mkdir(parents=True)
        runtime.write_text('{}')
        return []
    monkeypatch.setattr(package_release, '_copy_release_tree', copy)
    assert package_release.main(['--out-dir', 'success']) == 0
    assert not staging[-1].exists()
    def fail_archive(root, output):
        output.write_bytes(b'partial archive')
        raise RuntimeError('archive failed')
    monkeypatch.setattr(package_release, '_zip_dir', fail_archive)
    with pytest.raises(RuntimeError, match='archive failed'):
        package_release.main(['--out-dir', 'failure'])
    assert not staging[-1].exists()
    assert not list((tmp_path / 'failure').glob('*.zip'))


def test_staging_is_removed_on_copy_failure(tmp_path, monkeypatch):
    staging = []
    monkeypatch.setattr(package_release, '_tools_root', lambda: tmp_path)
    monkeypatch.setattr(package_release, '_source_revision', lambda root: 'a' * 40)
    def fail_copy(root, destination):
        staging.append(destination.parent)
        raise RuntimeError('copy failed')
    monkeypatch.setattr(package_release, '_copy_release_tree', fail_copy)
    with pytest.raises(RuntimeError, match='copy failed'):
        package_release.main([])
    assert staging and not staging[0].exists()
    assert not list((tmp_path / 'dist').glob('*.zip'))


def test_packaging_requires_clean_commit(tmp_path):
    import subprocess
    subprocess.run(['git', 'init', str(tmp_path)], check=True, capture_output=True)
    for key, value in [('user.name', 'Release test'), ('user.email', 'release@example.invalid')]:
        subprocess.run(['git', '-C', str(tmp_path), 'config', key, value], check=True)
    file = tmp_path / 'source.txt'
    file.write_text('committed', encoding='utf-8')
    subprocess.run(['git', '-C', str(tmp_path), 'add', '.'], check=True)
    subprocess.run(['git', '-C', str(tmp_path), 'commit', '-m', 'fixture'], check=True, capture_output=True)
    revision = package_release._source_revision(tmp_path)
    assert len(revision) == 40
    file.write_text('uncommitted', encoding='utf-8')
    with pytest.raises(RuntimeError, match='clean source checkout'):
        package_release._source_revision(tmp_path)


@pytest.mark.parametrize('revision', ['', '1.1.0', 'a' * 39])
def test_invalid_source_revision_is_rejected(tmp_path, revision):
    package = identity_fixture(tmp_path)
    path = package / 'RELEASE_MANIFEST.json'
    manifest = json.loads(path.read_text(encoding='utf-8'))
    manifest['source_revision'] = revision
    path.write_text(json.dumps(manifest), encoding='utf-8')
    with pytest.raises(RuntimeError, match='source_revision'):
        verify._verify_release_identity(package, tmp_path / 'source')


def test_sbom_revision_must_match_manifest(tmp_path):
    package = identity_fixture(tmp_path)
    path = package / 'SBOM.json'
    payload = json.loads(path.read_text(encoding='utf-8'))
    payload['source_revision'] = 'b' * 40
    path.write_text(json.dumps(payload), encoding='utf-8')
    with pytest.raises(RuntimeError, match='source_revision'):
        verify._verify_release_identity(package, tmp_path / 'source')
