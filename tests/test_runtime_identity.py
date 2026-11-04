from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import struct
import sys
import zipfile

import pytest

from rdc_tool import runtime_identity as identity


def make_elf(build_id: bytes = b"runtime-build", *, bits: int = 64) -> bytes:
    note = struct.pack("<III", 4, len(build_id), 3) + b"GNU\0" + build_id
    note += b"\0" * (-len(note) % 4)
    start = 120 if bits == 64 else 84
    data = bytearray(start + len(note))
    data[:7] = b"\x7fELF" + bytes([2 if bits == 64 else 1, 1, 1])
    if bits == 64:
        struct.pack_into("<Q", data, 32, 64)
        struct.pack_into("<HH", data, 54, 56, 1)
        struct.pack_into("<I", data, 64, 4)
        struct.pack_into("<Q", data, 72, start)
        struct.pack_into("<Q", data, 96, len(note))
    else:
        struct.pack_into("<I", data, 28, 52)
        struct.pack_into("<HH", data, 42, 32, 1)
        struct.pack_into("<II", data, 52, 4, start)
        struct.pack_into("<I", data, 68, len(note))
    data[start:] = note
    return bytes(data)


def make_apk(path: Path, abi: str, *, certificate: bytes = b"fixture-certificate") -> Path:
    strings = ["manifest", "package", f"org.renderdoc.renderdoccmd.{abi}", "versionCode", "versionName", "a" * 40]
    values, offsets = b"", []
    for string in strings:
        raw = string.encode()
        offsets.append(len(values))
        values += bytes([len(string), len(raw)]) + raw + b"\0"
    pool_start = 28 + len(strings) * 4
    pool = struct.pack("<HHIIIIII", 1, 28, pool_start + len(values), len(strings), 0, 0x100, pool_start, 0)
    pool += struct.pack("<" + "I" * len(offsets), *offsets) + values
    attrs = b""
    for name, raw, kind, value in [(1, 2, 3, 2), (3, 0xFFFFFFFF, 0x10, 145), (4, 5, 3, 5)]:
        attrs += struct.pack("<IIIHBBI", 0xFFFFFFFF, name, raw, 8, 0, kind, value)
    node = struct.pack("<HHIII", 0x102, 16, 36 + len(attrs), 0, 0xFFFFFFFF)
    node += struct.pack("<IIHHHHHH", 0xFFFFFFFF, 0, 20, 20, 3, 0, 0, 0) + attrs
    manifest = struct.pack("<HHI", 3, 8, 8 + len(pool) + len(node)) + pool + node
    memory = io.BytesIO()
    arch = "arm64-v8a" if abi == "arm64" else "armeabi-v7a"
    with zipfile.ZipFile(memory, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("AndroidManifest.xml", manifest)
        for library in ("libVkLayer_GLES_RenderDoc.so", "librenderdoccmd.so"):
            archive.writestr(f"lib/{arch}/{library}", make_elf(bits=64 if abi == "arm64" else 32))
    data = bytearray(memory.getvalue())
    end = data.rfind(b"PK\x05\x06")
    central = struct.unpack_from("<I", data, end + 16)[0]
    def length(value):
        return struct.pack("<I", len(value)) + value
    signed = length(b"") + length(length(certificate)) + length(b"")
    value = length(length(length(signed) + length(b"") + length(b"")))
    pair = struct.pack("<QI", len(value) + 4, 0x7109871A) + value
    block = struct.pack("<Q", len(pair) + 24) + pair + struct.pack("<Q", len(pair) + 24) + b"APK Sig Block 42"
    data[central:central] = block
    struct.pack_into("<I", data, end + len(block) + 16, central + len(block))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def native_inputs(root: Path) -> list[str]:
    source = root / "staging"
    (source / "pymodules").mkdir(parents=True, exist_ok=True)
    for path, value in ((source / "renderdoc.dll", b"renderdoc"), (source / "pymodules/renderdoc.pyd", b"renderdoc-pyd")):
        if not path.exists():
            path.write_bytes(value)
    apks = {abi: make_apk(source / f"{abi}.apk", abi) for abi in ("arm32", "arm64")}
    targets = {"windows-x64": {"renderdoc_dll": source / "renderdoc.dll", "renderdoc_pyd": source / "pymodules/renderdoc.pyd"},
               **{f"android-{abi}": {"helper_apk": path} for abi, path in apks.items()}}
    builds = [{"target": target, "configuration": "fixture", "toolchain": {"compiler": "fixture"},
               "inputs_sha256": "c" * 64,
               "outputs": [{"role": role, "path": str(path.relative_to(root)), **identity.file_identity(path)} for role, path in files.items()]}
              for target, files in targets.items()]
    runtime_files = [*source.glob("*.dll"), *source.glob("*.json"),
                     *sorted((source / "pymodules").glob("*.pyd")),
                     *sorted((source / "pymodules").glob("*.dll")),
                     *sorted((source / "pymodules").glob("*.json"))]
    builds[0]["runtime_files"] = [{"path": path.relative_to(source).as_posix(), **identity.file_identity(path)}
                                   for path in runtime_files]
    receipt = {"source": {"base_revision": "a" * 40, "upstream_revision": "b" * 40, "tree_sha256": "c" * 64}, "builds": builds}
    (root / "receipt.json").write_text(json.dumps(receipt), encoding="utf-8")
    return ["--source", "staging", "--arm32-apk", str(apks["arm32"]), "--arm64-apk", str(apks["arm64"]), "--build-receipt", "receipt.json"]


@pytest.mark.parametrize("bits", [32, 64])
def test_elf_build_id_reads_actual_note_and_rejects_truncation(bits):
    data = make_elf(b"actual-build", bits=bits)
    assert identity._elf_build_id(data) == b"actual-build".hex()
    with pytest.raises(ValueError, match="truncated"):
        identity._elf_build_id(data[:-8])


def test_apk_identity_retains_native_hashes_and_actual_signer(tmp_path):
    apk = make_apk(tmp_path / "helper.apk", "arm64")
    result = identity.apk_native_identity(apk, "arm64")
    assert result["version_code"] == 145
    assert result["apk_sha256"] == hashlib.sha256(apk.read_bytes()).hexdigest()
    assert result["signer_certificate_sha256"] == [hashlib.sha256(b"fixture-certificate").hexdigest()]
    assert result["signature_validation"] == "not_performed"
    assert len(result["libraries"]) == 2
    for library in result["libraries"]:
        assert library["sha256"] == hashlib.sha256(make_elf()).hexdigest()
        assert library["build_id"] == b"runtime-build".hex()
    with pytest.raises(ValueError, match="package differs"):
        identity.apk_native_identity(apk, "arm32")


def test_missing_native_receipt_is_unknown_not_verified(tmp_path):
    manifest = tmp_path / "binaries/windows/x64/manifest.runtime.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text("{}", encoding="utf-8")
    assert identity.native_manifest_status(tmp_path) == {"status": "unavailable", "reason": "native_build_receipt_missing"}


def native_manifest_fixture(root: Path, layer_bytes: bytes | None) -> Path:
    native_inputs(root)
    receipt = json.loads((root / "receipt.json").read_text(encoding="utf-8"))
    for build in receipt["builds"]:
        for output in build["outputs"]:
            source = root / output["path"]
            output["path"] = identity.NATIVE_OUTPUTS[build["target"]][output["role"]]
            target = root / output["path"]
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source.read_bytes())
            if build["target"].startswith("android-"):
                output["apk"] = identity.apk_native_identity(target, build["target"].removeprefix("android-"))
    directory = root / "binaries/windows/x64"
    if layer_bytes is not None:
        (directory / "renderdoc.json").write_bytes(layer_bytes)
    receipt["builds"][0]["runtime_files"] = [
        {"path": "binaries/windows/x64/" + name, **identity.file_identity(path)}
        for name, path in identity.windows_native_files(directory).items()
    ]
    manifest = directory / "manifest.runtime.json"
    manifest.write_text(json.dumps({"native_build": receipt}), encoding="utf-8")
    return manifest


@pytest.mark.parametrize("layer_bytes", [
    b'{"layer":{"implementation_version":"48\r"}}',
    b'{"layer":', b'', b'\xff', b'[]', b'null', b'"layer"',
    b'{"layer":NaN}', b'{"layer":Infinity}',
])
def test_hash_matched_layer_manifest_with_invalid_json_is_rejected(tmp_path, layer_bytes):
    manifest_path = native_manifest_fixture(tmp_path, layer_bytes)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entries = manifest["native_build"]["builds"][0]["runtime_files"]
    entry = next(item for item in entries if item["path"].endswith("/renderdoc.json"))
    assert entry["sha256"] == hashlib.sha256(layer_bytes).hexdigest()
    assert entry["size"] == len(layer_bytes)
    status = identity.native_manifest_status(tmp_path)
    assert status["status"] == "invalid"
    assert "Vulkan layer manifest" in status["reason"]


@pytest.mark.parametrize("layer_bytes", [
    None, b'{}',
    b'\xef\xbb\xbf{\r\n  "layer": {"implementation_version": "48"}\r\n}\r\n',
    b'{"layer":{"implementation_version":"48\\r"}}',
])
def test_optional_layer_manifest_accepts_json_object_without_rewriting_bytes(tmp_path, layer_bytes):
    native_manifest_fixture(tmp_path, layer_bytes)
    assert identity.native_manifest_status(tmp_path)["status"] == "verified"
    layer_path = tmp_path / "binaries/windows/x64/renderdoc.json"
    if layer_bytes is None:
        assert not layer_path.exists()
    else:
        assert layer_path.read_bytes() == layer_bytes


def test_loader_diagnostic_does_not_import_renderdoc(tmp_path, monkeypatch):
    python = tmp_path / "python.exe"
    python.write_bytes(b"python")
    monkeypatch.setattr(sys, "executable", str(python))
    monkeypatch.delitem(sys.modules, "renderdoc", raising=False)
    monkeypatch.setattr(identity, "_loaded_renderdoc_dll", lambda: None)
    result = identity.loaded_runtime_identity(tmp_path, tmp_path / "pymodules")
    assert result["status"] == "not_loaded"
    assert "renderdoc" not in sys.modules
    assert result["python"]["sha256"] == hashlib.sha256(b"python").hexdigest()


@pytest.mark.parametrize("foreign", [False, True])
def test_native_dll_is_observed_even_without_a_python_binding(tmp_path, monkeypatch, foreign):
    configured = tmp_path / "configured"
    actual = tmp_path / "foreign" if foreign else configured
    actual.mkdir()
    dll = actual / "renderdoc.dll"
    dll.write_bytes(b"loaded native library")
    monkeypatch.delitem(sys.modules, "renderdoc", raising=False)
    monkeypatch.setattr(identity, "_loaded_renderdoc_dll", lambda: dll.resolve())
    result = identity.loaded_runtime_identity(configured, configured / "pymodules")
    assert result["status"] == ("mismatch" if foreign else "partial")
    assert result["configured_paths_match"] is (not foreign)
    assert result["native"]["path"] == str(dll.resolve())
    assert result["binding"] == {"status": "not_loaded"}
    assert "renderdoc" not in sys.modules
