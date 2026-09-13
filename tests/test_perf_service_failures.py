from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from rdx.core import perf_service
from rdx.core.perf_service import PerfService


class _SessionManager:
    def __init__(self, controller: object) -> None:
        self._controller = controller

    def get_controller(self, session_id: str) -> object:
        return self._controller


def test_counter_operations_fail_when_renderdoc_runtime_is_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(perf_service, "_lazy_import_renderdoc", lambda: None)
    service = PerfService()
    sessions = _SessionManager(object())

    with pytest.raises(RuntimeError, match="counter query unavailable"):
        asyncio.run(service.enumerate_counters("sess_demo", sessions))
    with pytest.raises(RuntimeError, match="counter sampling unavailable"):
        asyncio.run(service.sample_counters("sess_demo", (1, 2), [1], sessions))
    with pytest.raises(RuntimeError, match="counter query unavailable"):
        asyncio.run(service.detect_hotspots("sess_demo", sessions))


def test_counter_fetch_failures_are_not_reported_as_empty_success(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Controller:
        def EnumerateCounters(self) -> list[int]:
            return [1]

        def DescribeCounter(self, counter: int) -> SimpleNamespace:
            return SimpleNamespace(name="EventGPUDuration", description="GPU duration", unit=1, resultType=1, resultByteWidth=8)

        def FetchCounters(self, counters: list[int]) -> list[object]:
            raise OSError("driver rejected counter fetch")

    async def _inline_offload(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    monkeypatch.setattr(perf_service, "_lazy_import_renderdoc", lambda: object())
    monkeypatch.setattr(PerfService, "_offload", staticmethod(_inline_offload))
    service = PerfService()
    sessions = _SessionManager(_Controller())

    with pytest.raises(RuntimeError, match="counter read failed"):
        asyncio.run(service.sample_counters("sess_demo", (1, 2), [1], sessions))
    with pytest.raises(RuntimeError, match="counter read failed"):
        asyncio.run(service.detect_hotspots("sess_demo", sessions))


def test_hotspots_top_k_zero_returns_all_events_in_microseconds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Controller:
        def EnumerateCounters(self) -> list[int]:
            return [7]

        def DescribeCounter(self, counter: int) -> SimpleNamespace:
            assert counter == 7
            return SimpleNamespace(
                name="EventGPUDuration",
                description="GPU duration",
                unit=1,  # renderdoc.CounterUnit.Seconds
                resultType=1,  # renderdoc.CompType.Float
                resultByteWidth=8,
            )

        def FetchCounters(self, counters: list[int]) -> list[SimpleNamespace]:
            assert counters == [7]
            return [
                SimpleNamespace(eventId=11, counter=7, value=SimpleNamespace(d=0.000_001)),
                SimpleNamespace(eventId=12, counter=7, value=SimpleNamespace(d=0.000_003)),
                SimpleNamespace(eventId=13, counter=7, value=SimpleNamespace(d=0.000_002)),
            ]

    async def _inline_offload(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    monkeypatch.setattr(perf_service, "_lazy_import_renderdoc", lambda: object())
    monkeypatch.setattr(PerfService, "_offload", staticmethod(_inline_offload))

    hotspots = asyncio.run(
        PerfService().detect_hotspots("sess_demo", _SessionManager(_Controller()), top_k=0)
    )

    assert hotspots == [
        {"event_id": 12, "duration_us": 3.0, "rank": 1},
        {"event_id": 13, "duration_us": 2.0, "rank": 2},
        {"event_id": 11, "duration_us": 1.0, "rank": 3},
    ]


def test_numeric_uint_counter_type_reads_the_matching_union_member() -> None:
    result = SimpleNamespace(value=SimpleNamespace(u64=42))
    desc = SimpleNamespace(resultType=4, resultByteWidth=8)

    assert perf_service._extract_counter_value(result, desc) == 42.0


def test_duration_counter_rejects_non_seconds_unit() -> None:
    desc = SimpleNamespace(unit=5)  # renderdoc.CounterUnit.Cycles

    with pytest.raises(ValueError, match="duration counter unit"):
        perf_service._duration_to_microseconds(10.0, desc)
