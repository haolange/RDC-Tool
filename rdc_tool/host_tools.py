"""One resolver for bundled host executables and explicit user overrides."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
from rdc_tool.runtime_paths import binaries_root

HOST_TOOLS = {
    "adb": ("adb/adb.exe", "RDC_TOOL_ANDROID_ADB_PATH"),
    "spirv_as": ("spirv-tools/spirv-as.exe", "RDC_TOOL_SPIRV_TOOLS_PATH"),
    "spirv_dis": ("spirv-tools/spirv-dis.exe", "RDC_TOOL_SPIRV_TOOLS_PATH"),
}
ADB_DLLS = ("adb/AdbWinApi.dll", "adb/AdbWinUsbApi.dll")
BUNDLED_HOST_FILES = tuple(item[0] for item in HOST_TOOLS.values()) + ADB_DLLS + (
    "adb/NOTICE.txt", "adb/source.properties", "spirv-tools/LICENSE.txt", "spirv-tools/SPIRV-Headers-LICENSE.txt",
)

class HostToolUnavailableError(RuntimeError):
    code = "host_tool_unavailable"

def resolve_host_tool(name: str) -> Path:
    relative, variable = HOST_TOOLS[name]
    override = os.environ.get(variable, "").strip()
    if override:
        path = Path(override).expanduser()
        if name != "adb":
            path = path / Path(relative).name
        if not path.is_absolute():
            raise HostToolUnavailableError(f"{variable} must be an absolute path.")
    else:
        path = binaries_root() / relative
    if not path.is_file():
        source = variable if override else "this RDC-Tool installation"
        raise HostToolUnavailableError(f"{name} executable not found in {source}: {path}. Verify or repair the installation.")
    return path.resolve()

def host_tools_status() -> dict:
    result = {}
    for name, (relative, variable) in HOST_TOOLS.items():
        override = os.environ.get(variable, "").strip()
        entry = {"source": "explicit" if override else "bundled", "path": "", "available": False}
        try:
            entry.update(path=str(resolve_host_tool(name)), available=True)
        except HostToolUnavailableError as error:
            entry["error"] = str(error)
        result[name] = entry
    return result

def validate_bundled_host_tools() -> tuple[bool, list[str]]:
    root = binaries_root()
    failures = []
    try:
        manifest = json.loads((root / "manifest.runtime.json").read_text(encoding="utf-8"))
        records = {entry["path"]: entry for entry in manifest["files"]}
        sources = manifest["bundled_tools"]
        for name in HOST_TOOLS:
            source = sources[name]
            if not source.get("version") or not source.get("source_url") or not source.get("license"):
                failures.append(f"incomplete third-party provenance: {name}")
        for relative in BUNDLED_HOST_FILES:
            path = root / relative
            record = records.get(relative)
            if not path.is_file() or not record:
                failures.append(f"missing bundled host tool: {relative}")
            elif path.stat().st_size != record["size"] or hashlib.sha256(path.read_bytes()).hexdigest() != record["sha256"]:
                failures.append(f"bundled host tool integrity mismatch: {relative}")
    except (OSError, ValueError, KeyError, TypeError) as error:
        failures.append(f"invalid host tool manifest: {error}")
    return not failures, failures
