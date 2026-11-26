"""The single boundary between the worker's event loop and blocking native work.

Every RenderDoc call, adb helper and other blocking callable reached from async
code enters the executor here. A call carries the caller's context variables
into the executor thread, reports throttled native-call frames for the
no-progress watchdog, and is never abandoned: cancellation waits until the
native call has returned before it is re-raised, because a running native call
cannot be interrupted and still owns its thread, handles and device state.
"""

from __future__ import annotations

import asyncio
import contextvars
import functools
import time
from typing import Any, Callable

from rdc_tool import progress


def call_name(fn: Any) -> str:
    target = fn.func if isinstance(fn, functools.partial) else fn
    return str(getattr(target, "__name__", "") or type(target).__name__)


class NativeCall:
    """One blocking call running on the loop's default executor."""

    def __init__(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
        loop = asyncio.get_running_loop()
        context = contextvars.copy_context()
        self.name = call_name(fn)
        self._scope = progress.current_request()
        self._started = time.monotonic()
        if self._scope is not None:
            self._scope.native_call(self.name, "enter")
        self._future = loop.run_in_executor(None, functools.partial(context.run, fn, *args, **kwargs))
        self._future.add_done_callback(self._finished)

    def _finished(self, future: asyncio.Future) -> None:
        if self._scope is not None and time.monotonic() - self._started > progress.NATIVE_CALL_EXIT_MIN_S:
            self._scope.native_call(self.name, "exit")
        if not future.cancelled():
            future.exception()  # A settled call's failure is observed by its awaiting caller.

    def done(self) -> bool:
        return self._future.done()

    async def settled(self) -> None:
        """Wait until the native call returns, even while the awaiting task is being cancelled."""
        while not self._future.done():
            try:
                await asyncio.wait({self._future})
            except asyncio.CancelledError:
                continue

    def outcome(self) -> Any:
        """The settled call's result, raising its exception."""
        return self._future.result()

    async def result(self, *, on_cancel: Callable[[], None] | None = None) -> Any:
        """The call's result; on cancellation signal ``on_cancel``, settle the call, then re-raise."""
        try:
            return await asyncio.shield(self._future)
        except asyncio.CancelledError:
            if on_cancel is not None:
                on_cancel()
            await self.settled()
            raise


async def offload(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Run one blocking callable off the event loop and return its result."""
    return await NativeCall(fn, *args, **kwargs).result()
