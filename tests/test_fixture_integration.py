"""Real replay of the committed captures through an installation's own launcher.

Opt in with --fixture-integration (and --fixture-root for another installation,
such as a local candidate). Once enabled, an installation that cannot replay
locally is a failure, never a skip.
"""
from __future__ import annotations

import json
import os
import subprocess
import uuid
from pathlib import Path

import pytest

from conftest import TEST_ROOT
from rdc_tool.platform import host as platform_host
from rdc_tool.platform import process
from rdc_tool.runtime_paths import host_layout

pytestmark = pytest.mark.fixture_integration
FIXTURES = Path(__file__).resolve().parent / "fixtures"


class Installation:
    def __init__(self, root: Path, state: Path) -> None:
        self.root, self.state = root, state

    def run(self, *args: str, timeout: int = 600) -> dict:
        env = {**os.environ, "RDC_TOOL_INTERMEDIATE_ROOT": str(self.state)}
        completed = subprocess.run([*process.launcher_argv(str(self.root / host_layout().launcher)), *args],
                                   cwd=self.state, env=env, capture_output=True, text=True, encoding="utf-8",
                                   errors="replace", timeout=timeout, check=False)
        start, end = completed.stdout.find("{"), completed.stdout.rfind("}")
        assert start >= 0, f"no JSON from {args}: exit={completed.returncode}\n{completed.stdout}{completed.stderr}"
        return json.loads(completed.stdout[start:end + 1])

    def call(self, context: str, operation: str, **arguments: object) -> dict:
        return self.run("--daemon-context", context, "call", operation, "--args-json", json.dumps(arguments))


@pytest.fixture(scope="module")
def installation(request: pytest.FixtureRequest) -> Installation:
    if not request.config.getoption("--fixture-integration"):
        pytest.skip("fixture integration is opt-in: pass --fixture-integration [--fixture-root <installation>]")
    state = TEST_ROOT / "fixture-integration" / uuid.uuid4().hex[:12]
    state.mkdir(parents=True)
    found = Installation(Path(request.config.getoption("--fixture-root")).resolve(), state)
    doctor = found.run("--json", "doctor", timeout=180)
    details = doctor.get("data") or (doctor.get("error") or {}).get("details") or {}
    renderdoc = details.get("renderdoc") or {}
    target = platform_host.host_target()
    usable = ((details.get("python") or {}).get("bundled_python_ok") is True
              and renderdoc.get("layout_ok") is True
              and (renderdoc.get("native_build") or {}).get("targets", {}).get(target) == "verified"
              and (renderdoc.get("loaded_runtime") or {}).get("status") != "mismatch")
    if not usable:
        pytest.fail(f"{found.root} cannot replay locally on {target}: {json.dumps(details)[:4000]}")
    return found


def _capability_or_ok(payload: dict) -> None:
    """A software driver may lack a capability; that must surface as a declared capability error, never a crash."""
    assert payload["ok"] or (payload.get("error") or {}).get("category") == "capability", json.dumps(payload)[:2000]


@pytest.mark.parametrize("capture", ["vkcube.rdc", "vkcube_validation.rdc"])
def test_capture_replays_and_observes_through_the_launcher(installation: Installation, capture: str) -> None:
    context = f"fixture-{Path(capture).stem}-{uuid.uuid4().hex[:8]}"
    try:
        opened = installation.run("--daemon-context", context, "capture", "open", "--file", str(FIXTURES / capture),
                                  "--frame-index", "0")
        assert opened["ok"], json.dumps(opened)[:4000]
        session_id = opened["data"]["session_id"]
        tree = installation.call(context, "rd.event.get_action_tree", session_id=session_id)
        assert tree["ok"] and tree["data"], json.dumps(tree)[:2000]
        _capability_or_ok(installation.call(context, "rd.pipeline.get_state", session_id=session_id))
        image = installation.state / f"{context}.png"
        observed = installation.call(context, "rd.session.observe", out_path=str(image))
        _capability_or_ok(observed)
        if observed["ok"]:
            assert image.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
        closed = installation.call(context, "rd.capture.close_replay", session_id=session_id)
        assert closed["ok"], json.dumps(closed)[:2000]
    finally:
        installation.run("--daemon-context", context, "context", "clear", timeout=120)
        installation.run("--daemon-context", context, "daemon", "stop", timeout=120)
