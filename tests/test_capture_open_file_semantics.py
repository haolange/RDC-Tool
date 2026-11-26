from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from rdc_tool.context_snapshot import clear_context_snapshot
from rdc_tool.runtime_state import clear_context_state
from rdc_tool.runtime import action_index, live_state, preview_sync, renderdoc_api, visual_target
from rdc_tool.runtime.operations import capture as capture_ops


class _FakeCaptureFile:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def OpenFile(self, path: str, *_args) -> str:
        self.calls.append(f"OpenFile:{path}")
        return "ok"

    def DriverName(self) -> str:
        self.calls.append("DriverName")
        return "D3D12"

    def OpenCapture(self, *_args):
        raise AssertionError("rd.capture.open_file must not call OpenCapture")

    def CloseFile(self) -> None:
        self.calls.append("CloseFile")


@pytest.mark.parametrize('action', ['open_file', 'close_file', 'get_info', 'open_replay'])
def test_missing_capture_rejected_before_effects(monkeypatch, tmp_path, action):
    owned = live_state.CaptureFileHandle(capture_file_id='owned', file_path='owned.rdc', read_only=True)
    monkeypatch.setattr(live_state._runtime, 'captures', {'owned': owned})
    monkeypatch.setattr(live_state._runtime, 'replays', {
        'session': live_state.ReplayHandle(session_id='session', capture_file_id='owned', active_event_id=1),
    })
    monkeypatch.setattr(live_state._runtime, 'context_states', {
        live_state._runtime_context_id(): {'current_session_id': 'session', 'sessions': {}},
    })
    args = {'file_path': str(tmp_path / 'missing.rdc')} if action == 'open_file' else {'capture_file_id': 'missing'}
    result = asyncio.run(capture_ops.dispatch(action, args))
    assert not result.ok
    assert result.code == 'capture_file_not_found'
    assert result.category == 'validation'
    assert result.details['effects_attempted'] is False
    assert result.details['context_preserved'] is True
    assert live_state._runtime.captures == {'owned': owned}


def test_dispatch_capture_open_file_does_not_open_replay(monkeypatch, tmp_path) -> None:
    original_captures = dict(live_state._runtime.captures)
    fake_capture = _FakeCaptureFile()
    sample = tmp_path / "sample.rdc"
    sample.write_bytes(b"rdc")

    async def _inline_offload(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    monkeypatch.setattr(renderdoc_api, "_offload", _inline_offload)
    monkeypatch.setattr(renderdoc_api, "_check_status", lambda status, operation, **kwargs: None)
    monkeypatch.setattr(renderdoc_api, "_get_rd", lambda: SimpleNamespace(OpenCaptureFile=lambda: fake_capture))

    clear_context_snapshot()
    clear_context_state()
    live_state._runtime.context_snapshots.clear()
    live_state._runtime.context_states.clear()
    live_state._runtime.hydrated_contexts.clear()
    live_state._runtime.captures.clear()
    try:
        payload = asyncio.run(capture_ops.dispatch("open_file", {"file_path": str(sample)}))
        assert payload.ok is True
        assert payload.data['driver'] == "D3D12"
        assert fake_capture.calls == [f"OpenFile:{sample}", "DriverName", "CloseFile"]
    finally:
        clear_context_snapshot()
        clear_context_state()
        live_state._runtime.context_snapshots.clear()
        live_state._runtime.context_states.clear()
        live_state._runtime.hydrated_contexts.clear()
        live_state._runtime.captures.clear()
        live_state._runtime.captures.update(original_captures)


def test_dispatch_capture_open_replay_returns_after_ready_state_without_preview_sync(monkeypatch, tmp_path) -> None:
    original_captures = dict(live_state._runtime.captures)
    original_replays = dict(live_state._runtime.replays)
    original_session_manager = live_state._session_manager
    sample = tmp_path / "sample.rdc"
    sample.write_bytes(b"rdc")

    class _FakeController:
        def GetRootActions(self):  # noqa: N802
            return []

        def GetAPIProperties(self):  # noqa: N802
            raise AssertionError("open_replay should not wait for API properties after ready state")

    class _FakeSessionManager:
        def __init__(self) -> None:
            self.controller = _FakeController()

        async def create_session(self, *, backend_config, replay_config):  # type: ignore[no-untyped-def]
            return SimpleNamespace(session_id="sess_demo")

        async def open_capture(self, session_id: str, rdc_path: str):  # type: ignore[no-untyped-def]
            assert session_id == "sess_demo"
            assert rdc_path == str(sample)
            return SimpleNamespace(frame_count=1)

        def get_controller(self, session_id: str):  # type: ignore[no-untyped-def]
            assert session_id == "sess_demo"
            return self.controller

        def get_state(self, session_id: str):  # type: ignore[no-untyped-def]
            return SimpleNamespace(retained_transfer_dirs=[], transfer_progress=None)

        async def close_session(self, session_id: str) -> None:
            raise AssertionError("open_replay success should not close the session")

    async def _inline_offload(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    async def _pick_previewable_default_event_id(*_args, **_kwargs) -> int:
        return 147

    async def _unexpected_preview_sync(*_args, **_kwargs) -> None:
        raise AssertionError("open_replay should not auto-sync preview before returning")

    monkeypatch.setattr(renderdoc_api, "_offload", _inline_offload)
    monkeypatch.setattr(action_index, "_pick_default_event_id", lambda _roots: 147)
    monkeypatch.setattr(visual_target, "_pick_previewable_default_event_id", _pick_previewable_default_event_id)
    monkeypatch.setattr(preview_sync, "_auto_sync_preview_if_enabled", _unexpected_preview_sync)

    clear_context_snapshot()
    clear_context_state()
    live_state._runtime.context_snapshots.clear()
    live_state._runtime.context_states.clear()
    live_state._runtime.hydrated_contexts.clear()
    live_state._runtime.captures.clear()
    live_state._runtime.replays.clear()
    live_state._runtime.captures["capf_demo"] = live_state.CaptureFileHandle(
        capture_file_id="capf_demo",
        file_path=str(sample),
        read_only=True,
        driver="D3D12",
    )
    live_state._session_manager = _FakeSessionManager()
    try:
        payload = asyncio.run(capture_ops.dispatch("open_replay", {"capture_file_id": "capf_demo", "options": {}}))

        assert payload.ok is True
        assert payload.data['session_id'] == "sess_demo"
        assert payload.data['capture_file_id'] == "capf_demo"
        assert payload.data['active_event_id'] == 147
        assert payload.data['recovery_status'] == "ready"
        assert payload.data['api_properties'] == {}
    finally:
        clear_context_snapshot()
        clear_context_state()
        live_state._runtime.context_snapshots.clear()
        live_state._runtime.context_states.clear()
        live_state._runtime.hydrated_contexts.clear()
        live_state._runtime.captures.clear()
        live_state._runtime.captures.update(original_captures)
        live_state._runtime.replays.clear()
        live_state._runtime.replays.update(original_replays)
        live_state._session_manager = original_session_manager

def test_dispatch_capture_open_replay_reuses_live_session_for_same_capture(monkeypatch, tmp_path) -> None:
    original_captures = dict(live_state._runtime.captures)
    original_replays = dict(live_state._runtime.replays)
    original_session_manager = live_state._session_manager
    sample = tmp_path / "sample.rdc"
    sample.write_bytes(b"rdc")

    class _UnexpectedSessionManager:
        async def create_session(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            raise AssertionError("live same-capture replay should be reused")

        async def open_capture(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            raise AssertionError("live same-capture replay should be reused")

    clear_context_snapshot()
    clear_context_state()
    live_state._runtime.context_snapshots.clear()
    live_state._runtime.context_states.clear()
    live_state._runtime.hydrated_contexts.clear()
    live_state._runtime.captures.clear()
    live_state._runtime.replays.clear()
    live_state._runtime.captures["capf_demo"] = live_state.CaptureFileHandle(
        capture_file_id="capf_demo",
        file_path=str(sample),
        read_only=True,
        driver="D3D12",
    )
    live_state._runtime.replays["sess_live"] = live_state.ReplayHandle(
        session_id="sess_live",
        capture_file_id="capf_demo",
        frame_index=0,
        active_event_id=7010,
    )
    live_state._session_manager = _UnexpectedSessionManager()
    try:
        payload = asyncio.run(capture_ops.dispatch("open_replay", {"capture_file_id": "capf_demo", "options": {}}))

        assert payload.ok is True
        assert payload.data['session_id'] == "sess_live"
        assert payload.data['capture_file_id'] == "capf_demo"
        assert payload.data['active_event_id'] == 7010
        assert payload.data['reused_session'] is True
    finally:
        clear_context_snapshot()
        clear_context_state()
        live_state._runtime.context_snapshots.clear()
        live_state._runtime.context_states.clear()
        live_state._runtime.hydrated_contexts.clear()
        live_state._runtime.captures.clear()
        live_state._runtime.captures.update(original_captures)
        live_state._runtime.replays.clear()
        live_state._runtime.replays.update(original_replays)
        live_state._session_manager = original_session_manager
