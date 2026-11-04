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


def test_license_bytes_cannot_be_replaced_by_inventory_claim(tmp_path, monkeypatch):
    monkeypatch.setattr(verify, 'native_manifest_status', lambda root: {'status': 'verified'})
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
    monkeypatch.setattr(package_release, '_qualify_source', lambda root: None)
    monkeypatch.setattr(package_release, '_qualify_package', lambda path: None)
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
    monkeypatch.setattr(package_release, '_qualify_source', lambda root: None)
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


def candidate_source_fixture(root, monkeypatch):
    from scripts import package_runtime
    from test_runtime_identity import native_inputs
    inputs = native_inputs(root)
    monkeypatch.setattr(package_runtime, '_tools_root', lambda: root)
    assert package_runtime.main(inputs) == 0
    for name in ('LICENSE', 'README.md'):
        (root / name).write_text('fixture\n', encoding='utf-8')
    (root / 'CHANGELOG.md').write_text(f'## {verify.TOOL_VERSION}\n', encoding='utf-8')
    (root / 'pyproject.toml').write_text(f'[project]\nversion="{verify.TOOL_VERSION}"\n', encoding='utf-8')
    for name in verify.EXPECTED_ENTRYPOINTS:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('fixture', encoding='utf-8')
    metadata = root / f'binaries/windows/x64/python/Lib/site-packages/rdc_tool-{verify.TOOL_VERSION}.dist-info/METADATA'
    metadata.parent.mkdir(parents=True)
    metadata.write_text(f'Version: {verify.TOOL_VERSION}\n', encoding='utf-8')
    monkeypatch.setattr(package_release, '_tools_root', lambda: root)
    monkeypatch.setattr(package_release, '_candidate_source', lambda root: {'base_revision': 'a' * 40, 'working_diff_sha256': 'd' * 64})


def test_local_candidate_does_not_weaken_release_source_gate(tmp_path, monkeypatch):
    candidate_source_fixture(tmp_path, monkeypatch)
    def no_release(root):
        raise RuntimeError('Release packaging requires a clean source checkout')
    monkeypatch.setattr(package_release, '_source_revision', no_release)
    assert package_release.main(['--candidate-dir', 'intermediate/candidate']) == 0
    candidate = tmp_path / 'intermediate/candidate'
    manifest = json.loads((candidate / 'CANDIDATE_MANIFEST.json').read_text(encoding='utf-8'))
    assert manifest['kind'] == 'local_validation_candidate'
    assert manifest['source_snapshot']['base_revision'] == 'a' * 40
    assert len(manifest['source_snapshot']['shipped_source_sha256']) == 64
    assert {'SBOM.json', 'LICENSE_INVENTORY.json'} <= {item['path'] for item in manifest['files']}
    assert not (candidate / 'RELEASE_MANIFEST.json').exists()
    verify._verify_release_identity(candidate, tmp_path, manifest_name='CANDIDATE_MANIFEST.json')
    with pytest.raises(RuntimeError, match='clean source checkout'):
        package_release.main([])
    with pytest.raises(FileExistsError, match='overwrite'):
        package_release.main(['--candidate-dir', 'intermediate/candidate'])
    assert not list(candidate.parent.glob('.candidate-stage-*'))


def test_local_candidate_rejects_source_drift_and_removes_its_stage(tmp_path, monkeypatch):
    candidate_source_fixture(tmp_path, monkeypatch)
    original_copy = package_release._copy_release_tree
    def changed(root, destination):
        files = original_copy(root, destination)
        (root / 'README.md').write_text('changed during copy', encoding='utf-8')
        return files
    monkeypatch.setattr(package_release, '_copy_release_tree', changed)
    with pytest.raises(RuntimeError, match='Source input changed'):
        package_release.main(['--candidate-dir', 'intermediate/candidate'])
    assert not (tmp_path / 'intermediate/candidate').exists()
    assert not list((tmp_path / 'intermediate').glob('.candidate-stage-*'))


def test_local_candidate_rejects_damaged_native_or_output_outside_disposable_root(tmp_path, monkeypatch):
    candidate_source_fixture(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match='intermediate'):
        package_release.main(['--candidate-dir', 'binaries/candidate'])
    (tmp_path / 'binaries/windows/x64/renderdoc.dll').write_bytes(b'damaged')
    with pytest.raises(RuntimeError, match='paired native build'):
        package_release.main(['--candidate-dir', 'intermediate/candidate'])
    assert not (tmp_path / 'intermediate/candidate').exists()


def test_candidate_integrity_detects_source_tampering_and_false_snapshot(tmp_path, monkeypatch):
    candidate_source_fixture(tmp_path, monkeypatch)
    assert package_release.main(['--candidate-dir', 'intermediate/candidate']) == 0
    candidate = tmp_path / 'intermediate/candidate'
    readme = candidate / 'README.md'
    before = readme.read_bytes()
    readme.write_bytes(b'tampered')
    with pytest.raises(RuntimeError, match='package bytes'):
        verify._verify_release_identity(candidate, tmp_path, manifest_name='CANDIDATE_MANIFEST.json')
    readme.write_bytes(before)
    sbom_path = candidate / 'SBOM.json'
    sbom = json.loads(sbom_path.read_text(encoding='utf-8'))
    sbom['source_snapshot']['working_diff_sha256'] = 'e' * 64
    sbom_path.write_text(json.dumps(sbom), encoding='utf-8')
    with pytest.raises(RuntimeError, match='package bytes|source snapshot'):
        verify._verify_release_identity(candidate, tmp_path, manifest_name='CANDIDATE_MANIFEST.json')


def test_candidate_uses_verified_runtime_output_without_changing_current_install(tmp_path, monkeypatch):
    from scripts import package_runtime
    from test_runtime_identity import native_inputs
    candidate_source_fixture(tmp_path, monkeypatch)
    # The configured current runtime can differ from the new paired build.
    original = tmp_path / 'binaries/windows/x64/renderdoc.dll'
    original.write_bytes(b'current user runtime')
    inputs = native_inputs(tmp_path)
    before = {path.relative_to(tmp_path).as_posix(): path.read_bytes()
              for path in tmp_path.rglob('*') if path.is_file()}
    assert package_runtime.main(inputs + ['--output-root', 'intermediate/task/runtime']) == 0
    assert package_release.main(['--candidate-dir', 'intermediate/task/candidate',
                                 '--runtime-root', 'intermediate/task/runtime']) == 0
    for name, contents in before.items():
        assert (tmp_path / name).read_bytes() == contents
    candidate = tmp_path / 'intermediate/task/candidate'
    assert (candidate / 'binaries/windows/x64/renderdoc.dll').read_bytes() == b'renderdoc'
    assert (candidate / 'README.md').read_bytes() == (tmp_path / 'README.md').read_bytes()
    manifest = json.loads((candidate / 'CANDIDATE_MANIFEST.json').read_text(encoding='utf-8'))
    assert manifest['source_snapshot']['base_revision'] == 'a' * 40
    assert manifest['source_snapshot']['shipped_source_sha256'] == package_release.source_file_digest(manifest['files'])
    assert not (candidate / 'RELEASE_MANIFEST.json').exists()
    verify._verify_release_identity(candidate, tmp_path, manifest_name='CANDIDATE_MANIFEST.json')
    assert not list(candidate.parent.glob('.candidate-stage-*'))


def test_runtime_input_override_is_candidate_only_and_cannot_overlap_output(tmp_path, monkeypatch):
    candidate_source_fixture(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match='only valid with --candidate-dir'):
        package_release.main(['--runtime-root', 'intermediate/task/runtime'])
    runtime = tmp_path / 'intermediate/task/runtime'
    runtime.mkdir(parents=True)
    with pytest.raises(ValueError, match='overlaps'):
        package_release.main(['--runtime-root', 'intermediate/task/runtime',
                              '--candidate-dir', 'intermediate/task/runtime/candidate'])
    assert not (runtime / 'candidate').exists()
