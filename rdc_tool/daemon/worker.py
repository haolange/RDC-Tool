"""Worker process lifecycle for daemon-owned RenderDoc runtime."""

from __future__ import annotations

import json
import logging
import math
import os
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

from rdc_tool.io_utils import safe_json_text
from rdc_tool.progress import ProgressEvent, ProgressSink
from rdc_tool.runtime_paths import binaries_root, pymodules_dir
from rdc_tool.runtime_worker_state import clear_worker_state, save_worker_state
from rdc_tool.runtime_identity import host_native_manifest_status


READY_TIMEOUT_S = 10.0
REQUEST_TIMEOUT_S = 30.0


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


class RuntimeWorkerProcess:
    def __init__(self, *, context_id: str) -> None:
        self.context_id = str(context_id)
        self._proc: Optional[subprocess.Popen[str]] = None
        self._reader_thread: Optional[threading.Thread] = None
        self._queue: "queue.Queue[Dict[str, Any]]" = queue.Queue()
        self._io_lock = threading.Lock()
        self._request_seq = 0
        self._runtime: Optional[Dict[str, Any]] = None

    def is_running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def snapshot(self) -> Dict[str, Any]:
        runtime = self._runtime
        return {
            "running": self.is_running(),
            "pid": int(self._proc.pid) if self._proc and self.is_running() else 0,
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
        native = host_native_manifest_status(bin_dir.parents[2])
        if native["status"] == "invalid":
            raise RuntimeError(f"Native runtime integrity failed before worker startup: {native['reason']}")
        manifest_path = (bin_dir / "manifest.runtime.json").resolve()
        runtime = {
            "binaries_dir": str(bin_dir),
            "pymodules_dir": str(pymod_dir),
            "source_manifest": str(manifest_path),
        }
        env = dict(os.environ)
        env["RDC_TOOL_CONTEXT_ID"] = self.context_id
        env["RDC_TOOL_DAEMON_PID"] = str(os.getpid())
        env["RDC_TOOL_RUNTIME_DLL_DIR"] = runtime["binaries_dir"]
        env["RDC_TOOL_RENDERDOC_PATH"] = runtime["pymodules_dir"]
        env["RDC_TOOL_WORKER_SOURCE_MANIFEST"] = runtime["source_manifest"]

        tools_root = str(env.get("RDC_TOOL_ROOT", "")).strip()
        if tools_root:
            py_path = env.get("PYTHONPATH", "")
            root_path = str(Path(tools_root).resolve())
            env["PYTHONPATH"] = root_path + os.pathsep + py_path if py_path else root_path

        popen_kwargs: Dict[str, Any] = {
            "stdin": subprocess.PIPE,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.DEVNULL,
            "text": True,
            "encoding": "utf-8",
            "bufsize": 1,
            "env": env,
        }
        if os.name == "nt":
            # ADB children need a real console for reliable captured output.
            # Own it in the worker and hide it at creation; children inherit it.
            startup = subprocess.STARTUPINFO()
            startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startup.wShowWindow = subprocess.SW_HIDE
            popen_kwargs["startupinfo"] = startup
            popen_kwargs["creationflags"] = subprocess.CREATE_NEW_CONSOLE | subprocess.CREATE_NEW_PROCESS_GROUP

        proc = subprocess.Popen(
            [sys.executable, "-m", "rdc_tool.runtime_worker", "--context-id", self.context_id],
            **popen_kwargs,
        )
        assert proc.stdout is not None
        self._proc = proc
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
        deadline = time.time() + READY_TIMEOUT_S
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

    def request(self, method: str, params: Optional[Dict[str, Any]] = None, *, timeout: float = REQUEST_TIMEOUT_S, progress_sink: ProgressSink | None = None) -> Dict[str, Any]:
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

            deadline = time.time() + max(1.0, float(timeout))
            trace_id = ""
            while time.time() < deadline:
                remaining = max(0.1, min(0.5, deadline - time.time()))
                try:
                    payload = self._queue.get(timeout=remaining)
                except queue.Empty:
                    continue
                if str(payload.get("kind") or "") == "eof":
                    raise RuntimeError("worker exited before responding")
                if str(payload.get("id") or "") != req_id:
                    continue
                if payload.get("kind") == "progress":
                    if method != "exec":
                        raise RuntimeError("Unexpected worker progress for lifecycle request")
                    event = _decode_progress_event(payload.get("event"), str((params or {}).get("operation") or ""))
                    if trace_id and event.trace_id != trace_id:
                        raise RuntimeError("Worker progress trace changed within a request")
                    trace_id = event.trace_id
                    if progress_sink is not None:
                        try:
                            progress_sink.publish(event)
                        except Exception:
                            logging.getLogger(__name__).warning("Daemon progress delivery failed", exc_info=True)
                    continue
                if payload.get("kind") is not None:
                    raise RuntimeError("Unexpected worker response type")
                if self._runtime is not None and isinstance(payload.get("loaded_runtime"), dict):
                    self._runtime["loaded_runtime"] = payload["loaded_runtime"]
                self._save_state()
                return payload
            raise TimeoutError(f"worker request timed out: {method}")

    def stop(self) -> None:
        proc = self._proc
        if proc is None:
            clear_worker_state(self.context_id)
            self._runtime = None
            return
        try:
            if proc.poll() is None:
                try:
                    self.request("shutdown", {}, timeout=5.0)
                except Exception:
                    pass
                try:
                    proc.wait(timeout=5.0)
                except Exception:
                    proc.kill()
                    proc.wait(timeout=3.0)
        finally:
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
