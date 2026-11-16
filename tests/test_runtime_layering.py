"""Structure of rdc_tool/runtime: dependencies point down, routing covers the catalog exactly."""
from __future__ import annotations

import ast
import inspect
from pathlib import Path

from rdc_tool.operation_definitions import OPERATIONS
from rdc_tool.runtime import routing

ROOT = Path(__file__).resolve().parents[1] / "rdc_tool"
RUNTIME = ROOT / "runtime"
# The replay services restore and probe each other; this is the one cycle the runtime allows.
REPLAY_SERVICES = {"replay_access", "session_recovery", "shader_patches", "truth_matrix", "visual_target"}
TOP = {"routing", "dispatch", "worker_main"}


def _module(path: Path) -> str:
    return str(path.relative_to(RUNTIME).with_suffix("")).replace("/", ".")


def _runtime_imports(path: Path) -> set[str]:
    """Runtime modules imported at module level (function-local imports are deliberate re-entries)."""
    found = set()
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.ImportFrom) and node.module == "rdc_tool.runtime":
            found |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module == "rdc_tool.runtime.operations":
            found |= {f"operations.{alias.name}" for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and (node.module or "").startswith("rdc_tool.runtime."):
            found.add(node.module.removeprefix("rdc_tool.runtime."))
    return found


def _graph() -> dict[str, set[str]]:
    return {_module(path): _runtime_imports(path)
            for path in [*RUNTIME.glob("*.py"), *RUNTIME.glob("operations/*.py")] if path.name != "__init__.py"}


def _cycles(graph: dict[str, set[str]]) -> list[set[str]]:
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    stack: list[str] = []
    found: list[set[str]] = []

    def visit(node: str) -> None:
        index[node] = low[node] = len(index)
        stack.append(node)
        for target in graph[node]:
            if target not in index:
                visit(target)
                low[node] = min(low[node], low[target])
            elif target in stack:
                low[node] = min(low[node], index[target])
        if low[node] == index[node]:
            component = set()
            while True:
                member = stack.pop()
                component.add(member)
                if member == node:
                    break
            if len(component) > 1:
                found.append(component)

    for node in graph:
        if node not in index:
            visit(node)
    return found


def test_only_the_replay_services_form_a_cycle():
    assert _cycles(_graph()) == [REPLAY_SERVICES]


def test_services_never_import_operations_or_the_dispatch_layer():
    for module, imports in _graph().items():
        if module.startswith("operations.") or module in TOP:
            continue
        upward = {name for name in imports if name.startswith("operations.") or name in TOP}
        assert not upward, f"{module} imports {sorted(upward)}"


def _is_runtime(module: str) -> bool:
    return module == "rdc_tool.runtime" or module.startswith("rdc_tool.runtime.")


def test_code_outside_the_runtime_does_not_import_it():
    for path in ROOT.rglob("*.py"):
        if path.is_relative_to(RUNTIME) or "__pycache__" in path.parts:
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8-sig"))):
            if isinstance(node, ast.ImportFrom):
                assert not _is_runtime(node.module or ""), path
            elif isinstance(node, ast.Import):
                assert not any(_is_runtime(alias.name) for alias in node.names), path


def test_every_catalog_namespace_routes_to_a_dispatching_module():
    namespaces = {operation["name"].split(".")[1] for operation in OPERATIONS}
    assert set(routing.OPERATION_MODULES) == namespaces
    for module in routing.OPERATION_MODULES.values():
        assert inspect.iscoroutinefunction(module.dispatch), module.__name__


def test_each_namespace_handles_exactly_its_catalog_actions():
    catalog: dict[str, set[str]] = {}
    for operation in OPERATIONS:
        _, namespace, action = operation["name"].split(".")
        catalog.setdefault(namespace, set()).add(action)
    for namespace, module in routing.OPERATION_MODULES.items():
        handled = set()
        for node in ast.walk(ast.parse(Path(module.__file__).read_text(encoding="utf-8"))):
            if isinstance(node, ast.Compare) and isinstance(node.left, ast.Name) and node.left.id == "action":
                for op, value in zip(node.ops, node.comparators):
                    if isinstance(op, ast.Eq) and isinstance(value, ast.Constant):
                        handled.add(value.value)
                    elif isinstance(op, ast.In) and isinstance(value, (ast.Set, ast.Tuple, ast.List)):
                        handled |= {item.value for item in value.elts if isinstance(item, ast.Constant)}
        assert handled == catalog[namespace], namespace
