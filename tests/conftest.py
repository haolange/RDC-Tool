from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("RDC_TOOL_INTERMEDIATE_ROOT", str(ROOT / "intermediate" / "tool-convergence-tests"))
TEST_ROOT = Path(os.environ["RDC_TOOL_INTERMEDIATE_ROOT"])
PYTEST_OUT = TEST_ROOT / "pytest"
PYTEST_OUT.mkdir(parents=True, exist_ok=True)

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rdc_tool.context_snapshot import clear_context_snapshot
from rdc_tool.platform import host as platform_host
from rdc_tool.runtime_paths import cli_runtime_dir
from rdc_tool.runtime_state import clear_context_state

os.environ.setdefault("RDC_TOOL_ARTIFACT_DIR", str(TEST_ROOT / "artifacts"))


@pytest.fixture
def pin_host(monkeypatch):
    """Make every host-dependent decision see one target, e.g. a windows-x64 package built by a test on Linux."""
    def pin(target: str) -> None:
        monkeypatch.setattr(platform_host, "host_target", lambda: target)
    return pin


@pytest.fixture(autouse=True)
def _isolate_runtime_state() -> None:
    state_dir = cli_runtime_dir()
    state_dir.mkdir(parents=True, exist_ok=True)
    for pattern in ("runtime_state*.json", "runtime_logs*.jsonl", "context_snapshot*.json"):
        for path in state_dir.glob(pattern):
            path.unlink(missing_ok=True)
    clear_context_state("default")
    clear_context_snapshot("default")
    try:
        yield
    finally:
        for pattern in ("runtime_state*.json", "runtime_logs*.jsonl", "context_snapshot*.json"):
            for path in state_dir.glob(pattern):
                path.unlink(missing_ok=True)
        clear_context_state("default")
        clear_context_snapshot("default")
