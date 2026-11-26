"""Worker process lifecycle for daemon-owned RenderDoc runtime."""

from __future__ import annotations

import json
import logging
import math
import os
import queue
import subprocess
import threading
import time
from typing import Any, Dict, Optional

from rdc_tool import timeout_policy
from rdc_tool.daemon.state import load_json_with_status
from rdc_tool.io_utils import safe_json_text
from rdc_tool.platform import process
from rdc_tool.platform.process import ProcessIdentity, SpawnProfile
from rdc_tool.progress import FrameSink, NativeCallFrame, ProgressEvent
from rdc_tool.runtime_paths import binaries_root, child_python_argv, child_python_env, pymodules_dir, tools_root
from rdc_tool.runtime_worker_state import clear_worker_state, save_worker_state, worker_state_path
from rdc_tool.runtime_identity import native_manifest_status


def _decode_progress_event(payload: Any, operation: str) -> ProgressEvent:
    fields = {"trace_id", "operation", "stage", "message", "progress_pct", "details", "ts_ms"}
    if not isinstance(payload, dict) or set(payload) != fields:
        raise RuntimeError("Invalid worker progress event fields")
    if any(not isinstance(payload[key], str) for key in ("trace_id", "operation", "stage", "message")):
        raise RuntimeError("Invalid worker progress event text")
    if not payload["trace_id"].strip() or not payload["stage"].strip() or payload["operation"] != operation:
        raise RuntimeError("Worker progress event identity mismatch")
    percent = payload["progress_pct"]
    if percent is not None and (isinstance(percent, bool) or not isinstance(percent, (int, float)) or not math.isfinite(percent)):
        raise RuntimeError("Invalid worker progress percentage")
    if not isinstance(payload["details"], dict) or type(payload["ts_ms"]) is not int or payload["ts_ms"] <= 0:
        raise RuntimeError("Invalid worker progress event details")
    return ProgressEvent(**payload)


def _decode_native_call_frame(payload: Dict[str, Any]) -> NativeCallFrame:
    if set(payload) != {"id", "kind", "trace_id", "name", "phase", "ts_ms"}:
        raise RuntimeError("Invalid worker native-call frame fields")
    if not isinstance(payload["trace_id"], str) or not payload["trace_id"].strip():
        raise RuntimeError("Invalid worker native-call frame trace")
    if not isinstance(payload["name"], str) or not payload["name"].strip() or payload["phase"] not in {"enter", "exit"}:
        raise RuntimeError("Invalid worker native-call frame call")
    if type(payload["ts_ms"]) is not int or payload["ts_ms"] <= 0:
        raise RuntimeError("Invalid worker native-call frame time")
    return NativeCallFrame(payload["trace_id"], payload["name"], payload["phase"], payload["ts_ms"])


class RuntimeWorkerProcess:
    def __init__(self, *, context_id: str) -> None:
        self.context_id = str(context_id)
        self._proc: Optional[subprocess.Popen[str]] = None
        self._reader_thread: Optional[threading.Thread] = None
        self._queue: "queue.Queue[Dict[str, Any]]" = queue.Queue()
        self._io_lock = threading.Lock()
        self._request_seq = 0
        self._runtime: Optional[Dict[str, Any]] = None
        self._birth = ""

    def is_running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def previous_identity(self) -> ProcessIdentity:
        if self._proc is not None:
            return ProcessIdentity(self._proc.pid, self._birth)
        status, record = load_json_with_status(worker_state_path(self.context_id))
        if status == "missing":
            return ProcessIdentity(0)
        if (status != "ok" or record.get("context_id") != self.context_id
                or type(record.get("pid")) is not int or record["pid"] <= 0
                or not isinstance(record.get("birth", ""), str)):
            raise RuntimeError("Worker identity record is invalid; preserve it for recovery")
        return ProcessIdentity(record["pid"], record.get("birth", ""))

    def snapshot(self) -> Dict[str, Any]:
        runtime = self._runtime
        return {
            "running": self.is_running(),
            "pid": int(self._proc.pid) if self._proc and self.is_running() else 0,
            "birth": self._birth if self.is_running() else "",
            "binaries_dir": runtime.get("binaries_dir", "") if runtime else "",
            "pymodules_dir": runtime.get("pymodules_dir", "") if runtime else "",
            "source_manifest": runtime.get("source_manifest", "") if runtime else "",
            "loaded_runtime": runtime.get("loaded_runtime", {"status": "unavailable", "reason": "worker_has_not_reported_loaded_runtime"}) if runtime else {"status": "not_loaded"},
        }

    def _save_state(self) -> None:
        payload = {
            "context_id": self.context_id,
            **self.snapshot(),
        }
        if payload["running"]:
            save_worker_state(payload, context=self.context_id)
        else:
            clear_worker_state(self.context_id)

    def _pump_stdout(self, stdout: Any) -> None:
        for line in iter(stdout.readline, ""):
            text = str(line).strip()
            if not text:
                continue
            try:
                payload = json.loads(text)
            except Exception:
                payload = {"kind": "invalid", "raw": text}
            self._queue.put(payload)
        self._queue.put({"kind": "eof"})

    def _spawn(self) -> None:
        bin_dir = binaries_root().resolve()
        pymod_dir = pymodules_dir().resolve()
        native = native_manifest_status(tools_root())
        if native["status"] == "invalid":
            raise RuntimeError(f"Native runtime integrity failed before worker startup: {native['reason']}")
        manifest_path = (bin_dir / "manifest.runtime.json").resolve()
        runtime = {
            "binaries_dir": str(bin_dir),
            "pymodules_dir": str(pymod_dir),
            "source_manifest": str(manifest_path),
        }
        env = child_python_env(os.environ)
        env["RDC_TOOL_CONTEXT_ID"] = self.context_id
        daemon = process.self_identity()
        env["RDC_TOOL_DAEMON_PID"] = str(daemon.pid)
        env["RDC_TOOL_DAEMON_BIRTH"] = daemon.birth

        popen_kwargs: Dict[str, Any] = {
            "stdin": subprocess.PIPE,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.DEVNULL,
            "text": True,
            "encoding": "utf-8",
            "bufsize": 1,
            "env": env,
            **process.popen_options(SpawnProfile.WORKER),
        }

        proc = subprocess.Popen(
            child_python_argv("rdc_tool.runtime.worker_main", "--context-id", self.context_id),
            **popen_kwargs,
        )
        assert proc.stdout is not None
        self._proc = proc
        try:
            self._birth = process.identify(proc.pid).birth
        except ProcessLookupError:
            self._birth = ""
        self._runtime = runtime
        self._queue = queue.Queue()
        self._reader_thread = threading.Thread(
            target=self._pump_stdout,
            args=(proc.stdout,),
            name=f"rdc-tool-worker-reader-{self.context_id}",
            daemon=True,
        )
        self._reader_thread.start()
        self._await_ready()
        self._save_state()

    def _await_ready(self) -> None:
        deadline = time.time() + timeout_policy.WORKER_READY_TIMEOUT_S
        while time.time() < deadline:
            timeout = max(0.1, min(0.5, deadline - time.time()))
            try:
                payload = self._queue.get(timeout=timeout)
            except queue.Empty:
                continue
            kind = str(payload.get("kind") or "")
            if kind == "ready":
                if self._runtime is not None and isinstance(payload.get("loaded_runtime"), dict):
                    self._runtime["loaded_runtime"] = payload["loaded_runtime"]
                return
            if kind == "eof":
                break
            if kind == "startup_error":
                raise RuntimeError(str(payload.get("message") or "worker startup failed"))
        raise RuntimeError("worker failed to report ready state")

    def ensure_started(self) -> None:
        if self.is_running():
            return
        self.stop()
        self._spawn()

    def request(self, method: str, params: Optional[Dict[str, Any]] = None, *, no_progress_s: float,
                frame_sink: FrameSink | None = None) -> Dict[str, Any]:
        """Send one request and wait for its reply while frames keep arriving.

        There is no total deadline: every frame of this request moves the
        deadline forward by ``no_progress_s``.
        """
        with self._io_lock:
            if not self.is_running():
                raise RuntimeError("worker process is unavailable; use the owning daemon lifecycle")
            proc = self._proc
            if proc is None or proc.stdin is None:
                raise RuntimeError("worker process is unavailable")
            self._request_seq += 1
            req_id = f"wrk_{self._request_seq}"
            proc.stdin.write(
                safe_json_text({"id": req_id, "method": str(method), "params": dict(params or {})}) + "\n"
            )
            proc.stdin.flush()

            window = max(1.0, float(no_progress_s))
            deadline = time.monotonic() + window
            trace_id = ""
            while time.monotonic() < deadline:
                remaining = max(0.1, min(0.5, deadline - time.monotonic()))
                try:
                    payload = self._queue.get(timeout=remaining)
                except queue.Empty:
                    continue
                if str(payload.get("kind") or "") == "eof":
                    raise RuntimeError("worker exited before responding")
                if str(payload.get("id") or "") != req_id:
                    continue
                if payload.get("kind") in {"progress", "native_call"}:
                    if method != "exec":
                        raise RuntimeError("Unexpected worker frame for lifecycle request")
                    frame = (_decode_progress_event(payload.get("event"), str((params or {}).get("operation") or ""))
                             if payload["kind"] == "progress" else _decode_native_call_frame(payload))
                    if trace_id and frame.trace_id != trace_id:
                        raise RuntimeError("Worker frame trace changed within a request")
                    trace_id = frame.trace_id
                    deadline = time.monotonic() + window
                    if frame_sink is not None:
                        try:
                            if isinstance(frame, ProgressEvent):
                                frame_sink.publish(frame)
                            else:
                                frame_sink.native_call(frame)
                        except Exception:
                            logging.getLogger(__name__).warning("Daemon frame delivery failed", exc_info=True)
                    continue
                if payload.get("kind") is not None:
                    raise RuntimeError("Unexpected worker response type")
                if self._runtime is not None and isinstance(payload.get("loaded_runtime"), dict):
                    self._runtime["loaded_runtime"] = payload["loaded_runtime"]
                self._save_state()
                return payload
            raise TimeoutError(f"worker reported no progress for {window:.0f} s: {method}")

    def stop(self) -> None:
        proc = self._proc
        if proc is None:
            clear_worker_state(self.context_id)
            self._runtime = None
            return
        try:
            if proc.poll() is None:
                try:
                    self.request("shutdown", {}, no_progress_s=timeout_policy.WORKER_CONTROL_TIMEOUT_S)
                except Exception:
                    pass
                try:
                    proc.wait(timeout=timeout_policy.WORKER_EXIT_TIMEOUT_S)
                except Exception:
                    proc.kill()
                    proc.wait(timeout=3.0)
        finally:
            # A failed stop must retain the handle and registration while the
            # old worker could still own a native replay.
            if proc.poll() is not None:
                try:
                    if proc.stdin:
                        proc.stdin.close()
                except Exception:
                    pass
                try:
                    if proc.stdout:
                        proc.stdout.close()
                except Exception:
                    pass
                self._proc = None
                self._runtime = None
                clear_worker_state(self.context_id)
