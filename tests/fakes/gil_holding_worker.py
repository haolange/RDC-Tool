"""The real runtime worker with an operation that blocks while holding the GIL.

The daemon spawns this script in place of ``rdc_tool.runtime.worker_main``.
Everything except the operation is the production worker: its request loop,
frame sink, stack-dump watchdog and parent watch. The operation starts a
descendant process (as an adb client would), reports one progress frame and
then runs a catastrophically backtracking regular expression. ``re`` never
releases the GIL, so no Python thread in the worker can run until it is killed;
only faulthandler's C thread can still report where it is.
"""
from __future__ import annotations

import re
import subprocess
import sys


def main() -> int:
    from rdc_tool.runtime import dispatch, runtime_lifecycle, worker_main

    async def blocking_operation(operation, args, *, progress_sink=None, trace_id=None, **kwargs):
        from rdc_tool.platform import process
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
        sys.stderr.write(f"descendant {child.pid} {process.identify(child.pid).birth}\n")
        sys.stderr.flush()
        from rdc_tool.progress import ProgressEvent
        progress_sink.publish(ProgressEvent(trace_id=trace_id, operation=operation, stage="blocking",
                                            message="Entering a call that holds the GIL"))
        re.match(r"(a+)+$", "a" * 40 + "b")
        return {"ok": True}

    async def shutdown(**kwargs):
        return None

    dispatch.dispatch_operation = blocking_operation
    runtime_lifecycle.runtime_shutdown = shutdown
    return worker_main.main(sys.argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
