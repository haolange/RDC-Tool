"""Context daemon: owns one context, its runtime worker and its authenticated endpoint."""

from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
import threading
from multiprocessing import AuthenticationError
from typing import Any, Dict

from rdc_tool.context_snapshot import normalize_context_id
from rdc_tool.daemon.client import context_has_unreleased_resources, owner_lost_should_stop
from rdc_tool.daemon.state import (
    DEFAULT_IDLE_TIMEOUT_S, DEFAULT_LEASE_TIMEOUT_S, epoch_ms, iso_to_ms, normalize_timeout, owner_process,
    process_identity, public_view, save_state, state_path, utc_now_iso,
)
from rdc_tool.daemon.ownership import OwnerLease
from rdc_tool.daemon.worker import RuntimeWorkerProcess
from rdc_tool.platform import ipc, process
from rdc_tool.platform.ipc import Endpoint
from rdc_tool.progress import ProgressEvent, ProgressSink
from rdc_tool.runtime_state import load_context_state, save_context_state
from rdc_tool.runtime_worker_state import load_worker_state
from rdc_tool.timeout_policy import worker_exec_timeout_s

logger = logging.getLogger("rdc_tool.daemon")
# Do not release an owner's kernel lock while this process is still alive,
# including listener/worker teardown and interpreter shutdown.
_PROCESS_OWNER_LEASES: list[OwnerLease] = []


def _resolved_birth(pid: int) -> str:
    """Birth of a process named by a caller; empty when it is absent or unreadable."""
    if pid <= 0:
        return ""
    try:
        return process.identify(pid).birth
    except ProcessLookupError:
        return ""


class DaemonRuntime(ProgressSink):
    def __init__(
        self,
        *,
        endpoint: Endpoint,
        token: str,
        daemon_context: str = "default",
        owner_pid: int = 0,
        lease_timeout_seconds: int = DEFAULT_LEASE_TIMEOUT_S,
        idle_timeout_seconds: int = DEFAULT_IDLE_TIMEOUT_S,
    ) -> None:
        self.endpoint = endpoint
        self.token = token
        self.daemon_context = normalize_context_id(daemon_context)
        self.owner_pid = int(owner_pid) if owner_pid else 0
        self.owner_birth = _resolved_birth(self.owner_pid)
        self.lease_timeout_seconds = normalize_timeout(
            lease_timeout_seconds,
            default=DEFAULT_LEASE_TIMEOUT_S,
        )
        self.idle_timeout_seconds = normalize_timeout(
            idle_timeout_seconds,
            default=DEFAULT_IDLE_TIMEOUT_S,
        )
        self.running = True
        self._serve_started = False
        now_iso = utc_now_iso()
        self.state: Dict[str, Any] = {
            "context_id": self.daemon_context,
            "endpoint": endpoint.address,
            "token": token,
            "pid": int(os.getpid()),
            "birth": process.self_identity().birth,
            "started_at": now_iso,
            "last_activity_at": now_iso,
            "owner_pid": self.owner_pid,
            "owner_birth": self.owner_birth,
            "lease_timeout_seconds": self.lease_timeout_seconds,
            "idle_timeout_seconds": self.idle_timeout_seconds,
            "attached_clients": [],
            "active_request_count": 0,
            "active_operation": {},
            "session_id": "",
            "capture_file_id": "",
            "capture_path": "",
            "active_event_id": 0,
            "frame_index": 0,
            "session_count": 0,
            "capture_count": 0,
            "recovery_status": "idle",
            "backend": "local",
            "worker": {
                "running": False,
                "pid": 0,
                "birth": "",
                "binaries_dir": "",
                "pymodules_dir": "",
                "source_manifest": "",
            },
        }
        self._listener = None
        self._stop_event = threading.Event()
        self._state_lock = threading.Lock()
        self._exec_lock = threading.Lock()
        self._worker: RuntimeWorkerProcess | None = None
        self._owner_lease: OwnerLease | None = None

    def _persist_state(self) -> None:
        with self._state_lock:
            payload = dict(self.state)
            payload["attached_clients"] = [dict(item) for item in payload.get("attached_clients", [])]
        if self._owner_lease is None:
            raise RuntimeError("Daemon has not acquired its context owner lock")
        save_state(payload, context=self.daemon_context, lease=self._owner_lease)

    def _touch_activity(self) -> None:
        with self._state_lock:
            self.state["last_activity_at"] = utc_now_iso()

    def _prune_clients_locked(self, now_ms: int) -> None:
        current = self.state.get("attached_clients")
        items = current if isinstance(current, list) else []
        kept: list[Dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            client = process_identity(item.get("pid"), item.get("birth"))
            if client.pid > 0 and not process.is_alive(client):
                continue
            lease_ms = normalize_timeout(
                item.get("lease_timeout_seconds"),
                default=self.lease_timeout_seconds,
            ) * 1000
            last_heartbeat_ms = iso_to_ms(item.get("last_heartbeat_at"))
            if last_heartbeat_ms > 0 and (now_ms - last_heartbeat_ms) > lease_ms:
                continue
            kept.append(
                {
                    "client_id": str(item.get("client_id") or "").strip(),
                    "client_type": str(item.get("client_type") or "unknown").strip() or "unknown",
                    "pid": client.pid,
                    "birth": client.birth,
                    "attached_at": str(item.get("attached_at") or utc_now_iso()),
                    "last_heartbeat_at": str(item.get("last_heartbeat_at") or utc_now_iso()),
                    "lease_timeout_seconds": normalize_timeout(
                        item.get("lease_timeout_seconds"),
                        default=self.lease_timeout_seconds,
                    ),
                }
            )
        self.state["attached_clients"] = kept

    def _snapshot_state(self) -> Dict[str, Any]:
        with self._state_lock:
            self._prune_clients_locked(epoch_ms())
            self._refresh_state_from_runtime_locked()
            payload = dict(self.state)
            payload["attached_clients"] = [dict(item) for item in payload.get("attached_clients", [])]
            payload["worker"] = dict(payload.get("worker") or {})
        return payload

    def _status_payload(self) -> Dict[str, Any]:
        state = self._snapshot_state()
        self._persist_state()
        return {"ok": True, "result": {"running": self.running, "state": public_view(state)}}

    def _stop(self) -> None:
        if self._worker is not None:
            try:
                self._worker.stop()
            except Exception:
                logger.exception("daemon context=%s worker stop failed", self.daemon_context)
                return
        self.running = False
        self._stop_event.set()
        if self._listener is not None:
            try:
                self._listener.close()
            except Exception:
                pass
        if self._serve_started:
            # Retain the identity receipt until an external observer confirms
            # exit. The OS releases the owner lock only as this process dies.
            os._exit(0)

    def _clear_context_snapshot_locked(self) -> None:
        self.state["session_id"] = ""
        self.state["capture_file_id"] = ""
        self.state["capture_path"] = ""
        self.state["active_event_id"] = 0
        self.state["frame_index"] = 0
        self.state["session_count"] = 0
        self.state["capture_count"] = 0
        self.state["recovery_status"] = "idle"
        self.state["backend"] = "local"
        self.state["active_operation"] = {}

    def _set_active_operation_locked(
        self,
        *,
        operation: str,
        stage: str,
        message: str,
        trace_id: str = "",
        progress_pct: float | None = None,
        details: Dict[str, Any] | None = None,
    ) -> None:
        existing = self.state.get("active_operation")
        started_at_ms = 0
        if isinstance(existing, dict):
            started_at_ms = int(existing.get("started_at_ms") or 0)
        self.state["active_operation"] = {
            "trace_id": str(trace_id or (existing.get("trace_id") if isinstance(existing, dict) else "") or ""),
            "operation": str(operation),
            "stage": str(stage),
            "message": str(message),
            "progress_pct": progress_pct,
            "details": dict(details or {}),
            "started_at_ms": started_at_ms or epoch_ms(),
            "updated_at_ms": epoch_ms(),
        }

    def _clear_active_operation_locked(self) -> None:
        self.state["active_operation"] = {}

    def publish(self, event: ProgressEvent) -> None:
        with self._state_lock:
            self._set_active_operation_locked(
                operation=event.operation,
                stage=event.stage,
                message=event.message,
                trace_id=event.trace_id,
                progress_pct=event.progress_pct,
                details=event.details,
            )
            self.state["last_activity_at"] = utc_now_iso()
        self._persist_state()

    def _sync_context_snapshot_locked(self, params: Dict[str, Any]) -> None:
        mapping = {
            "session_id": "",
            "capture_file_id": "",
            "capture_path": "",
            "active_event_id": 0,
            "frame_index": 0,
        }
        for key, default in mapping.items():
            if key not in params:
                continue
            value = params.get(key, default)
            if isinstance(default, int):
                self.state[key] = int(value or 0)
            else:
                self.state[key] = str(value or "")

    def _worker_snapshot_locked(self) -> Dict[str, Any]:
        if self._worker is not None:
            worker = dict(self._worker.snapshot())
        else:
            worker = dict(load_worker_state(self.daemon_context) or {})
            identity = process_identity(worker.get("pid"), worker.get("birth"))
            worker["running"] = bool(worker.get("running")) and identity.pid > 0 and process.is_alive(identity)
            if not worker["running"]:
                worker["pid"] = 0
                worker["birth"] = ""
        return {
            "running": bool(worker.get("running")),
            "pid": int(worker.get("pid") or 0),
            "birth": str(worker.get("birth") or ""),
            "binaries_dir": str(worker.get("binaries_dir") or ""),
            "pymodules_dir": str(worker.get("pymodules_dir") or ""),
            "source_manifest": str(worker.get("source_manifest") or ""),
        }

    def _refresh_state_from_runtime_locked(self) -> None:
        context_state = load_context_state(self.daemon_context)
        sessions = context_state.get("sessions", {}) if isinstance(context_state.get("sessions"), dict) else {}
        captures = context_state.get("captures", {}) if isinstance(context_state.get("captures"), dict) else {}
        current_session_id = str(context_state.get("current_session_id") or "")
        current_capture_file_id = str(context_state.get("current_capture_file_id") or "")
        current_session = sessions.get(current_session_id) if current_session_id else {}
        current_capture = captures.get(current_capture_file_id) if current_capture_file_id else {}

        self.state["session_id"] = current_session_id
        self.state["capture_file_id"] = current_capture_file_id
        self.state["capture_path"] = str(
            (current_capture or {}).get("file_path")
            or (current_session or {}).get("rdc_path")
            or ""
        )
        self.state["active_event_id"] = int((current_session or {}).get("active_event_id") or 0)
        self.state["frame_index"] = int((current_session or {}).get("frame_index") or 0)
        self.state["session_count"] = len(context_state.get("sessions", {}))
        self.state["capture_count"] = len(context_state.get("captures", {}))
        self.state["recovery_status"] = str((context_state.get("recovery") or {}).get("status") or "idle")
        self.state["backend"] = str(context_state.get("backend") or "local")
        self.state["worker"] = self._worker_snapshot_locked()

    def _ensure_worker(self) -> RuntimeWorkerProcess:
        if self._worker is None:
            self._worker = RuntimeWorkerProcess(context_id=self.daemon_context)
        if not self._worker.is_running():
            prior = self._worker.previous_identity()
            if prior.pid and process.probe(prior) is not process.Liveness.EXITED:
                raise RuntimeError("Previous worker identity is still live or unavailable; preserve context for recovery")
            self._mark_replay_requires_restart(
                "Replay worker changed; close and reopen the capture through its owning lifecycle", prior)
        self._worker.ensure_started()
        return self._worker

    def _mark_replay_requires_restart(self, message: str, exited_worker: process.ProcessIdentity | None = None) -> None:
        state = load_context_state(self.daemon_context)
        sessions = state.get("sessions") or {}
        for record in sessions.values():
            previous_recovery = dict(record.get("recovery") or {})
            previous_exit = (previous_recovery.get("worker_exit")
                             if previous_recovery.get("status") == "requires_restart" and record.get("is_live") is False
                             else None)
            record["state"] = "degraded"
            record["is_live"] = False
            record["last_error"] = message
            record["recovery"] = {**previous_recovery,
                "status": "requires_restart", "last_error": message,
                "worker_exit": ({"pid": exited_worker.pid, "birth": exited_worker.birth}
                                if exited_worker is not None and exited_worker.pid > 0 else previous_exit)}
        if sessions:
            state["recovery"] = {**dict(state.get("recovery") or {}),
                "status": "degraded", "last_error": message,
                "recovered_session_ids": [], "deferred_session_ids": [],
                "degraded_session_ids": list(sessions)}
            save_context_state(state, self.daemon_context)

    def _request_worker(self, method: str, params: Dict[str, Any], *, timeout: float = 30.0) -> Dict[str, Any]:
        worker = self._ensure_worker()
        try:
            response = worker.request(method, params, timeout=timeout, progress_sink=self)
            if not bool(response.get("ok")):
                error = response.get("error") if isinstance(response.get("error"), dict) else {}
                raise RuntimeError(str(error.get("message") or f"worker {method} failed"))
            return dict(response)
        except Exception as exc:
            # A lost response can follow an applied mutation. Never resubmit it
            # to a fresh worker or recover the old controller implicitly.
            message = f"Replay worker request failed; outcome unknown; clear context before retrying: {exc}"
            prior = worker.previous_identity()
            try:
                worker.stop()
            except Exception as cleanup_error:
                message += f"; worker cleanup failed: {cleanup_error}"
            confirmed = prior if prior.pid > 0 and process.probe(prior) is process.Liveness.EXITED else None
            self._mark_replay_requires_restart(message, confirmed)
            raise RuntimeError(message) from exc

    def _handle_attach_client(self, params: Dict[str, Any]) -> Dict[str, Any]:
        client_id = str(params.get("client_id") or "").strip()
        if not client_id:
            return {"ok": False, "error": {"code": "bad_request", "message": "client_id is required"}}
        now_iso = utc_now_iso()
        client = {
            "client_id": client_id,
            "client_type": str(params.get("client_type") or "unknown").strip() or "unknown",
            "pid": int(params.get("pid") or 0),
            "birth": _resolved_birth(int(params.get("pid") or 0)),
            "attached_at": now_iso,
            "last_heartbeat_at": now_iso,
            "lease_timeout_seconds": normalize_timeout(
                params.get("lease_timeout_seconds"),
                default=self.lease_timeout_seconds,
            ),
        }
        with self._state_lock:
            self._prune_clients_locked(epoch_ms())
            clients = [item for item in self.state.get("attached_clients", []) if item.get("client_id") != client_id]
            clients.append(client)
            self.state["attached_clients"] = clients
            self.state["last_activity_at"] = now_iso
        self._persist_state()
        return self._status_payload()

    def _handle_claim_owner(self, params: Dict[str, Any]) -> Dict[str, Any]:
        owner_pid = int(params.get("owner_pid") or 0)
        if owner_pid <= 0:
            return {"ok": False, "error": {"code": "bad_request", "message": "owner_pid is required"}}
        with self._state_lock:
            current = int(self.state.get("owner_pid") or 0)
            if current > 0 and current != owner_pid:
                return {"ok": False, "error": {"code": "conflict", "message": "owner_pid already set"}}
            self.owner_pid = owner_pid
            self.owner_birth = _resolved_birth(owner_pid)
            self.state["owner_pid"] = owner_pid
            self.state["owner_birth"] = self.owner_birth
            self.state["last_activity_at"] = utc_now_iso()
        self._persist_state()
        return self._status_payload()

    def _handle_heartbeat(self, params: Dict[str, Any]) -> Dict[str, Any]:
        client_id = str(params.get("client_id") or "").strip()
        if not client_id:
            return {"ok": False, "error": {"code": "bad_request", "message": "client_id is required"}}
        now_iso = utc_now_iso()
        found = False
        with self._state_lock:
            self._prune_clients_locked(epoch_ms())
            clients = []
            for item in self.state.get("attached_clients", []):
                if item.get("client_id") == client_id:
                    updated = dict(item)
                    if int(params.get("pid") or 0):
                        updated["pid"] = int(params.get("pid") or 0)
                        updated["birth"] = _resolved_birth(updated["pid"])
                    updated["last_heartbeat_at"] = now_iso
                    clients.append(updated)
                    found = True
                else:
                    clients.append(item)
            self.state["attached_clients"] = clients
            self.state["last_activity_at"] = now_iso
        if not found:
            return {"ok": False, "error": {"code": "not_found", "message": f"client not attached: {client_id}"}}
        self._persist_state()
        return self._status_payload()

    def _handle_detach_client(self, params: Dict[str, Any]) -> Dict[str, Any]:
        client_id = str(params.get("client_id") or "").strip()
        if not client_id:
            return {"ok": False, "error": {"code": "bad_request", "message": "client_id is required"}}
        with self._state_lock:
            clients = [item for item in self.state.get("attached_clients", []) if item.get("client_id") != client_id]
            self.state["attached_clients"] = clients
            self.state["last_activity_at"] = utc_now_iso()
        self._persist_state()
        return self._status_payload()

    def _run_exec(self, operation: str, args: Dict[str, Any], *, transport: str, remote: bool) -> Dict[str, Any]:
        with self._exec_lock:
            with self._state_lock:
                self.state["active_request_count"] = int(self.state.get("active_request_count") or 0) + 1
                self.state["last_activity_at"] = utc_now_iso()
                self._set_active_operation_locked(
                    operation=operation,
                    stage="starting",
                    message="Operation queued in daemon",
                )
            self._persist_state()
            try:
                worker_timeout_s = worker_exec_timeout_s(operation, args)
                response = self._request_worker(
                    "exec",
                    {
                        "operation": operation,
                        "args": dict(args or {}),
                        "transport": transport,
                        "remote": remote,
                        "context_id": self.daemon_context,
                    },
                    timeout=worker_timeout_s,
                )
                result = response.get("result")
                with self._state_lock:
                    self._refresh_state_from_runtime_locked()
                return {"ok": True, "result": result}
            except Exception as exc:
                with self._state_lock:
                    self._refresh_state_from_runtime_locked()
                return {"ok": False, "error": {"code": "worker_error", "message": str(exc)}}
            finally:
                with self._state_lock:
                    self.state["active_request_count"] = max(
                        0,
                        int(self.state.get("active_request_count") or 0) - 1,
                    )
                    self._clear_active_operation_locked()
                    self.state["last_activity_at"] = utc_now_iso()
                self._persist_state()

    def _run_clear_context(self) -> Dict[str, Any]:
        with self._exec_lock:
            with self._state_lock:
                self.state["active_request_count"] = int(self.state.get("active_request_count") or 0) + 1
                self.state["last_activity_at"] = utc_now_iso()
                self._set_active_operation_locked(
                    operation="rd.session.clear_context",
                    stage="starting",
                    message="Clearing daemon context",
                )
            self._persist_state()
            released: Dict[str, Any] = {}
            cleared = False
            try:
                response = self._request_worker("clear_context", {"context_id": self.daemon_context}, timeout=15.0)
                result = response.get("result")
                if not isinstance(result, dict) or result.get("ok") is not True:
                    error = result.get("error") if isinstance(result, dict) else None
                    return {"ok": False, "error": error if isinstance(error, dict) else
                            {"code": "context_cleanup_failed", "message": "Worker did not confirm context cleanup"}}
                data = result.get("data")
                if isinstance(data, dict):
                    released = dict(data.get("released") or {})
                cleared = True
            except Exception as exc:
                return {"ok": False, "error": {"code": "worker_error", "message": str(exc)}}
            finally:
                with self._state_lock:
                    self._refresh_state_from_runtime_locked()
                    if cleared:
                        self._clear_context_snapshot_locked()
                    self.state["active_request_count"] = max(
                        0,
                        int(self.state.get("active_request_count") or 0) - 1,
                    )
                    self._clear_active_operation_locked()
                    self.state["last_activity_at"] = utc_now_iso()
                self._persist_state()
            return {"ok": True, "result": {"released": released, "state": public_view(self._snapshot_state())}}

    def _watch_lifecycle(self) -> None:
        while self.running:
            if self._stop_event.wait(1.0):
                break
            now_ms = epoch_ms()
            should_stop = False
            reason = ""
            try:
                with self._state_lock:
                    self._prune_clients_locked(now_ms)
                    self.state["pid"] = int(os.getpid())
                    attached = list(self.state.get("attached_clients", []))
                    active_request_count = int(self.state.get("active_request_count") or 0)
                    last_activity_ms = iso_to_ms(self.state.get("last_activity_at"))
                    owner = owner_process(self.state)
                    owner_running = process.is_alive(owner) if owner.pid > 0 else True
                    if owner_lost_should_stop(
                        owner_pid=owner.pid,
                        owner_running=owner_running,
                        has_live_clients=bool(attached),
                        last_activity_ms=last_activity_ms,
                        now_ms=now_ms,
                        lease_timeout_seconds=self.lease_timeout_seconds,
                    ):
                        should_stop = True
                        reason = f"owner pid {owner.pid} lost and lease expired"
                    if not should_stop and not attached and active_request_count == 0:
                        idle_ms = self.idle_timeout_seconds * 1000
                        if last_activity_ms > 0 and (now_ms - last_activity_ms) >= idle_ms \
                                and not context_has_unreleased_resources(self.daemon_context):
                            should_stop = True
                            reason = f"idle timeout exceeded ({self.idle_timeout_seconds}s)"
                self._persist_state()
            except Exception:
                logger.exception("daemon context=%s lifecycle watch failed", self.daemon_context)
                continue
            if should_stop:
                logger.info("daemon context=%s stopping: %s", self.daemon_context, reason)
                self._stop()
                break

    def handle_request(self, request: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(request, dict):
            return {"ok": False, "error": {"code": "bad_request", "message": "request must be an object"}}
        method = str(request.get("method") or "").strip().lower()
        logger.info("daemon.request method=%s", method)
        params = request.get("params")
        if not isinstance(params, dict):
            params = {}

        if method == "ping":
            self._touch_activity()
            self._persist_state()
            return {"ok": True, "result": {"pong": True, "context_id": self.daemon_context}}
        if method == "status":
            self._touch_activity()
            return self._status_payload()
        if method == "shutdown":
            self._touch_activity()
            self._stop()
            return {"ok": True, "result": {"stopping": True, "state": public_view(self._snapshot_state())}}
        if method == "claim_owner":
            return self._handle_claim_owner(params)
        if method == "attach_client":
            return self._handle_attach_client(params)
        if method == "heartbeat":
            return self._handle_heartbeat(params)
        if method == "detach_client":
            return self._handle_detach_client(params)
        if method == "set_state":
            with self._state_lock:
                self._sync_context_snapshot_locked(dict(params))
                self.state["last_activity_at"] = utc_now_iso()
            self._persist_state()
            return self._status_payload()
        if method == "get_state":
            self._touch_activity()
            self._persist_state()
            return {"ok": True, "result": {"state": public_view(self._snapshot_state())}}
        if method == "clear_context":
            return self._run_clear_context()
        if method == "exec":
            operation = str(params.get("operation") or "").strip()
            args = params.get("args")
            if not isinstance(args, dict):
                args = {}
            transport = str(params.get("transport") or "daemon")
            remote = bool(params.get("remote", False))
            arg_keys = ",".join(sorted(args.keys())) if args else "-"
            logger.info(
                "daemon.exec op=%s transport=%s remote=%s arg_keys=%s",
                operation,
                transport,
                remote,
                arg_keys,
            )
            result = self._run_exec(operation, args, transport=transport, remote=remote)
            payload = result.get("result")
            if isinstance(payload, dict):
                meta = payload.get("meta", {})
                logger.info(
                    "daemon.exec.done op=%s trace_id=%s ok=%s duration_ms=%s",
                    operation,
                    (meta.get("trace_id") if isinstance(meta, dict) else ""),
                    bool(payload.get("ok")),
                    (meta.get("duration_ms") if isinstance(meta, dict) else None),
                )
            return result
        return {"ok": False, "error": {"code": "unknown_method", "message": f"unknown method: {method}"}}

    def _serve_connection(self, conn: Any) -> None:
        try:
            request = conn.recv()
            conn.send(self.handle_request(request))
        except Exception as exc:  # noqa: BLE001
            try:
                conn.send({"ok": False, "error": {"code": "daemon_error", "message": str(exc)}})
            except Exception:
                pass
        finally:
            conn.close()

    def serve_forever(self) -> int:
        self._owner_lease = OwnerLease(state_path(self.daemon_context), self.daemon_context)
        _PROCESS_OWNER_LEASES.append(self._owner_lease)
        self._listener = ipc.listen(self.endpoint, authkey=self.token.encode("utf-8"))
        self._serve_started = True
        logger.info("daemon listening on %s", self.endpoint.address)
        self._persist_state()
        try:
            threading.Thread(
                target=self._watch_lifecycle,
                name="rdc-tool-daemon-lifecycle-monitor",
                daemon=True,
            ).start()
            while self.running:
                try:
                    # The HMAC challenge runs here, before any request is unpickled.
                    conn = self._listener.accept()
                except (AuthenticationError, EOFError, OSError):
                    if not self.running:
                        break
                    logger.warning("daemon context=%s rejected a connection", self.daemon_context)
                    continue
                threading.Thread(
                    target=self._serve_connection,
                    args=(conn,),
                    name=f"rdc-tool-daemon-conn-{epoch_ms()}",
                    daemon=True,
                ).start()
        finally:
            if self._listener is not None:
                try:
                    self._listener.close()
                except Exception:
                    pass
            self._stop()
        return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="RDC-Tool context daemon")
    parser.add_argument("--endpoint", required=True, help="IPC endpoint address created by the client")
    parser.add_argument("--log-level", default="INFO")
    parser.add_argument("--daemon-context", default="default")
    parser.add_argument("--owner-pid", type=int, default=0)
    parser.add_argument("--lease-timeout-seconds", type=int, default=DEFAULT_LEASE_TIMEOUT_S)
    parser.add_argument("--idle-timeout-seconds", type=int, default=DEFAULT_IDLE_TIMEOUT_S)
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, str(args.log_level).upper(), logging.INFO),
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    # The client writes the IPC key to stdin so it never appears in argv.
    token = sys.stdin.readline().strip()
    if not token:
        raise SystemExit("daemon IPC key was not provided on stdin")
    daemon = DaemonRuntime(
        endpoint=Endpoint(str(args.endpoint)),
        token=token,
        daemon_context=str(args.daemon_context),
        owner_pid=int(args.owner_pid),
        lease_timeout_seconds=int(args.lease_timeout_seconds),
        idle_timeout_seconds=int(args.idle_timeout_seconds),
    )

    def _stop(*_a: Any) -> None:
        daemon._stop()

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)
    raise SystemExit(daemon.serve_forever())


if __name__ == "__main__":
    main()
