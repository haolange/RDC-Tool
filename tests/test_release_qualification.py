from __future__ import annotations

from pathlib import Path
import json

import pytest

from scripts import package_release as package, verify_release_package as verify


def archive_fixture(root: Path, monkeypatch) -> None:
    root.mkdir(exist_ok=True)
    (root / "LICENSE").write_bytes(b"fixture\n")
    runtime = root / "binaries/windows/x64/manifest.runtime.json"
    runtime.parent.mkdir(parents=True)
    runtime.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(package, "_tools_root", lambda: root)
    monkeypatch.setattr(package, "_source_revision", lambda root: "a" * 40)
    monkeypatch.setattr(package, "_qualify_source", lambda root: None)


@pytest.mark.parametrize("status", ["unavailable", "invalid"])
def test_formal_package_rejects_unverified_native_before_creating_archive(tmp_path, monkeypatch, status):
    monkeypatch.setattr(package, "_tools_root", lambda: tmp_path)
    monkeypatch.setattr(package, "_source_revision", lambda root: "a" * 40)
    monkeypatch.setattr(package, "native_manifest_status", lambda root: {"status": status})
    with pytest.raises(RuntimeError, match="paired native runtime"):
        package.main([])
    assert not (tmp_path / "dist").exists()


def test_source_gate_failure_prevents_packaging(tmp_path, monkeypatch):
    from scripts import release_gate
    monkeypatch.setattr(package, "_tools_root", lambda: tmp_path)
    monkeypatch.setattr(package, "_source_revision", lambda root: "a" * 40)
    monkeypatch.setattr(package, "native_manifest_status", lambda root: {"status": "verified"})
    calls = []

    def fail(args):
        calls.append(args)
        return 1

    monkeypatch.setattr(release_gate, "main", fail)
    with pytest.raises(RuntimeError, match="source qualification failed"):
        package.main([])
    assert calls == [["--report", "intermediate/logs/release_package_source_gate.md"]]
    assert not (tmp_path / "dist").exists()


def test_complete_zip_verification_failure_leaves_no_deliverable(tmp_path, monkeypatch):
    archive_fixture(tmp_path, monkeypatch)
    verified = []

    def fail(args):
        assert args[0] == "--zip"
        staged = Path(args[1])
        assert staged.is_file()
        assert (staged.parent / "SHA256SUMS").is_file()
        assert staged.parent.name.startswith(".release-stage-")
        verified.append(staged)
        return 1

    monkeypatch.setattr(verify, "main", fail)
    with pytest.raises(RuntimeError, match="archive verification failed"):
        package.main([])
    assert verified and not verified[0].exists()
    assert not list((tmp_path / "dist").iterdir())


def test_archive_becomes_deliverable_only_after_full_verification(tmp_path, monkeypatch):
    archive_fixture(tmp_path, monkeypatch)
    calls = []

    def success(args):
        calls.append(args)
        assert args[0] == "--zip" and len(args) == 2
        assert not list((tmp_path / "dist").glob("*.zip"))
        return 0

    monkeypatch.setattr(verify, "main", success)
    assert package.main([]) == 0
    assert len(calls) == 1
    assert len(list((tmp_path / "dist").glob("*.zip"))) == 1
    assert (tmp_path / "dist/SHA256SUMS").is_file()
    assert not list((tmp_path / "dist").glob(".release-stage-*"))


@pytest.mark.parametrize("change_at", ["qualification", "archive"])
def test_revision_change_during_release_prevents_acceptance(tmp_path, monkeypatch, change_at):
    archive_fixture(tmp_path, monkeypatch)
    revisions = iter(["a" * 40, "b" * 40] if change_at == "qualification"
                     else ["a" * 40, "a" * 40, "b" * 40])
    monkeypatch.setattr(package, "_source_revision", lambda root: next(revisions))
    monkeypatch.setattr(verify, "main", lambda args: 0)
    with pytest.raises(RuntimeError, match="source changed"):
        package.main([])
    assert not list(tmp_path.rglob("*.zip"))
    assert not list(tmp_path.rglob(".release-stage-*"))


def test_input_drift_even_with_unchanged_revision_prevents_acceptance(tmp_path, monkeypatch):
    archive_fixture(tmp_path, monkeypatch)

    def mutate(args):
        (tmp_path / "LICENSE").write_bytes(b"changed after snapshot")
        return 0

    monkeypatch.setattr(verify, "main", mutate)
    with pytest.raises(RuntimeError, match="input changed.*LICENSE"):
        package.main([])
    assert not list((tmp_path / "dist").iterdir())


def test_formal_archive_requires_paired_native_receipt_too(tmp_path):
    from test_release_identity import identity_fixture

    root = identity_fixture(tmp_path)
    with pytest.raises(RuntimeError, match="paired native runtime"):
        verify._verify_release_identity(root, tmp_path / "source")


@pytest.mark.parametrize("failed_name", ["SHA256SUMS", "release_report.md"])
@pytest.mark.parametrize("prior_metadata", [False, True])
def test_final_metadata_failure_rolls_back_zip_and_preserves_previous_metadata(
        tmp_path, monkeypatch, failed_name, prior_metadata):
    archive_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(verify, "main", lambda args: 0)
    out = tmp_path / "dist"
    out.mkdir()
    if prior_metadata:
        for name in ("SHA256SUMS", "release_report.md"):
            (out / name).write_bytes(b"previous " + name.encode())
    original_replace = Path.replace

    def fail_replace(self, destination):
        if Path(destination).name == failed_name:
            raise PermissionError("metadata locked")
        return original_replace(self, destination)

    monkeypatch.setattr(Path, "replace", fail_replace)
    with pytest.raises(PermissionError, match="metadata locked"):
        package.main([])
    assert not list(out.glob("*.zip"))
    assert not list(out.glob(".release-stage-*"))
    for name in ("SHA256SUMS", "release_report.md"):
        if prior_metadata:
            assert (out / name).read_bytes() == b"previous " + name.encode()
        else:
            assert not (out / name).exists()


@pytest.mark.parametrize("status,accepted", [("unavailable", False), ("invalid", False), ("verified", True)])
def test_repository_gate_cannot_accept_unverified_native(tmp_path, monkeypatch, status, accepted):
    from scripts import release_gate

    monkeypatch.setattr(release_gate, "native_manifest_status", lambda root: {"status": status})
    ok, detail = release_gate._check_paired_native(tmp_path)
    assert ok is accepted
    assert status in detail


@pytest.mark.parametrize("import_ok,paths_match", [(False, False), (True, False), (True, True)])
def test_native_loader_requires_actual_import_and_same_installation(
        tmp_path, monkeypatch, import_ok, paths_match):
    calls = []

    def result(command, cwd, **kwargs):
        calls.append((command, cwd, kwargs))
        native = tmp_path / "binaries/windows/x64"
        return 0, json.dumps({"import_ok": import_ok, "loaded": {
            "configured_paths_match": paths_match,
            "python": {"path": str(native / "python/python.exe")},
            "native": {"path": str(native / "renderdoc.dll")},
            "binding": {"path": str(native / "pymodules/renderdoc.pyd")},
        }})

    monkeypatch.setattr(verify, "_run", result)
    if import_ok and paths_match:
        verify._verify_native_loader(tmp_path)
    else:
        with pytest.raises(RuntimeError, match="native loader failed"):
            verify._verify_native_loader(tmp_path)
    command, cwd, kwargs = calls[0]
    assert command[0] == str(tmp_path / "binaries/windows/x64/python/python.exe")
    assert cwd == tmp_path
    env = kwargs["env"]
    assert env["PATH"].lower().endswith("system32")
    assert "PYTHONPATH" not in env and "JAVA_HOME" not in env


def test_foreign_runtime_override_cannot_certify_package_loader(tmp_path, monkeypatch):
    monkeypatch.setenv("RDC_TOOL_RUNTIME_DLL_DIR", "D:/foreign-runtime")
    monkeypatch.setenv("RDC_TOOL_RENDERDOC_PATH", "D:/foreign-runtime/pymodules")
    native = tmp_path / "binaries/windows/x64"

    def foreign(command, cwd, **kwargs):
        env = kwargs["env"]
        assert Path(env["RDC_TOOL_RUNTIME_DLL_DIR"]) == native
        assert Path(env["RDC_TOOL_RENDERDOC_PATH"]) == native / "pymodules"
        return 0, json.dumps({"import_ok": True, "loaded": {
            "configured_paths_match": True,
            "python": {"path": str(native / "python/python.exe")},
            "native": {"path": "D:/foreign-runtime/renderdoc.dll"},
            "binding": {"path": "D:/foreign-runtime/pymodules/renderdoc.pyd"},
        }})

    monkeypatch.setattr(verify, "_run", foreign)
    with pytest.raises(RuntimeError, match="native loader failed"):
        verify._verify_native_loader(tmp_path)
