from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("RDC_TOOL_INTERMEDIATE_ROOT", str(ROOT / "intermediate" / "tool-convergence-tests"))
DEFAULT_FIXTURE_DEVICES = "nvidia-vulkan"
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


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("fixture integration", "real replay of committed captures through an installation's launcher")
    group.addoption("--fixture-integration", action="store_true",
                    help="Run fixture_integration tests; an unusable runtime then fails instead of skipping.")
    group.addoption("--fixture-root", default=str(ROOT),
                    help="Installation root whose launcher and runtime the integration tests use (default: this checkout).")
    group.addoption("--fixture-devices", default=DEFAULT_FIXTURE_DEVICES,
                    help="Comma-separated device classes this machine can replay (tests/fixtures/fixtures.json `device`); "
                         "a compatible software Vulkan host passes `software-vulkan`.")


@pytest.fixture
def fake_renderdoc(monkeypatch):
    """Unit tests replay against the fake binding on every host; real replay is fixture_integration's job."""
    from fakes import renderdoc
    monkeypatch.setitem(sys.modules, "renderdoc", renderdoc)
    return renderdoc


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
