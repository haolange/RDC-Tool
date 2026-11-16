"""Every RDC_TOOL_* variable the code or scripts read is documented in docs/configuration.md."""
from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NAME = re.compile(r"RDC_TOOL_[A-Z0-9_]+")


def _python_names() -> set[str]:
    found = set()
    for path in [*(ROOT / "rdc_tool").rglob("*.py"), *(ROOT / "scripts").glob("*.py")]:
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8-sig"))):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and NAME.fullmatch(node.value):
                found.add(node.value)
    return found


def _shell_names() -> set[str]:
    """Variables a shell script reads from the environment with a default: ${NAME:-...}."""
    return {match.group(1) for path in (ROOT / "scripts").glob("*.sh")
            for match in re.finditer(r"\$\{(RDC_TOOL_[A-Z0-9_]+):-", path.read_text(encoding="utf-8"))}


def test_every_variable_the_code_reads_is_documented():
    documented = set(re.findall(r"`(RDC_TOOL_[A-Z0-9_]+)`", (ROOT / "docs/configuration.md").read_text(encoding="utf-8-sig")))
    assert sorted((_python_names() | _shell_names()) - documented) == []
