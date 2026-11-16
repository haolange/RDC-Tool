from __future__ import annotations

import ast
from pathlib import Path

import pytest

from rdc_tool import runtime_catalog
from rdc_tool.operation_definitions import OPERATIONS

ROOT = Path(__file__).resolve().parents[1]


def _code_strings(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    docstrings = {id(node.body[0].value) for node in ast.walk(tree)
                  if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                  and node.body and isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant)}
    return {node.value for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings}


def test_runtime_never_reads_the_generated_catalog():
    readers = [path.relative_to(ROOT).as_posix() for path in (ROOT / "rdc_tool").rglob("*.py")
               if any("tool_catalog.json" in text for text in _code_strings(path))]
    assert readers == []


def test_operation_index_is_the_code_owned_definitions_and_immutable():
    assert list(runtime_catalog.OPERATION_INDEX) == [tool["name"] for tool in OPERATIONS]
    with pytest.raises(TypeError):
        runtime_catalog.OPERATION_INDEX["rd.fake"] = {}  # type: ignore[index]


def test_describe_operation_returns_a_caller_owned_copy():
    copy = runtime_catalog.describe_operation("rd.core.get_config")
    copy["description"] = "changed"
    assert runtime_catalog.OPERATION_INDEX["rd.core.get_config"]["description"] != "changed"
    with pytest.raises(ValueError, match="Unknown operation"):
        runtime_catalog.describe_operation("rd.missing.operation")
