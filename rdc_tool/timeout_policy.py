"""The single source of execution budgets and control deadlines.

Operation work is never bounded by a fixed duration. It is bounded by how long
it may run without reporting progress: a progress event or a native-call frame
moves its deadline forward. The budget is chosen per request (``no_progress_ms``)
within the range every catalog entry publishes as ``execution_budget``.

Inside one budget the layers fire in a fixed order, so the most informative
outcome always wins: cooperative deadlines (remote connection, device transfer)
end with a structured error first, the worker then dumps every thread's stack,
and only after that does the daemon terminate the worker tree.

Control methods (status, cancel, lifecycle requests) do no operation work and
keep short fixed deadlines.
"""

from __future__ import annotations

from typing import Any

DEFAULT_NO_PROGRESS_MS = 300_000
MIN_NO_PROGRESS_MS = 30_000
MAX_NO_PROGRESS_MS = 3_600_000

# The watchdog margin separates the cooperative deadline, the stack dump and
# the kill: at most 5 s, at most a tenth of the budget.
_WATCHDOG_MARGIN_CAP_S = 5.0

# Daemon control requests (status, attach, heartbeat, context status, ...).
CONTROL_REQUEST_TIMEOUT_S = 10.0
# The daemon sends a heartbeat on every open exec connection at this interval,
# and the client declares the daemon unresponsive after this silence.
DAEMON_HEARTBEAT_INTERVAL_S = 2.0
DAEMON_HEARTBEAT_GAP_S = 15.0
# A queued exec waits for the execution lock in slices, so it keeps answering
# cancellation and heartbeats while another request runs.
EXEC_LOCK_SLICE_S = 1.0
# Worker process lifecycle: ready report, status and shutdown requests.
WORKER_READY_TIMEOUT_S = 10.0
WORKER_CONTROL_TIMEOUT_S = 5.0
WORKER_EXIT_TIMEOUT_S = 5.0
PIXEL_HISTORY_TIMEOUT_S = 20.0


class NoProgressBudgetError(ValueError):
    code = "invalid_no_progress_ms"
    category = "validation"

    def __init__(self, value: Any) -> None:
        super().__init__(f"no_progress_ms must be an integer from {MIN_NO_PROGRESS_MS} to {MAX_NO_PROGRESS_MS}, "
                         f"got {value!r}")
        self.details = {"no_progress_ms": value, **execution_budget()}


def execution_budget() -> dict[str, Any]:
    """The budget rule every catalog operation publishes."""
    return {"rule": "no_progress", "default_no_progress_ms": DEFAULT_NO_PROGRESS_MS,
            "min_no_progress_ms": MIN_NO_PROGRESS_MS, "max_no_progress_ms": MAX_NO_PROGRESS_MS}


def validate_no_progress_ms(value: Any) -> int:
    """A request's budget; ``None`` selects the default, anything outside the published range is rejected."""
    if value is None:
        return DEFAULT_NO_PROGRESS_MS
    if type(value) is not int or not MIN_NO_PROGRESS_MS <= value <= MAX_NO_PROGRESS_MS:
        raise NoProgressBudgetError(value)
    return value


def _margin_s(no_progress_ms: int) -> float:
    return min(_WATCHDOG_MARGIN_CAP_S, no_progress_ms / 10_000)


def watchdog_s(no_progress_ms: int) -> float:
    """The daemon terminates a worker that reported nothing for this long."""
    return no_progress_ms / 1000


def stack_dump_after_s(no_progress_ms: int) -> float:
    """The worker dumps every thread's stack after this much silence, just before the daemon's watchdog."""
    return watchdog_s(no_progress_ms) - _margin_s(no_progress_ms)


def cooperative_no_progress_s(no_progress_ms: int) -> float:
    """Cooperative loops inside the worker give up after this much silence, before the stack dump."""
    return watchdog_s(no_progress_ms) - 2 * _margin_s(no_progress_ms)
