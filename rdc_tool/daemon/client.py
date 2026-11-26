"""Daemon client: start, reuse, request, clean up and stop a context daemon."""

from __future__ import annotations

import os
import secrets
import subprocess
import time
from contextlib import ExitStack, contextmanager
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Optional, Tuple

from rdc_tool import timeout_policy
from rdc_tool.context_snapshot import clear_context_snapshot, context_snapshot_path, normalize_context_id
from rdc_tool.daemon import context_status
from rdc_tool.daemon.ownership import DaemonOwnerUnavailable, owner_is_busy, wait_for_owner_exit
from rdc_tool.daemon.state import (
    DEFAULT_IDLE_TIMEOUT_S, DEFAULT_LEASE_TIMEOUT_S, clear_state, context_from_state_path, daemon_process,
    is_complete, iso_to_ms, list_daemon_context_ids, load_json_with_status, load_state, normalize_attached_clients,
    normalize_state, normalize_timeout, epoch_ms, owner_identity, owner_process, process_identity, retire_incomplete_state, state_path,
    utc_now_iso, worker_process,
)
from rdc_tool.platform import ipc, process
from rdc_tool.platform.ipc import Endpoint
from rdc_tool.platform.locks import LockTimeout, path_lock
from rdc_tool.platform.process import ProcessIdentity, SpawnProfile
from rdc_tool.runtime_state import clear_context_state, context_log_path, context_state_path, list_context_ids
from rdc_tool.runtime_paths import child_python_argv, child_python_env, cli_runtime_dir
from rdc_tool.runtime_worker_state import clear_worker_state, worker_state_path

POLL_DELAYS = (0.1, 0.2, 0.3, 0.5, 0.8, 1.2, 1.6, 2.0)
MAX_STOP_TIMEOUT_S = 8.0


DAEMON_START_LOCK_TIMEOUT_S = 30.0
DAEMON_START_LOCK_POLL_S = 0.05


class DaemonStartLockTimeout(TimeoutError):
    def __init__(self, context: str, stage: str, elapsed: float, timeout: float) -> None:
        super().__init__(f"Timed out acquiring daemon startup lock for context {context!r}")
        self.code = "daemon_start_lock_timeout"
        self.category = "runtime"
        self.details = {
            "context_id": context,
            "failed_step": "daemon_start_lock",
            "waiting_for": stage,
            "elapsed_seconds": max(0.0, elapsed),
            "timeout_seconds": timeout,
            "recovery_hint": "Wait and retry the same context; do not stop the active owner or remove its state/lock.",
        }


@contextmanager
def _locked_daemon_start(context: str):
    # One acquisition deadline covers both thread and process contention.
    lock_path = state_path(context).with_suffix(".start.lock")
    with ExitStack() as stack:
        try:
            stack.enter_context(path_lock(lock_path, timeout=DAEMON_START_LOCK_TIMEOUT_S,
                                          poll_interval=DAEMON_START_LOCK_POLL_S))
        except LockTimeout as exc:
            raise DaemonStartLockTimeout(context, exc.stage, exc.elapsed, exc.timeout) from exc
        yield


class DaemonRequestTimeout(TimeoutError):
    def __init__(self, message: str, *, details: dict[str, Any]) -> None:
        super().__init__(message)
        self.code = "daemon_timeout"
        self.category = "runtime"
        self.details = dict(details)


class DaemonExecInterrupted(RuntimeError):
    """The daemon stopped answering a request whose outcome is therefore unknown."""

    category = "runtime"

    def __init__(self, code: str, message: str, *, details: dict[str, Any]) -> None:
        super().__init__(message)
        self.code = code
        self.details = dict(details)


# Requests that run operation work: the client waits for their reply without a
# fixed deadline, as long as the daemon lives and keeps sending heartbeats.
_STREAMED_METHODS = frozenset({"exec", "clear_context"})


def _await_streamed_reply(conn: Any, state: Dict[str, Any], method: str, params: Dict[str, Any],
                          context: Optional[str], on_frame: Optional[Callable[[Dict[str, Any]], None]]) -> Any:
    daemon = daemon_process(state)
    last_message = time.monotonic()

    def interrupted(code: str, reason: str, message: str, **extra: Any) -> DaemonExecInterrupted:
        exited = process.probe(daemon) is process.Liveness.EXITED
        return DaemonExecInterrupted(code, message, details={
            "failure_stage": "await_daemon_reply", "reason": reason, "outcome": "unknown",
            "operation": str(params.get("operation") or method), "request_id": str(params.get("request_id") or ""),
            "context_id": normalize_context_id(context),
            "daemon": {"pid": daemon.pid, "start_generation": daemon.birth}, "daemon_exit_confirmed": exited,
            **extra,
            "recovery_hint": "Inspect `rdc-tool context status`; the request may have completed or still be running.",
        })

    while True:
        if conn.poll(1.0):
            try:
                message = conn.recv()
            except (EOFError, OSError) as exc:
                raise interrupted("daemon_lost", "connection_closed",
                                  f"The daemon connection closed before {method} replied: {exc}") from exc
            last_message = time.monotonic()
            if isinstance(message, dict) and "kind" in message:
                if on_frame is not None:
                    on_frame(message)
                continue
            return message
        if process.probe(daemon) is process.Liveness.EXITED:
            raise interrupted("daemon_lost", "daemon_exited", f"The daemon exited before {method} replied")
        silence = time.monotonic() - last_message
        if silence > timeout_policy.DAEMON_HEARTBEAT_GAP_S:
            raise interrupted("daemon_unresponsive", "heartbeat_gap",
                              f"The daemon sent no heartbeat for {silence:.0f} s while {method} was pending",
                              heartbeat_gap_ms=int(silence * 1000))


def _active_operation_excerpt(state: Dict[str, Any]) -> Dict[str, Any]:
    payload = state.get("active_operation")
    if not isinstance(payload, dict):
        return {}
    excerpt: Dict[str, Any] = {}
    for key in ("operation", "trace_id", "started_at", "started_at_ms", "transport", "remote", "context_id"):
        if key in payload:
            excerpt[key] = payload.get(key)
    return excerpt


def _daemon_state_excerpt(state: Dict[str, Any]) -> Dict[str, Any]:
    excerpt: Dict[str, Any] = {}
    for key in (
        "context_id",
        "pid",
        "session_id",
        "capture_file_id",
        "active_event_id",
        "backend",
        "active_request_count",
        "last_activity_at",
        "recovery_status",
    ):
        if key in state:
            excerpt[key] = state.get(key)
    return excerpt


def context_occupies_capacity(context: Optional[str] = None) -> bool:
    ctx = normalize_context_id(context)
    if owner_is_busy(state_path(ctx), ctx):
        return True
    try:
        state = load_state(context=ctx)
    except DaemonOwnerUnavailable as exc:
        if exc.details.get("reason") != "invalid_state":
            raise
        _retire_unused_pipe_state(ctx)
        return False
    if not state:
        return False
    return any(identity.pid > 0 and process.is_alive(identity)
               for identity in (daemon_process(state), owner_process(state), worker_process(state)))


def _retire_unused_pipe_state(context: str) -> None:
    """Remove a pre-endpoint state only when its entire ownership is settled."""
    path = state_path(context)
    with _locked_daemon_start(context):
        status, expected = load_json_with_status(path)
        if status == "missing":
            return
        if status != "ok":
            raise DaemonOwnerUnavailable(context, path, "invalid_state")

        def verify(raw: Dict[str, Any]) -> None:
            def reject(reason: str) -> None:
                raise DaemonOwnerUnavailable(context, path, reason)

            if (raw.get("context_id") != context or raw.get("daemon_context", context) != context
                    or not isinstance(raw.get("pipe_name"), str) or not raw["pipe_name"].strip()
                    or raw.get("endpoint") or not isinstance(raw.get("token"), str) or not raw["token"]):
                reject("invalid_state")
            if any(type(raw.get(key)) is not int or raw[key] != 0 for key in ("session_count", "capture_count", "active_request_count")):
                reject("legacy_state_resources_unconfirmed")
            if any(raw.get(key) for key in ("session_id", "capture_file_id", "active_operation")):
                reject("legacy_state_resources_unconfirmed")
            worker = raw.get("worker")
            clients = raw.get("attached_clients")
            if not isinstance(worker, dict) or not isinstance(clients, list):
                reject("legacy_state_identity_unconfirmed")
            identities = [(raw, "pid", "birth", True), (raw, "owner_pid", "owner_birth", False),
                          (worker, "pid", "birth", bool(worker.get("running")))]
            for client in clients:
                if not isinstance(client, dict):
                    reject("legacy_state_identity_unconfirmed")
                identities.append((client, "pid", "birth", True))
            worker_status, worker_record = load_json_with_status(worker_state_path(context))
            if worker_status == "invalid":
                reject("legacy_state_identity_unconfirmed")
            if worker_status == "ok":
                if worker_record.get("context_id") != context:
                    reject("legacy_state_identity_unconfirmed")
                identities.append((worker_record, "pid", "birth", bool(worker_record.get("running"))))
            for item, pid_key, birth_key, required in identities:
                pid = item.get(pid_key)
                if type(pid) is not int or pid < 0 or (required and pid == 0):
                    reject("legacy_state_identity_unconfirmed")
                birth = item.get(birth_key, "")
                if not isinstance(birth, str):
                    reject("legacy_state_identity_unconfirmed")
                if pid and process.probe(ProcessIdentity(pid, birth)) is not process.Liveness.EXITED:
                    reject("legacy_state_identity_unconfirmed")
            if context_has_unreleased_resources(context):
                reject("legacy_state_resources_unconfirmed")
            snapshot_status, snapshot = load_json_with_status(context_snapshot_path(context))
            runtime_status, runtime = load_json_with_status(context_state_path(context))
            if snapshot_status == "invalid" or runtime_status == "invalid":
                reject("legacy_state_resources_unconfirmed")
            for status, record in ((snapshot_status, snapshot), (runtime_status, runtime)):
                if status == "ok" and record.get("context_id") != context:
                    reject("legacy_state_resources_unconfirmed")
            if snapshot_status == "ok":
                remote = snapshot.get("remote")
                snapshot_runtime = snapshot.get("runtime")
                preview = snapshot.get("preview", {})
                if not isinstance(remote, dict) or not isinstance(snapshot_runtime, dict) or not isinstance(preview, dict):
                    reject("legacy_state_resources_unconfirmed")
                bootstrap = remote.get("bootstrap") or {}
                if (not isinstance(bootstrap, dict) or remote.get("state", "none") != "none"
                        or remote.get("origin_remote_id") or remote.get("consumed_by_session_id")
                        or bootstrap.get("owned_pids") or preview.get("enabled")
                        or preview.get("bound_session_id") or preview.get("bound_capture_file_id")):
                    reject("legacy_state_resources_unconfirmed")
            elif raw.get("backend") != "local":
                reject("legacy_state_resources_unconfirmed")
            if runtime_status == "ok":
                preview = runtime.get("preview", {})
                if (not isinstance(runtime.get("sessions"), dict) or not isinstance(runtime.get("captures"), dict)
                        or runtime.get("current_session_id") or runtime.get("current_capture_file_id")
                        or not isinstance(preview, dict) or preview.get("enabled")
                        or preview.get("bound_session_id") or preview.get("bound_capture_file_id")):
                    reject("legacy_state_resources_unconfirmed")

        retire_incomplete_state(context, expected, verify)


def list_occupying_context_ids() -> list[str]:
    ids = { normalize_context_id(item) for item in list_context_ids() }
    ids.update(normalize_context_id(item) for item in list_daemon_context_ids())
    return sorted(ctx for ctx in ids if context_occupies_capacity(ctx))


def _state_paths(context: Optional[str] = None) -> Iterable[Path]:
    if context is not None:
        path = state_path(context)
        if path.is_file():
            yield path
        return
    yield from cli_runtime_dir().glob("daemon_state*.json")


def _remove_file_if_exists(path: Path, cleaned: list[str]) -> None:
    try:
        if not path.is_file():
            return
    except Exception:
        return
    try:
        path.unlink(missing_ok=True)
    except Exception:
        return
    cleaned.append(path.name)


def _clear_orphan_context_artifacts(context: str, cleaned: Dict[str, list[str]]) -> None:
    ctx = normalize_context_id(context)
    if owner_is_busy(state_path(ctx), ctx) or context_has_unreleased_resources(ctx):
        return
    _remove_file_if_exists(context_state_path(ctx), cleaned["context_files"])
    _remove_file_if_exists(context_snapshot_path(ctx), cleaned["snapshot_files"])
    _remove_file_if_exists(context_log_path(ctx), cleaned["log_files"])
    _remove_file_if_exists(worker_state_path(ctx), cleaned["worker_files"])


def context_has_unreleased_resources(context: str) -> bool:
    """A dead daemon does not prove that its persisted native resources were released."""
    for path in (context_state_path(context), context_snapshot_path(context)):
        status, payload = load_json_with_status(path)
        if status == "invalid":
            return True
        if status == "missing":
            continue
        if path == context_state_path(context):
            if payload.get("sessions") or payload.get("captures"):
                return True
            continue
        runtime = payload.get("runtime") or {}
        remote = payload.get("remote") or {}
        if not isinstance(runtime, dict) or not isinstance(remote, dict):
            return True
        bootstrap = remote.get("bootstrap") or {}
        if not isinstance(bootstrap, dict):
            return True
        if (runtime.get("session_id") or runtime.get("capture_file_id")
                or remote.get("remote_id") or remote.get("active_session_ids")
                or bootstrap.get("started_activity") or bootstrap.get("created_forward")):
            return True
    return False


def owner_lost_should_stop(
    *,
    owner_pid: int,
    owner_running: bool,
    has_live_clients: bool,
    last_activity_ms: int,
    now_ms: int,
    lease_timeout_seconds: int,
) -> bool:
    if int(owner_pid) <= 0 or owner_running or has_live_clients:
        return False
    lease_ms = normalize_timeout(lease_timeout_seconds, default=DEFAULT_LEASE_TIMEOUT_S) * 1000
    return last_activity_ms <= 0 or (now_ms - last_activity_ms) >= lease_ms


def _is_client_live(client: Dict[str, Any], now_ms: int) -> bool:
    identity = process_identity(client.get("pid"), client.get("birth"))
    if identity.pid > 0 and not process.is_alive(identity):
        return False
    heartbeat_ms = iso_to_ms(client.get("last_heartbeat_at"))
    lease_ms = normalize_timeout(
        client.get("lease_timeout_seconds"),
        default=DEFAULT_LEASE_TIMEOUT_S,
    ) * 1000
    if heartbeat_ms <= 0:
        return True
    return (now_ms - heartbeat_ms) <= lease_ms


def _state_should_reap(state: Dict[str, Any], now_ms: Optional[int] = None) -> bool:
    if not state:
        return True
    current_ms = epoch_ms() if now_ms is None else int(now_ms)
    daemon = daemon_process(state)
    if daemon.pid <= 0 or not process.is_alive(daemon):
        return True

    clients = normalize_attached_clients(state.get("attached_clients"))
    live_clients = [item for item in clients if _is_client_live(item, current_ms)]
    if live_clients:
        return False

    last_activity_ms = iso_to_ms(state.get("last_activity_at"))
    if last_activity_ms <= 0:
        last_activity_ms = iso_to_ms(state.get("started_at"))
    owner = owner_process(state)
    if owner_lost_should_stop(
        owner_pid=owner.pid,
        owner_running=process.is_alive(owner) if owner.pid > 0 else True,
        has_live_clients=False,
        last_activity_ms=last_activity_ms,
        now_ms=current_ms,
        lease_timeout_seconds=normalize_timeout(state.get("lease_timeout_seconds"), default=DEFAULT_LEASE_TIMEOUT_S),
    ):
        return True
    if int(state.get("active_request_count") or 0) > 0:
        return False
    idle_timeout_ms = normalize_timeout(
        state.get("idle_timeout_seconds"), default=DEFAULT_IDLE_TIMEOUT_S,
    ) * 1000
    if last_activity_ms > 0 and (current_ms - last_activity_ms) >= idle_timeout_ms:
        return not context_has_unreleased_resources(normalize_context_id(state.get("context_id")))
    return False


def daemon_request(
    method: str,
    *,
    params: Optional[Dict[str, Any]] = None,
    timeout: float = timeout_policy.CONTROL_REQUEST_TIMEOUT_S,
    state: Optional[Dict[str, Any]] = None,
    context: Optional[str] = "default",
    on_frame: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> Dict[str, Any]:
    """One daemon request. Control methods have a short deadline; exec and
    clear_context wait for as long as the daemon lives and sends heartbeats."""
    st = state or load_state(context=context)
    if not is_complete(st):
        raise RuntimeError("No active daemon state. Run `rdc-tool daemon start` first.")
    payload = {"method": str(method), "params": dict(params or {})}
    conn = ipc.connect(Endpoint(st["endpoint"]), authkey=st["token"].encode("utf-8"))
    try:
        conn.send(payload)
        if method in _STREAMED_METHODS:
            response = _await_streamed_reply(conn, st, method, payload["params"], context, on_frame)
        elif timeout:
            deadline = time.time() + timeout
            while time.time() < deadline:
                if conn.poll(0.1):
                    break
            else:
                operation = str((params or {}).get("operation") or method).strip()
                try:
                    latest_state = load_state(context=context)
                except Exception:
                    latest_state = {}
                diagnostic_state = latest_state or st
                raise DaemonRequestTimeout(
                    f"Timed out waiting for daemon response to {method}",
                    details={
                        "operation": operation,
                        "failed_step": "daemon_request",
                        "context_id": normalize_context_id(context),
                        "timeout_seconds": float(timeout),
                        "active_request_count": int(diagnostic_state.get("active_request_count") or 0),
                        "active_operation": _active_operation_excerpt(diagnostic_state),
                        "daemon_state_excerpt": _daemon_state_excerpt(diagnostic_state),
                        "recovery_hint": "Run `rdc-tool context clear` or `rd.core.shutdown` on the same context before retrying.",
                    },
                )
            response = conn.recv()
        else:
            response = conn.recv()
    finally:
        conn.close()
    if not isinstance(response, dict):
        raise RuntimeError(f"Invalid daemon response: {type(response).__name__}")
    return response


def read_context_status(context: Optional[str] = "default") -> Dict[str, Any]:
    """The context's read-only status. Asks a live daemon; otherwise reads the
    recorded state and probes its identities. Never starts or cleans up anything."""
    chosen_ctx = normalize_context_id(context)
    status, state = load_json_with_status(state_path(chosen_ctx))
    if status != "ok" or not is_complete(state) or not process.is_alive(daemon_process(state)):
        return context_status.from_state_files(chosen_ctx)
    try:
        response = daemon_request("context_status", params={}, context=chosen_ctx, state=state)
    except Exception as exc:  # noqa: BLE001
        return context_status.from_state_files(chosen_ctx, daemon_error=f"daemon_unreachable: {exc}")
    if not bool(response.get("ok")) or not isinstance(response.get("result"), dict):
        error = response.get("error") if isinstance(response.get("error"), dict) else {}
        return context_status.from_state_files(chosen_ctx, daemon_error=f"daemon_rejected: {error.get('code', '')}")
    return dict(response["result"])


def cancel_request(*, context: Optional[str] = "default", request_id: str) -> Dict[str, Any]:
    """Cancel one queued or running request and return its receipt; never starts a daemon."""
    chosen_ctx = normalize_context_id(context)
    state = load_state(context=chosen_ctx)
    if not state or not process.is_alive(daemon_process(state)):
        # No live daemon owns the context, so no request of it can be queued or running.
        return {"request_id": request_id, "trace_id": "", "outcome": "not_found", "settled_at_ms": epoch_ms()}
    response = daemon_request("cancel", params={"request_id": request_id}, context=chosen_ctx, state=state,
                              timeout=timeout_policy.CANCEL_REQUEST_TIMEOUT_S)
    if not bool(response.get("ok")):
        error = response.get("error") if isinstance(response.get("error"), dict) else {}
        raise DaemonExecInterrupted(str(error.get("code") or "cancel_failed"), str(error.get("message") or "cancel failed"),
                                    details=error.get("details") if isinstance(error.get("details"), dict) else {})
    return dict(response.get("result") or {})


def _wait_for_daemon_ready(state: Dict[str, Any]) -> bool:
    for delay in POLL_DELAYS:
        try:
            daemon_request("ping", params={}, timeout=1.0, state=state, context=state.get("context_id"))
            return True
        except Exception:
            time.sleep(delay)
    return False


def _shutdown_stateful_daemon(daemon: ProcessIdentity, state: Dict[str, Any], context: str) -> bool:
    if daemon.pid > 0 and process.is_alive(daemon):
        for _ in range(4):
            try:
                daemon_request("shutdown", params={}, state=state, context=context)
            except Exception:
                pass
            if process.wait_exit(daemon, 2.0):
                return True
            time.sleep(0.5)

        process.kill_tree(daemon)
        return process.wait_exit(daemon, 3.0)
    return True


def cleanup_stale_daemon_states(context: Optional[str] = None) -> Dict[str, list[str]]:
    cleaned = {
        "state_files": [],
        "killed_pids": [],
        "context_files": [],
        "snapshot_files": [],
        "log_files": [],
        "worker_files": [],
    }
    live_contexts: set[str] = set()
    for path in _state_paths(context):
        status, raw = load_json_with_status(path)
        ctx = context_from_state_path(path)
        if status == "missing":
            if owner_is_busy(path, ctx):
                live_contexts.add(ctx)
            continue
        if status == "invalid":
            live_contexts.add(ctx)
            continue
        try:
            state = normalize_state(raw, ctx) if raw else {}
            valid = bool(state) and is_complete(state)
        except (TypeError, ValueError, OverflowError):
            valid = False
        if not valid:
            live_contexts.add(ctx)
            continue
        daemon = daemon_process(state)
        worker = worker_process(state)

        if _state_should_reap(state):
            if daemon.pid > 0 and process.is_alive(daemon):
                try:
                    daemon_request("shutdown", params={}, state=state, context=ctx)
                except Exception:
                    pass
                if not process.wait_exit(daemon, MAX_STOP_TIMEOUT_S):
                    if process.kill_tree(daemon):
                        cleaned["killed_pids"].append(str(daemon.pid))
                        process.wait_exit(daemon, 3.0)
            if worker.pid > 0 and process.is_alive(worker):
                if process.kill_tree(worker):
                    cleaned["killed_pids"].append(str(worker.pid))
                    process.wait_exit(worker, 3.0)
            if (daemon.pid > 0 and process.is_alive(daemon)) or (worker.pid > 0 and process.is_alive(worker)):
                live_contexts.add(ctx)
                continue
            if owner_is_busy(path, ctx):
                live_contexts.add(ctx)
                continue
            clear_state(ctx, expected=state)
            clear_worker_state(ctx)
            ipc.discard(Endpoint(state["endpoint"]))
            cleaned["state_files"].append(path.name)
            continue

        live_contexts.add(ctx)

    if context is None:
        for ctx in list_context_ids():
            normalized = normalize_context_id(ctx)
            if normalized in live_contexts:
                continue
            _clear_orphan_context_artifacts(normalized, cleaned)
    return cleaned


def _update_saved_state_from_response(
    response: Dict[str, Any], context: str, *, expected: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    result = response.get("result")
    if isinstance(result, dict):
        daemon_state = result.get("state")
        if isinstance(daemon_state, dict):
            normalized = normalize_state(daemon_state, context)
            current = load_state(context)
            # Daemon responses never carry the IPC key; keep the caller's copy.
            normalized["token"] = str((expected or current or {}).get("token") or "")
            if (expected and owner_identity(expected) != owner_identity(normalized)) or (
                current and owner_identity(current) != owner_identity(normalized)
            ):
                raise DaemonOwnerUnavailable(context, state_path(context), "response_owner_changed")
            # The daemon publishes its own state. A delayed RPC response must
            # never overwrite a newer heartbeat or another generation.
            return normalized
    state = load_state(context=context)
    if state:
        return state
    return {}


def ensure_daemon(
    *,
    context: Optional[str] = "default",
    owner_pid: Optional[int] = None,
    lease_timeout_seconds: int = DEFAULT_LEASE_TIMEOUT_S,
    idle_timeout_seconds: int = DEFAULT_IDLE_TIMEOUT_S,
) -> Tuple[bool, str, Dict[str, Any]]:
    with _locked_daemon_start(normalize_context_id(context)):
        return _ensure_daemon_locked(
            context=context, owner_pid=owner_pid,
            lease_timeout_seconds=lease_timeout_seconds, idle_timeout_seconds=idle_timeout_seconds,
        )


def _ensure_daemon_locked(
    *, context: Optional[str],
    owner_pid: Optional[int], lease_timeout_seconds: int, idle_timeout_seconds: int,
) -> Tuple[bool, str, Dict[str, Any]]:
    chosen_ctx = normalize_context_id(context)
    owner_state = state_path(chosen_ctx)
    status, _ = load_json_with_status(owner_state)
    existing = load_state(context=chosen_ctx)
    if not existing and (status == "invalid" or owner_is_busy(owner_state, chosen_ctx)):
        raise DaemonOwnerUnavailable(chosen_ctx, owner_state, "invalid_state" if status == "invalid" else "owner_state_missing")
    if existing:
        daemon = daemon_process(existing)
        if daemon.pid > 0 and process.is_alive(daemon):
            if owner_pid is not None and int(existing.get("owner_pid") or 0) == 0:
                try:
                    claimed = daemon_request(
                        "claim_owner",
                        params={"owner_pid": int(owner_pid)},
                        context=chosen_ctx,
                        state=existing,
                    )
                    existing = _update_saved_state_from_response(claimed, chosen_ctx, expected=existing) or existing
                except Exception:
                    pass
            try:
                response = daemon_request("status", params={}, context=chosen_ctx, state=existing)
                if not response.get("ok"):
                    raise RuntimeError("Daemon status was rejected")
            except Exception as exc:
                raise DaemonOwnerUnavailable(chosen_ctx, owner_state, "live_owner_status_failed") from exc
            else:
                updated = _update_saved_state_from_response(response, chosen_ctx, expected=existing)
                return True, "daemon already running", updated or existing
        else:
            if owner_is_busy(owner_state, chosen_ctx):
                raise DaemonOwnerUnavailable(chosen_ctx, owner_state, "owner_exit_unconfirmed")
            cleanup_stale_daemon_states(context=chosen_ctx)
            worker = worker_process(existing)
            if worker.pid > 0 and process.is_alive(worker):
                raise DaemonOwnerUnavailable(chosen_ctx, owner_state, "worker_exit_unconfirmed")
            remaining_status, _ = load_json_with_status(owner_state)
            if remaining_status != "missing":
                # Cleanup retains state when any recorded owner/resource could
                # not be released. It alone authorizes retiring that state.
                raise DaemonOwnerUnavailable(chosen_ctx, owner_state, "owner_exit_unconfirmed")

    if owner_is_busy(owner_state, chosen_ctx):
        raise DaemonOwnerUnavailable(chosen_ctx, owner_state, "owner_lock_busy")

    endpoint = ipc.new_endpoint()
    token = secrets.token_hex(32)
    cmd = child_python_argv(
        "rdc_tool.daemon.server",
        "--endpoint",
        endpoint.address,
        "--daemon-context",
        chosen_ctx,
        "--lease-timeout-seconds",
        str(normalize_timeout(lease_timeout_seconds, default=DEFAULT_LEASE_TIMEOUT_S)),
        "--idle-timeout-seconds",
        str(normalize_timeout(idle_timeout_seconds, default=DEFAULT_IDLE_TIMEOUT_S)),
    )
    if owner_pid is not None:
        cmd.extend(["--owner-pid", str(int(owner_pid))])

    popen_kwargs: Dict[str, Any] = {
        # The IPC key reaches the daemon through stdin, never through argv.
        "stdin": subprocess.PIPE,
        "text": True,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        **process.popen_options(SpawnProfile.DAEMON),
    }
    popen_kwargs["env"] = child_python_env(os.environ)

    proc = subprocess.Popen(cmd, **popen_kwargs)
    assert proc.stdin is not None
    with proc.stdin:
        proc.stdin.write(token + "\n")
    try:
        daemon = process.identify(proc.pid)
    except ProcessLookupError:
        daemon = ProcessIdentity(int(proc.pid))
    state = normalize_state(
        {
            "endpoint": endpoint.address,
            "token": token,
            "pid": daemon.pid,
            "birth": daemon.birth,
            "started_at": utc_now_iso(),
            "last_activity_at": utc_now_iso(),
            "context_id": chosen_ctx,
            "owner_pid": int(owner_pid) if owner_pid else 0,
            "lease_timeout_seconds": lease_timeout_seconds,
            "idle_timeout_seconds": idle_timeout_seconds,
            "attached_clients": [],
        },
        chosen_ctx,
    )

    if not _wait_for_daemon_ready(state):
        process.kill_tree(daemon)
        if not process.wait_exit(daemon, 3.0) or owner_is_busy(owner_state, chosen_ctx):
            raise DaemonOwnerUnavailable(chosen_ctx, owner_state, "startup_exit_unconfirmed")
        clear_state(context=chosen_ctx, expected=state)
        ipc.discard(endpoint)
        return False, "daemon failed to start (ready timeout)", {}

    try:
        response = daemon_request("status", params={}, timeout=2.0, state=state, context=chosen_ctx)
        if not response.get("ok"):
            raise RuntimeError("Daemon status was rejected")
    except Exception as exc:
        raise DaemonOwnerUnavailable(chosen_ctx, owner_state, "started_owner_status_failed") from exc

    updated = _update_saved_state_from_response(response, chosen_ctx, expected=state)
    return True, "daemon started", updated or state


def attach_client(
    *,
    context: Optional[str] = "default",
    client_id: str,
    client_type: str,
    pid: int,
    lease_timeout_seconds: int = DEFAULT_LEASE_TIMEOUT_S,
    owner_pid: Optional[int] = None,
) -> Tuple[bool, str, Dict[str, Any]]:
    chosen_ctx = normalize_context_id(context)
    ok, message, state = ensure_daemon(
        context=chosen_ctx,
        owner_pid=owner_pid,
        lease_timeout_seconds=lease_timeout_seconds,
    )
    if not ok:
        return False, message, {}
    response = daemon_request(
        "attach_client",
        params={
            "client_id": str(client_id),
            "client_type": str(client_type),
            "pid": int(pid),
            "lease_timeout_seconds": normalize_timeout(
                lease_timeout_seconds,
                default=DEFAULT_LEASE_TIMEOUT_S,
            ),
        },
        context=chosen_ctx,
        state=state,
    )
    if not bool(response.get("ok")):
        err = response.get("error") if isinstance(response.get("error"), dict) else {}
        return False, str(err.get("message") or "attach client failed"), state
    updated = _update_saved_state_from_response(response, chosen_ctx, expected=state)
    return True, message, updated or state


def heartbeat_client(
    *,
    context: Optional[str] = "default",
    client_id: str,
    pid: int = 0,
) -> Tuple[bool, str, Dict[str, Any]]:
    chosen_ctx = normalize_context_id(context)
    state = load_state(context=chosen_ctx)
    if not state:
        return False, "no active daemon", {}
    response = daemon_request(
        "heartbeat",
        params={"client_id": str(client_id), "pid": int(pid or 0)},
        context=chosen_ctx,
        state=state,
    )
    if not bool(response.get("ok")):
        err = response.get("error") if isinstance(response.get("error"), dict) else {}
        return False, str(err.get("message") or "heartbeat failed"), state
    updated = _update_saved_state_from_response(response, chosen_ctx, expected=state)
    return True, "heartbeat updated", updated or state


def detach_client(
    *,
    context: Optional[str] = "default",
    client_id: str,
) -> Tuple[bool, str, Dict[str, Any]]:
    chosen_ctx = normalize_context_id(context)
    state = load_state(context=chosen_ctx)
    if not state:
        return False, "no active daemon", {}
    response = daemon_request(
        "detach_client",
        params={"client_id": str(client_id)},
        context=chosen_ctx,
        state=state,
    )
    if not bool(response.get("ok")):
        err = response.get("error") if isinstance(response.get("error"), dict) else {}
        return False, str(err.get("message") or "detach failed"), state
    updated = _update_saved_state_from_response(response, chosen_ctx, expected=state)
    return True, "client detached", updated or state


def _worker_record_exited(context: str) -> bool:
    status, record = load_json_with_status(worker_state_path(context))
    if status == "missing":
        return True
    if (status != "ok" or record.get("context_id") != context or type(record.get("pid")) is not int
            or record["pid"] <= 0 or not isinstance(record.get("birth", ""), str)):
        return False
    return process.probe(ProcessIdentity(record["pid"], record.get("birth", ""))) is process.Liveness.EXITED


def clear_context(context: Optional[str] = "default") -> Tuple[bool, str, Dict[str, Any]]:
    chosen_ctx = normalize_context_id(context)
    state = load_state(context=chosen_ctx)
    if not state:
        status, _ = load_json_with_status(state_path(chosen_ctx))
        if status == "invalid" or owner_is_busy(state_path(chosen_ctx), chosen_ctx):
            raise DaemonOwnerUnavailable(chosen_ctx, state_path(chosen_ctx), "owner_state_unavailable")
        cleanup_stale_daemon_states(context=chosen_ctx)
        if context_has_unreleased_resources(chosen_ctx):
            return False, "context still owns resources; restart its daemon and clear it", {"context_id": chosen_ctx}
        if not _worker_record_exited(chosen_ctx):
            return False, "context worker identity is unconfirmed; preserve its registration", {"context_id": chosen_ctx}
        clear_context_snapshot(context=chosen_ctx)
        clear_context_state(context=chosen_ctx)
        clear_worker_state(context=chosen_ctx)
        return True, "context cleared (no active daemon)", {"released": {}, "state": {}}

    try:
        response = daemon_request("clear_context", params={}, context=chosen_ctx, state=state)
    except Exception:
        if process.is_alive(daemon_process(state)) or owner_is_busy(state_path(chosen_ctx), chosen_ctx):
            return False, "context clear failed; owner termination is unconfirmed", {"state": state}
        cleanup_stale_daemon_states(context=chosen_ctx)
        refreshed = load_state(context=chosen_ctx)
        if refreshed:
            return False, "context clear failed", {"state": refreshed}
        if context_has_unreleased_resources(chosen_ctx):
            return False, "context clear failed; persisted resources remain", {"context_id": chosen_ctx}
        if not _worker_record_exited(chosen_ctx):
            return False, "context clear failed; worker identity is unconfirmed", {"context_id": chosen_ctx}
        clear_context_snapshot(context=chosen_ctx)
        clear_context_state(context=chosen_ctx)
        clear_worker_state(context=chosen_ctx)
        return True, "context cleared (no active daemon)", {"released": {}, "state": {}}
    if not bool(response.get("ok")):
        err = response.get("error") if isinstance(response.get("error"), dict) else {}
        return False, str(err.get("message") or "context clear failed"), {}
    updated = _update_saved_state_from_response(response, chosen_ctx, expected=state)
    clear_context_snapshot(context=chosen_ctx)
    clear_context_state(context=chosen_ctx)
    result = response.get("result") if isinstance(response.get("result"), dict) else {}
    details = dict(result)
    if updated:
        details["state"] = updated
    return True, "context cleared", details


def stop_daemon(context: Optional[str] = "default") -> Tuple[bool, str]:
    # A new starter must wait until both daemon and worker exits are confirmed.
    with _locked_daemon_start(normalize_context_id(context)):
        return _stop_daemon_locked(context)


def _stop_daemon_locked(context: Optional[str]) -> Tuple[bool, str]:
    chosen_ctx = normalize_context_id(context)
    if context_has_unreleased_resources(chosen_ctx):
        return False, "context still owns resources; clear it before stopping the daemon"
    st = load_state(context=chosen_ctx)
    if not st:
        cleanup_stale_daemon_states(context=chosen_ctx)
        st = load_state(context=chosen_ctx)
    if not st:
        clear_state(context=chosen_ctx)
        clear_worker_state(context=chosen_ctx)
        return False, "no active daemon"

    daemon = daemon_process(st)
    worker = worker_process(st)
    if not _shutdown_stateful_daemon(daemon, st, chosen_ctx):
        # An unreadable identity is reported as such: it never authorizes a kill.
        return False, f"daemon stop timed out: pid {daemon.pid} is {process.probe(daemon).value}"

    if worker.pid > 0 and process.is_alive(worker):
        if not process.kill_tree(worker) or not process.wait_exit(worker, 3.0):
            return False, "worker stop timed out"

    if not wait_for_owner_exit(state_path(chosen_ctx), chosen_ctx):
        return False, "daemon ownership release timed out"
    clear_state(context=chosen_ctx, expected=st)
    ipc.discard(Endpoint(st["endpoint"]))
    clear_worker_state(context=chosen_ctx)
    return True, "daemon stopped"
