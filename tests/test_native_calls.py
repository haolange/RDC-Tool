"""The single native-call boundary: context propagation, frames and settled cancellation."""
from __future__ import annotations

import ast
import asyncio
import contextvars
import threading
import time
from pathlib import Path

import pytest

from rdc_tool import native_calls, progress
from rdc_tool.progress import RequestScope

ROOT = Path(__file__).resolve().parents[1] / "rdc_tool"
_MARKER: contextvars.ContextVar[str] = contextvars.ContextVar("native_calls_test_marker", default="")


class _Frames:
    def __init__(self) -> None:
        self.frames = []

    def publish(self, event):
        self.frames.append(("progress", event))

    def native_call(self, frame):
        self.frames.append((frame.phase, frame.name))


async def _scoped(scope, work):
    token = progress._CURRENT_REQUEST.set(scope)
    try:
        return await work
    finally:
        progress._CURRENT_REQUEST.reset(token)


def test_offload_runs_in_the_executor_with_the_callers_context():
    def native(value):
        return threading.get_ident(), _MARKER.get(), value

    async def scenario():
        _MARKER.set("owned")
        return threading.get_ident(), await native_calls.offload(native, 7)

    loop_thread, (native_thread, marker, value) = asyncio.run(scenario())
    assert native_thread != loop_thread
    assert (marker, value) == ("owned", 7)


def test_enter_frames_are_throttled_and_exit_frames_report_only_slow_calls(monkeypatch):
    frames = _Frames()
    scope = RequestScope(request_id="req", trace_id="trc_owned", sink=frames)
    monkeypatch.setattr(progress, "NATIVE_CALL_EXIT_MIN_S", 0.05)

    def SetFrameEvent():
        return None

    def SlowCall():
        time.sleep(0.1)

    async def scenario():
        for _ in range(5):
            await native_calls.offload(SetFrameEvent)
        await native_calls.offload(SlowCall)
        await native_calls.offload(SetFrameEvent)

    asyncio.run(_scoped(scope, scenario()))
    # Repeated fast calls of one name share one enter frame; a new name always reports.
    assert frames.frames == [("enter", "SetFrameEvent"), ("enter", "SlowCall"), ("exit", "SlowCall"),
                             ("enter", "SetFrameEvent")]


def test_cancellation_waits_for_the_native_call_before_it_is_raised():
    entered, release, returned = threading.Event(), threading.Event(), threading.Event()

    def native():
        entered.set()
        assert release.wait(5)
        returned.set()

    async def scenario():
        task = asyncio.create_task(native_calls.offload(native))
        while not entered.is_set():
            await asyncio.sleep(0.01)
        task.cancel()
        await asyncio.sleep(0.05)
        assert not task.done()
        task.cancel()  # A repeated cancellation is absorbed while the call settles.
        await asyncio.sleep(0.05)
        assert not task.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert returned.is_set()

    asyncio.run(scenario())


def test_cancel_signal_runs_before_the_call_settles_and_the_outcome_stays_readable():
    signalled = threading.Event()

    def native():
        assert signalled.wait(5)
        return "settled"

    async def scenario():
        call = native_calls.NativeCall(native)
        task = asyncio.create_task(call.result(on_cancel=signalled.set))
        await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        return call.outcome()

    assert asyncio.run(scenario()) == "settled"


def test_every_executor_entry_goes_through_the_native_call_boundary():
    offenders = []
    for path in ROOT.rglob("*.py"):
        if "__pycache__" in path.parts or path.name == "native_calls.py":
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8-sig"))):
            if isinstance(node, ast.Attribute) and node.attr in {"run_in_executor", "to_thread"}:
                offenders.append(f"{path.relative_to(ROOT)}:{node.lineno}")
    assert offenders == []
