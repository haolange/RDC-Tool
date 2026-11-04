from __future__ import annotations

import json
from pathlib import Path

from scripts import package_runtime
from rdc_tool import __version__
from scripts.distribution_metadata import write_distribution_metadata
from test_runtime_identity import native_inputs


def _write(path: Path, content: bytes | str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf-8")


def test_package_runtime_bundles_python_and_excludes_dev_only_packages(tmp_path: Path, monkeypatch) -> None:
    tools_root = tmp_path / "tools"
    renderdoc_src = tools_root / "staging"
    python_home = tmp_path / "python-home"
    site_packages = tools_root / ".venv" / "Lib" / "site-packages"
    _write(tools_root / 'pyproject.toml', (Path(__file__).resolve().parents[1] / 'pyproject.toml').read_text(encoding='utf-8'))

    _write(renderdoc_src / "renderdoc.dll", b"renderdoc")
    _write(renderdoc_src / "renderdoc.json", "{}")
    _write(renderdoc_src / "pymodules" / "renderdoc.pyd", b"renderdoc-pyd")

    for name in ("python.exe", "pythonw.exe", "python3.dll", "python314.dll", "vcruntime140.dll", "vcruntime140_1.dll", "LICENSE.txt"):
        _write(python_home / name, b"x")
    _write(python_home / "DLLs" / "_socket.pyd", b"socket")
    _write(python_home / "Lib" / "os.py", "# os\n")
    _write(python_home / "Lib" / "site.py", "# site\n")
    _write(python_home / "Lib" / "encodings" / "__init__.py", "# enc\n")

    _write(site_packages / "numpy.libs" / "libopenblas.dll", b"blas")
    _write(site_packages / "pyarrow" / "__init__.py", "# should be excluded\n")
    _write(site_packages / "pyarrow.libs" / "arrow.dll", b"arrow")
    _write(site_packages / "pyarrow-12.0.0.dist-info" / "METADATA", "Name: pyarrow\n")
    _write(site_packages / "pytest" / "__init__.py", "# should be excluded\n")
    _write(site_packages / "pytest-9.0.0.dist-info" / "METADATA", "Name: pytest\n")

    monkeypatch.setattr(package_runtime, "_tools_root", lambda: tools_root)

    paired_inputs = native_inputs(tools_root)

    code = package_runtime.main(
        paired_inputs + [
            "--python-home",
            str(python_home),
            "--site-packages-source",
            ".venv/Lib/site-packages",
            "--python-version",
            "3.14.3",
        ]
    )

    assert code == 0
    out_root = tools_root / "binaries" / "windows" / "x64"
    manifest = json.loads((out_root / "manifest.runtime.json").read_text(encoding="utf-8"))
    bundled_python = manifest["bundled_python"]
    assert bundled_python["python_version"] == "3.14.3"
    assert (out_root / bundled_python["python_entry"]).is_file()
    assert (out_root / bundled_python["pth_file"]).is_file()
    assert (out_root / "python" / "Lib" / "site-packages" / "numpy.libs" / "libopenblas.dll").is_file()
    assert not (out_root / "python" / "Lib" / "site-packages" / "pyarrow").exists()
    assert not (out_root / "python" / "Lib" / "site-packages" / "pyarrow.libs").exists()
    assert not (out_root / "python" / "Lib" / "site-packages" / "pytest").exists()
    indexed = {item["path"]: item for item in manifest["files"]}
    assert "python/python.exe" in indexed
    assert "renderdoc.dll" in indexed
    metadata = out_root / f'python/Lib/site-packages/rdc_tool-{__version__}.dist-info'
    assert 'Name: rdc-tool' in (metadata / 'METADATA').read_text(encoding='utf-8')
    assert not (metadata / 'direct_url.json').exists()
    assert 'rdc-tool = rdc_tool.cli:main' in (metadata / 'entry_points.txt').read_text(encoding='utf-8')
    assert b'\r' not in (metadata / 'RECORD').read_bytes()
    removed_field = "worker_" + "materialize"
    assert all(removed_field not in item for item in manifest["files"])


def test_metadata_upgrade_replaces_only_owned_previous_version(tmp_path: Path) -> None:
    import pytest
    root = Path(__file__).resolve().parents[1]
    previous = tmp_path / 'rdc_tool-0.0.0.dist-info'
    _write(previous / 'INSTALLER', 'rdc-tool-runtime\n')
    write_distribution_metadata(root, tmp_path)
    assert not previous.exists()
    assert len(list(tmp_path.glob('rdc_tool-*.dist-info'))) == 1
    _write(previous / 'INSTALLER', 'external-installer\n')
    with pytest.raises(RuntimeError, match='non-generated'):
        write_distribution_metadata(root, tmp_path)
    assert previous.exists()

def test_package_runtime_rejects_site_packages_source_inside_output_tree(tmp_path: Path, monkeypatch) -> None:
    tools_root = tmp_path / "tools"
    python_home = tmp_path / "python-home"
    site_packages = tools_root / "binaries" / "windows" / "x64" / "python" / "Lib" / "site-packages"

    for name in ("python.exe", "pythonw.exe", "python3.dll", "python314.dll", "vcruntime140.dll", "vcruntime140_1.dll", "LICENSE.txt"):
        _write(python_home / name, b"x")
    _write(python_home / "DLLs" / "_socket.pyd", b"socket")
    _write(python_home / "Lib" / "os.py", "# os\n")
    _write(python_home / "Lib" / "site.py", "# site\n")
    _write(python_home / "Lib" / "encodings" / "__init__.py", "# enc\n")
    _write(site_packages / "pydantic" / "__init__.py", "# runtime dep\n")

    monkeypatch.setattr(package_runtime, "_tools_root", lambda: tools_root)

    code = package_runtime.main(
        [
            "--python-home",
            str(python_home),
            "--site-packages-source",
            "binaries/windows/x64/python/Lib/site-packages",
            "--python-version",
            "3.14.3",
        ]
    )

    assert code == 1


def test_runtime_regeneration_keeps_bundled_host_files_and_provenance(tmp_path, monkeypatch):
    tools_root = tmp_path / "tools"
    out_root = tools_root / "binaries/windows/x64"
    metadata = {"adb": {"version": "fixture", "source_url": "https://example.test/source", "license": "fixture"}}
    for relative in package_runtime.BUNDLED_HOST_FILES:
        _write(out_root / relative, b"host-tool")
    _write(out_root / "unrelated/cache.bin", b"excluded")
    _write(out_root / "manifest.runtime.json", json.dumps({"bundled_tools": metadata}))
    monkeypatch.setattr(package_runtime, "_tools_root", lambda: tools_root)
    assert package_runtime.main([]) == 0
    manifest = json.loads((out_root / "manifest.runtime.json").read_text(encoding="utf-8"))
    assert manifest["bundled_tools"] == metadata
    assert {entry["path"] for entry in manifest["files"]} == set(package_runtime.BUNDLED_HOST_FILES)
    assert manifest["file_count"] == len(package_runtime.BUNDLED_HOST_FILES)


def test_native_replacement_requires_the_complete_build_set(tmp_path, monkeypatch):
    monkeypatch.setattr(package_runtime, "_tools_root", lambda: tmp_path)
    assert package_runtime.main(["--source", "staging"]) == 1
    assert not (tmp_path / "binaries").exists()
    assert not list(tmp_path.glob(".runtime-stage-*"))


def test_copy_failure_cannot_rewrite_old_runtime_or_its_manifest(tmp_path, monkeypatch):
    inputs = native_inputs(tmp_path)
    old = tmp_path / "binaries/windows/x64"
    _write(old / "renderdoc.dll", b"old")
    _write(old / "manifest.runtime.json", '{"previous":"retained"}')
    original_copy = package_runtime.shutil.copy2
    def fail_copy(source, destination, *args, **kwargs):
        if Path(source) == tmp_path / "staging/renderdoc.dll":
            raise PermissionError("locked native input")
        return original_copy(source, destination, *args, **kwargs)
    monkeypatch.setattr(package_runtime, "_tools_root", lambda: tmp_path)
    monkeypatch.setattr(package_runtime.shutil, "copy2", fail_copy)
    assert package_runtime.main(inputs) == 1
    assert (old / "renderdoc.dll").read_bytes() == b"old"
    assert (old / "manifest.runtime.json").read_text(encoding="utf-8") == '{"previous":"retained"}'
    assert not list(tmp_path.glob(".runtime-stage-*"))


def test_failed_publish_restores_the_complete_original_directory(tmp_path, monkeypatch):
    inputs = native_inputs(tmp_path)
    old = tmp_path / "binaries/windows/x64"
    _write(old / "renderdoc.dll", b"old")
    _write(old / "manifest.runtime.json", '{}')
    original_rename = Path.rename
    def fail_publish(path, target):
        if path.name == "binaries" and path.parent.name.startswith(".runtime-stage-"):
            raise PermissionError("publish rejected")
        return original_rename(path, target)
    monkeypatch.setattr(package_runtime, "_tools_root", lambda: tmp_path)
    monkeypatch.setattr(Path, "rename", fail_publish)
    assert package_runtime.main(inputs) == 1
    assert (old / "renderdoc.dll").read_bytes() == b"old"
    assert (old / "manifest.runtime.json").read_text(encoding="utf-8") == '{}'
    assert not (tmp_path / "binaries/android").exists()
    assert not list(tmp_path.glob(".runtime-stage-*"))


def test_changed_build_input_is_rejected_before_publish(tmp_path, monkeypatch):
    inputs = native_inputs(tmp_path)
    (tmp_path / "staging/renderdoc.dll").write_bytes(b"changed after build")
    monkeypatch.setattr(package_runtime, "_tools_root", lambda: tmp_path)
    assert package_runtime.main(inputs) == 1
    assert not (tmp_path / "binaries").exists()
    assert not list(tmp_path.glob(".runtime-stage-*"))


def test_failed_python_assembly_preserves_existing_python(tmp_path, monkeypatch):
    old = tmp_path / "binaries/windows/x64"
    _write(old / "python/python.exe", b"old python")
    _write(old / "manifest.runtime.json", '{}')
    _write(tmp_path / "python-home/python.exe", b"new python")
    (tmp_path / "site-packages").mkdir()
    monkeypatch.setattr(package_runtime, "_tools_root", lambda: tmp_path)
    assert package_runtime.main(["--python-home", "python-home", "--python-version", "3.14.3",
                                 "--site-packages-source", "site-packages"]) == 1
    assert (old / "python/python.exe").read_bytes() == b"old python"
    assert (old / "manifest.runtime.json").read_text(encoding="utf-8") == '{}'
    assert not list(tmp_path.glob(".runtime-stage-*"))


def test_same_source_receipt_is_required_for_every_target(tmp_path, monkeypatch):
    inputs = native_inputs(tmp_path)
    receipt_path = tmp_path / "receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["builds"][1]["inputs_sha256"] = "d" * 64
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    monkeypatch.setattr(package_runtime, "_tools_root", lambda: tmp_path)
    assert package_runtime.main(inputs) == 1
    assert not (tmp_path / "binaries").exists()


def test_paired_build_is_rechecked_when_manifest_is_regenerated(tmp_path, monkeypatch):
    inputs = native_inputs(tmp_path)
    monkeypatch.setattr(package_runtime, "_tools_root", lambda: tmp_path)
    assert package_runtime.main(inputs) == 0
    apk = tmp_path / "binaries/android/arm64/org.renderdoc.renderdoccmd.arm64.apk"
    apk.write_bytes(b"damaged")
    manifest = tmp_path / "binaries/windows/x64/manifest.runtime.json"
    before = manifest.read_bytes()
    assert package_runtime.main([]) == 1
    assert manifest.read_bytes() == before


def test_native_replacement_removes_old_files_but_preserves_python_and_host_tools(tmp_path, monkeypatch):
    source = tmp_path / "staging"
    _write(source / "d3dcompiler_47.dll", b"matched support library")
    _write(source / "pymodules/d3dcompiler_47.dll", b"matched binding support library")
    inputs = native_inputs(tmp_path)
    old = tmp_path / "binaries/windows/x64"
    _write(old / "stale.dll", b"old unlisted library")
    _write(old / "old.json", "{}")
    _write(old / "pymodules/stale.pyd", b"old unlisted binding")
    _write(old / "python/Lib/retained.py", b"python unchanged")
    _write(old / "adb/adb.exe", b"host tool unchanged")
    _write(old / "manifest.runtime.json", "{}")
    monkeypatch.setattr(package_runtime, "_tools_root", lambda: tmp_path)
    assert package_runtime.main(inputs) == 0
    assert not (old / "stale.dll").exists()
    assert not (old / "old.json").exists()
    assert not (old / "pymodules/stale.pyd").exists()
    assert (old / "d3dcompiler_47.dll").read_bytes() == b"matched support library"
    assert (old / "pymodules/d3dcompiler_47.dll").read_bytes() == b"matched binding support library"
    assert (old / "python/Lib/retained.py").read_bytes() == b"python unchanged"
    assert (old / "adb/adb.exe").read_bytes() == b"host tool unchanged"
    assert package_runtime.runtime_identity.native_manifest_status(tmp_path)["status"] == "verified"


def test_native_source_support_files_require_complete_unchanged_receipt(tmp_path, monkeypatch):
    support = tmp_path / "staging/dbghelp.dll"
    _write(support, b"support library")
    inputs = native_inputs(tmp_path)
    monkeypatch.setattr(package_runtime, "_tools_root", lambda: tmp_path)
    receipt = tmp_path / "receipt.json"
    before = receipt.read_text(encoding="utf-8")
    contents = json.loads(before)
    contents["builds"][0]["runtime_files"] = [item for item in contents["builds"][0]["runtime_files"] if item["path"] != "dbghelp.dll"]
    receipt.write_text(json.dumps(contents), encoding="utf-8")
    assert package_runtime.main(inputs) == 1
    assert not (tmp_path / "binaries").exists()
    receipt.write_text(before, encoding="utf-8")
    support.write_bytes(b"changed support library")
    assert package_runtime.main(inputs) == 1
    assert not (tmp_path / "binaries").exists()


def test_unlisted_native_file_cannot_be_certified_by_manifest_regeneration(tmp_path, monkeypatch):
    inputs = native_inputs(tmp_path)
    monkeypatch.setattr(package_runtime, "_tools_root", lambda: tmp_path)
    assert package_runtime.main(inputs) == 0
    old = tmp_path / "binaries/windows/x64"
    _write(old / "stale.dll", b"unlisted binary")
    assert package_runtime.runtime_identity.native_manifest_status(tmp_path)["status"] == "invalid"
    before = (old / "manifest.runtime.json").read_bytes()
    assert package_runtime.main([]) == 1
    assert (old / "manifest.runtime.json").read_bytes() == before


def test_open_windows_file_cannot_leave_a_mixed_runtime(tmp_path, monkeypatch):
    import ctypes
    import os
    import pytest
    if os.name != "nt":
        pytest.skip("Windows file-sharing semantics")
    old = tmp_path / "binaries/windows/x64"
    _write(old / "renderdoc.dll", b"old")
    _write(old / "manifest.runtime.json", '{}')
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint, ctypes.c_uint, ctypes.c_void_p,
                                  ctypes.c_uint, ctypes.c_uint, ctypes.c_void_p]
    kernel.CreateFileW.restype = ctypes.c_void_p
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = kernel.CreateFileW(str(old / "renderdoc.dll"), 0x80000000, 1, None, 3, 0, None)
    assert handle not in (None, ctypes.c_void_p(-1).value)
    monkeypatch.setattr(package_runtime, "_tools_root", lambda: tmp_path)
    try:
        assert package_runtime.main([]) == 1
        assert (old / "renderdoc.dll").read_bytes() == b"old"
        assert (old / "manifest.runtime.json").read_text(encoding="utf-8") == '{}'
    finally:
        kernel.CloseHandle(handle)
    assert not list(tmp_path.glob(".runtime-stage-*"))


def test_explicit_output_root_leaves_every_existing_source_file_unchanged(tmp_path, monkeypatch):
    inputs = native_inputs(tmp_path)
    old = tmp_path / "binaries/windows/x64"
    _write(old / "renderdoc.dll", b"current live native")
    _write(old / "pymodules/old.pyd", b"current live binding")
    _write(old / "python/Lib/retained.py", b"current Python")
    _write(old / "adb/adb.exe", b"current host tool")
    _write(old / "manifest.runtime.json", '{"current":true}')
    before = {path.relative_to(tmp_path).as_posix(): path.read_bytes()
              for path in tmp_path.rglob("*") if path.is_file()}
    monkeypatch.setattr(package_runtime, "_tools_root", lambda: tmp_path)
    assert package_runtime.main(inputs + ["--output-root", "intermediate/task/runtime"]) == 0
    for name, contents in before.items():
        assert (tmp_path / name).read_bytes() == contents
    target = tmp_path / "intermediate/task/runtime"
    assert package_runtime.runtime_identity.native_manifest_status(target)["status"] == "verified"
    assert (target / "binaries/windows/x64/renderdoc.dll").read_bytes() == b"renderdoc"
    assert not (target / "binaries/windows/x64/pymodules/old.pyd").exists()
    assert (target / "binaries/windows/x64/python/Lib/retained.py").read_bytes() == b"current Python"
    assert (target / "binaries/windows/x64/adb/adb.exe").read_bytes() == b"current host tool"
    import pytest
    with pytest.raises(FileExistsError, match="overwrite"):
        package_runtime.main(inputs + ["--output-root", "intermediate/task/runtime"])
    assert not list(target.parent.glob(".runtime-stage-*"))


def test_explicit_output_root_rejects_escape_source_and_input_overlap(tmp_path, monkeypatch):
    import pytest
    inputs = native_inputs(tmp_path)
    monkeypatch.setattr(package_runtime, "_tools_root", lambda: tmp_path)
    for destination in (".", "../outside", "binaries/new"):
        with pytest.raises(ValueError, match="task directory|escapes"):
            package_runtime.main(inputs + ["--output-root", destination])
    with pytest.raises(ValueError, match="overlaps"):
        package_runtime.main(inputs + ["--source", "intermediate/input", "--output-root", "intermediate/input/output"])
    assert not (tmp_path / "binaries").exists()
    assert not list(tmp_path.rglob(".runtime-stage-*"))


def test_explicit_output_root_rejects_reparse_parent(tmp_path, monkeypatch):
    import os
    import subprocess
    import pytest
    inputs = native_inputs(tmp_path)
    target = tmp_path / "target"
    target.mkdir()
    parent = tmp_path / "intermediate"
    parent.mkdir()
    link = parent / "linked"
    if os.name == "nt":
        subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)],
                       capture_output=True, check=True)
    else:
        link.symlink_to(target, target_is_directory=True)
    monkeypatch.setattr(package_runtime, "_tools_root", lambda: tmp_path)
    try:
        with pytest.raises(ValueError, match="link"):
            package_runtime.main(inputs + ["--output-root", "intermediate/linked/runtime"])
        assert not list(target.iterdir())
    finally:
        if os.name == "nt":
            link.rmdir()
        else:
            link.unlink()
