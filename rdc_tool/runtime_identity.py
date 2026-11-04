"""File, APK and loader evidence for a paired native runtime.

The build receipt describes recorded build inputs. File hashes and loader paths
are separate observations; an embedded commit alone never certifies a source tree.
"""
from __future__ import annotations

import ctypes
import hashlib
import json
import os
from pathlib import Path
import struct
import sys
from typing import Any
import zipfile

from rdc_tool.android_apk_identity import read_apk_identity


NATIVE_OUTPUTS = {
    "windows-x64": {
        "renderdoc_dll": "binaries/windows/x64/renderdoc.dll",
        "renderdoc_pyd": "binaries/windows/x64/pymodules/renderdoc.pyd",
    },
    "android-arm32": {"helper_apk": "binaries/android/arm32/org.renderdoc.renderdoccmd.arm32.apk"},
    "android-arm64": {"helper_apk": "binaries/android/arm64/org.renderdoc.renderdoccmd.arm64.apk"},
}
_OBSERVED_FILES: dict[tuple[str, int, int], dict[str, Any]] = {}


def file_identity(path: Path) -> dict[str, Any]:
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    return {"size": path.stat().st_size, "sha256": digest}


def _observed_file(path: Path) -> dict[str, Any]:
    stat = path.stat()
    key = (str(path.resolve()), stat.st_size, stat.st_mtime_ns)
    if key not in _OBSERVED_FILES:
        _OBSERVED_FILES[key] = file_identity(path)
    return dict(_OBSERVED_FILES[key])


def windows_native_files(directory: Path) -> dict[str, Path]:
    """The Windows native surface, separate from Python and host tools."""
    result = {path.name: path for path in directory.iterdir()
              if path.is_file() and path.suffix.lower() in {".dll", ".pyd", ".json"}
              and path.name != "manifest.runtime.json"}
    modules = directory / "pymodules"
    if modules.is_dir():
        result.update({path.relative_to(directory).as_posix(): path for path in modules.rglob("*")
                       if path.is_file() and "__pycache__" not in path.parts and path.suffix.lower() != ".pyc"})
    return result


def _elf_build_id(data: bytes) -> str:
    if len(data) < 52 or data[:4] != b"\x7fELF" or data[4] not in (1, 2) or data[5] not in (1, 2):
        raise ValueError("native APK library is not a supported ELF")
    order = "<" if data[5] == 1 else ">"
    if data[4] == 2:
        offset = struct.unpack_from(order + "Q", data, 32)[0]
        size, count = struct.unpack_from(order + "HH", data, 54)
        minimum = 56
    else:
        offset = struct.unpack_from(order + "I", data, 28)[0]
        size, count = struct.unpack_from(order + "HH", data, 42)
        minimum = 32
    if size < minimum or offset + size * count > len(data):
        raise ValueError("ELF program headers are truncated")
    for index in range(count):
        at = offset + size * index
        if struct.unpack_from(order + "I", data, at)[0] != 4:  # PT_NOTE
            continue
        if data[4] == 2:
            start = struct.unpack_from(order + "Q", data, at + 8)[0]
            length = struct.unpack_from(order + "Q", data, at + 32)[0]
        else:
            start = struct.unpack_from(order + "I", data, at + 4)[0]
            length = struct.unpack_from(order + "I", data, at + 16)[0]
        end = start + length
        if end > len(data):
            raise ValueError("ELF note is truncated")
        while start + 12 <= end:
            names, values, kind = struct.unpack_from(order + "III", data, start)
            name_at = start + 12
            value_at = name_at + ((names + 3) & ~3)
            next_at = value_at + ((values + 3) & ~3)
            if next_at > end:
                raise ValueError("ELF note value is truncated")
            if kind == 3 and data[name_at:name_at + names].rstrip(b"\0") == b"GNU" and values:
                return data[value_at:value_at + values].hex()
            start = next_at
    raise ValueError("native APK library has no GNU BuildID")


def _length_prefixed(data: bytes, at: int = 0) -> tuple[bytes, int]:
    if at + 4 > len(data):
        raise ValueError("APK signer length is truncated")
    size = struct.unpack_from("<I", data, at)[0]
    end = at + 4 + size
    if end > len(data):
        raise ValueError("APK signer value is truncated")
    return data[at + 4:end], end


def _apk_signer_certificates(data: bytes) -> list[str]:
    # Read the actual v2/v3 signer certificate DER, without a host SDK. This is
    # signer identity evidence, not a claim of cryptographic signature validation.
    eocd = data.rfind(b"PK\x05\x06", max(0, len(data) - 65557))
    if eocd < 0 or eocd + 22 > len(data):
        raise ValueError("APK ZIP end record is missing")
    central = struct.unpack_from("<I", data, eocd + 16)[0]
    if central < 24 or data[central - 16:central] != b"APK Sig Block 42":
        raise ValueError("APK v2/v3 signing block is missing")
    size = struct.unpack_from("<Q", data, central - 24)[0]
    start = central - size - 8
    if start < 0 or start + 8 > central or struct.unpack_from("<Q", data, start)[0] != size:
        raise ValueError("APK signing block size mismatch")
    certificates: set[str] = set()
    at = start + 8
    while at < central - 24:
        if at + 8 > central - 24:
            raise ValueError("APK signing entry is truncated")
        length = struct.unpack_from("<Q", data, at)[0]
        end = at + 8 + length
        if length < 4 or end > central - 24:
            raise ValueError("APK signing entry size is invalid")
        kind = struct.unpack_from("<I", data, at + 8)[0]
        if kind in (0x7109871A, 0xF05368C0, 0x1B93AD61):
            signers, _ = _length_prefixed(data[at + 12:end])
            signer_at = 0
            while signer_at < len(signers):
                signer, signer_at = _length_prefixed(signers, signer_at)
                signed, _ = _length_prefixed(signer)
                _, cert_at = _length_prefixed(signed)
                certs, _ = _length_prefixed(signed, cert_at)
                certificate, _ = _length_prefixed(certs)
                if not certificate:
                    raise ValueError("APK signer certificate is empty")
                certificates.add(hashlib.sha256(certificate).hexdigest())
        at = end
    if not certificates:
        raise ValueError("APK has no v2/v3 signer certificates")
    return sorted(certificates)


def apk_native_identity(path: Path, abi: str) -> dict[str, Any]:
    identity = read_apk_identity(str(path))
    expected = f"org.renderdoc.renderdoccmd.{abi}"
    if identity["package_name"] != expected:
        raise ValueError(f"APK package differs from target: {expected}")
    arch = "arm64-v8a" if abi == "arm64" else "armeabi-v7a"
    with zipfile.ZipFile(path) as archive:
        libraries = []
        for name in ("libVkLayer_GLES_RenderDoc.so", "librenderdoccmd.so"):
            member = f"lib/{arch}/{name}"
            data = archive.read(member)
            libraries.append({"path": member, "size": len(data),
                              "sha256": hashlib.sha256(data).hexdigest(), "build_id": _elf_build_id(data)})
    return {**identity, "signer_certificate_sha256": _apk_signer_certificates(path.read_bytes()),
            "signature_validation": "not_performed", "libraries": libraries}


def native_manifest_status(root: Path) -> dict[str, Any]:
    manifest_path = root / "binaries/windows/x64/manifest.runtime.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        receipt = manifest.get("native_build")
        if not receipt:
            return {"status": "unavailable", "reason": "native_build_receipt_missing"}
        builds = receipt["builds"]
        if {build["target"] for build in builds} != set(NATIVE_OUTPUTS) or len(builds) != 3:
            raise ValueError("native receipt requires exactly three build targets")
        source = receipt["source"]
        for key, length in (("base_revision", 40), ("upstream_revision", 40), ("tree_sha256", 64)):
            value = source[key]
            if not isinstance(value, str) or len(value) != length or any(c not in "0123456789abcdef" for c in value):
                raise ValueError(f"invalid native source {key}")
        apks = []
        for build in builds:
            target = build["target"]
            if not isinstance(build["configuration"], str) or not build["configuration"].strip() or not isinstance(build["toolchain"], dict) or not build["toolchain"]:
                raise ValueError(f"build configuration/toolchain missing for {target}")
            if build["inputs_sha256"] != source["tree_sha256"]:
                raise ValueError(f"source digest differs for {target}")
            outputs = build["outputs"]
            expected = NATIVE_OUTPUTS[target]
            if len(outputs) != len(expected) or {item["role"] for item in outputs} != set(expected):
                raise ValueError(f"native output roles differ for {target}")
            if target == "windows-x64":
                files = build["runtime_files"]
                actual = {"binaries/windows/x64/" + name: path
                          for name, path in windows_native_files(root / "binaries/windows/x64").items()}
                if len(files) != len(actual) or {item["path"] for item in files} != set(actual):
                    raise ValueError("Windows native runtime file set differs from its build receipt")
                indexed = {item["path"]: item for item in files}
                for name, path in actual.items():
                    item = indexed[name]
                    if file_identity(path) != {"size": item["size"], "sha256": item["sha256"]}:
                        raise ValueError(f"Windows native runtime bytes differ: {name}")
                    if name == "binaries/windows/x64/renderdoc.json":
                        def reject_constant(value: str) -> None:
                            raise ValueError(f"invalid JSON numeric constant: {value}")
                        try:
                            layer_manifest = json.loads(path.read_bytes().decode("utf-8-sig"),
                                                        parse_constant=reject_constant)
                        except (UnicodeError, ValueError) as exc:
                            raise ValueError(f"Windows Vulkan layer manifest JSON is invalid: {name}: {exc}") from exc
                        if not isinstance(layer_manifest, dict):
                            raise ValueError(f"Windows Vulkan layer manifest must be a JSON object: {name}")
            for item in outputs:
                if item["path"] != expected[item["role"]]:
                    raise ValueError(f"native output path differs for {target}")
                path = root / item["path"]
                if file_identity(path) != {"size": item["size"], "sha256": item["sha256"]}:
                    raise ValueError(f"native bytes differ: {item['path']}")
                if target.startswith("android-"):
                    if apk_native_identity(path, target.removeprefix("android-")) != item["apk"]:
                        raise ValueError(f"APK native identity differs: {item['path']}")
                    apks.append(item["apk"])
        if apks[0]["signer_certificate_sha256"] != apks[1]["signer_certificate_sha256"]:
            raise ValueError("Android ABI helpers were signed by different certificates")
        if (apks[0]["version_code"], apks[0]["version_name"]) != (apks[1]["version_code"], apks[1]["version_name"]):
            raise ValueError("Android ABI helpers have different source/version metadata")
        return {"status": "verified", "source": source,
                "receipt_sha256": hashlib.sha256(json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode()).hexdigest()}
    except (OSError, ValueError, KeyError, TypeError, IndexError, struct.error, zipfile.BadZipFile) as exc:
        return {"status": "invalid", "reason": str(exc)}


def _loaded_renderdoc_dll() -> Path | None:
    if os.name != "nt":
        raise OSError("native_loader_query_unsupported")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetModuleHandleW.argtypes = [ctypes.c_wchar_p]
    kernel.GetModuleHandleW.restype = ctypes.c_void_p
    kernel.GetModuleFileNameW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_uint]
    kernel.GetModuleFileNameW.restype = ctypes.c_uint
    handle = kernel.GetModuleHandleW("renderdoc.dll")
    if not handle:
        return None
    buffer = ctypes.create_unicode_buffer(32768)
    if not kernel.GetModuleFileNameW(handle, buffer, len(buffer)):
        raise OSError("loaded renderdoc.dll path is unavailable")
    return Path(buffer.value).resolve()


def loaded_runtime_identity(bin_dir: Path, pymod_dir: Path) -> dict[str, Any]:
    """Observe this process only; do not import RenderDoc or start a worker."""
    try:
        python = Path(sys.executable).resolve()
        result: dict[str, Any] = {"python": {"path": str(python), **_observed_file(python)}}
    except OSError as exc:
        return {"status": "unavailable", "reason": str(exc)}
    try:
        dll = _loaded_renderdoc_dll()
        module = sys.modules.get("renderdoc")
        if dll is not None:
            result["native"] = {"path": str(dll), "on_disk": _observed_file(dll)}
        if module is not None:
            pyd = Path(module.__file__).resolve()
            result["binding"] = {"path": str(pyd), "on_disk": _observed_file(pyd)}
            result["embedded_commit"] = str(module.GetCommitHash())
            result["version"] = str(module.GetVersionString())
        else:
            result["binding"] = {"status": "not_loaded"}
        if dll is None:
            return {**result, "status": "not_loaded" if module is None else "unavailable",
                    "reason": "native_dll_not_loaded"}
        matches = dll == (bin_dir / "renderdoc.dll").resolve()
        if module is not None:
            matches = matches and pyd == (pymod_dir / "renderdoc.pyd").resolve()
        return {**result, "status": ("observed" if module is not None else "partial") if matches else "mismatch",
                "configured_paths_match": matches, "hash_scope": "on_disk_files_at_observation"}
    except (OSError, AttributeError, TypeError) as exc:
        return {**result, "status": "unavailable", "reason": str(exc)}
