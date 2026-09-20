"""Sequential read-only CLI batches; no independent runtime or operation catalog."""
from __future__ import annotations

import json
import signal
from pathlib import Path
from typing import Any, Callable

from rdc_tool.core.contracts import canonical_error
from rdc_tool.io_utils import safe_json_text, safe_stream_write
from rdc_tool.runtime_catalog import describe_operation, validate_operation_arguments
import sys

READ_EFFECTS = frozenset({"replay_position", "replay_position_temporary"})


def run_batch(source: str, execute: Callable[[str, dict[str, Any]], dict[str, Any]]) -> int:
    interrupted = False
    def cancel(_signum: int, _frame: Any) -> None:
        nonlocal interrupted
        interrupted = True
    previous = signal.signal(signal.SIGINT, cancel)
    index, operation = 0, ""
    try:
        with Path(source).open("rb") as stream:
            for index, line in enumerate(stream):
                operation = ""
                try:
                    if interrupted:
                        raise InterruptedError("Batch cancelled before dispatch")
                    item = json.loads(line)
                    if not isinstance(item, dict) or set(item) != {"operation", "args"}:
                        raise ValueError("Each line must contain exactly operation and args")
                    operation = item["operation"] if isinstance(item["operation"], str) else ""
                    if not operation or not isinstance(item["args"], dict):
                        raise ValueError("operation must be a string and args an object")
                    definition = describe_operation(operation)
                    if not set(definition["effects"]).issubset(READ_EFFECTS):
                        raise ValueError("Batch accepts read-only operations, not lifecycle or write effects")
                    validate_operation_arguments(operation, item["args"])
                    payload = execute(operation, item["args"])
                except Exception as exc:
                    payload = canonical_error(result_kind=operation or "rdc_tool.batch", code="batch_cancelled" if isinstance(exc, InterruptedError) else "batch_failed",
                        category="runtime" if not isinstance(exc, ValueError) else "validation", message=str(exc), transport="cli")
                payload.setdefault("meta", {})["batch"] = {"index": index, "operation": operation}
                if interrupted:
                    payload["meta"]["batch"]["cancelled"] = True
                    payload["meta"]["batch"]["in_flight_completion"] = "observed" if payload.get("ok") else "see_error"
                safe_stream_write(safe_json_text(payload) + "\n", sys.stdout)
                if interrupted:
                    return 130
                if not payload.get("ok"):
                    return 1
        return 0
    except OSError as exc:
        payload = canonical_error(result_kind="rdc_tool.batch", code="batch_input_failed", category="validation", message=str(exc), transport="cli")
        payload["meta"]["batch"] = {"index": index, "operation": operation}
        safe_stream_write(safe_json_text(payload) + "\n", sys.stdout)
        return 2
    finally:
        signal.signal(signal.SIGINT, previous)
