#!/usr/bin/env python3
"""Build a self-contained Windows x64 release zip for rdc-tool."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

SCRIPT_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))

from rdc_tool import __version__ as TOOL_VERSION
from rdc_tool.runtime_identity import native_manifest_status
from scripts._shared import ensure_within_root, task_directory, tools_root, write_text


PACKAGE_PLATFORM = "windows-x64"
PACKAGE_PREFIX = "rdc-tool"
EXCLUDE_DIRS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "dist",
    "intermediate",
}
EXCLUDE_FILE_SUFFIXES = {".pyc", ".pyo", ".pdb", ".ilk", ".exp", ".lib", ".rdc"}
RELEASE_ROOT_FILES = {
    ".gitattributes",
    ".gitignore",
    "AGENTS.md",
    "CHANGELOG.md",
    "LICENSE",
    "THIRD_PARTY_NOTICES.md",
    "README.md",
    "pyproject.toml",
    "bin/rdc-tool.cmd",
    "install.cmd",
}
RELEASE_DIRS = {
    "bin",
    "binaries",
    "cli",
    "docs",
    "policy",
    "rdc_tool",
    "scripts",
    "spec",
}


def _tools_root() -> Path:
    return tools_root(__file__)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _should_skip(path: Path, root: Path) -> bool:
    rel = path.relative_to(root)
    if rel.as_posix() == 'docs/tool-convergence-tasks.md':
        return True  # Maintainer history contains local evidence, not installation documentation.
    if any(part in EXCLUDE_DIRS for part in rel.parts):
        return True
    if path.is_file() and path.suffix.lower() in EXCLUDE_FILE_SUFFIXES:
        return True
    if rel.parts and rel.parts[0] == "tests":
        return True
    return False


def _copy_release_tree(root: Path, staging_root: Path, *, runtime_root: Path | None = None) -> list[dict[str, object]]:
    copied: list[dict[str, object]] = []
    allowed_roots = RELEASE_ROOT_FILES | RELEASE_DIRS
    inputs = [(root, path) for path in sorted(root.rglob("*"))
              if runtime_root is None or not path.relative_to(root).parts or path.relative_to(root).parts[0] != "binaries"]
    if runtime_root is not None:
        inputs.extend((runtime_root, path) for path in sorted((runtime_root / "binaries").rglob("*")))
    for source_root, path in inputs:
        if path.is_dir() or _should_skip(path, source_root):
            continue
        rel = path.relative_to(source_root)
        if not rel.parts or rel.parts[0] not in allowed_roots:
            continue
        if path.is_symlink() or path.is_junction():
            raise RuntimeError(f"Package source file must not be a link: {path}")
        target = staging_root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        copied.append(
            {
                "path": rel.as_posix(),
                "size": int(target.stat().st_size),
                "sha256": _sha256(target),
            }
        )
    return copied


def _license_inventory(staging_root: Path) -> list[dict[str, str]]:
    rows = [{"name": "rdc-tool", "version": TOOL_VERSION, "license": "Apache-2.0", "path": "LICENSE"}]
    site_packages = staging_root / "binaries" / "windows" / "x64" / "python" / "Lib" / "site-packages"
    if not site_packages.is_dir():
        return rows
    for meta in sorted(site_packages.glob("*.dist-info/METADATA")):
        name = ""
        version = ""
        license_name = ""
        for line in meta.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("Name: "):
                name = line[6:].strip()
            elif line.startswith("Version: "):
                version = line[9:].strip()
            elif line.startswith("License: "):
                license_name = line[9:].strip()
        if name and name != PACKAGE_PREFIX:
            rows.append(
                {
                    "name": name,
                    "version": version,
                    "license": license_name or "UNKNOWN",
                    "path": meta.relative_to(staging_root).as_posix(),
                }
            )
    return rows


def _source_revision(root: Path) -> str:
    def git(*args: str) -> str:
        return subprocess.check_output(['git', '-C', str(root), *args], text=True).strip()
    if git('status', '--porcelain', '--untracked-files=normal'):
        raise RuntimeError('Release packaging requires a clean source checkout')
    return git('rev-parse', 'HEAD')


def source_file_digest(files: list[dict[str, object]]) -> str:
    generated = {"SBOM.json", "LICENSE_INVENTORY.json", "CANDIDATE_MANIFEST.json", "RELEASE_MANIFEST.json"}
    source = sorted((item for item in files if not str(item["path"]).startswith("binaries/") and item["path"] not in generated), key=lambda item: item["path"])
    return hashlib.sha256(json.dumps(source, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _write_release_metadata(staging_root: Path, files: list[dict[str, object]], revision: str,
                            *, candidate_source: dict[str, str] | None = None) -> None:
    manifest = {
        "name": PACKAGE_PREFIX,
        "version": TOOL_VERSION,
        "platform": PACKAGE_PLATFORM,
        "source_revision": revision,
        "public_commands": ["rdc-tool"],
        "entrypoints": ["bin/rdc-tool.cmd", "bin/rdc-tool", "cli/run_cli.py", "install.cmd"],
        "file_count": len(files),
        "files": files,
    }
    licenses = _license_inventory(staging_root)
    runtime_manifest = json.loads((staging_root / "binaries/windows/x64/manifest.runtime.json").read_text(encoding="utf-8"))
    for name, tool in runtime_manifest.get("bundled_tools", {}).items():
        licenses.append({"name": name, **tool})
    sbom = {
        "schema": "rdc-tool.sbom.v1",
        "name": PACKAGE_PREFIX,
        "version": TOOL_VERSION,
        "platform": PACKAGE_PLATFORM,
        "source_revision": revision,
        "components": licenses,
    }
    manifest_name = "RELEASE_MANIFEST.json"
    if candidate_source is not None:
        manifest_name = "CANDIDATE_MANIFEST.json"
        manifest["kind"] = "local_validation_candidate"
        manifest["source_snapshot"] = candidate_source
        sbom["kind"] = "local_validation_candidate"
        sbom["source_snapshot"] = candidate_source
    write_text(staging_root / "LICENSE_INVENTORY.json", json.dumps(licenses, ensure_ascii=False, indent=2) + "\n")
    write_text(staging_root / "SBOM.json", json.dumps(sbom, ensure_ascii=False, indent=2) + "\n")
    if candidate_source is not None:
        manifest["files"] = [*files, *[{"path": name, "size": (staging_root / name).stat().st_size,
                                      "sha256": _sha256(staging_root / name)}
                                     for name in ("LICENSE_INVENTORY.json", "SBOM.json")]]
        manifest["file_count"] = len(manifest["files"])
    write_text(staging_root / manifest_name, json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")


def _candidate_source(root: Path) -> dict[str, str]:
    def git(*args: str) -> bytes:
        return subprocess.check_output(["git", "-C", str(root), *args])
    return {"base_revision": git("rev-parse", "HEAD").decode("ascii").strip(),
            "working_diff_sha256": hashlib.sha256(git("diff", "--binary", "HEAD", "--", ".", ":!binaries")).hexdigest()}


def _build_candidate(root: Path, raw_destination: str, *, runtime_root: Path | None = None) -> int:
    destination = task_directory(root, raw_destination, label="local candidate", new=True)
    if runtime_root is not None and (runtime_root.is_relative_to(destination) or destination.is_relative_to(runtime_root)):
        raise ValueError("Candidate output overlaps the runtime input root")
    before = _candidate_source(root)
    status = native_manifest_status(runtime_root or root)
    if status["status"] != "verified":
        raise RuntimeError(f"Local candidate requires a verified paired native build: {status}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".candidate-stage-", dir=destination.parent) as temporary:
        staged = Path(temporary) / PACKAGE_PREFIX
        staged.mkdir()
        files = _copy_release_tree(root, staged, runtime_root=runtime_root) if runtime_root is not None else _copy_release_tree(root, staged)
        if _candidate_source(root) != before:
            raise RuntimeError("Source changed while the candidate was copied")
        for item in files:
            source_root = runtime_root if runtime_root is not None and str(item["path"]).startswith("binaries/") else root
            path = source_root / str(item["path"])
            if path.stat().st_size != item["size"] or _sha256(path) != item["sha256"]:
                raise RuntimeError(f"Source input changed while packaging: {item['path']}")
        source = {**before, "shipped_source_sha256": source_file_digest(files)}
        _write_release_metadata(staged, files, before["base_revision"], candidate_source=source)
        from scripts.verify_release_package import _verify_release_identity, _verify_release_manifest, _verify_license_inventory
        _verify_release_manifest(staged, manifest_name="CANDIDATE_MANIFEST.json")
        _verify_license_inventory(staged)
        _verify_release_identity(staged, root, manifest_name="CANDIDATE_MANIFEST.json")
        staged.rename(destination)
    print(f"[candidate] complete local validation directory: {destination}")
    return 0


def _zip_dir(staging_root: Path, zip_path: Path) -> None:
    with zipfile.ZipFile(zip_path, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for path in sorted(staging_root.rglob("*")):
            if path.is_file():
                zf.write(path, arcname=f"{PACKAGE_PREFIX}/{path.relative_to(staging_root).as_posix()}")


def _qualify_source(root: Path) -> None:
    native = native_manifest_status(root)
    if native["status"] != "verified":
        raise RuntimeError(f"Release paired native runtime is not verified: {native}")
    from scripts.release_gate import main as source_gate
    print("[release] validating source and repository runtime", flush=True)
    if source_gate(["--report", "intermediate/logs/release_package_source_gate.md"]) != 0:
        raise RuntimeError("Release source qualification failed; no package accepted")


def _qualify_package(zip_path: Path) -> None:
    from scripts.verify_release_package import main as verify_package
    print("[release] validating complete staged archive", flush=True)
    if verify_package(["--zip", str(zip_path)]) != 0:
        raise RuntimeError("Release archive verification failed; no package accepted")


def _accept_release(staged_zip: Path, package_path: Path) -> None:
    metadata = ["SHA256SUMS", "release_report.md"]
    previous = {name: (package_path.parent / name).read_bytes()
                if (package_path.parent / name).exists() else None for name in metadata}
    accepted: list[Path] = []
    try:
        staged_zip.rename(package_path)
        accepted.append(package_path)
        for name in metadata:
            destination = package_path.parent / name
            (staged_zip.parent / name).replace(destination)
            accepted.append(destination)
    except BaseException:
        failures = []
        for destination in reversed(accepted):
            try:
                original = previous.get(destination.name)
                if original is None:
                    destination.unlink(missing_ok=True)
                else:
                    destination.write_bytes(original)
            except OSError as exc:
                failures.append(f"{destination}: {exc}")
        if failures:
            recovery = Path(tempfile.mkdtemp(prefix=".release-recovery-", dir=package_path.parent))
            for name, original in previous.items():
                if original is not None:
                    (recovery / name).write_bytes(original)
            raise RuntimeError(f"Release rollback incomplete: {failures}; original metadata saved in {recovery}")
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build rdc-tool release package")
    parser.add_argument("--out-dir", default="dist", help="Output directory under the rdc-tool root")
    parser.add_argument("--version", default=TOOL_VERSION, help="Expected package version")
    parser.add_argument("--candidate-dir", default="", help="Build a non-release local validation directory under intermediate/ or dist/")
    parser.add_argument("--runtime-root", default="", help="Candidate-only verified runtime root under intermediate/ or dist/")
    args = parser.parse_args(argv)

    if str(args.version) != TOOL_VERSION:
        print(f"[release] version mismatch: requested={args.version} package={TOOL_VERSION}")
        return 2

    root = _tools_root().resolve()
    if args.runtime_root and not args.candidate_dir:
        raise ValueError("--runtime-root is only valid with --candidate-dir")
    if args.candidate_dir:
        runtime = task_directory(root, args.runtime_root, label="candidate runtime root", new=False) if args.runtime_root else None
        return _build_candidate(root, str(args.candidate_dir), runtime_root=runtime)
    revision = _source_revision(root)
    _qualify_source(root)
    if _source_revision(root) != revision:
        raise RuntimeError("Release source changed during qualification")
    out_dir = (root / str(args.out_dir)).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    package_name = f"{PACKAGE_PREFIX}-{TOOL_VERSION}-{PACKAGE_PLATFORM}.zip"
    package_path = out_dir / package_name
    if package_path.exists():
        raise FileExistsError(f"Refusing to overwrite an existing release candidate: {package_path}")
    with tempfile.TemporaryDirectory(prefix=".release-stage-", dir=out_dir) as staging:
        staging_root = Path(staging) / PACKAGE_PREFIX
        staging_root.mkdir()
        files = _copy_release_tree(root, staging_root)
        _write_release_metadata(staging_root, files, revision)
        staged_zip = Path(staging) / package_name
        _zip_dir(staging_root, staged_zip)
        sha = _sha256(staged_zip)
        write_text(Path(staging) / "SHA256SUMS", f"{sha}  {package_name}\n")
        _qualify_package(staged_zip)
        if _source_revision(root) != revision:
            raise RuntimeError("Release source changed while packaging")
        for item in files:
            source = root / item["path"]
            if source.stat().st_size != item["size"] or _sha256(source) != item["sha256"]:
                raise RuntimeError(f"Release input changed while packaging: {item['path']}")
        report = [
            "# rdc-tool Release Report", "",
            f"- version: {TOOL_VERSION}", f"- platform: {PACKAGE_PLATFORM}",
            f"- package: {package_path}", f"- sha256: {sha}",
            f"- files: {len(files)}", "",
        ]
        write_text(Path(staging) / "release_report.md", "\n".join(report))
        _accept_release(staged_zip, package_path)
    print(f"[release] package: {package_path}")
    print(f"[release] sha256: {sha}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
