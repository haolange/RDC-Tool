"""Worker process lifecycle for daemon-owned RenderDoc runtime."""

from __future__ import annotations

import collections
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
from rdc_tool.io_utils import rotating_log_handler, safe_json_text
from rdc_tool.platform import process
from rdc_tool.platform.process import ProcessIdentity, SpawnProfile
from rdc_tool.progress import FrameSink, NativeCallFrame, ProgressEvent
from rdc_tool.runtime_paths import binaries_root, child_python_argv, child_python_env, pymodules_dir, tools_root
from rdc_tool.runtime_worker_state import clear_worker_state, save_worker_state, worker_log_path, worker_state_path
from rdc_tool.runtime_identity import native_manifest_status

# faulthandler starts every no-progress dump with this line.
_STACK_DUMP_MARKER = "Timeout ("
_STDERR_TAIL_LINES = 400
STACK_TAIL_CHARS = 8192


class WorkerFailure(RuntimeError):
    """A worker request that ended without a reply; its outcome is unknown."""

    def __init__(self, code: str, reason: str, message: str, *, worker: ProcessIdentity,
                 exit_confirmed: bool = False, stack_log: Optional[Dict[str, str]] = None, trace_id: str = "") -> None:
        super().__init__(message)
        self.code = code  # worker_stuck | worker_lost | worker_request_failed
        self.reason = reason
        self.worker = worker
        self.exit_confirmed = exit_confirmed
        self.stack_log = dict(stack_log or {})
        self.trace_id = trace_id


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
        self._stderr_thread: Optional[threading.Thread] = None
        self._queue: "queue.Queue[Dict[str, Any]]" = queue.Queue()
        self._io_lock = threading.Lock()
        self._request_seq = 0
        self._runtime: Optional[Dict[str, Any]] = None
        self._birth = ""
        self._log: Optional[logging.Logger] = None
        self._stderr_lock = threading.Lock()
        self._stderr_tail: "collections.deque[str]" = collections.deque(maxlen=_STDERR_TAIL_LINES)
        self._stderr_count = 0
        self._dump_start: Optional[int] = None
        self._dump_seen = threading.Event()

    @property
    def log_path(self) -> str:
        return str(worker_log_path(self.context_id))

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

    def _worker_log(self) -> logging.Logger:
        if self._log is None:
            log = logging.getLogger(f"rdc_tool.worker_stderr.{self.context_id}")
            log.propagate = False
            log.setLevel(logging.INFO)
            if not log.handlers:
                handler = rotating_log_handler(worker_log_path(self.context_id))
                handler.setFormatter(logging.Formatter("%(message)s"))
                log.addHandler(handler)
            self._log = log
        return self._log

    def _close_log(self) -> None:
        if self._stderr_thread is not None:
            self._stderr_thread.join(timeout=1.0)
        if self._log is not None:
            for handler in list(self._log.handlers):
                self._log.removeHandler(handler)
                handler.close()
            self._log = None

    def _pump_stderr(self, stderr: Any, log: logging.Logger) -> None:
        # Always drain stderr: a full pipe would block the worker on its next write.
        for line in iter(stderr.readline, ""):
            text = str(line).rstrip("\r\n")
            try:
                log.info(text)
            except Exception:
                pass
            with self._stderr_lock:
                self._stderr_tail.append(text)
                self._stderr_count += 1
                if text.startswith(_STACK_DUMP_MARKER):
                    self._dump_start = self._stderr_count
                    self._dump_seen.set()

    def _stack_log(self, since: int) -> Dict[str, str]:
        """The worker log path and the stderr written since ``since``: from the latest stack dump when there is one."""
        with self._stderr_lock:
            lines = list(self._stderr_tail)
            count = self._stderr_count
            dump = self._dump_start
        start = dump if dump is not None and dump > since else since + 1
        recent = lines[max(0, len(lines) - (count - start + 1)):]
        if dump is None or dump <= since:
            recent = recent[-40:]
        return {"path": self.log_path, "tail": "\n".join(recent)[:STACK_TAIL_CHARS]}

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
            "stderr": subprocess.PIPE,
            "text": True,
            "encoding": "utf-8",
            "errors": "replace",
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
        if proc.stderr is not None:
            log = self._worker_log()
            log.info("--- worker pid=%s birth=%s started for context %s", proc.pid, self._birth, self.context_id)
            self._stderr_thread = threading.Thread(
                target=self._pump_stderr,
                args=(proc.stderr, log),
                name=f"rdc-tool-worker-stderr-{self.context_id}",
                daemon=True,
            )
            self._stderr_thread.start()
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

    def _await_exit(self, proc: subprocess.Popen[str]) -> bool:
        try:
            proc.wait(timeout=timeout_policy.WORKER_EXIT_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            return False
        if self._stderr_thread is not None:
            # Let the last lines a dying worker wrote reach the log and the tail.
            self._stderr_thread.join(timeout=1.0)
        return True

    def _terminate(self, proc: subprocess.Popen[str]) -> bool:
        """Kill the worker and its descendants; True once its exit is confirmed."""
        identity = ProcessIdentity(proc.pid, self._birth)
        if not (self._birth and process.kill_tree(identity)) and proc.poll() is None:
            proc.kill()  # The Popen handle itself still names exactly this process.
        return self._await_exit(proc)

    def terminate_stuck(self, reason: str, *, since: int, trace_id: str = "") -> WorkerFailure:
        """End a worker that stopped reporting progress, after the stack dump had its chance to land."""
        proc = self._proc
        identity = ProcessIdentity(proc.pid if proc else 0, self._birth)
        if reason == "no_progress":
            self._dump_seen.wait(timeout_policy.STACK_DUMP_GRACE_S)
        exited = self._terminate(proc) if proc is not None else True
        return WorkerFailure("worker_stuck", reason, f"Worker reported no progress ({reason}); it was terminated",
                             worker=identity, exit_confirmed=exited, stack_log=self._stack_log(since),
                             trace_id=trace_id)

    def request(self, method: str, params: Optional[Dict[str, Any]] = None, *, no_progress_s: float,
                frame_sink: FrameSink | None = None) -> Dict[str, Any]:
        """Send one request and wait for its reply while frames keep arriving.

        There is no total deadline: every frame of this request moves the
        deadline forward by ``no_progress_s``. A silent worker is terminated
        with its descendants after its stack dump; an exited worker is lost.
        """
        with self._io_lock:
            if not self.is_running():
                raise RuntimeError("worker process is unavailable; use the owning daemon lifecycle")
            proc = self._proc
            if proc is None or proc.stdin is None:
                raise RuntimeError("worker process is unavailable")
            identity = ProcessIdentity(proc.pid, self._birth)
            self._request_seq += 1
            req_id = f"wrk_{self._request_seq}"
            with self._stderr_lock:
                since = self._stderr_count
            self._dump_seen.clear()
            trace_id = str((params or {}).get("trace_id") or "")
            try:
                proc.stdin.write(
                    safe_json_text({"id": req_id, "method": str(method), "params": dict(params or {})}) + "\n"
                )
                proc.stdin.flush()
            except OSError as exc:
                raise WorkerFailure("worker_request_failed", "stdin_write_failed", f"Worker request could not be sent: {exc}",
                                    worker=identity, stack_log=self._stack_log(since), trace_id=trace_id) from exc

            window = max(1.0, float(no_progress_s))
            deadline = time.monotonic() + window
            while time.monotonic() < deadline:
                remaining = max(0.1, min(0.5, deadline - time.monotonic()))
                try:
                    payload = self._queue.get(timeout=remaining)
                except queue.Empty:
                    continue
                if str(payload.get("kind") or "") == "eof":
                    exited = self._await_exit(proc)
                    raise WorkerFailure("worker_lost", "worker_exited", "Worker exited before replying",
                                        worker=identity, exit_confirmed=exited, stack_log=self._stack_log(since),
                                        trace_id=trace_id)
                if str(payload.get("id") or "") != req_id:
                    continue
                try:
                    if payload.get("kind") in {"progress", "native_call"}:
                        if method not in {"exec", "clear_context"}:
                            raise RuntimeError("Unexpected worker frame for lifecycle request")
                        operation = str((params or {}).get("operation") or "rd.session.clear_context")
                        frame = (_decode_progress_event(payload.get("event"), operation)
                                 if payload["kind"] == "progress" else _decode_native_call_frame(payload))
                        if trace_id and frame.trace_id != trace_id:
                            raise RuntimeError("Worker frame trace changed within a request")
                    elif payload.get("kind") is not None:
                        raise RuntimeError("Unexpected worker response type")
                    else:
                        frame = None
                except RuntimeError as exc:
                    raise WorkerFailure("worker_request_failed", "invalid_frame", str(exc), worker=identity,
                                        stack_log=self._stack_log(since), trace_id=trace_id) from exc
                if frame is not None:
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
                if self._runtime is not None and isinstance(payload.get("loaded_runtime"), dict):
                    self._runtime["loaded_runtime"] = payload["loaded_runtime"]
                self._save_state()
                return payload
            raise self.terminate_stuck("no_progress", since=since, trace_id=trace_id)

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
                if proc.poll() is None and not self._await_exit(proc):
                    self._terminate(proc)
        finally:
            # A failed stop must retain the handle and registration while the
            # old worker could still own a native replay.
            if proc.poll() is not None:
                self._close_log()
                for stream in (proc.stdin, proc.stdout, proc.stderr):
                    try:
                        if stream:
                            stream.close()
                    except Exception:
                        pass
                self._proc = None
                self._runtime = None
                clear_worker_state(self.context_id)
