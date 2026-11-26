#!/usr/bin/env python3
"""Verify a self-contained rdc-tool release zip in an extracted path."""

from __future__ import annotations

import argparse
import tomllib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

SCRIPT_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))

from scripts._shared import extract_json_payload
from scripts.release_runtime import isolated_release_runtime
from rdc_tool import __version__ as TOOL_VERSION
from rdc_tool.io_utils import sha256_file
from rdc_tool.platform import process
from rdc_tool.runtime_identity import native_manifest_status
from rdc_tool.runtime_paths import host_layout
from scripts.package_release import ENTRYPOINTS, SBOM_SCHEMA, certified_targets


PUBLIC_COMMAND = "rdc-tool"
EXPECTED_PUBLIC_COMMANDS = [PUBLIC_COMMAND]


def _run(cmd: list[str], cwd: Path, *, timeout_s: int = 180, env: dict[str, str] | None = None) -> tuple[int, str]:
    proc = subprocess.run(
        cmd,
        cwd=str(cwd),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout_s,
        env=env,
        check=False,
    )
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def _public_env(root: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["PATH"] = str(root / "bin") + os.pathsep + str(env.get("PATH") or "")
    pathext = str(env.get("PATHEXT") or "")
    if ".CMD" not in pathext.upper().split(";"):
        env["PATHEXT"] = pathext + (";" if pathext else "") + ".CMD"
    return env


def _run_public(root: Path, args: list[str], *, timeout_s: int = 180) -> tuple[int, str]:
    return _run([*process.launcher_argv(PUBLIC_COMMAND), *args], root, timeout_s=timeout_s, env=_public_env(root))


def _run_launcher_file(root: Path, args: list[str], *, timeout_s: int = 180) -> tuple[int, str]:
    return _run([*process.launcher_argv(str(root / host_layout().launcher)), *args], root, timeout_s=timeout_s)


def _expect_public_error(root: Path, args: list[str], expected_codes: set[str]) -> None:
    code, output = _run_public(root, args)
    payload = extract_json_payload(output)
    code_value = str(((payload or {}).get("error") or {}).get("code") or "")
    if code == 0 or code_value not in expected_codes:
        expected = ", ".join(sorted(expected_codes))
        raise RuntimeError(f"negative contract check expected one of {expected}: {PUBLIC_COMMAND} {' '.join(args)} exit={code} code={code_value}\n{output}")


def _find_package_root(extract_dir: Path) -> Path:
    candidates = [p for p in extract_dir.iterdir() if p.is_dir() and (p / "cli/run_cli.py").is_file()]
    if len(candidates) != 1:
        raise RuntimeError(f"expected one package root with cli/run_cli.py, found {len(candidates)}")
    return candidates[0]


def _extract_package(zip_path: Path, destination: Path) -> None:
    """Extract and restore each member's recorded mode, which ZipFile.extractall drops."""
    with zipfile.ZipFile(zip_path, "r") as archive:
        archive.extractall(destination)
        for info in archive.infolist():
            mode = (info.external_attr >> 16) & 0o777
            if mode and not info.is_dir():
                os.chmod(destination / info.filename, mode)


def _verify_release_manifest(root: Path, *, manifest_name: str = "RELEASE_MANIFEST.json") -> None:
    manifest_path = root / manifest_name
    if not manifest_path.is_file():
        raise RuntimeError(f"missing release manifest: {manifest_path}")
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if payload.get("public_commands") != EXPECTED_PUBLIC_COMMANDS:
        raise RuntimeError(f"release manifest public_commands mismatch: {payload.get('public_commands')!r}")
    entrypoints = payload.get("entrypoints")
    if sorted(entrypoints or []) != sorted(ENTRYPOINTS):
        raise RuntimeError(f"release manifest entrypoints mismatch: {entrypoints!r}")
    files = payload.get("files")
    if not isinstance(files, list):
        raise RuntimeError("release manifest files field is missing or invalid")
    paths = {str(item.get("path") or "") for item in files if isinstance(item, dict)}
    missing_entrypoints = [entry for entry in ENTRYPOINTS if entry not in paths or not (root / entry).is_file()]
    if missing_entrypoints:
        raise RuntimeError(f"release manifest missing physical entrypoints: {missing_entrypoints}")
    leaked_tests = sorted(path for path in paths if path == "tests" or path.startswith("tests/"))
    if leaked_tests:
        raise RuntimeError(f"release manifest exposes test paths: {leaked_tests[:5]}")
    leaked_rdc = sorted(path for path in paths if path.lower().endswith(".rdc"))
    if leaked_rdc:
        raise RuntimeError(f"release manifest exposes .rdc fixtures: {leaked_rdc[:5]}")


def _verify_release_identity(root: Path, source: Path = SCRIPT_ROOT,
                             *, manifest_name: str = "RELEASE_MANIFEST.json") -> None:
    if (root / "LICENSE").read_bytes() != (source / "LICENSE").read_bytes():
        raise RuntimeError("LICENSE bytes do not match release source")
    for name in (manifest_name, "SBOM.json"):
        payload = json.loads((root / name).read_text(encoding="utf-8"))
        if payload.get("version") != TOOL_VERSION:
            raise RuntimeError(f"{name} version does not match release source")
    inventory = json.loads((root / "LICENSE_INVENTORY.json").read_text(encoding="utf-8"))
    rows = [row for row in inventory if row.get("name") == "rdc-tool"]
    if len(rows) != 1 or rows[0].get("version") != TOOL_VERSION:
        raise RuntimeError("license inventory version does not match release source")
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    if project["project"]["version"] != TOOL_VERSION:
        raise RuntimeError("pyproject version does not match release source")
    layout = host_layout()
    metadata = list((root / layout.runtime_dir / layout.python["site_packages"]).glob("rdc_tool-*.dist-info/METADATA"))
    if len(metadata) != 1 or f"Version: {TOOL_VERSION}\n" not in metadata[0].read_text(encoding="utf-8"):
        raise RuntimeError("bundled distribution version does not match release source")
    sbom = json.loads((root / "SBOM.json").read_text(encoding="utf-8"))
    components = [row for row in sbom.get("components", []) if row.get("name") == "rdc-tool"]
    if len(components) != 1 or components[0].get("version") != TOOL_VERSION:
        raise RuntimeError("SBOM component version does not match release source")
    if f"## {TOOL_VERSION}" not in (root / "CHANGELOG.md").read_text(encoding="utf-8-sig"):
        raise RuntimeError("CHANGELOG missing release version")
    manifest = json.loads((root / manifest_name).read_text(encoding="utf-8"))
    revision = manifest.get('source_revision', '')
    if not isinstance(revision, str) or not re.fullmatch(r'[0-9a-f]{40}', revision):
        raise RuntimeError('release source_revision must be a complete Git commit')
    if sbom.get('source_revision') != revision:
        raise RuntimeError('SBOM source_revision does not match release manifest')
    for item in manifest["files"]:
        file = (root / item["path"]).resolve()
        if not file.is_relative_to(root.resolve()) or not file.is_file():
            raise RuntimeError("manifest path is missing or outside package")
        if file.stat().st_size != item["size"] or sha256_file(file) != item["sha256"]:
            raise RuntimeError(f"package bytes do not match manifest: {item['path']}")
    if manifest_name == "CANDIDATE_MANIFEST.json":
        from scripts.package_release import source_file_digest
        snapshot = manifest.get("source_snapshot")
        if manifest.get("kind") != "local_validation_candidate" or sbom.get("kind") != manifest["kind"]:
            raise RuntimeError("Local candidate must not claim release identity")
        if not isinstance(snapshot, dict) or snapshot != sbom.get("source_snapshot") or snapshot.get("base_revision") != revision:
            raise RuntimeError("Candidate source snapshot does not match its base/SBOM")
        for key in ("working_diff_sha256", "shipped_source_sha256"):
            if not re.fullmatch(r"[0-9a-f]{64}", str(snapshot.get(key) or "")):
                raise RuntimeError(f"Candidate source snapshot is missing {key}")
        if source_file_digest(manifest["files"]) != snapshot["shipped_source_sha256"]:
            raise RuntimeError("Candidate source file digest does not match its manifest")
        if (root / "RELEASE_MANIFEST.json").exists():
            raise RuntimeError("Local candidate contains a release manifest")
    native = native_manifest_status(root, required=certified_targets(root, candidate=manifest_name == "CANDIDATE_MANIFEST.json"))
    if native["status"] != "verified":
        raise RuntimeError(f"Package paired native runtime is not verified: {native}")


def _verify_archive_checksum(zip_path: Path) -> None:
    rows = (zip_path.parent / "SHA256SUMS").read_text(encoding="utf-8").splitlines()
    expected = [line.split()[0] for line in rows if len(line.split()) == 2 and line.split()[1] == zip_path.name]
    if len(expected) != 1 or expected[0] != sha256_file(zip_path):
        raise RuntimeError("release archive checksum mismatch")


def _verify_license_inventory(root: Path) -> None:
    inventory_path = root / "LICENSE_INVENTORY.json"
    sbom_path = root / "SBOM.json"
    if not inventory_path.is_file():
        raise RuntimeError(f"missing license inventory: {inventory_path}")
    if not sbom_path.is_file():
        raise RuntimeError(f"missing SBOM: {sbom_path}")
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    if not isinstance(inventory, list):
        raise RuntimeError("license inventory is not a list")
    project_rows = [row for row in inventory if isinstance(row, dict) and row.get("name") == "rdc-tool"]
    if not project_rows:
        raise RuntimeError("license inventory missing rdc-tool row")
    if project_rows[0].get("license") != "Apache-2.0" or project_rows[0].get("path") != "LICENSE":
        raise RuntimeError(f"rdc-tool license inventory mismatch: {project_rows[0]!r}")
    sbom = json.loads(sbom_path.read_text(encoding="utf-8"))
    if not isinstance(sbom, dict) or sbom.get("schema") != SBOM_SCHEMA:
        raise RuntimeError(f"SBOM schema is not {SBOM_SCHEMA!r}")
    components = sbom.get("components")
    if not isinstance(components, list):
        raise RuntimeError("SBOM components field is missing or invalid")
    sbom_rows = [row for row in components if isinstance(row, dict) and row.get("name") == "rdc-tool"]
    if not sbom_rows or sbom_rows[0].get("license") != "Apache-2.0":
        raise RuntimeError("SBOM does not report Apache-2.0 for rdc-tool")


def _verify_doctor(root: Path) -> None:
    code, output = _run_public(root, ["--json", "doctor"])
    payload = extract_json_payload(output)
    if code != 0 or not payload or payload.get("ok") is not True:
        raise RuntimeError(f"doctor failed: exit={code}\n{output}")
    if payload.get("result_kind") != "rdc_tool.doctor":
        raise RuntimeError(f"doctor returned wrong result_kind: {json.dumps(payload)[:500]}")


def _verify_physical_launcher_file(root: Path) -> None:
    code, output = _run_launcher_file(root, ["--json", "doctor"])
    payload = extract_json_payload(output)
    if code != 0 or not payload or payload.get("ok") is not True:
        raise RuntimeError(f"launcher file doctor failed: exit={code}\n{output}")
    if payload.get("result_kind") != "rdc_tool.doctor":
        raise RuntimeError(f"launcher file returned wrong result_kind: {json.dumps(payload)[:500]}")


def _verify_native_loader(root: Path) -> None:
    layout = host_layout()
    native_root = root / layout.runtime_dir
    python = native_root / layout.python["executable"]
    code = (
        "import sys,json;from pathlib import Path;sys.path.insert(0,str(Path.cwd()));"
        "from rdc_tool.runtime_bootstrap import bootstrap_renderdoc_runtime;"
        "report=bootstrap_renderdoc_runtime(probe_import=True);"
        "print(json.dumps({'import_ok':report.import_ok,'error':report.import_error,"
        "'loaded':report.loaded_runtime}))"
    )
    # Only the installation itself may supply the runtime: no inherited search paths or Python settings.
    env = {key: value for key, value in os.environ.items()
           if not key.upper().startswith(("PYTHON", "ANDROID_")) and key.upper() not in {"JAVA_HOME", "LD_LIBRARY_PATH"}}
    env["PATH"] = os.defpath
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    rc, output = _run([str(python), "-B", "-c", code], root, env=env)
    payload = extract_json_payload(output)
    loaded = (payload or {}).get("loaded") or {}
    expected = {"python": python, "native": native_root / layout.native_library,
                "binding": native_root / layout.binding_module}
    paths_match = all(Path(str((loaded.get(key) or {}).get("path", ""))).resolve() == path.resolve()
                      for key, path in expected.items())
    if (rc != 0 or (payload or {}).get("import_ok") is not True
            or loaded.get("configured_paths_match") is not True or not paths_match):
        raise RuntimeError(f"Bundled native loader failed: exit={rc}\n{output}")


def _verify_version_payload(root: Path) -> None:
    code, output = _run_public(root, ["version", "--json"])
    payload = extract_json_payload(output)
    data = payload.get("data") if isinstance(payload, dict) else {}
    if code != 0 or not payload or payload.get("ok") is not True or not isinstance(data, dict):
        raise RuntimeError(f"version --json failed: exit={code}\n{output}")
    if data.get("public_commands") != EXPECTED_PUBLIC_COMMANDS:
        raise RuntimeError(f"version public_commands mismatch: {data.get('public_commands')!r}")
    if data.get("tool_version") != TOOL_VERSION:
        raise RuntimeError("runtime version does not match release source")
    catalog = data.get("catalog")
    if not isinstance(catalog, dict) or not catalog.get("fingerprint") or not isinstance(catalog.get("tool_count"), int):
        raise RuntimeError(f"version catalog identity missing: {json.dumps(data)[:500]}")
    entrypoints = data.get("entrypoints")
    if not isinstance(entrypoints, dict) or "windows_cmd" not in entrypoints or "posix_shell" not in entrypoints or "python_cli" not in entrypoints:
        raise RuntimeError(f"version entrypoints missing physical launchers: {json.dumps(data)[:500]}")


def _verify_tools_catalog(root: Path) -> None:
    code, output = _run_public(root, ["tools", "list", "--json"])
    payload = extract_json_payload(output)
    data = payload.get("data") if isinstance(payload, dict) else {}
    if code != 0 or not payload or payload.get("ok") is not True or not isinstance(data, dict):
        raise RuntimeError(f"tools list failed: exit={code}\n{output}")
    tools = data.get("tools")
    if not isinstance(tools, list):
        raise RuntimeError("tools list returned no tools array")
    catalog_path = root / "spec" / "tool_catalog.json"
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    expected_tools = catalog.get("tools")
    expected_count = int(catalog.get("tool_count") or len(expected_tools or []))
    if int(data.get("tool_count") or len(tools)) != expected_count:
        raise RuntimeError(f"tools list count differs from packaged catalog: {data.get('tool_count')!r} != {expected_count}")
    names = {str(item.get("name") or "") for item in tools if isinstance(item, dict)}
    expected_names = {str(item.get("name") or "") for item in expected_tools or [] if isinstance(item, dict)}
    if names != expected_names:
        raise RuntimeError(
            f"tools list differs from packaged catalog: missing={sorted(expected_names - names)[:5]} extra={sorted(names - expected_names)[:5]}"
        )


def _verify_cli_contract(root: Path) -> None:
    checks = [
        (["context", "status", "--json"], "rdc_tool.context.status"),
        (["context", "list", "--json"], "rd.session.list_contexts"),
        (["--daemon-context", "package-contract", "context", "update", "--key", "notes", "--value", "package-verify", "--json"], "rd.session.update_context"),
        (["--daemon-context", "package-contract", "context", "clear", "--json"], "rdc_tool.context.clear"),
        (["vfs", "ls", "--path", "/", "--format", "tsv"], ""),
    ]
    for args, result_kind in checks:
        code, output = _run_public(root, args)
        if code != 0:
            raise RuntimeError(f"contract check failed: {PUBLIC_COMMAND} {' '.join(args)} exit={code}\n{output}")
        if result_kind:
            payload = extract_json_payload(output)
            if not payload or payload.get("ok") is not True or payload.get("result_kind") != result_kind:
                raise RuntimeError(f"contract check returned wrong payload for {' '.join(args)}:\n{output}")
    negative_checks = [
        (["vfs", "tree", "--path", "/", "--format", "tsv"], {"projection_not_supported"}),
        (["call", "rd.session.get_context", "--format", "tsv"], {"tabular_projection_missing"}),
        (["--daemon-context", "package-empty", "diff", "pipeline", "--event-a", "1", "--event-b", "2"], {"session_required"}),
    ]
    for args, expected_codes in negative_checks:
        _expect_public_error(root, args, expected_codes)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify an rdc-tool release package")
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--zip", dest="zip_path", help="Release zip path")
    inputs.add_argument("--candidate-dir", help="Non-release local candidate directory")
    parser.add_argument("--metadata-only", action="store_true", help="Check package bytes and identities without starting CLI processes")
    args = parser.parse_args(argv)

    if args.candidate_dir:
        root = Path(args.candidate_dir).resolve()
        try:
            _verify_release_manifest(root, manifest_name="CANDIDATE_MANIFEST.json")
            _verify_license_inventory(root)
            _verify_release_identity(root, manifest_name="CANDIDATE_MANIFEST.json")
            if not args.metadata_only:
                with isolated_release_runtime(root):
                    _verify_native_loader(root)
                    _verify_doctor(root)
                    _verify_physical_launcher_file(root)
                    _verify_version_payload(root)
                    _verify_tools_catalog(root)
                    _verify_cli_contract(root)
        except Exception as exc:
            print(f"[verify] {exc}")
            return 1
        print(f"[verify] PASS local candidate: {root}")
        return 0

    zip_path = Path(args.zip_path).resolve()
    if not zip_path.is_file():
        print(f"[verify] missing package: {zip_path}")
        return 2

    temp_dir = Path(tempfile.mkdtemp(prefix="rdc-tool package verify "))
    try:
        _verify_archive_checksum(zip_path)
        _extract_package(zip_path, temp_dir)
        root = _find_package_root(temp_dir)
        _verify_release_manifest(root)
        _verify_license_inventory(root)
        _verify_release_identity(root)
        if not args.metadata_only:
            with isolated_release_runtime(root):
                _verify_native_loader(root)
                _verify_doctor(root)
                _verify_physical_launcher_file(root)
                _verify_version_payload(root)
                _verify_tools_catalog(root)
                _verify_cli_contract(root)
    except Exception as exc:  # noqa: BLE001
        print(f"[verify] {exc}")
        return 1
    finally:
        shutil.rmtree(temp_dir)

    print(f"[verify] PASS: {zip_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
