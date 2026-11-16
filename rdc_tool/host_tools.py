"""Host utilities (adb, spirv-as, spirv-dis): bundled per host or explicitly overridden."""
from __future__ import annotations

import json
import os
from pathlib import Path

from rdc_tool.io_utils import sha256_file
from rdc_tool.runtime_paths import HostLayout, binaries_root, host_layout

# Explicit user overrides: adb names the executable, spirv names its directory.
OVERRIDE_VARIABLES = {
    "adb": "RDC_TOOL_ANDROID_ADB_PATH",
    "spirv_as": "RDC_TOOL_SPIRV_TOOLS_PATH",
    "spirv_dis": "RDC_TOOL_SPIRV_TOOLS_PATH",
}


class HostToolUnavailableError(RuntimeError):
    code = "host_tool_unavailable"


def bundled_host_files(layout: HostLayout | None = None) -> tuple[str, ...]:
    """Every host-tool file a runtime bundle ships: executables, support libraries, licenses."""
    chosen = layout or host_layout()
    return (*chosen.host_tools.values(), *chosen.host_tool_files)


def resolve_host_tool(name: str) -> Path:
    relative = host_layout().host_tools[name]
    variable = OVERRIDE_VARIABLES[name]
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
    for name, variable in OVERRIDE_VARIABLES.items():
        entry = {"source": "explicit" if os.environ.get(variable, "").strip() else "bundled", "path": "", "available": False}
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
        manifest = json.loads((binaries_root() / "manifest.runtime.json").read_text(encoding="utf-8"))
        records = {entry["path"]: entry for entry in manifest["files"]}
        sources = manifest["bundled_tools"]
        for name in OVERRIDE_VARIABLES:
            source = sources[name]
            if not source.get("version") or not source.get("source_url") or not source.get("license"):
                failures.append(f"incomplete third-party provenance: {name}")
        for relative in bundled_host_files():
            path = root / relative
            record = records.get(relative)
            if not path.is_file() or not record:
                failures.append(f"missing bundled host tool: {relative}")
            elif path.stat().st_size != record["size"] or sha256_file(path) != record["sha256"]:
                failures.append(f"bundled host tool integrity mismatch: {relative}")
    except (OSError, ValueError, KeyError, TypeError) as error:
        failures.append(f"invalid host tool manifest: {error}")
    return not failures, failures
