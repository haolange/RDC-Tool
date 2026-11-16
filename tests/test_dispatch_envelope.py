from __future__ import annotations

import asyncio

import pytest

from rdc_tool.runtime import dispatch, envelope, routing
from rdc_tool.runtime.live_state import ExecutionContext


def _execute_returning(monkeypatch, outcome: object, operation: str = "rd.test.result", **context) -> dict:
    async def route(name: str, args: dict) -> object:
        return outcome
    monkeypatch.setattr(routing, "route", route)
    return asyncio.run(dispatch._execute(operation, {}, ExecutionContext(**context)))


def test_success_metadata_survives_but_cannot_override_envelope_fields(monkeypatch) -> None:
    outcome = envelope.success(width=1920, height=1080, meta={"event_id": 202, "trace_id": "trc_untrusted",
                                                            "transport": "untrusted", "duration_ms": -1})
    result = _execute_returning(monkeypatch, outcome, "rd.export.screenshot", transport="cli", trace_id="trc_meta_test")

    assert result["ok"] is True
    assert result["data"] == {"width": 1920, "height": 1080}
    assert result["meta"]["event_id"] == 202
    assert result["meta"]["trace_id"] == "trc_meta_test"
    assert result["meta"]["transport"] == "cli"
    assert result["meta"]["duration_ms"] >= 0


def test_failure_becomes_the_canonical_error(monkeypatch) -> None:
    outcome = envelope.failure("no replay", code="replay_missing", category="validation", details={"session_id": "s"})
    result = _execute_returning(monkeypatch, outcome)

    assert result["ok"] is False
    assert result["error"]["code"] == "replay_missing"
    assert result["error"]["category"] == "validation"
    assert result["error"]["message"] == "no replay"
    assert result["error"]["details"] == {"session_id": "s"}


@pytest.mark.parametrize("raw", [{"success": True, "value": 1}, '{"success": true}', None])
def test_anything_but_an_outcome_is_an_internal_error(monkeypatch, raw) -> None:
    result = _execute_returning(monkeypatch, raw)

    assert result["ok"] is False
    assert result["error"]["code"] == "internal_error"


def test_data_named_like_envelope_artifacts_stays_data(monkeypatch) -> None:
    listing = [{"artifact_path": "a.png"}]
    result = _execute_returning(monkeypatch, envelope.success(artifacts=listing), "rd.util.list_artifacts")

    assert result["data"]["artifacts"] == listing


def test_outcome_values_are_json_safe_once_built() -> None:
    outcome = envelope.success(value=float("nan"), items=(1, 2), name=type("Named", (), {"__str__": lambda self: "named"})())

    assert outcome.data == {"value": "NaN", "items": [1, 2], "name": {}}
    with pytest.raises(TypeError, match="envelope field names"):
        envelope.success(ok=True)
