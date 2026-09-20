from __future__ import annotations

import json
import os
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.release_runtime import isolated_release_runtime


class ReleaseRuntimeTests(unittest.TestCase):
    def state(self, root: Path, context: str) -> None:
        directory = root / "runtime/rdc_tool_cli"
        directory.mkdir(parents=True, exist_ok=True)
        (directory / f"daemon_state_{context}.json").write_text(
            json.dumps({"context_id": context}), encoding="utf-8")

    def result(self, *args, **kwargs):
        return subprocess.CompletedProcess(args[0], 0, json.dumps(
            {"ok": True, "data": {"stopped": True}}), "")

    def test_success_stops_each_owned_context_then_removes_state(self):
        with patch("scripts.release_runtime.subprocess.run", side_effect=self.result) as run:
            with isolated_release_runtime(Path.cwd()) as state:
                self.state(state, "default")
                self.state(state, "other")
            self.assertFalse(state.exists())
            self.assertEqual([call.args[0][-2:] for call in run.call_args_list],
                             [["context", "clear"], ["daemon", "stop"]] * 2)

    def test_failure_and_cancellation_both_cleanup_and_restore_environment(self):
        for error in (ValueError("verification failed"), KeyboardInterrupt()):
            with self.subTest(error=type(error)), patch.dict(os.environ, {
                "RDC_TOOL_INTERMEDIATE_ROOT": "caller-state", "RDC_TOOL_ROOT": "caller-tools",
            }), patch("scripts.release_runtime.subprocess.run", side_effect=self.result) as run:
                with self.assertRaises(type(error)):
                    with isolated_release_runtime(Path.cwd()) as state:
                        self.state(state, "owned")
                        raise error
                self.assertEqual(run.call_count, 2)
                self.assertFalse(state.exists())
                self.assertEqual(os.environ["RDC_TOOL_INTERMEDIATE_ROOT"], "caller-state")
                self.assertEqual(os.environ["RDC_TOOL_ROOT"], "caller-tools")

    def test_clear_failure_still_stops_all_daemons_and_preserves_evidence(self):
        def run(cmd, **kwargs):
            if cmd[-2:] == ["context", "clear"]:
                raise subprocess.TimeoutExpired(cmd, 30)
            return self.result(cmd)
        with patch("scripts.release_runtime.subprocess.run", side_effect=run) as calls:
            with self.assertRaisesRegex(RuntimeError, "cleanup failed"):
                with isolated_release_runtime(Path.cwd()) as state:
                    self.state(state, "one")
                    self.state(state, "two")
            self.assertEqual(calls.call_count, 4)
            self.assertTrue(state.exists())
            import shutil
            shutil.rmtree(state)

    def test_cleanup_failure_preserves_original_error(self):
        with patch("scripts.release_runtime.subprocess.run", side_effect=OSError("stop failed")):
            with self.assertRaises(ExceptionGroup) as raised:
                with isolated_release_runtime(Path.cwd()) as state:
                    self.state(state, "owned")
                    raise ValueError("original failure")
            self.assertIsInstance(raised.exception.exceptions[0], ValueError)
            import shutil
            shutil.rmtree(state)

    def test_nested_runtime_does_not_touch_outer_context(self):
        with patch("scripts.release_runtime.subprocess.run", side_effect=self.result) as run:
            with isolated_release_runtime(Path.cwd()) as outer:
                self.state(outer, "outer")
                with isolated_release_runtime(Path.cwd()) as inner:
                    self.assertNotEqual(inner, outer)
                self.assertEqual(run.call_count, 0)
                self.assertEqual(os.environ["RDC_TOOL_INTERMEDIATE_ROOT"], str(outer))
            self.assertEqual(run.call_count, 2)

    def test_missing_stop_receipt_is_failure(self):
        with patch("scripts.release_runtime.subprocess.run", return_value=
                   subprocess.CompletedProcess([], 0, '{"ok":true,"data":{}}', "")):
            with self.assertRaisesRegex(RuntimeError, "did not confirm"):
                with isolated_release_runtime(Path.cwd()) as state:
                    self.state(state, "owned")
            import shutil
            shutil.rmtree(state)
