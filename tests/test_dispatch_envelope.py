from __future__ import annotations

import asyncio

from rdc_tool.runtime import dispatch, routing
from rdc_tool.runtime.live_state import ExecutionContext


def _route_returning(monkeypatch, result: object) -> None:
    async def route(operation: str, args: dict) -> object:
        return result
    monkeypatch.setattr(routing, "route", route)


def test_success_metadata_survives_canonical_envelope(monkeypatch) -> None:
    _route_returning(monkeypatch, {
        "success": True,
        "width": 1920,
        "height": 1080,
        "meta": {"event_id": 202, "width": 1920, "height": 1080, "trace_id": "trc_untrusted", "transport": "untrusted",
                 "duration_ms": -1},
    })
    result = asyncio.run(dispatch._execute("rd.export.screenshot", {}, ExecutionContext(transport="cli", trace_id="trc_meta_test")))

    assert result["ok"] is True
    assert result["data"]["width"] == 1920
    assert result["data"]["height"] == 1080
    assert result["meta"]["event_id"] == 202
    assert result["meta"]["width"] == 1920
    assert result["meta"]["height"] == 1080
    assert result["meta"]["trace_id"] == "trc_meta_test"
    assert result["meta"]["transport"] == "cli"
    assert result["meta"]["duration_ms"] >= 0


def test_success_ignores_non_object_metadata(monkeypatch) -> None:
    _route_returning(monkeypatch, {"success": True, "value": 1, "meta": "not an object"})
    result = asyncio.run(dispatch._execute("rd.test.result", {}, ExecutionContext()))

    assert result["ok"] is True
    assert result["data"] == {"value": 1}
    assert result["meta"]["transport"] == "core"
