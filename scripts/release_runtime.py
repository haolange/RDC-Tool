"""Own the runtime state and process teardown of release verification only."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path
from collections.abc import Iterator

from scripts._shared import extract_json_payload


def _cleanup(root: Path, state: Path) -> None:
    failures: list[str] = []
    contexts: set[str] = set()
    for file in (state / "runtime/rdc_tool_cli").glob("daemon_state*.json"):
        payload = json.loads(file.read_text(encoding="utf-8"))
        context = payload.get("context_id") or payload.get("daemon_context")
        if not isinstance(context, str) or not context:
            raise RuntimeError(f"Invalid verification daemon state: {file}")
        contexts.add(context)
    python = root / "binaries/windows/x64/python/python.exe"
    for context in sorted(contexts):
        # Even a failed clear must not skip stopping this owned daemon.
        for command in (["context", "clear"], ["daemon", "stop"]):
            try:
                result = subprocess.run(
                    [str(python), str(root / "cli/run_cli.py"), "--json",
                     "--daemon-context", context, *command],
                    cwd=root, env=os.environ.copy(), stdin=subprocess.DEVNULL,
                    capture_output=True, text=True, encoding="utf-8", errors="replace",
                    timeout=30, check=False,
                )
                payload = extract_json_payload(result.stdout)
                if result.returncode != 0 or not payload or payload.get("ok") is not True:
                    raise RuntimeError(result.stdout + result.stderr)
                if command[0] == "daemon" and (payload.get("data") or {}).get("stopped") is not True:
                    raise RuntimeError("daemon stop did not confirm process exit")
            except Exception as exc:
                failures.append(f"{context} {' '.join(command)}: {exc}")
    if failures:
        raise RuntimeError("Release runtime cleanup failed: " + "; ".join(failures))


@contextmanager
def isolated_release_runtime(root: Path) -> Iterator[Path]:
    """Never reuse caller state; restore its environment, including on cancellation."""
    state = Path(tempfile.mkdtemp(prefix="rdc-tool-release-runtime-"))
    keys = {"RDC_TOOL_INTERMEDIATE_ROOT": str(state), "RDC_TOOL_ROOT": str(root)}
    previous = {key: os.environ.get(key) for key in keys}
    os.environ.update(keys)
    original: BaseException | None = None
    try:
        yield state
    except BaseException as exc:
        original = exc
        raise
    finally:
        try:
            _cleanup(root, state)
            shutil.rmtree(state)
        except BaseException as cleanup:
            cleanup.add_note(f"Verification state retained for recovery: {state}")
            if original is not None:
                raise BaseExceptionGroup("Verification and cleanup failed", [original, cleanup])
            raise
        finally:
            for key, value in previous.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
