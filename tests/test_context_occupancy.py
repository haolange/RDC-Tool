from __future__ import annotations

import pytest

from rdc_tool.core.errors import CoreError
from rdc_tool.runtime_state import default_context_state, list_context_ids, save_context_state
from rdc_tool.server_runtime import _ensure_context_capacity


def test_empty_state_files_do_not_consume_capacity() -> None:
    for index in range(8):
        ctx = f"empty-{index}"
        save_context_state(default_context_state(ctx), ctx)
    assert len(list_context_ids()) >= 8
    _ensure_context_capacity("fresh-empty-ok")


def test_existing_namespace_reuses_without_capacity_check() -> None:
    save_context_state(default_context_state("kept"), "kept")
    _ensure_context_capacity("kept")


def test_eight_live_occupants_block_new_namespace(monkeypatch: pytest.MonkeyPatch) -> None:
    live = {f"live-{index}" for index in range(8)}
    monkeypatch.setattr("rdc_tool.daemon.client.list_occupying_context_ids", lambda: sorted(live))
    with pytest.raises(CoreError) as raised:
        _ensure_context_capacity("fresh-live-blocked")
    assert raised.value.code == "context_limit_exceeded"
    assert raised.value.details["max_contexts"] == 8
    assert raised.value.details["occupying_contexts"] == sorted(live)
    assert "fresh-live-blocked" not in raised.value.details["occupying_contexts"]
