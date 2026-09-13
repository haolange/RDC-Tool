from __future__ import annotations

import asyncio
import json
from pathlib import Path

from rdx import server
from rdx.context_snapshot import clear_context_snapshot
from rdx.core.engine import ExecutionContext


def test_session_context_update_and_get_round_trip() -> None:
    clear_context_snapshot()
    server._runtime.context_snapshots.clear()
    try:
        update_payload = asyncio.run(
            server.dispatch_operation("rd.session.update_context", {"key": "focus_pixel", "value": "12,34"}, transport="test")
        )
        assert update_payload["ok"] is True
        assert update_payload["data"]["focus"]["pixel"] == {"x": 12, "y": 34}

        get_payload = asyncio.run(server.dispatch_operation("rd.session.get_context", {}, transport="test"))
        assert get_payload["ok"] is True
        assert get_payload["data"]["focus"]["pixel"] == {"x": 12, "y": 34}
        removed_field = "runtime_" + "parallelism_" + "ceiling"
        assert removed_field not in get_payload["data"]
        assert get_payload["data"]["session_locator"] == {"rdc_path": "", "session_id": "", "frame_index": 0, "active_event_id": 0}

        invalid_payload = asyncio.run(
            server.dispatch_operation("rd.session.update_context", {"key": "session_id", "value": "sess_demo"}, transport="test")
        )
        assert invalid_payload["ok"] is False
        assert "runtime-owned" in invalid_payload["error"]["message"]
    finally:
        clear_context_snapshot()
        server._runtime.context_snapshots.clear()


def test_postprocess_context_snapshot_tracks_recent_artifacts(tmp_path: Path) -> None:
    clear_context_snapshot()
    server._runtime.context_snapshots.clear()
    artifact_path = tmp_path / "artifact.txt"
    artifact_path.write_text("ok", encoding="utf-8")
    payload = {
        "ok": True,
        "artifacts": [{"path": str(artifact_path), "type": "saved_path"}],
        "meta": {},
    }
    ctx = ExecutionContext(transport="test", remote=False, metadata={"context_id": "default"})
    try:
        server._postprocess_context_snapshot("rd.export.buffer", {}, payload, ctx)
        get_payload = asyncio.run(server.dispatch_operation("rd.session.get_context", {}, transport="test"))
        artifacts = get_payload["data"]["last_artifacts"]
        assert artifacts
        assert artifacts[0]["path"] == str(artifact_path)
        assert artifacts[0]["source_tool"] == "rd.export.buffer"
    finally:
        clear_context_snapshot()
        server._runtime.context_snapshots.clear()


def test_removed_pixel_explanation_macro_is_not_dispatchable() -> None:
    clear_context_snapshot()
    server._runtime.context_snapshots.clear()

    try:
        payload = asyncio.run(
            server.dispatch_operation(
                "rd.macro.explain_pixel",
                {"session_id": "sess_demo", "x": 5, "y": 9},
                transport="test",
            )
        )
        assert payload["ok"] is False
        assert payload["error"]["code"] == "not_found"
    finally:
        clear_context_snapshot()
        server._runtime.context_snapshots.clear()


def test_dispatch_operation_respects_explicit_context_id() -> None:
    clear_context_snapshot('ctx-demo')
    server._runtime.context_snapshots.clear()
    try:
        payload = asyncio.run(
            server.dispatch_operation(
                'rd.session.update_context',
                {'key': 'notes', 'value': 'ctx-demo-note'},
                transport='test',
                context_id='ctx-demo',
            )
        )
        assert payload['ok'] is True
        follow_up = asyncio.run(
            server.dispatch_operation(
                'rd.session.get_context',
                {},
                transport='test',
                context_id='ctx-demo',
            )
        )
        assert follow_up['ok'] is True
        assert follow_up['data']['context_id'] == 'ctx-demo'
        assert follow_up['data']['notes'] == 'ctx-demo-note'
    finally:
        clear_context_snapshot('ctx-demo')
        server._runtime.context_snapshots.clear()
