from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

SUPPORTED_SCRIPTS = (
    "scripts/README.md",
    "scripts/check_markdown_health.py",
    "scripts/cleanup_workspace.py",
    "scripts/package_release.py",
    "scripts/package_runtime.py",
    "scripts/python-runtimes.json",
    "scripts/rdc_tool_install.ps1",
    "scripts/release_gate.py",
    "scripts/runtime-dependencies.lock",
    "scripts/smoke_cli.sh",
    "scripts/verify_release_package.py",
)

FORBIDDEN_SNIPPETS = (
    "Desktop",
    "platform-tools\\adb.exe",
    "e38b8019",
)


def test_supported_scripts_exist() -> None:
    for rel in SUPPORTED_SCRIPTS:
        assert (ROOT / rel).is_file(), rel


def test_supported_scripts_do_not_embed_machine_local_defaults() -> None:
    for rel in SUPPORTED_SCRIPTS:
        text = (ROOT / rel).read_text(encoding="utf-8-sig")
        lower_text = text.lower()
        assert "path.home()" not in text, rel
        for snippet in FORBIDDEN_SNIPPETS:
            assert snippet not in text, f"{rel}: {snippet}"
        assert "c:\\users\\" not in lower_text, rel
        assert "d:\\utility\\" not in lower_text, rel
