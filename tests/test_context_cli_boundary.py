from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from rdc_tool.context_snapshot import clear_context_snapshot
from rdc_tool.runtime_state import clear_context_state
from rdc_tool.runtime import dispatch, live_state


@pytest.fixture(autouse=True)
def _reset_runtime_state() -> None:
    original_captures = dict(live_state._runtime.captures)
    original_replays = dict(live_state._runtime.replays)
    original_context_snapshots = dict(live_state._runtime.context_snapshots)
    original_context_states = dict(live_state._runtime.context_states)
    original_hydrated = set(live_state._runtime.hydrated_contexts)
    original_logs = list(live_state._runtime.logs)
    original_session_manager = live_state._session_manager
    original_bootstrapped = live_state._runtime_bootstrapped
    original_config = live_state._config
    for context_id in ("default", "ctx-alpha"):
        clear_context_snapshot(context_id)
        clear_context_state(context_id)
    live_state._runtime.captures.clear()
    live_state._runtime.replays.clear()
    live_state._runtime.context_snapshots.clear()
    live_state._runtime.context_states.clear()
    live_state._runtime.hydrated_contexts.clear()
    live_state._runtime.logs.clear()
    try:
        yield
    finally:
        for context_id in ("default", "ctx-alpha"):
            clear_context_snapshot(context_id)
            clear_context_state(context_id)
        live_state._runtime.captures = original_captures
        live_state._runtime.replays = original_replays
        live_state._runtime.context_snapshots = original_context_snapshots
        live_state._runtime.context_states = original_context_states
        live_state._runtime.hydrated_contexts = original_hydrated
        live_state._runtime.logs = original_logs
        live_state._session_manager = original_session_manager
        live_state._runtime_bootstrapped = original_bootstrapped
        live_state._config = original_config


def test_context_lifecycle_tools_report_session_locators() -> None:
    created = asyncio.run(
        dispatch.dispatch_operation(
            "rd.session.create_context",
            {"new_context_id": "ctx-alpha"},
            transport="test",
        )
    )
    assert created["ok"] is True
    assert created["data"]["context_id"] == "ctx-alpha"

    updated = asyncio.run(
        dispatch.dispatch_operation(
            "rd.session.update_context",
            {"key": "notes", "value": "alpha-notes", "context_id": "ctx-alpha"},
            transport="test",
        )
    )
    assert updated["ok"] is True
    assert updated["data"]["notes"] == "alpha-notes"

    default_snapshot = asyncio.run(dispatch.dispatch_operation("rd.session.get_context", {}, transport="test"))
    assert default_snapshot["ok"] is True
    assert default_snapshot["data"]["context_id"] == "default"
    assert default_snapshot["data"]["notes"] == ""
    assert default_snapshot["data"]["session_locator"] == {"rdc_path": "", "session_id": "", "frame_index": 0, "active_event_id": 0}

    listed = asyncio.run(dispatch.dispatch_operation("rd.session.list_contexts", {}, transport="test"))
    assert listed["ok"] is True
    contexts = listed["data"]["contexts"]
    context_ids = {item["context_id"] for item in contexts}
    assert {"default", "ctx-alpha"} <= context_ids
    assert all("session_locator" in item for item in contexts)

    selected = asyncio.run(
        dispatch.dispatch_operation(
            "rd.session.get_context",
            {},
            transport="test",
            context_id="ctx-alpha",
        )
    )
    assert selected["ok"] is True
    assert selected["data"]["context_id"] == "ctx-alpha"
    assert selected["data"]["notes"] == "alpha-notes"

    cleared = asyncio.run(
        dispatch.dispatch_operation(
            "rd.session.clear_context",
            {"target_context_id": "ctx-alpha"},
            transport="test",
        )
    )
    assert cleared["ok"] is True
    assert cleared["data"]["context_id"] == "ctx-alpha"
    assert cleared["data"]["notes"] == ""


def test_docs_and_catalog_describe_the_session_locator() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    for doc in ("README.md", "docs/session-model.md", "docs/agent-model.md"):
        assert "session_locator" in (repo_root / doc).read_text(encoding="utf-8-sig")
    catalog = json.loads((repo_root / "spec" / "tool_catalog.json").read_text(encoding="utf-8-sig"))
    tools = {item["name"]: item for item in catalog.get("tools") or []}
    assert "session_locator" in tools["rd.session.get_context"]["returns_raw"]
    assert "session_locator" in tools["rd.session.list_contexts"]["returns_raw"]
