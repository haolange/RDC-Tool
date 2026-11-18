#!/usr/bin/env python3
"""Assemble one host's runtime under binaries/ and write its manifest.

A runtime directory holds three independently owned parts: the paired native
set (build receipt), the bundled interpreter (pinned archive + hash-locked
dependencies) and the host tools (provenance file). Each input replaces only
its own part; everything is staged, verified and then published as a whole.
"""

from __future__ import annotations

import argparse
import json
import shutil
import struct
import sys
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

SCRIPT_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))

from rdc_tool import runtime_identity  # noqa: E402
from rdc_tool.host_tools import bundled_host_files  # noqa: E402
from rdc_tool.io_utils import sha256_file  # noqa: E402
from rdc_tool.platform import process  # noqa: E402
from rdc_tool.platform import host as platform_host  # noqa: E402
from rdc_tool.runtime_paths import HOST_LAYOUTS, HostLayout, tools_root  # noqa: E402
from scripts._shared import ensure_within_root, resolve_repo_path, task_directory, write_text  # noqa: E402
from scripts.distribution_metadata import write_distribution_metadata  # noqa: E402

PYTHON_PINS = SCRIPT_ROOT / "scripts" / "python-runtimes.json"
DEPENDENCY_LOCK = SCRIPT_ROOT / "scripts" / "runtime-dependencies.lock"
MANIFEST = "manifest.runtime.json"
HOST_TOOL_PROVENANCE = "bundled_tools.json"
DXC_VERSION = "v1.9.2609"
DXC_URL = "https://github.com/microsoft/DirectXShaderCompiler/releases/download/v1.9.2609/dxc_2026_09_29.zip"
DXC_SHA256 = "ad31b1fc8443175d204f77a611fdb3ef2ec42759bdc2f1167368de24a4a7e7f1"
DENY_SUFFIXES = {".pdb", ".lib", ".exp", ".ilk", ".h"}
SKIP_SUFFIXES = {".pyc", ".md", ".rst", ".chm"}
SKIP_STDLIB_TOP_LEVEL = {"site-packages", "test", "tests", "idlelib", "turtledemo", "ensurepip", "venv", "tkinter", "__pycache__"}


def _resolve_input_path(root: Path, raw_path: str, *, label: str, allow_outside_root: bool = False) -> Path:
    resolved = resolve_repo_path(root, raw_path)
    return resolved if allow_outside_root else ensure_within_root(root, resolved, label=label)


def _reject_links(root: Path) -> None:
    for path in (root, *root.rglob("*")):
        if path.is_symlink() or path.is_junction():
            raise RuntimeError(f"Runtime input contains a link: {path}")


# --- native set -------------------------------------------------------------

def _host_runtime_inputs(source: Path, build: dict[str, Any]) -> list[dict[str, Any]]:
    files = build["runtime_files"]
    actual = runtime_identity.native_runtime_files(source)
    if MANIFEST in actual:
        raise ValueError("Native source must not supply the generated runtime manifest")
    if len(files) != len(actual) or {item["path"] for item in files} != set(actual):
        raise ValueError(f"{build['target']} native source file set differs from its complete build receipt")
    for item in files:
        if runtime_identity.file_identity(actual[item["path"]]) != {"size": item["size"], "sha256": item["sha256"]}:
            raise ValueError(f"{build['target']} native input changed after receipt: {item['path']}")
    return files


def _install_native_set(root: Path, staged_root: Path, args: argparse.Namespace) -> dict[str, Any]:
    """Replace this host's native set and the paired helper APKs; return the packaged receipt."""
    receipt_path = _resolve_input_path(root, args.build_receipt, label="build receipt")
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    source = receipt["source"]
    if set(source) != runtime_identity.SOURCE_FIELDS:
        raise ValueError(f"Build receipt source fields must be exactly {sorted(runtime_identity.SOURCE_FIELDS)}")
    builds = {build["target"]: build for build in receipt["builds"]}
    if len(builds) != len(receipt["builds"]) or not set(builds) <= set(runtime_identity.NATIVE_TARGETS):
        raise ValueError(f"Build receipt targets must be unique and known: {[b['target'] for b in receipt['builds']]}")
    if args.host not in builds:
        raise ValueError(f"Build receipt has no {args.host} build")
    apks = {abi: raw for abi, raw in (("arm32", args.arm32_apk), ("arm64", args.arm64_apk)) if raw}
    paired_abis = {target.removeprefix("android-") for target in builds if target in runtime_identity.ANDROID_TARGETS}
    if set(apks) != paired_abis:
        raise ValueError(f"Helper APK inputs {sorted(apks)} must match the receipt's Android builds {sorted(paired_abis)}")

    native_source = _resolve_input_path(root, args.renderdoc_source, label="runtime source")
    if not native_source.is_dir():
        raise RuntimeError(f"missing source directory: {native_source}")
    _reject_links(native_source)
    files = _host_runtime_inputs(native_source, builds[args.host])
    out_root = staged_root / HOST_LAYOUTS[args.host].runtime_dir
    out_root.mkdir(parents=True, exist_ok=True)
    # Replace the native-owned set completely; Python and host tools have separate owners.
    for old in runtime_identity.native_runtime_files(out_root).values():
        if old.parent == out_root:
            old.unlink()
    shutil.rmtree(out_root / "pymodules", ignore_errors=True)
    (out_root / "pymodules").mkdir()
    for item in files:
        destination = out_root / str(item["path"])
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(native_source / str(item["path"]), destination)
    for abi, raw in apks.items():
        destination = staged_root / runtime_identity.ANDROID_TARGETS[f"android-{abi}"]["helper_apk"]
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(_resolve_input_path(root, raw, label=f"{abi} APK", allow_outside_root=True), destination)

    packaged = []
    for target, build in builds.items():
        if not isinstance(build["configuration"], str) or not build["configuration"].strip():
            raise ValueError(f"Build configuration is missing: {target}")
        if not isinstance(build["toolchain"], dict) or not build["toolchain"]:
            raise ValueError(f"Build toolchain is missing: {target}")
        # Other host targets were built and packaged on their own host; only their staged bytes are checked here.
        built_here = target == args.host or target in runtime_identity.ANDROID_TARGETS
        outputs = []
        for item in build["outputs"]:
            role = item["role"]
            destination = runtime_identity.NATIVE_TARGETS[target][role]
            expected = {"size": item["size"], "sha256": item["sha256"]}
            if built_here:
                original = Path(item["path"])
                original = original if original.is_absolute() else receipt_path.parent / original
                if runtime_identity.file_identity(original) != expected:
                    raise ValueError(f"Build output changed after receipt: {target}/{role}")
            if runtime_identity.file_identity(staged_root / destination) != expected:
                raise ValueError(f"Runtime input differs from build output: {target}/{role}")
            output = {"role": role, "path": destination, **expected}
            if target in runtime_identity.ANDROID_TARGETS:
                output["apk"] = runtime_identity.apk_native_identity(staged_root / destination, target.removeprefix("android-"))
            outputs.append(output)
        entry = {"target": target, "configuration": build["configuration"], "toolchain": build["toolchain"],
                 "inputs_sha256": build["inputs_sha256"], "outputs": outputs}
        if target in HOST_LAYOUTS:
            runtime_dir = HOST_LAYOUTS[target].runtime_dir
            entry["runtime_files"] = [{"path": f"{runtime_dir}/{item['path']}", "size": item["size"], "sha256": item["sha256"]}
                                      for item in build["runtime_files"]]
        packaged.append(entry)
    return {"source": {key: source[key] for key in ("repository", "revision", "base_revision", "upstream_revision", "tree_sha256")},
            "builds": packaged}


# --- bundled interpreter ----------------------------------------------------

def _interpreter_version(python: Path) -> str:
    completed = process.run_tool([str(python), "-I", "-c", "import sys; print('.'.join(map(str, sys.version_info[:3])))"],
                                 capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)
    if completed.returncode != 0:
        raise RuntimeError(f"Pinned interpreter does not run on this host: {python}: {completed.stderr.strip()}")
    return completed.stdout.strip()


def _install_dependencies(python: Path, site_packages: Path, lock: Path) -> None:
    """Install exactly the hash-locked wheels, using the pinned interpreter itself."""
    command = [str(python), "-I", "-m", "pip", "install", "--no-deps", "--require-hashes", "--only-binary=:all:",
               "--no-compile", "--disable-pip-version-check", "--no-input", "--target", str(site_packages), "-r", str(lock)]
    completed = process.run_tool(command, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)
    if completed.returncode != 0:
        raise RuntimeError(f"Locked dependency installation failed: {(completed.stdout + completed.stderr).strip()[-2000:]}")
    # Console scripts point at the temporary build interpreter; they are not part of the runtime.
    shutil.rmtree(site_packages / "bin", ignore_errors=True)


def _extract(archive: Path, destination: Path) -> None:
    if zipfile.is_zipfile(archive):
        with zipfile.ZipFile(archive) as bundle:
            for member in bundle.namelist():
                if PurePosixPath(member).is_absolute() or ".." in PurePosixPath(member).parts:
                    raise ValueError(f"Interpreter archive member escapes extraction: {member}")
            bundle.extractall(destination)
    else:
        with tarfile.open(archive) as bundle:
            bundle.extractall(destination, filter="data")


def _copy_interpreter_entry(home: Path, entry: str, python_dir: Path, stdlib: PurePosixPath) -> None:
    """Copy regular files only; aliases (symlinks), caches, docs and unused stdlib packages stay behind."""
    source = home / entry
    if source.is_symlink() or not source.exists():
        raise ValueError(f"Interpreter archive lacks pinned entry: {entry}")
    for path in [source] if source.is_file() else sorted(source.rglob("*")):
        if path.is_symlink() or not path.is_file():
            continue
        relative = PurePosixPath(path.relative_to(home).as_posix())
        if "__pycache__" in relative.parts or path.suffix.lower() in SKIP_SUFFIXES or path.name.startswith("_tkinter"):
            continue
        if relative.is_relative_to(stdlib):
            top = relative.relative_to(stdlib).parts[0]
            if top in SKIP_STDLIB_TOP_LEVEL or top.startswith("config-"):
                continue
        target = python_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)


def _path_config_lines(layout: HostLayout) -> list[str]:
    """A `._pth` file replaces sys.path next to the executable; a site `.pth` appends to it."""
    here = PurePosixPath(layout.python["path_config"]).parent
    root = "/".join([".."] * len(PurePosixPath(layout.runtime_dir, here).parts))
    if not layout.python["path_config"].endswith("._pth"):
        return [root]
    entries = [PurePosixPath(layout.python[role]).relative_to(here).as_posix()
               for role in ("extension_modules", "stdlib", "site_packages")]
    return [".", *entries, root, "import site"]


def _bundle_python(root: Path, out_root: Path, layout: HostLayout, args: argparse.Namespace, work: Path) -> dict[str, str]:
    pin = json.loads(PYTHON_PINS.read_text(encoding="utf-8"))[args.host]
    archive = _resolve_input_path(root, args.python_archive, label="interpreter archive", allow_outside_root=True)
    if sha256_file(archive) != pin["source_sha256"]:
        raise ValueError(f"Interpreter archive does not match the {args.host} pin in {PYTHON_PINS.name}")
    extracted = work / "interpreter"
    _extract(archive, extracted)
    home = extracted / pin["archive_root"]
    executable = home / PurePosixPath(layout.python["executable"]).relative_to("python")
    version = _interpreter_version(executable)
    if version != pin["python_version"]:
        raise ValueError(f"Interpreter archive reports Python {version}, pinned {pin['python_version']}")

    python_dir = out_root / "python"
    shutil.rmtree(python_dir, ignore_errors=True)
    stdlib = PurePosixPath(layout.python["stdlib"]).relative_to("python")
    for entry in pin["include"]:
        _copy_interpreter_entry(home, entry, python_dir, stdlib)
    site_packages = out_root / layout.python["site_packages"]
    site_packages.mkdir(parents=True, exist_ok=True)
    _install_dependencies(executable, site_packages, DEPENDENCY_LOCK)
    write_distribution_metadata(root, site_packages)
    write_text(out_root / layout.python["path_config"], "\n".join(_path_config_lines(layout)) + "\n")
    return {"python_version": version, "package": pin["package"], "source_url": pin["source_url"],
            "source_sha256": pin["source_sha256"], "dependency_lock_sha256": sha256_file(DEPENDENCY_LOCK)}


# --- host tools -------------------------------------------------------------

def _install_host_tools(root: Path, out_root: Path, layout: HostLayout, raw: str,
                        dxc_archive: str = "", work: Path | None = None) -> dict[str, Any]:
    source = _resolve_input_path(root, raw, label="host tools", allow_outside_root=True)
    _reject_links(source)
    provenance = json.loads((source / HOST_TOOL_PROVENANCE).read_text(encoding="utf-8"))
    dxc_names = {"dxc", "dxcompiler"} & set(layout.host_tools)
    required = set(layout.host_tools) - dxc_names
    if set(provenance) != required:
        raise ValueError(f"Host tool provenance must describe exactly {sorted(required)}")
    tools: dict[str, Any] = {}
    for name, record in provenance.items():
        if not all(str(record.get(key) or "").strip() for key in ("version", "source_url", "source_sha256", "license")):
            raise ValueError(f"Incomplete third-party provenance: {name}")
        if record.get("license_path") not in layout.host_tool_files:
            raise ValueError(f"{name} license_path must name a bundled license file: {record.get('license_path')}")
        tools[name] = {**record, "license_path": f"{layout.runtime_dir}/{record['license_path']}", "path": layout.host_tools[name]}
    files = tuple(relative for relative in bundled_host_files(layout) if not relative.startswith("dxc/"))
    for relative in files:
        if not (source / relative).is_file():
            raise ValueError(f"Missing host tool input: {relative}")
    for directory in {PurePosixPath(relative).parts[0] for relative in files}:
        shutil.rmtree(out_root / directory, ignore_errors=True)
    for relative in files:
        (out_root / relative).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source / relative, out_root / relative)
    if dxc_names:
        assert work is not None
        work.mkdir(parents=True, exist_ok=True)
        archive = (_resolve_input_path(root, dxc_archive, label="DXC archive", allow_outside_root=True)
                   if dxc_archive else work / "dxc.zip")
        if not dxc_archive:
            urllib.request.urlretrieve(DXC_URL, archive)
        if sha256_file(archive) != DXC_SHA256:
            raise ValueError("DXC archive does not match the pinned SHA-256")
        destination = out_root / "dxc"
        shutil.rmtree(destination, ignore_errors=True)
        destination.mkdir(parents=True)
        with zipfile.ZipFile(archive) as package:
            for member, name in (("bin/x64/dxc.exe", "dxc.exe"), ("bin/x64/dxcompiler.dll", "dxcompiler.dll"),
                                 ("LICENSE-LLVM.txt", "LICENSE-LLVM.txt")):
                with package.open(member) as reader, (destination / name).open("wb") as writer:
                    shutil.copyfileobj(reader, writer)
        record = {"version": DXC_VERSION, "source_url": DXC_URL, "source_sha256": DXC_SHA256,
                  "license": "LICENSE-LLVM", "license_path": f"{layout.runtime_dir}/dxc/LICENSE-LLVM.txt"}
        for name in dxc_names:
            tools[name] = {**record, "path": layout.host_tools[name]}
    return tools


# --- manifest ---------------------------------------------------------------

def _owned_files(out_root: Path, layout: HostLayout) -> Iterable[Path]:
    """Every file a part owns; anything else is rejected, never skipped or certified."""
    native = set(runtime_identity.native_runtime_files(out_root).values())
    host_files = set(bundled_host_files(layout))
    for path in sorted(out_root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(out_root).as_posix()
        if relative == MANIFEST or "__pycache__" in path.parts or path.suffix.lower() == ".pyc":
            continue
        if relative.startswith("python/"):
            yield path  # installed wheels stay byte-for-byte as their RECORD describes them
            continue
        if path.suffix.lower() in DENY_SUFFIXES:
            raise ValueError(f"Build-only file in runtime: {relative}")
        if path in native or relative in host_files:
            yield path
            continue
        raise ValueError(f"Runtime directory holds a file no part owns: {relative}")


def _assemble_runtime(root: Path, staged_root: Path, args: argparse.Namespace, work: Path) -> None:
    layout = HOST_LAYOUTS[args.host]
    out_root = staged_root / layout.runtime_dir
    out_root.mkdir(parents=True, exist_ok=True)
    manifest_path = out_root / MANIFEST
    previous = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.is_file() else {}
    receipt = _install_native_set(root, staged_root, args) if args.renderdoc_source else None
    bundled_python = _bundle_python(root, out_root, layout, args, work) if args.python_archive else previous.get("bundled_python")
    bundled_tools = (_install_host_tools(root, out_root, layout, args.host_tools, args.dxc_archive, work)
                     if args.host_tools else previous.get("bundled_tools"))

    files = [{"path": path.relative_to(out_root).as_posix(), "size": path.stat().st_size, "sha256": sha256_file(path)}
             for path in _owned_files(out_root, layout)]
    if not files:
        raise RuntimeError("no runtime files found to package")
    manifest: dict[str, Any] = {"file_count": len(files), "files": files}
    if bundled_python:
        manifest["bundled_python"] = bundled_python
    if bundled_tools:
        manifest["bundled_tools"] = bundled_tools
    write_text(manifest_path, json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")

    receipt_path = staged_root / runtime_identity.RECEIPT_PATH
    if receipt is not None:
        write_text(receipt_path, json.dumps(receipt, ensure_ascii=False, indent=2) + "\n")
    if receipt_path.is_file():
        listed = [build["target"] for build in json.loads(receipt_path.read_text(encoding="utf-8"))["builds"]]
        status = runtime_identity.native_manifest_status(staged_root, required=listed)
        if status["status"] != "verified":
            raise RuntimeError(f"Paired native runtime verification failed: {status}")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Assemble this host's rdc-tool runtime")
    parser.add_argument("--host", default=platform_host.host_target(), choices=sorted(HOST_LAYOUTS),
                        help="Runtime layout to assemble; must be this host, whose interpreter installs the dependencies")
    parser.add_argument("--source", dest="renderdoc_source", default="",
                        help="Repo-relative staging directory with this host's native set")
    parser.add_argument("--build-receipt", default="", help="JSON receipt for the builds from one frozen source tree")
    parser.add_argument("--arm32-apk", default="", help="arm32 helper APK, when the receipt pairs it")
    parser.add_argument("--arm64-apk", default="", help="arm64 helper APK, when the receipt pairs it")
    parser.add_argument("--python-archive", default="", help=f"Interpreter archive pinned in {PYTHON_PINS.name}")
    parser.add_argument("--host-tools", default="",
                        help=f"Directory with the layout's host-tool files and {HOST_TOOL_PROVENANCE}")
    parser.add_argument("--dxc-archive", default="", help="Use this pinned DXC archive instead of downloading it")
    parser.add_argument("--output-root", default="",
                        help="Assemble a new runtime root under intermediate/ or dist/ without replacing the current runtime")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.host != platform_host.host_target():
        print(f"[pack] --host {args.host} differs from this host ({platform_host.host_target()}); assemble each runtime on its own host")
        return 1
    if bool(args.renderdoc_source) != bool(args.build_receipt) or ((args.arm32_apk or args.arm64_apk) and not args.renderdoc_source):
        print("[pack] Native replacement requires --source with --build-receipt (and the APKs the receipt pairs)")
        return 1
    root = tools_root().resolve()
    if (root / "binaries").is_symlink() or (root / "binaries").is_junction():
        print("[pack] Runtime output must not be a link")
        return 1
    output = task_directory(root, args.output_root, label="runtime output root", new=True) if args.output_root else None
    destination = output if output is not None else ensure_within_root(root, root / "binaries", label="runtime output")
    if output is not None:
        for raw in (args.renderdoc_source, args.python_archive, args.host_tools, args.dxc_archive):
            if raw:
                source = resolve_repo_path(root, raw)
                if source.is_relative_to(output) or output.is_relative_to(source):
                    raise ValueError(f"Runtime output root overlaps a build input: {source}")
    stage_parent = output.parent if output is not None else root
    stage_parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".runtime-stage-", dir=stage_parent))
    staged_root = stage / "tree"
    backup = stage / "previous-binaries"
    retain = False
    try:
        inherited = root / "binaries" if output is not None else destination
        if inherited.exists():
            _reject_links(inherited)
            shutil.copytree(inherited, staged_root / "binaries", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        _assemble_runtime(root, staged_root, args, stage / "work")
        if output is not None and destination.exists():
            raise FileExistsError(f"Refusing to overwrite runtime output root: {destination}")
        if destination.exists():
            destination.rename(backup)
        try:
            (staged_root if output is not None else staged_root / "binaries").rename(destination)
        except BaseException:
            if backup.exists():
                try:
                    backup.rename(destination)
                except BaseException as restore:
                    retain = True
                    raise RuntimeError(f"Runtime publish and restoration failed; preserved original at {backup}") from restore
            raise
        if backup.exists():
            try:
                shutil.rmtree(backup)
            except OSError as cleanup:
                retain = True
                raise RuntimeError(f"New complete runtime published; previous runtime retained for cleanup at {backup}") from cleanup
        print(f"[pack] published verified runtime at {destination}")
        return 0
    except (OSError, ValueError, KeyError, TypeError, IndexError, RuntimeError, struct.error,
            zipfile.BadZipFile, tarfile.TarError) as exc:
        print(f"[pack] {exc}")
        return 1
    finally:
        if not retain and stage.exists():
            shutil.rmtree(stage)


if __name__ == "__main__":
    raise SystemExit(main())
