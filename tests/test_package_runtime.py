from __future__ import annotations

import hashlib
import io
import json
import os
import stat
import tarfile
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import package_runtime
from rdc_tool import __version__, python_runtime
from rdc_tool.runtime_paths import HOST_LAYOUTS
from scripts.distribution_metadata import write_distribution_metadata
from test_runtime_identity import WINDOWS_TARGETS, native_inputs

ROOT = Path(__file__).resolve().parents[1]
WINDOWS_ARCHIVE = {
    "python.exe": b"python", "pythonw.exe": b"pythonw", "python3.dll": b"abi3", "python314.dll": b"runtime",
    "vcruntime140.dll": b"crt", "vcruntime140_1.dll": b"crt1", "LICENSE.txt": b"psf",
    "DLLs/_socket.pyd": b"socket", "Lib/os.py": b"# os", "Lib/site.py": b"# site", "Lib/encodings/__init__.py": b"# enc",
    "Lib/site-packages/pip/__init__.py": b"# pip stays in the archive", "Lib/test/test_os.py": b"# test",
    "Lib/__pycache__/os.cpython-314.pyc": b"cache", "Lib/README.md": b"docs",
}
LINUX_ARCHIVE = {
    "bin/python3.14": b"python", "bin/pip3": b"#!pip", "lib/libpython3.14.so.1.0": b"embedding library",
    "lib/python3.14/os.py": b"# os", "lib/python3.14/site.py": b"# site", "lib/python3.14/encodings/__init__.py": b"# enc",
    "lib/python3.14/LICENSE.txt": b"psf", "lib/python3.14/lib-dynload/_json.cpython-314-x86_64-linux-gnu.so": b"json",
    "lib/python3.14/lib-dynload/_tkinter.cpython-314-x86_64-linux-gnu.so": b"needs tcl",
    "lib/python3.14/config-3.14-x86_64-linux-gnu/Makefile": b"build only",
    "lib/python3.14/site-packages/pip/__init__.py": b"# pip", "include/python3.14/Python.h": b"header",
}


@pytest.fixture(autouse=True)
def windows_host(pin_host):
    # Native fixtures are windows-x64 packages; Linux-specific tests switch the host explicitly.
    pin_host("windows-x64")


def _write(path: Path, content: bytes | str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf-8")


def _pin_archive(tmp_path: Path, monkeypatch, target: str, *, version: str = "3.14.9") -> Path:
    """A fake pinned interpreter archive plus a fake locked installer."""
    pins = json.loads(package_runtime.PYTHON_PINS.read_text(encoding="utf-8"))
    pin = pins[target]
    if target == "windows-x64":
        archive = tmp_path / "inputs/python.nupkg"
        archive.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(archive, "w") as bundle:
            for name, data in WINDOWS_ARCHIVE.items():
                bundle.writestr(f"{pin['archive_root']}/{name}", data)
    else:
        archive = tmp_path / "inputs/python.tar.gz"
        archive.parent.mkdir(parents=True, exist_ok=True)
        with tarfile.open(archive, "w:gz") as bundle:
            for name, data in LINUX_ARCHIVE.items():
                info = tarfile.TarInfo(f"{pin['archive_root']}/{name}")
                info.size, info.mode = len(data), 0o755 if name.startswith("bin/") else 0o644
                bundle.addfile(info, io.BytesIO(data))
            alias = tarfile.TarInfo(f"{pin['archive_root']}/bin/python")
            alias.type, alias.linkname = tarfile.SYMTYPE, "python3.14"
            bundle.addfile(alias)
    pins[target] = {**pin, "python_version": version, "source_sha256": hashlib.sha256(archive.read_bytes()).hexdigest()}
    pin_file = tmp_path / "inputs/python-runtimes.json"
    pin_file.write_text(json.dumps(pins), encoding="utf-8")
    monkeypatch.setattr(package_runtime, "PYTHON_PINS", pin_file)
    monkeypatch.setattr(package_runtime, "_interpreter_version", lambda python: version if python.is_file() else "missing")

    def install(python, site_packages, lock):
        assert python.is_file() and lock == package_runtime.DEPENDENCY_LOCK
        _write(site_packages / "numpy/__init__.py", "# locked wheel")
        _write(site_packages / "numpy/_core/include/numpy/ndarraytypes.h", "/* shipped by the wheel */")
        _write(site_packages / "numpy-2.5.5.dist-info/METADATA", "Name: numpy\n")
    monkeypatch.setattr(package_runtime, "_install_dependencies", install)
    return archive


def test_windows_interpreter_is_assembled_from_its_pinned_archive(tmp_path, monkeypatch):
    archive = _pin_archive(tmp_path, monkeypatch, "windows-x64")
    _write(tmp_path / "pyproject.toml", (ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    monkeypatch.setattr(package_runtime, "tools_root", lambda: tmp_path)
    assert package_runtime.main(["--python-archive", str(archive)]) == 0
    out_root = tmp_path / "binaries/windows/x64"
    python = out_root / "python"
    assert (python / "python.exe").read_bytes() == b"python"
    assert (python / "DLLs/_socket.pyd").is_file()
    assert not (python / "Lib/test").exists() and not (python / "Lib/README.md").exists()
    assert not (python / "Lib/site-packages/pip").exists()
    assert (python / "Lib/site-packages/numpy/__init__.py").is_file()
    assert (python / "python314._pth").read_text(encoding="utf-8").splitlines() == [
        ".", "DLLs", "Lib", "Lib/site-packages", "../../../..", "import site"]
    metadata = python / f"Lib/site-packages/rdc_tool-{__version__}.dist-info"
    assert "Name: rdc-tool" in (metadata / "METADATA").read_text(encoding="utf-8")
    assert "rdc-tool = rdc_tool.cli:main" in (metadata / "entry_points.txt").read_text(encoding="utf-8")
    assert b"\r" not in (metadata / "RECORD").read_bytes()
    manifest = json.loads((out_root / "manifest.runtime.json").read_text(encoding="utf-8"))
    assert manifest["bundled_python"]["python_version"] == "3.14.9"
    assert manifest["bundled_python"]["dependency_lock_sha256"] == hashlib.sha256(package_runtime.DEPENDENCY_LOCK.read_bytes()).hexdigest()
    listed = {item["path"] for item in manifest["files"]}
    assert {"python/python.exe", "python/Lib/site-packages/numpy/_core/include/numpy/ndarraytypes.h"} <= listed
    monkeypatch.setattr(python_runtime, "host_layout", lambda: HOST_LAYOUTS["windows-x64"])
    monkeypatch.setattr(python_runtime, "binaries_root", lambda: out_root)
    ok, failures, _ = python_runtime.validate_bundled_python_layout()
    assert ok, failures


def test_linux_interpreter_keeps_regular_files_and_points_site_at_the_installation(tmp_path, monkeypatch, pin_host):
    pin_host("linux-x64")
    archive = _pin_archive(tmp_path, monkeypatch, "linux-x64")
    _write(tmp_path / "pyproject.toml", (ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    monkeypatch.setattr(package_runtime, "tools_root", lambda: tmp_path)
    assert package_runtime.main(["--host", "linux-x64", "--python-archive", str(archive)]) == 0
    out_root = tmp_path / "binaries/linux/x64"
    python = out_root / "python"
    assert sorted(path.name for path in (python / "bin").iterdir()) == ["python3.14"]
    if os.name != "nt":
        assert (python / "bin/python3.14").stat().st_mode & stat.S_IXUSR
    stdlib = python / "lib/python3.14"
    assert (stdlib / "lib-dynload/_json.cpython-314-x86_64-linux-gnu.so").is_file()
    assert not (stdlib / "lib-dynload/_tkinter.cpython-314-x86_64-linux-gnu.so").exists()
    assert not (stdlib / "config-3.14-x86_64-linux-gnu").exists()
    assert not (python / "lib/libpython3.14.so.1.0").exists() and not (python / "include").exists()
    assert (stdlib / "site-packages/rdc_tool_root.pth").read_text(encoding="utf-8") == "../../../../../../..\n"
    monkeypatch.setattr(python_runtime, "host_layout", lambda: HOST_LAYOUTS["linux-x64"])
    monkeypatch.setattr(python_runtime, "binaries_root", lambda: out_root)
    ok, failures, _ = python_runtime.validate_bundled_python_layout()
    assert ok, failures
    pth_dir = stdlib / "site-packages"
    assert (pth_dir / "../../../../../../..").resolve() == tmp_path.resolve()


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

def test_runtime_regeneration_keeps_provenance_and_rejects_files_no_part_owns(tmp_path, monkeypatch):
    tools_root = tmp_path / "tools"
    out_root = tools_root / "binaries/windows/x64"
    metadata = {"adb": {"version": "fixture", "source_url": "https://example.test/source", "license": "fixture"}}
    host_files = package_runtime.bundled_host_files(HOST_LAYOUTS["windows-x64"])
    for relative in host_files:
        _write(out_root / relative, b"host-tool")
    _write(out_root / "unrelated/cache.bin", b"nobody owns this")
    _write(out_root / "manifest.runtime.json", json.dumps({"bundled_tools": metadata}))
    monkeypatch.setattr(package_runtime, "tools_root", lambda: tools_root)
    assert package_runtime.main([]) == 1
    (out_root / "unrelated/cache.bin").unlink()
    assert package_runtime.main([]) == 0
    manifest = json.loads((out_root / "manifest.runtime.json").read_text(encoding="utf-8"))
    assert manifest["bundled_tools"] == metadata
    assert {entry["path"] for entry in manifest["files"]} == set(host_files)
    assert manifest["file_count"] == len(host_files)


def test_native_replacement_requires_the_complete_build_set(tmp_path, monkeypatch):
    monkeypatch.setattr(package_runtime, "tools_root", lambda: tmp_path)
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
    monkeypatch.setattr(package_runtime, "tools_root", lambda: tmp_path)
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
        if path.name == "binaries" and path.parent.parent.name.startswith(".runtime-stage-"):
            raise PermissionError("publish rejected")
        return original_rename(path, target)
    monkeypatch.setattr(package_runtime, "tools_root", lambda: tmp_path)
    monkeypatch.setattr(Path, "rename", fail_publish)
    assert package_runtime.main(inputs) == 1
    assert (old / "renderdoc.dll").read_bytes() == b"old"
    assert (old / "manifest.runtime.json").read_text(encoding="utf-8") == '{}'
    assert not (tmp_path / "binaries/android").exists()
    assert not list(tmp_path.glob(".runtime-stage-*"))


def test_changed_build_input_is_rejected_before_publish(tmp_path, monkeypatch):
    inputs = native_inputs(tmp_path)
    (tmp_path / "staging/renderdoc.dll").write_bytes(b"changed after build")
    monkeypatch.setattr(package_runtime, "tools_root", lambda: tmp_path)
    assert package_runtime.main(inputs) == 1
    assert not (tmp_path / "binaries").exists()
    assert not list(tmp_path.glob(".runtime-stage-*"))


@pytest.mark.parametrize("problem", ["archive_bytes", "reported_version"])
def test_unpinned_interpreter_is_rejected_and_existing_python_preserved(tmp_path, monkeypatch, problem):
    old = tmp_path / "binaries/windows/x64"
    _write(old / "python/python.exe", b"old python")
    _write(old / "manifest.runtime.json", '{}')
    archive = _pin_archive(tmp_path, monkeypatch, "windows-x64")
    if problem == "archive_bytes":
        with zipfile.ZipFile(archive, "a") as bundle:
            bundle.writestr("tools/extra.dll", b"not pinned")
    else:
        monkeypatch.setattr(package_runtime, "_interpreter_version", lambda python: "3.14.0")
    monkeypatch.setattr(package_runtime, "tools_root", lambda: tmp_path)
    assert package_runtime.main(["--python-archive", str(archive)]) == 1
    assert (old / "python/python.exe").read_bytes() == b"old python"
    assert (old / "manifest.runtime.json").read_text(encoding="utf-8") == '{}'
    assert not list(tmp_path.glob(".runtime-stage-*"))


def test_same_source_receipt_is_required_for_every_target(tmp_path, monkeypatch):
    inputs = native_inputs(tmp_path)
    receipt_path = tmp_path / "receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["builds"][1]["inputs_sha256"] = "d" * 64
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    monkeypatch.setattr(package_runtime, "tools_root", lambda: tmp_path)
    assert package_runtime.main(inputs) == 1
    assert not (tmp_path / "binaries").exists()


def test_paired_build_is_rechecked_when_manifest_is_regenerated(tmp_path, monkeypatch):
    inputs = native_inputs(tmp_path)
    monkeypatch.setattr(package_runtime, "tools_root", lambda: tmp_path)
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
    monkeypatch.setattr(package_runtime, "tools_root", lambda: tmp_path)
    assert package_runtime.main(inputs) == 0
    assert not (old / "stale.dll").exists()
    assert not (old / "old.json").exists()
    assert not (old / "pymodules/stale.pyd").exists()
    assert (old / "d3dcompiler_47.dll").read_bytes() == b"matched support library"
    assert (old / "pymodules/d3dcompiler_47.dll").read_bytes() == b"matched binding support library"
    assert (old / "python/Lib/retained.py").read_bytes() == b"python unchanged"
    assert (old / "adb/adb.exe").read_bytes() == b"host tool unchanged"
    assert package_runtime.runtime_identity.native_manifest_status(tmp_path, required=WINDOWS_TARGETS)["status"] == "verified"


def test_native_source_support_files_require_complete_unchanged_receipt(tmp_path, monkeypatch):
    support = tmp_path / "staging/dbghelp.dll"
    _write(support, b"support library")
    inputs = native_inputs(tmp_path)
    monkeypatch.setattr(package_runtime, "tools_root", lambda: tmp_path)
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
    monkeypatch.setattr(package_runtime, "tools_root", lambda: tmp_path)
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
    monkeypatch.setattr(package_runtime, "tools_root", lambda: tmp_path)
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
    monkeypatch.setattr(package_runtime, "tools_root", lambda: tmp_path)
    assert package_runtime.main(inputs + ["--output-root", "intermediate/task/runtime"]) == 0
    for name, contents in before.items():
        assert (tmp_path / name).read_bytes() == contents
    target = tmp_path / "intermediate/task/runtime"
    assert package_runtime.runtime_identity.native_manifest_status(target, required=WINDOWS_TARGETS)["status"] == "verified"
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
    monkeypatch.setattr(package_runtime, "tools_root", lambda: tmp_path)
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
    monkeypatch.setattr(package_runtime, "tools_root", lambda: tmp_path)
    try:
        with pytest.raises(ValueError, match="link"):
            package_runtime.main(inputs + ["--output-root", "intermediate/linked/runtime"])
        assert not list(target.iterdir())
    finally:
        if os.name == "nt":
            link.rmdir()
        else:
            link.unlink()


def test_assembly_runs_only_for_this_host(tmp_path, monkeypatch):
    monkeypatch.setattr(package_runtime, "tools_root", lambda: tmp_path)
    assert package_runtime.main(["--host", "linux-x64"]) == 1
    assert not (tmp_path / "binaries").exists()


def test_locked_install_uses_only_hashed_wheels_and_drops_console_scripts(tmp_path, monkeypatch):
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        _write(tmp_path / "site/bin/f2py", "#!/tmp/build-python")
        return SimpleNamespace(returncode=0, stdout="", stderr="")
    monkeypatch.setattr(package_runtime.process, "run_tool", run)
    package_runtime._install_dependencies(tmp_path / "python", tmp_path / "site", tmp_path / "deps.lock")
    command = calls[0]
    assert command[:5] == [str(tmp_path / "python"), "-I", "-m", "pip", "install"]
    for flag in ("--no-deps", "--require-hashes", "--only-binary=:all:", "--no-compile"):
        assert flag in command
    assert command[command.index("--target") + 1] == str(tmp_path / "site")
    assert not (tmp_path / "site/bin").exists()
    monkeypatch.setattr(package_runtime.process, "run_tool", lambda command, **kwargs: SimpleNamespace(returncode=1, stdout="", stderr="no wheel"))
    with pytest.raises(RuntimeError, match="no wheel"):
        package_runtime._install_dependencies(tmp_path / "python", tmp_path / "site", tmp_path / "deps.lock")


def _host_tool_inputs(root: Path) -> Path:
    layout = HOST_LAYOUTS["windows-x64"]
    source = root / "inputs/host-tools"
    for relative in package_runtime.bundled_host_files(layout):
        _write(source / relative, f"new {relative}")
    record = {"version": "1", "source_url": "https://example.test/tool.zip", "source_sha256": "f" * 64, "license": "fixture"}
    _write(source / "bundled_tools.json", json.dumps({
        "adb": {**record, "license_path": "adb/NOTICE.txt"},
        "spirv_as": {**record, "license_path": "spirv-tools/LICENSE.txt", "build": "fixture"},
        "spirv_dis": {**record, "license_path": "spirv-tools/LICENSE.txt", "build": "fixture"},
    }))
    return source


def _pinned_dxc_fixture(root: Path, monkeypatch) -> Path:
    archive = root / "dxc.zip"
    with zipfile.ZipFile(archive, "w") as out:
        out.writestr("bin/x64/dxc.exe", b"official dxc fixture")
        out.writestr("bin/x64/dxcompiler.dll", b"official library fixture")
        out.writestr("LICENSE-LLVM.txt", b"fixture license")
    monkeypatch.setattr(package_runtime, "DXC_SHA256", hashlib.sha256(archive.read_bytes()).hexdigest())
    return archive


def test_host_tools_input_replaces_tool_files_and_records_provenance(tmp_path, monkeypatch):
    source = _host_tool_inputs(tmp_path)
    dxc_archive = _pinned_dxc_fixture(tmp_path, monkeypatch)
    old = tmp_path / "binaries/windows/x64"
    _write(old / "adb/adb.exe", b"old adb")
    _write(old / "adb/old-helper.dll", b"stale tool file")
    monkeypatch.setattr(package_runtime, "tools_root", lambda: tmp_path)
    assert package_runtime.main(["--host-tools", str(source), "--dxc-archive", str(dxc_archive)]) == 0
    assert (old / "adb/adb.exe").read_text(encoding="utf-8") == "new adb/adb.exe"
    assert not (old / "adb/old-helper.dll").exists()
    tools = json.loads((old / "manifest.runtime.json").read_text(encoding="utf-8"))["bundled_tools"]
    assert tools["adb"]["path"] == "adb/adb.exe"
    assert tools["adb"]["license_path"] == "binaries/windows/x64/adb/NOTICE.txt"
    assert tools["spirv_dis"]["build"] == "fixture"
    assert tools["dxc"]["source_sha256"] == package_runtime.DXC_SHA256
    assert (old / "dxc/dxcompiler.dll").read_bytes() == b"official library fixture"


def test_host_tools_reject_unpinned_dxc_archive(tmp_path, monkeypatch):
    source = _host_tool_inputs(tmp_path)
    archive = _pinned_dxc_fixture(tmp_path, monkeypatch)
    archive.write_bytes(archive.read_bytes() + b"changed")
    monkeypatch.setattr(package_runtime, "tools_root", lambda: tmp_path)
    assert package_runtime.main(["--host-tools", str(source), "--dxc-archive", str(archive)]) == 1
    assert not (tmp_path / "binaries").exists()


@pytest.mark.parametrize("damage", ["provenance", "license", "file"])
def test_incomplete_host_tool_input_is_rejected(tmp_path, monkeypatch, damage):
    source = _host_tool_inputs(tmp_path)
    dxc_archive = _pinned_dxc_fixture(tmp_path, monkeypatch)
    provenance = json.loads((source / "bundled_tools.json").read_text(encoding="utf-8"))
    if damage == "provenance":
        provenance["adb"]["source_sha256"] = ""
    elif damage == "license":
        provenance["adb"]["license_path"] = "adb/adb.exe"
    else:
        (source / "spirv-tools/spirv-dis.exe").unlink()
    (source / "bundled_tools.json").write_text(json.dumps(provenance), encoding="utf-8")
    monkeypatch.setattr(package_runtime, "tools_root", lambda: tmp_path)
    assert package_runtime.main(["--host-tools", str(source), "--dxc-archive", str(dxc_archive)]) == 1
    assert not (tmp_path / "binaries").exists()


def test_receipt_without_android_builds_takes_no_apks(tmp_path, monkeypatch):
    inputs = native_inputs(tmp_path)
    receipt_path = tmp_path / "receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["builds"] = [build for build in receipt["builds"] if build["target"] == "windows-x64"]
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    monkeypatch.setattr(package_runtime, "tools_root", lambda: tmp_path)
    assert package_runtime.main(inputs) == 1
    host_only = [value for index, value in enumerate(inputs)
                 if value not in ("--arm32-apk", "--arm64-apk") and inputs[index - 1] not in ("--arm32-apk", "--arm64-apk")]
    assert package_runtime.main(host_only) == 0
    status = package_runtime.runtime_identity.native_manifest_status(tmp_path, required=("windows-x64",))
    assert status["status"] == "verified" and set(status["targets"]) == {"windows-x64"}


def test_unknown_receipt_source_field_is_rejected(tmp_path, monkeypatch):
    inputs = native_inputs(tmp_path)
    receipt_path = tmp_path / "receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["source"]["branch"] = "v1.x"
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    monkeypatch.setattr(package_runtime, "tools_root", lambda: tmp_path)
    assert package_runtime.main(inputs) == 1
    assert not (tmp_path / "binaries").exists()
