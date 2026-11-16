"""Business code never inspects the host OS; rdc_tool.platform owns every OS difference."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLATFORM = ROOT / "rdc_tool" / "platform"
SCANNED = ("rdc_tool", "cli", "scripts")

FORBIDDEN_MODULES = {"msvcrt", "fcntl", "winreg", "_winapi", "ctypes", "ctypes.wintypes"}
FORBIDDEN_ATTRIBUTES = {
    ("os", "name"), ("sys", "platform"), ("platform", "system"), ("os", "add_dll_directory"),
    ("os", "kill"), ("os", "killpg"), ("subprocess", "STARTUPINFO"), ("subprocess", "SW_HIDE"),
}
FORBIDDEN_ATTRIBUTE_PREFIXES = {("subprocess", "CREATE_"), ("subprocess", "STARTF_")}
FORBIDDEN_KEYWORDS = {"creationflags", "start_new_session", "startupinfo"}
FORBIDDEN_STRINGS = ("taskkill", "cmd.exe")

# Inside the platform package each OS mechanism has exactly one home.
PLATFORM_HOMES = {
    ("os", "name"): {"host.py"},
    ("sys", "platform"): {"host.py"},
    "msvcrt": {"_windows.py"},
    "fcntl": {"_posix.py"},
    "ctypes": {"_windows.py", "_windows_preview.py", "_posix.py"},
}


def _sources():
    for top in SCANNED:
        for path in sorted((ROOT / top).rglob("*.py")):
            if "__pycache__" not in path.parts:
                yield path


def _violations(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found += [f"import {alias.name}" for alias in node.names if alias.name in FORBIDDEN_MODULES]
        elif isinstance(node, ast.ImportFrom) and node.module in FORBIDDEN_MODULES:
            found.append(f"from {node.module} import")
        elif isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            pair = (node.value.id, node.attr)
            if pair in FORBIDDEN_ATTRIBUTES or any(
                node.value.id == base and node.attr.startswith(prefix) for base, prefix in FORBIDDEN_ATTRIBUTE_PREFIXES
            ):
                found.append(f"{node.value.id}.{node.attr}")
        elif isinstance(node, ast.keyword) and node.arg in FORBIDDEN_KEYWORDS:
            found.append(f"{node.arg}=")
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node.value == FORBIDDEN_STRINGS[0] or node.value.lower().endswith(FORBIDDEN_STRINGS[1]):
                found.append(repr(node.value))
    return [f"{path.relative_to(ROOT).as_posix()}:{item}" for item in found]


def test_business_code_never_branches_on_the_host_os():
    violations = [item for path in _sources() if PLATFORM not in path.parents for item in _violations(path)]
    assert violations == []


def test_each_os_mechanism_has_one_home_inside_the_platform_package():
    misplaced = []
    for path in sorted(PLATFORM.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        for node in ast.walk(tree):
            keys = []
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
                keys.append((node.value.id, node.attr))
            elif isinstance(node, ast.Import):
                keys += [alias.name.split(".")[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                keys.append(node.module.split(".")[0])
            for key in keys:
                homes = PLATFORM_HOMES.get(key)
                if homes is not None and path.name not in homes:
                    misplaced.append(f"{path.name}:{key}")
    assert misplaced == []


def test_gate_detects_each_violation_kind(tmp_path):
    sample = tmp_path / "sample.py"
    sample.write_text(
        "import os, subprocess, msvcrt\n"
        "x = os.name\n"
        "subprocess.Popen([], creationflags=subprocess.CREATE_NO_WINDOW)\n"
        "y = 'taskkill'\n",
        encoding="utf-8",
    )
    original = ROOT
    try:
        globals()["ROOT"] = tmp_path
        found = {item.split(":", 1)[1] for item in _violations(sample)}
    finally:
        globals()["ROOT"] = original
    assert {"import msvcrt", "os.name", "creationflags=", "subprocess.CREATE_NO_WINDOW", "'taskkill'"} <= found
