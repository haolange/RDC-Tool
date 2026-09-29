from __future__ import annotations

import asyncio

from rdc_tool.core.engine import CoreEngine, ExecutionContext
from rdc_tool.core.operation_registry import OperationRegistry


def test_legacy_success_metadata_survives_canonical_envelope() -> None:
    async def handler(_args: dict, _context: dict) -> dict:
        return {
            "success": True,
            "width": 1920,
            "height": 1080,
            "meta": {
                "event_id": 202,
                "width": 1920,
                "height": 1080,
                "trace_id": "trc_untrusted",
                "transport": "untrusted",
                "duration_ms": -1,
            },
        }

    registry = OperationRegistry()
    registry.register("rd.export.screenshot", handler)
    result = asyncio.run(
        CoreEngine(registry=registry).execute(
            "rd.export.screenshot",
            context=ExecutionContext(transport="cli", trace_id="trc_meta_test"),
        )
    )

    assert result["ok"] is True
    assert result["data"]["width"] == 1920
    assert result["data"]["height"] == 1080
    assert result["meta"]["event_id"] == 202
    assert result["meta"]["width"] == 1920
    assert result["meta"]["height"] == 1080
    assert result["meta"]["trace_id"] == "trc_meta_test"
    assert result["meta"]["transport"] == "cli"
    assert result["meta"]["duration_ms"] >= 0


def test_legacy_success_ignores_non_object_metadata() -> None:
    async def handler(_args: dict, _context: dict) -> dict:
        return {"success": True, "value": 1, "meta": "not an object"}

    registry = OperationRegistry()
    registry.register("rd.test.result", handler)
    result = asyncio.run(CoreEngine(registry=registry).execute("rd.test.result"))

    assert result["ok"] is True
    assert result["data"] == {"value": 1}
    assert result["meta"]["transport"] == "core"
