from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from scripts import package_release, verify_release_package


def _write(path: Path, content: str = "ok\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_package_release_builds_self_contained_zip(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "tools"
    for rel in (
        "AGENTS.md",
        "CHANGELOG.md",
        "LICENSE",
        "THIRD_PARTY_NOTICES.md",
        "README.md",
        "pyproject.toml",
        "bin/rdc-tool.cmd",
        "install.cmd",
        "bin/rdc-tool",
        "cli/run_cli.py",
        "docs/quickstart.md",
        "policy/README.md",
        "rdc_tool/__init__.py",
        "scripts/rdc_tool_install.ps1",
        "scripts/smoke_cli.sh",
        "scripts/verify_release_package.py",
        "spec/tool_catalog.json",
        "binaries/windows/x64/manifest.runtime.json",
    ):
        _write(root / rel)
    _write(root / "intermediate/logs/secret.log", "must not ship\n")
    _write(root / "tests/fixtures/sample.rdc", "fixture must not ship\n")
    _write(root / "docs/sample.rdc", "rdc suffix must not ship\n")

    monkeypatch.setattr(package_release, "_tools_root", lambda: root)

    rc = package_release.main(["--out-dir", "dist"])

    assert rc == 0
    package = next((root / "dist").glob("rdc-tool-*-windows-x64.zip"))
    assert (root / "dist" / "SHA256SUMS").is_file()
    with zipfile.ZipFile(package) as zf:
        names = set(zf.namelist())
        assert "rdc-tool/RELEASE_MANIFEST.json" in names
        assert "rdc-tool/SBOM.json" in names
        assert "rdc-tool/LICENSE_INVENTORY.json" in names
        assert "rdc-tool/pyproject.toml" in names
        assert "rdc-tool/scripts/rdc_tool_install.ps1" in names
        assert "rdc-tool/THIRD_PARTY_NOTICES.md" in names
        assert "rdc-tool/uv.lock" not in names
        assert not any(name.startswith("rdc-tool/tests/") for name in names)
        assert not any(name.lower().endswith(".rdc") for name in names)
        assert "rdc-tool/intermediate/logs/secret.log" not in names
        manifest = json.loads(zf.read("rdc-tool/RELEASE_MANIFEST.json").decode("utf-8"))
        license_inventory = json.loads(zf.read("rdc-tool/LICENSE_INVENTORY.json").decode("utf-8"))
        sbom = json.loads(zf.read("rdc-tool/SBOM.json").decode("utf-8"))
    project_license = next(row for row in license_inventory if row["name"] == "rdc-tool")
    project_component = next(row for row in sbom["components"] if row["name"] == "rdc-tool")
    assert project_license["license"] == "Apache-2.0"
    assert project_license["path"] == "LICENSE"
    assert project_component["license"] == "Apache-2.0"
    assert manifest["platform"] == "windows-x64"
    assert manifest["public_commands"] == ["rdc-tool"]
    assert sorted(manifest["entrypoints"]) == ["bin/rdc-tool", "bin/rdc-tool.cmd", "cli/run_cli.py", "install.cmd"]
    manifest_paths = {entry["path"] for entry in manifest["files"]}
    assert "pyproject.toml" in manifest_paths
    assert "uv.lock" not in manifest_paths
    assert not any(path == "tests" or path.startswith("tests/") for path in manifest_paths)
    assert not any(path.lower().endswith(".rdc") for path in manifest_paths)


def test_verify_release_package_accepts_manifest_public_command_split(tmp_path: Path) -> None:
    root = tmp_path / "rdc-tool"
    for rel in ("bin/rdc-tool.cmd", "bin/rdc-tool", "cli/run_cli.py", "install.cmd"):
        _write(root / rel)
    manifest = {
        "name": "rdc-tool",
        "version": "1.0.0",
        "platform": "windows-x64",
        "public_commands": ["rdc-tool"],
        "entrypoints": ["bin/rdc-tool.cmd", "bin/rdc-tool", "cli/run_cli.py", "install.cmd"],
        "files": [
            {"path": "bin/rdc-tool.cmd", "size": 3, "sha256": "0" * 64},
            {"path": "bin/rdc-tool", "size": 3, "sha256": "0" * 64},
            {"path": "cli/run_cli.py", "size": 3, "sha256": "0" * 64},
            {"path": "install.cmd", "size": 3, "sha256": "0" * 64},
        ],
    }
    _write(root / "RELEASE_MANIFEST.json", json.dumps(manifest))

    verify_release_package._verify_release_manifest(root)


def test_verify_release_package_rejects_manifest_without_public_command(tmp_path: Path) -> None:
    root = tmp_path / "rdc-tool"
    for rel in ("bin/rdc-tool.cmd", "bin/rdc-tool", "cli/run_cli.py", "install.cmd"):
        _write(root / rel)
    manifest = {
        "name": "rdc-tool",
        "version": "1.0.0",
        "platform": "windows-x64",
        "entrypoints": ["bin/rdc-tool.cmd", "bin/rdc-tool", "cli/run_cli.py", "install.cmd"],
        "files": [
            {"path": "bin/rdc-tool.cmd", "size": 3, "sha256": "0" * 64},
            {"path": "bin/rdc-tool", "size": 3, "sha256": "0" * 64},
            {"path": "cli/run_cli.py", "size": 3, "sha256": "0" * 64},
            {"path": "install.cmd", "size": 3, "sha256": "0" * 64},
        ],
    }
    _write(root / "RELEASE_MANIFEST.json", json.dumps(manifest))

    with pytest.raises(RuntimeError, match="public_commands"):
        verify_release_package._verify_release_manifest(root)


def test_verify_release_package_rejects_pre_ga_payload_path(tmp_path: Path) -> None:
    package = tmp_path / "rdc-tool-1.0.0-windows-x64.zip"
    pre_ga_path = "rdc-tool/rdc_tool/" + "runtime_" + "materializer.py"
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr(pre_ga_path, "pre-ga\n")

    with pytest.raises(RuntimeError, match="pre-GA path"):
        verify_release_package._verify_no_pre_ga_payload(package)


def test_verify_release_package_rejects_pre_ga_payload_marker(tmp_path: Path) -> None:
    package = tmp_path / "rdc-tool-1.0.0-windows-x64.zip"
    pre_ga_marker = "worker_" + "materialize"
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr("rdc-tool/binaries/windows/x64/manifest.runtime.json", '{"flag":"' + pre_ga_marker + '"}')

    with pytest.raises(RuntimeError, match="pre-GA marker"):
        verify_release_package._verify_no_pre_ga_payload(package)


def test_verify_release_package_rejects_manifest_with_rdc_fixture(tmp_path: Path) -> None:
    root = tmp_path / "rdc-tool"
    for rel in ("bin/rdc-tool.cmd", "bin/rdc-tool", "cli/run_cli.py", "install.cmd", "tests/fixtures/sample.rdc"):
        _write(root / rel)
    manifest = {
        "name": "rdc-tool",
        "version": "1.0.0",
        "platform": "windows-x64",
        "public_commands": ["rdc-tool"],
        "entrypoints": ["bin/rdc-tool.cmd", "bin/rdc-tool", "cli/run_cli.py", "install.cmd"],
        "files": [
            {"path": "bin/rdc-tool.cmd", "size": 3, "sha256": "0" * 64},
            {"path": "bin/rdc-tool", "size": 3, "sha256": "0" * 64},
            {"path": "cli/run_cli.py", "size": 3, "sha256": "0" * 64},
            {"path": "install.cmd", "size": 3, "sha256": "0" * 64},
            {"path": "tests/fixtures/sample.rdc", "size": 3, "sha256": "0" * 64},
        ],
    }
    _write(root / "RELEASE_MANIFEST.json", json.dumps(manifest))

    with pytest.raises(RuntimeError, match="test paths"):
        verify_release_package._verify_release_manifest(root)


def test_verify_release_package_checks_license_inventory_and_sbom(tmp_path: Path) -> None:
    root = tmp_path / "rdc-tool"
    _write(root / "LICENSE_INVENTORY.json", json.dumps([{"name": "rdc-tool", "version": "1.0.0", "license": "Apache-2.0", "path": "LICENSE"}]))
    _write(root / "SBOM.json", json.dumps({"components": [{"name": "rdc-tool", "version": "1.0.0", "license": "Apache-2.0", "path": "LICENSE"}]}))

    verify_release_package._verify_license_inventory(root)

    _write(root / "LICENSE_INVENTORY.json", json.dumps([{"name": "rdc-tool", "version": "1.0.0", "license": "MIT", "path": "LICENSE"}]))
    with pytest.raises(RuntimeError, match="license inventory mismatch"):
        verify_release_package._verify_license_inventory(root)
