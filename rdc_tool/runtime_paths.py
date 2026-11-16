"""Runtime path helpers for the standalone rdc-tool distribution."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

from rdc_tool.platform.host import host_target


@dataclass(frozen=True)
class HostLayout:
    """Where one host's runtime lives inside an installation (paths are relative)."""

    runtime_dir: str
    native_library: str
    binding_module: str
    python_files: tuple[str, ...]
    python_dirs: tuple[str, ...]
    launcher: str
    host_tools: Mapping[str, str]
    host_tool_files: tuple[str, ...]


HOST_LAYOUTS: Mapping[str, HostLayout] = MappingProxyType({
    "windows-x64": HostLayout(
        runtime_dir="binaries/windows/x64",
        native_library="renderdoc.dll",
        binding_module="pymodules/renderdoc.pyd",
        python_files=("python_entry", "pythonw_entry", "python3_dll", "python_dll", "pth_file"),
        python_dirs=("stdlib_layout", "site_packages", "dll_dir"),
        launcher="bin/rdc-tool.cmd",
        host_tools=MappingProxyType({"adb": "adb/adb.exe", "spirv_as": "spirv-tools/spirv-as.exe",
                                     "spirv_dis": "spirv-tools/spirv-dis.exe"}),
        host_tool_files=("adb/AdbWinApi.dll", "adb/AdbWinUsbApi.dll", "adb/NOTICE.txt", "adb/source.properties",
                         "spirv-tools/LICENSE.txt", "spirv-tools/SPIRV-Headers-LICENSE.txt"),
    ),
    "linux-x64": HostLayout(
        runtime_dir="binaries/linux/x64",
        native_library="librenderdoc.so",
        binding_module="pymodules/renderdoc.so",
        python_files=("python_entry",),
        python_dirs=("stdlib_layout", "site_packages"),
        launcher="bin/rdc-tool",
        host_tools=MappingProxyType({"adb": "adb/adb", "spirv_as": "spirv-tools/spirv-as",
                                     "spirv_dis": "spirv-tools/spirv-dis"}),
        host_tool_files=("adb/NOTICE.txt", "adb/source.properties", "spirv-tools/LICENSE.txt",
                         "spirv-tools/SPIRV-Headers-LICENSE.txt"),
    ),
})


class UnsupportedHost(RuntimeError):
    code = "unsupported_host"

    def __init__(self, target: str) -> None:
        super().__init__(f"rdc-tool has no runtime layout for host {target}; supported: {', '.join(HOST_LAYOUTS)}")
        self.target = target


def tools_root() -> Path:
    """The installation root: the directory that contains the rdc_tool package."""
    return Path(__file__).resolve().parents[1]


def host_layout(target: str | None = None) -> HostLayout:
    chosen = target or host_target()
    try:
        return HOST_LAYOUTS[chosen]
    except KeyError:
        raise UnsupportedHost(chosen) from None


def binaries_root() -> Path:
    """This host's runtime directory: native library, binding, bundled Python and tools."""
    return tools_root() / host_layout().runtime_dir


def pymodules_dir() -> Path:
    return binaries_root() / "pymodules"


def native_library_path() -> Path:
    return binaries_root() / host_layout().native_library


def binding_module_path() -> Path:
    return binaries_root() / host_layout().binding_module


def native_library_name() -> str:
    return Path(host_layout().native_library).name


def binding_module_name() -> str:
    return Path(host_layout().binding_module).name


def child_python_env(base: Mapping[str, str]) -> dict[str, str]:
    """Environment for a Python child that must import this installation's rdc_tool first."""
    env = dict(base)
    env.pop("PYTHONHOME", None)
    inherited = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = os.pathsep.join([str(tools_root()), *([inherited] if inherited else [])])
    return env


def android_binaries_root() -> Path:
    """Directory containing packaged Android `RenderDocCmd` APKs."""
    return tools_root() / "binaries" / "android"


def intermediate_root() -> Path:
    override = os.environ.get("RDC_TOOL_INTERMEDIATE_ROOT", "").strip()
    return Path(override).expanduser().resolve() if override else tools_root() / "intermediate"


def runtime_root() -> Path:
    return intermediate_root() / "runtime"


def cli_runtime_dir() -> Path:
    return runtime_root() / "rdc_tool_cli"


def worker_state_dir() -> Path:
    return runtime_root() / "worker-state"


def artifacts_dir() -> Path:
    return intermediate_root() / "artifacts"


def pytest_dir() -> Path:
    return intermediate_root() / "pytest"


def logs_dir() -> Path:
    return intermediate_root() / "logs"


def ensure_runtime_dirs() -> None:
    for path in (
        intermediate_root(),
        runtime_root(),
        cli_runtime_dir(),
        worker_state_dir(),
        artifacts_dir(),
        pytest_dir(),
        logs_dir(),
    ):
        path.mkdir(parents=True, exist_ok=True)
