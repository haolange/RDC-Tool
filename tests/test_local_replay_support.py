from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from rdc_tool.core import session_manager as sm
from rdc_tool.core.errors import CoreError


class _Capture:
    def __init__(self, support: str) -> None:
        self.support = support
        self.opened_replay = False

    def OpenFile(self, path, filetype, progress):
        return SimpleNamespace(OK=lambda: True)

    def LocalReplaySupport(self):
        return self.support

    def DriverName(self):
        return "D3D11"

    def OpenCapture(self, options, progress):
        self.opened_replay = True
        return SimpleNamespace(OK=lambda: True), SimpleNamespace(CreateOutput=lambda data, kind: "output")


def _renderdoc(capture: _Capture) -> SimpleNamespace:
    return SimpleNamespace(
        OpenCaptureFile=lambda: capture,
        ReplaySupport=SimpleNamespace(Unsupported="unsupported", Supported="supported", SuggestRemote="suggest_remote"),
        ReplayOptions=lambda: object(),
        CreateHeadlessWindowingData=lambda width, height: object(),
        ReplayOutputType=SimpleNamespace(Texture=1),
    )


def _open(capture: _Capture, monkeypatch, pin_host) -> sm.SessionState:
    monkeypatch.setattr(sm, "_get_rd", lambda: _renderdoc(capture))
    pin_host("linux-x64")
    state = sm.SessionState(session_id="s1", backend_type=sm.BackendType.LOCAL)
    asyncio.run(sm.SessionManager()._open_local_capture(state, "/captures/frame.rdc"))
    return state


def test_unsupported_local_api_fails_before_any_replay_is_created(monkeypatch, pin_host):
    capture = _Capture("unsupported")
    with pytest.raises(CoreError) as raised:
        _open(capture, monkeypatch, pin_host)
    error = raised.value
    assert (error.code, error.category) == ("local_replay_unsupported", "capability")
    assert error.details["capture_api"] == "D3D11"
    assert error.details["host_target"] == "linux-x64"
    assert "rd.remote.connect" in error.details["recovery_hint"]
    assert not capture.opened_replay


@pytest.mark.parametrize("support", ["supported", "suggest_remote"])
def test_locally_replayable_capture_opens(monkeypatch, pin_host, support):
    capture = _Capture(support)
    state = _open(capture, monkeypatch, pin_host)
    assert capture.opened_replay
    assert state.capture_file is capture and state.output == "output"
