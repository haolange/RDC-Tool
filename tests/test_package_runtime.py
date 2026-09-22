from __future__ import annotations

import json
from pathlib import Path

from scripts import package_runtime
from rdc_tool import __version__
from scripts.distribution_metadata import write_distribution_metadata


def _write(path: Path, content: bytes | str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf-8")


def test_package_runtime_bundles_python_and_excludes_dev_only_packages(tmp_path: Path, monkeypatch) -> None:
    tools_root = tmp_path / "tools"
    renderdoc_src = tools_root / "staging"
    python_home = tmp_path / "python-home"
    site_packages = tools_root / ".venv" / "Lib" / "site-packages"
    _write(tools_root / 'pyproject.toml', (Path(__file__).resolve().parents[1] / 'pyproject.toml').read_text(encoding='utf-8'))

    _write(renderdoc_src / "renderdoc.dll", b"renderdoc")
    _write(renderdoc_src / "renderdoc.json", "{}")
    _write(renderdoc_src / "pymodules" / "renderdoc.pyd", b"renderdoc-pyd")

    for name in ("python.exe", "pythonw.exe", "python3.dll", "python314.dll", "vcruntime140.dll", "vcruntime140_1.dll", "LICENSE.txt"):
        _write(python_home / name, b"x")
    _write(python_home / "DLLs" / "_socket.pyd", b"socket")
    _write(python_home / "Lib" / "os.py", "# os\n")
    _write(python_home / "Lib" / "site.py", "# site\n")
    _write(python_home / "Lib" / "encodings" / "__init__.py", "# enc\n")

    _write(site_packages / "numpy.libs" / "libopenblas.dll", b"blas")
    _write(site_packages / "pyarrow" / "__init__.py", "# should be excluded\n")
    _write(site_packages / "pyarrow.libs" / "arrow.dll", b"arrow")
    _write(site_packages / "pyarrow-12.0.0.dist-info" / "METADATA", "Name: pyarrow\n")
    _write(site_packages / "pytest" / "__init__.py", "# should be excluded\n")
    _write(site_packages / "pytest-9.0.0.dist-info" / "METADATA", "Name: pytest\n")

    monkeypatch.setattr(package_runtime, "_tools_root", lambda: tools_root)

    code = package_runtime.main(
        [
            "--source",
            "staging",
            "--python-home",
            str(python_home),
            "--site-packages-source",
            ".venv/Lib/site-packages",
            "--python-version",
            "3.14.3",
        ]
    )

    assert code == 0
    out_root = tools_root / "binaries" / "windows" / "x64"
    manifest = json.loads((out_root / "manifest.runtime.json").read_text(encoding="utf-8"))
    bundled_python = manifest["bundled_python"]
    assert bundled_python["python_version"] == "3.14.3"
    assert (out_root / bundled_python["python_entry"]).is_file()
    assert (out_root / bundled_python["pth_file"]).is_file()
    assert (out_root / "python" / "Lib" / "site-packages" / "numpy.libs" / "libopenblas.dll").is_file()
    assert not (out_root / "python" / "Lib" / "site-packages" / "pyarrow").exists()
    assert not (out_root / "python" / "Lib" / "site-packages" / "pyarrow.libs").exists()
    assert not (out_root / "python" / "Lib" / "site-packages" / "pytest").exists()
    indexed = {item["path"]: item for item in manifest["files"]}
    assert "python/python.exe" in indexed
    assert "renderdoc.dll" in indexed
    metadata = out_root / f'python/Lib/site-packages/rdc_tool-{__version__}.dist-info'
    assert 'Name: rdc-tool' in (metadata / 'METADATA').read_text(encoding='utf-8')
    assert not (metadata / 'direct_url.json').exists()
    assert 'rdc-tool = rdc_tool.cli:main' in (metadata / 'entry_points.txt').read_text(encoding='utf-8')
    assert b'\r' not in (metadata / 'RECORD').read_bytes()
    removed_field = "worker_" + "materialize"
    assert all(removed_field not in item for item in manifest["files"])


def test_metadata_upgrade_replaces_only_owned_previous_version(tmp_path: Path) -> None:
    import pytest
    root = Path(__file__).resolve().parents[1]
    previous = tmp_path / 'rdc_tool-0.0.0.dist-info'
    _write(previous / 'INSTALLER', 'rdc-tool-runtime\n')
    write_distribution_metadata(root, tmp_path)
    assert not previous.exists()
    assert len(list(tmp_path.glob('rdc_tool-*.dist-info'))) == 1
    _write(previous / 'INSTALLER', 'external-installer\n')
    with pytest.raises(RuntimeError, match='non-generated'):
        write_distribution_metadata(root, tmp_path)
    assert previous.exists()

def test_package_runtime_rejects_site_packages_source_inside_output_tree(tmp_path: Path, monkeypatch) -> None:
    tools_root = tmp_path / "tools"
    python_home = tmp_path / "python-home"
    site_packages = tools_root / "binaries" / "windows" / "x64" / "python" / "Lib" / "site-packages"

    for name in ("python.exe", "pythonw.exe", "python3.dll", "python314.dll", "vcruntime140.dll", "vcruntime140_1.dll", "LICENSE.txt"):
        _write(python_home / name, b"x")
    _write(python_home / "DLLs" / "_socket.pyd", b"socket")
    _write(python_home / "Lib" / "os.py", "# os\n")
    _write(python_home / "Lib" / "site.py", "# site\n")
    _write(python_home / "Lib" / "encodings" / "__init__.py", "# enc\n")
    _write(site_packages / "pydantic" / "__init__.py", "# runtime dep\n")

    monkeypatch.setattr(package_runtime, "_tools_root", lambda: tools_root)

    code = package_runtime.main(
        [
            "--python-home",
            str(python_home),
            "--site-packages-source",
            "binaries/windows/x64/python/Lib/site-packages",
            "--python-version",
            "3.14.3",
        ]
    )

    assert code == 1
