#!/usr/bin/env python3
"""Copy runtime binaries into rdc-tool/binaries and generate manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import struct
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Iterable

SCRIPT_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))

from rdc_tool.host_tools import BUNDLED_HOST_FILES
from rdc_tool.runtime_requirements import should_bundle_site_package
from rdc_tool import runtime_identity
from scripts.distribution_metadata import write_distribution_metadata
from scripts._shared import ensure_within_root, resolve_repo_path, task_directory, tools_root, write_text


DENY_SUFFIXES = {".pdb", ".lib", ".exp", ".ilk", ".h"}
ALLOW_PATTERNS = (
    "*.dll",
    "*.json",
)
ALLOW_PYMODULE_PATTERNS = (
    "*.pyd",
    "*.dll",
    "*.json",
)
SKIP_STDLIB_TOP_LEVEL = {"site-packages", "test", "tests", "idlelib", "turtledemo", "ensurepip", "venv", "__pycache__"}
PYTHON_BASE_FILES = (
    "python.exe",
    "pythonw.exe",
    "python3.dll",
    "vcruntime140.dll",
    "vcruntime140_1.dll",
    "LICENSE.txt",
)


def _tools_root() -> Path:
    return tools_root(__file__)


def _resolve_input_path(root: Path, raw_path: str, *, label: str, allow_outside_root: bool = False) -> Path:
    resolved = resolve_repo_path(root, raw_path)
    if allow_outside_root:
        return resolved
    return ensure_within_root(root, resolved, label=label)


def _iter_allowed_files(src: Path) -> Iterable[Path]:
    for pattern in ALLOW_PATTERNS:
        for p in sorted(src.glob(pattern)):
            if p.is_file():
                yield p
    pymod = src / "pymodules"
    if pymod.is_dir():
        for pattern in ALLOW_PYMODULE_PATTERNS:
            for p in sorted(pymod.glob(pattern)):
                if p.is_file():
                    yield p


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _copy_tree_filtered(src: Path, dst: Path, *, skip_top_level: set[str] | None = None) -> None:
    skip_top_level = {item.lower() for item in (skip_top_level or set())}
    for path in src.rglob("*"):
        if path.is_dir():
            continue
        rel = path.relative_to(src)
        parts = [part.lower() for part in rel.parts]
        if any(part == "__pycache__" for part in parts):
            continue
        if path.suffix.lower() in (".pyc", ".md", ".rst", ".chm"):
            continue
        if rel.parts and rel.parts[0].lower() in skip_top_level:
            continue
        target = dst / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)


def _copy_site_packages(src: Path, dst: Path) -> None:
    dst.mkdir(parents=True, exist_ok=True)
    for child in sorted(src.iterdir()):
        if not should_bundle_site_package(child.name):
            continue
        target = dst / child.name
        if child.is_dir():
            _copy_tree_filtered(child, target)
        else:
            if child.suffix.lower() in (".pyc", ".md", ".rst", ".chm"):
                continue
            shutil.copy2(child, target)


def _probe_python_version(python_home: Path) -> str:
    python_exe = python_home / "python.exe"
    if not python_exe.is_file():
        raise RuntimeError(f"missing python.exe in python home: {python_exe}")
    proc = subprocess.run(
        [str(python_exe), "-c", "import sys; print('.'.join(map(str, sys.version_info[:3])))"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"failed to probe python version from {python_exe}: {(proc.stdout or '')}{(proc.stderr or '')}".strip())
    return str(proc.stdout or "").strip()


def _python_tag(python_version: str) -> str:
    parts = str(python_version or "").strip().split(".")
    if len(parts) < 2:
        raise RuntimeError(f"invalid python version: {python_version}")
    return f"{parts[0]}{parts[1]}"


def _bundle_python_runtime(root: Path, out_root: Path, python_home_raw: str, site_packages_raw: str | None, python_version_raw: str | None) -> dict[str, str]:
    python_home = _resolve_input_path(root, python_home_raw, label="python home", allow_outside_root=True)
    if not python_home.is_dir():
        raise RuntimeError(f"missing python home: {python_home}")

    site_packages_source: Path | None = None
    if site_packages_raw:
        site_packages_source = _resolve_input_path(root, site_packages_raw, label="site-packages source")
        if not site_packages_source.is_dir():
            raise RuntimeError(f"missing site-packages source: {site_packages_source}")

    python_version = str(python_version_raw or "").strip() or _probe_python_version(python_home)
    tag = _python_tag(python_version)
    python_dir = out_root / "python"
    if site_packages_source is not None:
        site_packages_resolved = site_packages_source.resolve()
        python_dir_resolved = python_dir.resolve()
        try:
            site_packages_resolved.relative_to(python_dir_resolved)
        except ValueError:
            pass
        else:
            raise RuntimeError(
                f"site-packages source must not point inside the bundled python output tree: {site_packages_resolved}"
            )
    if python_dir.exists():
        shutil.rmtree(python_dir)
    python_dir.mkdir(parents=True, exist_ok=True)

    for name in PYTHON_BASE_FILES:
        src = python_home / name
        if src.is_file():
            shutil.copy2(src, python_dir / name)
    versioned_dll = python_home / f"python{tag}.dll"
    if not versioned_dll.is_file():
        raise RuntimeError(f"missing versioned python dll: {versioned_dll}")
    shutil.copy2(versioned_dll, python_dir / versioned_dll.name)

    dll_dir = python_home / "DLLs"
    if dll_dir.is_dir():
        _copy_tree_filtered(dll_dir, python_dir / "DLLs")

    lib_dir = python_home / "Lib"
    if not lib_dir.is_dir():
        raise RuntimeError(f"missing stdlib directory: {lib_dir}")
    _copy_tree_filtered(lib_dir, python_dir / "Lib", skip_top_level=SKIP_STDLIB_TOP_LEVEL)

    bundled_site_packages = python_dir / "Lib" / "site-packages"
    bundled_site_packages.mkdir(parents=True, exist_ok=True)
    if site_packages_source is not None:
        _copy_site_packages(site_packages_source, bundled_site_packages)

    if (bundled_site_packages / "win32").is_dir() and (bundled_site_packages / "pywin32_system32").is_dir():
        write_text(
            bundled_site_packages / "pywin32.pth",
            "win32\nwin32\\lib\npywin32_system32\n",
            encoding="utf-8",
        )

    pth_lines = [
        ".",
        "DLLs",
        "Lib",
        "Lib/site-packages",
        "..\\..\\..\\..",
        "import site",
        "",
    ]
    write_text(python_dir / f"python{tag}._pth", "\n".join(pth_lines), encoding="utf-8")

    return {
        "python_version": python_version,
        "python_entry": "python/python.exe",
        "pythonw_entry": "python/pythonw.exe",
        "python3_dll": "python/python3.dll",
        "python_dll": f"python/python{tag}.dll",
        "stdlib_layout": "python/Lib",
        "site_packages": "python/Lib/site-packages",
        "dll_dir": "python/DLLs",
        "pth_file": f"python/python{tag}._pth",
    }


def _existing_bundled_python_metadata(out_root: Path) -> dict[str, str]:
    python_dir = out_root / "python"
    python_exe = python_dir / "python.exe"
    if not python_exe.is_file():
        return {}
    try:
        python_version = _probe_python_version(python_dir)
        tag = _python_tag(python_version)
    except RuntimeError:
        return {}
    metadata = {
        "python_version": python_version,
        "python_entry": "python/python.exe",
        "pythonw_entry": "python/pythonw.exe",
        "python3_dll": "python/python3.dll",
        "python_dll": f"python/python{tag}.dll",
        "stdlib_layout": "python/Lib",
        "site_packages": "python/Lib/site-packages",
        "dll_dir": "python/DLLs",
        "pth_file": f"python/python{tag}._pth",
    }
    required = ("python_entry", "python_dll", "stdlib_layout", "site_packages", "pth_file")
    for key in required:
        if not (out_root / metadata[key]).exists():
            return {}
    return metadata


def _iter_manifest_files(out_root: Path) -> Iterable[Path]:
    for path in sorted(out_root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(out_root).as_posix()
        if rel == "manifest.runtime.json":
            continue
        if "__pycache__/" in rel or path.suffix.lower() == ".pyc":
            continue
        if path.suffix.lower() in DENY_SUFFIXES:
            continue
        if rel in BUNDLED_HOST_FILES:
            yield path
            continue
        if rel.startswith("python/"):
            yield path
            continue
        if rel.startswith("pymodules/"):
            yield path
            continue
        if "/" in rel:
            continue
        if path.name.lower().startswith("python"):
            continue
        yield path


def _manifest_entry(path: Path, out_root: Path) -> dict[str, object]:
    rel = path.relative_to(out_root).as_posix()
    return {
        "path": rel,
        "size": int(path.stat().st_size),
        "sha256": _sha256(path),
    }


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Package runtime binaries for rdc-tool")
    parser.add_argument("--source", dest="renderdoc_source", default="", help="Repo-relative staging directory under the rdc-tool root")
    parser.add_argument("--python-home", default="", help="Absolute or repo-relative CPython home used to build the bundled runtime")
    parser.add_argument("--site-packages-source", default=".venv/Lib/site-packages", help="Repo-relative site-packages source for the bundled runtime")
    parser.add_argument("--python-version", default="", help="Override the bundled CPython version metadata")
    parser.add_argument("--arm32-apk", default="", help="Matching arm32 helper APK build output")
    parser.add_argument("--arm64-apk", default="", help="Matching arm64 helper APK build output")
    parser.add_argument("--build-receipt", default="", help="JSON receipt for all three builds from one frozen source tree")
    parser.add_argument("--output-root", default="", help="Assemble a new runtime root under intermediate/ or dist/ without replacing the current runtime")
    return parser.parse_args(argv)


def _reject_links(root: Path) -> None:
    for path in (root, *root.rglob("*")):
        if path.is_symlink() or path.is_junction():
            raise RuntimeError(f"Runtime input contains a link: {path}")


def _windows_runtime_inputs(root: Path, source: Path, args: argparse.Namespace) -> list[dict[str, object]]:
    receipt_path = _resolve_input_path(root, args.build_receipt, label="build receipt")
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    builds = [build for build in receipt["builds"] if build["target"] == "windows-x64"]
    if len(builds) != 1:
        raise ValueError("Build receipt requires exactly one Windows build")
    files = builds[0]["runtime_files"]
    actual = {path.relative_to(source).as_posix(): path for path in _iter_allowed_files(source)}
    if "manifest.runtime.json" in actual:
        raise ValueError("Native source must not supply the generated runtime manifest")
    if len(files) != len(actual) or {item["path"] for item in files} != set(actual):
        raise ValueError("Windows native source file set differs from its complete build receipt")
    for item in files:
        if runtime_identity.file_identity(actual[item["path"]]) != {"size": item["size"], "sha256": item["sha256"]}:
            raise ValueError(f"Windows native input changed after receipt: {item['path']}")
    return files


def _native_build_receipt(root: Path, staged_root: Path, args: argparse.Namespace) -> dict[str, object]:
    receipt_path = _resolve_input_path(root, args.build_receipt, label="build receipt")
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    builds = []
    for build in receipt["builds"]:
        target = build["target"]
        if target not in runtime_identity.NATIVE_OUTPUTS:
            raise ValueError(f"Unknown native build target: {target}")
        if not isinstance(build["configuration"], str) or not build["configuration"].strip():
            raise ValueError(f"Build configuration is missing: {target}")
        if not isinstance(build["toolchain"], dict) or not build["toolchain"]:
            raise ValueError(f"Build toolchain is missing: {target}")
        outputs = []
        for item in build["outputs"]:
            role = item["role"]
            destination = runtime_identity.NATIVE_OUTPUTS[target][role]
            original = Path(item["path"])
            if not original.is_absolute():
                original = receipt_path.parent / original
            expected = {"size": item["size"], "sha256": item["sha256"]}
            if runtime_identity.file_identity(original) != expected:
                raise ValueError(f"Build output changed after receipt: {target}/{role}")
            packaged = staged_root / destination
            if runtime_identity.file_identity(packaged) != expected:
                raise ValueError(f"Runtime input differs from build output: {target}/{role}")
            output = {"role": role, "path": destination, **expected}
            if target.startswith("android-"):
                output["apk"] = runtime_identity.apk_native_identity(packaged, target.removeprefix("android-"))
            outputs.append(output)
        packaged_build = {"target": target, "configuration": build["configuration"],
                          "toolchain": build["toolchain"], "inputs_sha256": build["inputs_sha256"], "outputs": outputs}
        if target == "windows-x64":
            source = _resolve_input_path(root, args.renderdoc_source, label="runtime source")
            files = _windows_runtime_inputs(root, source, args)
            packaged_files = []
            for item in files:
                destination = "binaries/windows/x64/" + str(item["path"])
                expected = {"size": item["size"], "sha256": item["sha256"]}
                if runtime_identity.file_identity(staged_root / destination) != expected:
                    raise ValueError(f"Packaged Windows input differs from build receipt: {item['path']}")
                packaged_files.append({"path": destination, **expected})
            packaged_build["runtime_files"] = packaged_files
        builds.append(packaged_build)
    return {"source": {key: receipt["source"][key] for key in ("base_revision", "upstream_revision", "tree_sha256")},
            "builds": builds}


def _assemble_runtime(tools_root_path: Path, staged_root: Path, args: argparse.Namespace) -> int:
    out_root = staged_root / "binaries/windows/x64"
    out_root.mkdir(parents=True, exist_ok=True)
    (out_root / "pymodules").mkdir(parents=True, exist_ok=True)
    manifest_path = out_root / "manifest.runtime.json"
    previous = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.is_file() else {}
    bundled_python: dict[str, str] = {}
    renderdoc_source_raw = str(args.renderdoc_source or "").strip()
    if renderdoc_source_raw:
        src = _resolve_input_path(tools_root_path, renderdoc_source_raw, label="runtime source")
        if not src.is_dir():
            raise RuntimeError(f"missing source directory: {src}")
        _reject_links(src)
        files = _windows_runtime_inputs(tools_root_path, src, args)
        # This is only the isolated staging copy. Replace the native-owned file
        # set completely; Python and host-tool directories have separate owners.
        for old in runtime_identity.windows_native_files(out_root).values():
            if old.parent == out_root:
                old.unlink()
        modules = out_root / "pymodules"
        shutil.rmtree(modules)
        modules.mkdir()
        for item in files:
            rel = Path(str(item["path"]))
            src_file = src / rel
            dst_file = out_root / rel
            dst_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_file, dst_file)
        for abi, raw in (("arm32", args.arm32_apk), ("arm64", args.arm64_apk)):
            source = _resolve_input_path(tools_root_path, raw, label=f"{abi} APK", allow_outside_root=True)
            destination = staged_root / f"binaries/android/{abi}/org.renderdoc.renderdoccmd.{abi}.apk"
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
    python_home_raw = str(args.python_home or "").strip()
    if python_home_raw:
        try:
            bundled_python = _bundle_python_runtime(
                tools_root_path,
                out_root,
                python_home_raw,
                str(args.site_packages_source or "").strip() or None,
                str(args.python_version or "").strip() or None,
            )
        except RuntimeError:
            raise
    else:
        bundled_python = _existing_bundled_python_metadata(out_root)

    if bundled_python:
        write_distribution_metadata(tools_root_path, out_root / 'python' / 'Lib' / 'site-packages')
    manifest_entries = [_manifest_entry(path, out_root) for path in _iter_manifest_files(out_root)]

    if not manifest_entries:
        print("[pack] no runtime files found to package")
        return 1

    manifest = {
        "file_count": len(manifest_entries),
        "files": manifest_entries,
    }
    if bundled_python:
        manifest["bundled_python"] = bundled_python
    for key in ("bundled_tools", "native_build"):
        if key in previous:
            manifest[key] = previous[key]
    if renderdoc_source_raw:
        manifest["native_build"] = _native_build_receipt(tools_root_path, staged_root, args)
    write_text(manifest_path, json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    if manifest.get("native_build"):
        status = runtime_identity.native_manifest_status(staged_root)
        if status["status"] != "verified":
            raise RuntimeError(f"Paired native runtime verification failed: {status}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    root = _tools_root().resolve()
    if (root / "binaries").is_symlink() or (root / "binaries").is_junction():
        print("[pack] Runtime output must not be a link")
        return 1
    output = task_directory(root, args.output_root, label="runtime output root", new=True) if args.output_root else None
    destination = output if output is not None else ensure_within_root(root, root / "binaries", label="runtime output")
    native_inputs = (args.renderdoc_source, args.arm32_apk, args.arm64_apk, args.build_receipt)
    if any(native_inputs) and not all(native_inputs):
        print("[pack] Native replacement requires --source, both --arm32-apk/--arm64-apk and --build-receipt")
        return 1
    if output is not None:
        for raw in (args.renderdoc_source, args.python_home, args.site_packages_source if args.python_home else ""):
            if raw:
                source = resolve_repo_path(root, raw)
                if source.is_relative_to(output) or output.is_relative_to(source):
                    raise ValueError(f"Runtime output root overlaps a build input: {source}")
    if args.python_home:
        site = _resolve_input_path(root, args.site_packages_source, label="site-packages source")
        if output is None and site.is_relative_to(root / "binaries/windows/x64/python"):
            print(f"[pack] site-packages source must not point inside the bundled python output tree: {site}")
            return 1
    stage_parent = output.parent if output is not None else root
    stage_parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".runtime-stage-", dir=stage_parent))
    backup = stage / "previous-binaries"
    retain = False
    try:
        inherited = root / "binaries" if output is not None else destination
        if inherited.exists():
            _reject_links(inherited)
            shutil.copytree(inherited, stage / "binaries", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        if _assemble_runtime(root, stage, args) != 0:
            return 1
        if output is not None and destination.exists():
            raise FileExistsError(f"Refusing to overwrite runtime output root: {destination}")
        if destination.exists():
            destination.rename(backup)
        try:
            (stage if output is not None else stage / "binaries").rename(destination)
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
    except (OSError, ValueError, KeyError, TypeError, IndexError, RuntimeError, struct.error, zipfile.BadZipFile) as exc:
        print(f"[pack] {exc}")
        return 1
    finally:
        if not retain and stage.exists():
            shutil.rmtree(stage)


if __name__ == "__main__":
    raise SystemExit(main())
