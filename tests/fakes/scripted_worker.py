"""The real runtime worker with scripted operations, spawned by tests in place of worker_main.

Everything except the operation is the production worker: its stdin reader,
request loop, cancellation, frame sink, stack-dump watchdog and parent watch.

- ``test.block_gil`` starts a descendant process (as an adb client would),
  reports one progress frame and then runs a catastrophically backtracking
  regular expression. ``re`` never releases the GIL, so no Python thread in the
  worker can run until it is killed; only faulthandler's C thread can report.
- ``test.cooperative`` keeps making short native calls, so a cancel stops it at
  the next native-call boundary.
- ``test.native_sleep`` makes one native call that does not return for minutes,
  so a cancel cannot settle.
- anything else succeeds at once.
"""
from __future__ import annotations

import re
import subprocess
import sys
import time


def main() -> int:
    from rdc_tool import native_calls
    from rdc_tool.platform import process
    from rdc_tool.progress import ProgressEvent
    from rdc_tool.runtime import dispatch, runtime_lifecycle, worker_main

    async def scripted_operation(operation, args, *, progress_sink=None, trace_id=None, **kwargs):
        def progress(stage):
            progress_sink.publish(ProgressEvent(trace_id=trace_id, operation=operation, stage=stage, message=stage))

        if operation == "test.block_gil":
            child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
            sys.stderr.write(f"descendant {child.pid} {process.identify(child.pid).birth}\n")
            sys.stderr.flush()
            progress("blocking")
            re.match(r"(a+)+$", "a" * 40 + "b")
        elif operation == "test.cooperative":
            progress("looping")
            for _ in range(1200):
                await native_calls.offload(time.sleep, 0.05)
        elif operation == "test.native_sleep":
            progress("sleeping")
            await native_calls.offload(time.sleep, 120)
        return {"ok": True, "result_kind": operation, "meta": {"trace_id": trace_id}}

    async def shutdown(**kwargs):
        return None

    dispatch.dispatch_operation = scripted_operation
    runtime_lifecycle.runtime_shutdown = shutdown
    return worker_main.main(sys.argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
