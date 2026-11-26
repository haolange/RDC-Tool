from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import shlex
import subprocess
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from rdc_tool import native_calls, progress, timeout_policy
from rdc_tool.platform import process
from rdc_tool.platform import host as platform_host
from rdc_tool.core.errors import CoreError
from rdc_tool.core.renderdoc_status import build_renderdoc_error_details, status_ok as _rd_status_ok, status_text as _rd_status_text
from rdc_tool.models import (
    BackendType,
    CaptureInfo,
    ErrorDetail,
    GraphicsAPI,
    SessionCapabilities,
    SessionInfo,
    _new_id,
)

logger = logging.getLogger(__name__)


def _get_rd() -> Any:
    import renderdoc as rd

    return rd


_GRAPHICS_API_MAP: Dict[str, GraphicsAPI] = {
    "d3d11": GraphicsAPI.D3D11,
    "d3d12": GraphicsAPI.D3D12,
    "vulkan": GraphicsAPI.VULKAN,
    "opengl": GraphicsAPI.OPENGL,
    "opengles": GraphicsAPI.OPENGLES,
}


def _map_graphics_api(api_props: Any) -> GraphicsAPI:
    raw_value = None
    try:
        raw_value = getattr(api_props, "pipelineType")
    except (AttributeError, TypeError):
        return GraphicsAPI.UNKNOWN
    try:
        raw_int = int(raw_value)
    except (TypeError, ValueError):
        raw_int = None
    if raw_int is not None:
        numeric_map: Dict[int, GraphicsAPI] = {
            0: GraphicsAPI.D3D11,
            1: GraphicsAPI.D3D12,
            2: GraphicsAPI.OPENGL,
            3: GraphicsAPI.VULKAN,
        }
        if raw_int in numeric_map:
            return numeric_map[raw_int]
    raw = str(raw_value).lower()
    for key, value in _GRAPHICS_API_MAP.items():
        if key in raw:
            return value
    return GraphicsAPI.UNKNOWN


def _count_actions(actions: Any) -> int:
    total = 0
    for action in actions or []:
        total += 1
        children = getattr(action, "children", None)
        if children:
            total += _count_actions(children)
    return total


def _controller_patch_supported(controller: Any) -> bool:
    required = ("BuildTargetShader", "ReplaceResource", "RemoveReplacement", "FreeTargetResource")
    return all(hasattr(controller, name) for name in required)


def _status_ok(status: Any) -> bool:
    return _rd_status_ok(status, _get_rd())


def _status_text(status: Any) -> str:
    return _rd_status_text(status)


def _check_status(
    status: Any,
    operation: str,
    *,
    backend_type: str = "local",
    capture_context: Optional[Dict[str, Any]] = None,
    source_layer: str = "renderdoc_status",
    classification: str = "renderdoc_status",
    fix_hint: str = "Inspect the RenderDoc status and capture context before retrying.",
) -> None:
    if not _status_ok(status):
        details = build_renderdoc_error_details(
            status,
            operation=operation,
            source_layer=source_layer,
            backend_type=backend_type,
            capture_context=capture_context,
            classification=classification,
            fix_hint=fix_hint,
        )
        raise SessionError(
            code="renderdoc_error",
            message=f"{operation} failed with status: {details['renderdoc_status']['status_text']}",
            details=details,
        )


@dataclass
class SessionState:
    session_id: str
    backend_type: BackendType
    controller: Any = None
    output: Any = None
    capture_file: Any = None
    remote_server: Any = None
    remote_server_owned: bool = True
    presentation_sequence: int = 0
    remote_host: str = ""
    remote_port: Any = None
    remote_transport: str = ""
    remote_bootstrap: Dict[str, Any] = field(default_factory=dict)
    remote_bootstrap_result: Any = None
    remote_device_serial: str = ""
    transfer_progress: Any = None
    # Device-side transfer directories whose release could not be confirmed;
    # the owning context removes them during clear_context.
    retained_transfer_dirs: List[str] = field(default_factory=list)
    capabilities: SessionCapabilities = field(default_factory=SessionCapabilities)
    capture_id: Optional[str] = None
    is_initialized: bool = False
    rdc_path: Optional[str] = None
    replay_config: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    cleanup_error: str = ""


class TransferInterrupted(RuntimeError):
    """An adb transfer stopped making progress or was cancelled; its client was killed."""

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason  # stalled | cancelled


def _run_transfer(command: list[str], observe_size: Any, on_growth: Any, window_s: float) -> subprocess.CompletedProcess:
    """Run one adb transfer under a no-progress budget instead of a fixed timeout.

    Once a second the destination size is observed: growth is progress, a
    destination that does not grow for ``window_s`` is a stall, and a cancelled
    request stops the transfer. Either way only the adb client is killed;
    device-side work it started may continue, so the caller keeps the recovery
    paths.
    """
    proc = process.start_tool(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    largest = -1
    last_growth = time.monotonic()
    try:
        while True:
            try:
                out, err = proc.communicate(timeout=1.0)
                return subprocess.CompletedProcess(command, proc.returncode, out, err)
            except subprocess.TimeoutExpired:
                pass
            if progress.cancel_requested():
                raise TransferInterrupted("cancelled", "transfer cancelled by the request owner")
            observed = observe_size()
            if observed > largest:
                largest, last_growth = observed, time.monotonic()
                on_growth(observed)
            elif time.monotonic() - last_growth > window_s:
                raise TransferInterrupted("stalled", f"transfer made no progress for {window_s:.0f} s")
    except BaseException:
        if proc.poll() is None:
            proc.kill()
        proc.communicate()
        raise


class SessionError(Exception):
    def __init__(self, code: str, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message)
        self.detail = ErrorDetail(code=code, message=message, details=details)


class SessionManager:
    _instance: Optional["SessionManager"] = None
    _initialized: bool = False

    def __new__(cls) -> "SessionManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        if SessionManager._initialized:
            return
        self._sessions: Dict[str, SessionState] = {}
        self._lock: asyncio.Lock = asyncio.Lock()
        self._replay_initialized: bool = False
        SessionManager._initialized = True

    @classmethod
    def reset(cls) -> None:
        cls._instance = None
        cls._initialized = False

    async def create_session(
        self,
        backend_config: Dict[str, Any],
        replay_config: Dict[str, Any],
        *,
        preferred_session_id: Optional[str] = None,
    ) -> SessionInfo:
        backend_type = BackendType.REMOTE if backend_config.get("type") == "remote" else BackendType.LOCAL
        async with self._lock:
            session_id = str(preferred_session_id or "").strip() or _new_id("sess")
            if session_id in self._sessions:
                raise SessionError(
                    code="session_conflict",
                    message=f"Session {session_id} already exists",
                )
            state = SessionState(
                session_id=session_id,
                backend_type=backend_type,
                replay_config=dict(replay_config or {}),
            )
            if backend_type == BackendType.LOCAL:
                await self._ensure_local_replay_initialized()
            else:
                await self._init_remote(state, backend_config)
                state.capabilities.remote = True
            self._sessions[session_id] = state
            return SessionInfo(
                session_id=session_id,
                backend_type=backend_type,
                capabilities=state.capabilities,
                created_at=state.created_at,
            )

    async def open_capture(self, session_id: str, rdc_path: str) -> CaptureInfo:
        async with self._lock:
            state = self._require_state(session_id)
            if state.is_initialized:
                raise SessionError(
                    code="capture_already_open",
                    message=f"Session {session_id} already has an opened capture",
                )
            if state.backend_type == BackendType.LOCAL:
                await self._open_local_capture(state, rdc_path)
            else:
                await self._open_remote_capture(state, rdc_path)

            controller = state.controller
            if controller is None:
                raise SessionError(code="controller_missing", message=f"Session {session_id} has no replay controller")

            try:
                props = await native_calls.offload(controller.GetAPIProperties)
            except Exception:
                props = None
            state.capabilities.api = _map_graphics_api(props)
            state.capabilities.remote = state.backend_type == BackendType.REMOTE
            state.capabilities.shader_debug_supported = bool(getattr(props, "shaderDebugging", False)) if props is not None else False
            state.capabilities.patch_supported = _controller_patch_supported(controller)
            state.capabilities.counters_supported = True

            try:
                roots = await native_calls.offload(controller.GetRootActions)
            except Exception:
                roots = []

            state.capture_id = _new_id("cap")
            state.rdc_path = str(rdc_path)
            state.is_initialized = True

            return CaptureInfo(
                capture_id=state.capture_id,
                session_id=session_id,
                rdc_path=str(rdc_path),
                api=state.capabilities.api,
                frame_count=1,
                total_events=_count_actions(roots),
            )

    async def close_session(self, session_id: str) -> None:
        async with self._lock:
            state = self._sessions.get(session_id)
            if state is None:
                raise SessionError(code="session_not_found", message=f"Unknown session_id: {session_id}")
            if state.cleanup_error:
                raise SessionError(code="session_cleanup_unconfirmed", message=state.cleanup_error)
            try:
                await self._cleanup(state)
            except BaseException as exc:
                state.cleanup_error = f"Session cleanup did not complete: {exc}"
                raise
            self._sessions.pop(session_id)

    def get_controller(self, session_id: str) -> Any:
        state = self._require_state(session_id)
        if state.controller is None:
            raise SessionError(code="controller_missing", message=f"Session {session_id} has no replay controller")
        return state.controller

    def get_output(self, session_id: str) -> Any:
        state = self._require_state(session_id)
        if state.output is None:
            raise SessionError(code="output_missing", message=f"Session {session_id} has no replay output")
        return state.output

    def get_state(self, session_id: str) -> SessionState:
        return self._require_state(session_id)

    def list_sessions(self) -> List[SessionInfo]:
        return [
            SessionInfo(
                session_id=state.session_id,
                backend_type=state.backend_type,
                capabilities=state.capabilities,
                created_at=state.created_at,
            )
            for state in self._sessions.values()
        ]

    def _require_state(self, session_id: str) -> SessionState:
        state = self._sessions.get(session_id)
        if state is None:
            raise SessionError(code="session_not_found", message=f"Unknown session_id: {session_id}")
        return state

    async def present_remote(self, session_id: str, event_id: int, texture_id: Any) -> int:
        """Present through this replay's native remote connection, requiring a fresh receipt."""
        state = self._require_state(session_id)
        if state.backend_type != BackendType.REMOTE or state.remote_server is None:
            raise SessionError(code="remote_presentation_unavailable", message="No owning remote connection")
        if not hasattr(state.remote_server, "PresentReplay"):
            raise SessionError(code="remote_presentation_unsupported", message="Installed native binding lacks presentation acknowledgement; install the matching runtime and helper")
        resource = texture_id if texture_id is not None else _get_rd().ResourceId.Null()
        status, sequence = await native_calls.offload(state.remote_server.PresentReplay, event_id, resource)
        _check_status(status, "remote.PresentReplay", backend_type="remote",
                      capture_context={"session_id": session_id, "event_id": event_id},
                      source_layer="native_presentation")
        if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence <= state.presentation_sequence:
            raise SessionError(code="remote_presentation_stale", message="Native presentation receipt sequence is not fresh")
        state.presentation_sequence = sequence
        return sequence

    async def _ensure_local_replay_initialized(self) -> None:
        if self._replay_initialized:
            return
        rd = _get_rd()
        await native_calls.offload(rd.InitialiseReplay, rd.GlobalEnvironment(), [])
        self._replay_initialized = True
        logger.debug("RenderDoc replay subsystem initialised")

    async def _init_remote(self, state: SessionState, backend_config: Dict[str, Any]) -> None:
        rd = _get_rd()
        host = str(backend_config.get("host") or "").strip()
        port = backend_config.get("port")
        if not host:
            raise SessionError(
                code="remote_endpoint_required",
                message="Remote session backend requires an explicit host from options.remote_id",
            )
        url = f"{host}:{port}" if port else host
        state.remote_host = host
        state.remote_port = port

        remote = backend_config.get("remote_server")
        if remote is not None:
            state.remote_server = remote
            state.remote_server_owned = bool(backend_config.get("close_remote_server_on_cleanup", False))
            state.remote_transport = str(backend_config.get("transport") or "").strip()
            state.remote_bootstrap = dict(backend_config.get("bootstrap") or {})
            state.remote_bootstrap_result = backend_config.get("bootstrap_result")
            state.remote_device_serial = str(backend_config.get("device_serial") or "").strip()
            logger.debug("Reusing remote RenderDoc server connection at %s", url)
            return

        status, remote = await native_calls.offload(rd.CreateRemoteServerConnection, url)
        _check_status(
            status,
            f"CreateRemoteServerConnection({url})",
            backend_type="remote",
            capture_context={"session_id": state.session_id, "endpoint": url},
            classification="remote_replay_runtime",
            fix_hint="Confirm the remote endpoint is reachable and still owns a valid replay runtime.",
        )
        state.remote_server = remote
        state.remote_server_owned = True
        state.remote_transport = str(backend_config.get("transport") or "").strip()
        logger.debug("Connected to remote RenderDoc server at %s", url)

    async def _open_local_capture(self, state: SessionState, rdc_path: str) -> None:
        rd = _get_rd()
        cap = await native_calls.offload(rd.OpenCaptureFile)
        status = await native_calls.offload(cap.OpenFile, rdc_path, "", None)
        _check_status(
            status,
            f"OpenFile({rdc_path})",
            backend_type="local",
            capture_context={"session_id": state.session_id, "capture_path": str(rdc_path)},
            classification="rdc_invalid_or_unsupported",
            fix_hint="Verify that the .rdc file is valid and supported by this RenderDoc runtime.",
        )
        state.capture_file = cap
        if await native_calls.offload(cap.LocalReplaySupport) == rd.ReplaySupport.Unsupported:
            capture_api = str(await native_calls.offload(cap.DriverName))
            raise CoreError(
                code="local_replay_unsupported",
                message=f"This host's RenderDoc runtime cannot replay {capture_api} captures locally",
                category="capability",
                details={
                    "capture_api": capture_api,
                    "host_target": platform_host.host_target(),
                    "capture_path": str(rdc_path),
                    "recovery_hint": "Replay on a host whose runtime supports this API, or connect a remote target "
                                     "with rd.remote.connect and pass options.remote_id.",
                },
            )

        status, controller = await native_calls.offload(cap.OpenCapture, rd.ReplayOptions(), None)
        _check_status(
            status,
            "OpenCapture",
            backend_type="local",
            capture_context={"session_id": state.session_id, "capture_path": str(rdc_path)},
            classification="rdc_invalid_or_unsupported",
            fix_hint="Verify the capture can be replayed locally with the current RenderDoc runtime.",
        )
        state.controller = controller
        await self._create_headless_output(state, controller)

    async def _open_remote_capture(self, state: SessionState, rdc_path: str) -> None:
        if state.remote_server is None:
            raise SessionError(code="no_remote_server", message="Remote session has no active server connection")
        try:
            remote_server, remote_rdc_path, controller = await native_calls.offload(self._open_remote_capture_sync, state, rdc_path)
        finally:
            state.transfer_progress = None
        state.remote_server = remote_server
        state.controller = controller
        state.presentation_sequence = 0
        await self._create_headless_output(state, controller)

    def _open_remote_capture_sync(self, state: SessionState, rdc_path: str) -> tuple[Any, str, Any]:
        rd = _get_rd()
        remote_server = state.remote_server
        # The owning runtime hands this session its already connected remote.
        # A second connection races the live handle and is rejected as busy.
        copy_error = ""
        try:
            if state.transfer_progress:
                state.transfer_progress("capture_transfer_started", 0.0)
            if state.remote_transport == "adb_android":
                remote_rdc_path = self._copy_android_capture_with_adb(state, rdc_path)
            else:
                remote_rdc_path = remote_server.CopyCaptureToRemote(rdc_path, lambda fraction: state.transfer_progress("capture_transfer_progress", float(fraction)) if state.transfer_progress else None)
            if state.transfer_progress and str(remote_rdc_path or "").strip():
                state.transfer_progress("capture_transfer_done", 1.0)
        except Exception as exc:
            remote_rdc_path = ""
            copy_error = str(exc)
        if not str(remote_rdc_path or "").strip():
            details = {
                "source_layer": "renderdoc_remote_copy",
                "operation": "adb capture transfer" if state.remote_transport == "adb_android" else "remote.CopyCaptureToRemote()",
                "backend_type": "remote",
                "capture_context": {
                    "session_id": state.session_id,
                    "capture_path": str(rdc_path),
                    "remote_capture_path": "",
                },
                "classification": "remote_replay_runtime",
                "fix_hint": "Verify the remote endpoint can receive the capture before retrying remote replay.",
            }
            if copy_error:
                details["copy_error"] = copy_error
            raise SessionError(
                code="remote_capture_copy_failed",
                message="Capture transfer did not return a verified remote capture path",
                details=details,
            )
        status, controller = remote_server.OpenCapture(
            0,
            remote_rdc_path,
            rd.ReplayOptions(),
            None,
        )
        _check_status(
            status,
            f"remote.OpenCapture({remote_rdc_path})",
            backend_type="remote",
            capture_context={
                "session_id": state.session_id,
                "capture_path": str(rdc_path),
                "remote_capture_path": str(remote_rdc_path),
            },
            classification="remote_replay_runtime",
            fix_hint="Verify the remote endpoint can open the copied capture and has a compatible replay environment.",
        )
        return remote_server, str(remote_rdc_path), controller

    def _copy_android_capture_with_adb(self, state: SessionState, rdc_path: str) -> str:
        bootstrap_result = state.remote_bootstrap_result
        bootstrap = dict(state.remote_bootstrap or {})
        adb_path = str(getattr(bootstrap_result, "adb_path", "") or bootstrap.get("adb_path") or "").strip()
        device_serial = str(
            state.remote_device_serial
            or getattr(bootstrap_result, "device_serial", "")
            or bootstrap.get("device_serial")
            or ""
        ).strip()
        package_name = str(getattr(bootstrap_result, "package_name", "") or bootstrap.get("package_name") or "").strip()
        if not adb_path or not device_serial or not package_name:
            return ""
        if not re.fullmatch(r"org\.renderdoc\.renderdoccmd\.(?:arm32|arm64)", package_name):
            raise RuntimeError("Cannot verify Android capture path: unknown helper package")
        base_cmd = [adb_path, "-s", device_serial]

        def app_command(*args: str) -> list[str]:
            return base_cmd + ["shell", "run-as", package_name, *args]

        def run(command: list[str]) -> Any:
            # A per-step limit for short adb queries; transfers below use a no-progress budget.
            return process.run_tool(command, check=False, capture_output=True, text=True, timeout=30)

        private_root = run(app_command("pwd"))
        remote_root = str(private_root.stdout or "").strip()
        if (private_root.returncode or str(private_root.stderr or "").strip()
                or not re.fullmatch(rf"/data/(?:user/\d+|data)/{re.escape(package_name)}", remote_root)):
            raise RuntimeError("Cannot verify Android capture path: helper private directory is unavailable")
        remote_dir = f"{remote_root}/files/rdc_tool_captures"
        with Path(rdc_path).open("rb") as source:
            digest = hashlib.file_digest(source, "sha256").hexdigest()
        remote_path = f"{remote_dir}/{digest}.rdc"
        total_bytes = max(1, Path(rdc_path).stat().st_size)
        window_s = timeout_policy.cooperative_no_progress_s(progress.current_no_progress_ms())

        def size_of(command: list[str]) -> int:
            try:
                observed = run(command)
            except Exception:
                return -1
            text = str(observed.stdout or "").strip()
            return int(text) if not observed.returncode and text.isdigit() else -1

        def growth(phase: float) -> Any:
            # Push fills the first half of the transfer, the device writer the second.
            def report(observed: int) -> None:
                if state.transfer_progress:
                    state.transfer_progress("capture_transfer_progress", phase + 0.5 * min(1.0, observed / total_bytes))
            return report

        def checked_digest(result: Any, path: str) -> str:
            match = re.fullmatch(r"([0-9a-fA-F]{64})\s+(.+)", str(result.stdout or "").strip())
            if not result.returncode and not str(result.stderr or "").strip() and match and match[2] == path:
                return match[1].lower()
            # Only an explicit missing-file response permits creating a path.
            if (result.returncode and not str(result.stdout or "").strip()
                    and path in str(result.stderr or "")
                    and str(result.stderr or "").strip().endswith("No such file or directory")):
                return ""
            raise RuntimeError(f"Cannot verify Android capture path: {result.stderr.strip() or 'empty SHA256 response'}")

        def remote_digest(path: str) -> str:
            return checked_digest(run(app_command("sha256sum", path)), path)

        existing = remote_digest(remote_path)
        if existing:
            if existing != digest:
                raise RuntimeError("Remote capture cache content does not match its digest; refusing overwrite")
            return remote_path

        created = run(app_command("mkdir", "-p", remote_dir))
        if created.returncode:
            raise RuntimeError(f"Android capture directory creation failed: {created.stderr.strip()}")
        nonce = uuid.uuid4().hex
        shell_dir = f"/data/local/tmp/rdc-tool-transfer-{nonce}"
        shell_source = f"{shell_dir}/source.rdc"

        def keep_shell_dir() -> None:
            # Unconfirmed device-side state is kept for recovery; the owning context
            # releases the shell directory during clear_context.
            if shell_dir not in state.retained_transfer_dirs:
                state.retained_transfer_dirs.append(shell_dir)

        def retain(message: str, error: BaseException | str) -> RuntimeError:
            keep_shell_dir()
            return RuntimeError(f"{message}: {error}")

        script = (f"umask 077; mkdir -m 700 {shlex.quote(shell_dir)} "
                  f"&& printf '{nonce}:SHELL_CREATED\\n'")
        try:
            shell_created = run(base_cmd + ["shell", script])
        except BaseException as error:
            raise retain(f"Android capture sync directory creation unconfirmed; retain {shell_dir}", error) from error
        if shell_created.returncode or str(shell_created.stdout or "").strip() != f"{nonce}:SHELL_CREATED":
            raise retain(f"Android capture sync directory creation unconfirmed; retain {shell_dir}",
                         shell_created.stderr.strip())
        # ADB sync transfers file bytes without sending them through shell stdin,
        # whose Windows transport can normalize CRLF even without a PTY.
        try:
            pushed = _run_transfer(base_cmd + ["push", str(rdc_path), shell_source],
                                   lambda: size_of(base_cmd + ["shell", "stat", "-c", "%s", shell_source]),
                                   growth(0.0), window_s)
        except BaseException as error:
            raise retain(f"Android capture sync outcome unconfirmed; retain {shell_dir}", error) from error
        if pushed.returncode:
            raise retain(f"Android capture sync outcome unconfirmed; retain {shell_dir}", pushed.stderr.strip())
        try:
            if checked_digest(run(base_cmd + ["shell", "sha256sum", shell_source]), shell_source) != digest:
                raise RuntimeError("Android capture sync SHA256 verification failed")
        except BaseException as error:
            # A missing/unreadable digest is not a device-side write exit receipt.
            raise retain(f"Android capture sync verification unconfirmed; retain {shell_dir}", error) from error
        # noclobber makes this exact cache path exclusive. Native replay must not
        # open or own it until this nonce's writer and its bytes are verified.
        script = (f"set -C; exec 3> {shlex.quote(remote_path)} || exit; "
                  f"printf '{nonce}:CREATED\\n'; cat >&3; result=$?; "
                  f"printf '{nonce}:DONE:%s\\n' \"$result\"; exit \"$result\"")
        # The binary pipe is entirely on the device: only shell may read the
        # restricted sync source, while run-as creates the destination as its UID.
        command = base_cmd + ["shell", f"cat {shlex.quote(shell_source)} | "
                              f"run-as {package_name} sh -c {shlex.quote(script)}"]
        try:
            transferred = _run_transfer(command, lambda: size_of(app_command("stat", "-c", "%s", remote_path)),
                                        growth(0.5), window_s)
        except BaseException as error:
            # Killing/joining an ADB client is not a device-writer exit receipt.
            # Retain the exact recovery asset rather than unlinking a live file.
            raise retain(f"Android capture transfer outcome unconfirmed; device writer completion is unknown; "
                         f"retain {shell_dir} and {remote_path}", error) from error
        lines = str(transferred.stdout or "").splitlines()
        terminal = re.fullmatch(rf"{nonce}:DONE:(\d+)", lines[-1]) if lines else None
        if not (len(lines) == 2 and lines[0] == f"{nonce}:CREATED" and terminal):
            raise retain(f"Android capture transfer outcome unconfirmed; device writer completion is unknown; "
                         f"retain {shell_dir} and {remote_path}",
                         transferred.stderr.strip() or "missing matching device writer receipt")
        owned_paths = [remote_path]

        def remove_owned(path: str) -> None:
            script = f"rm -f {shlex.quote(path)} && printf '{nonce}:REMOVED\\n'"
            removed = run(app_command("sh", "-c", shlex.quote(script)))
            if removed.returncode or str(removed.stdout or "").strip() != f"{nonce}:REMOVED":
                raise RuntimeError(f"ADB removal unconfirmed for {path}: {removed.stderr.strip()}")

        def cleanup_owned() -> list[str]:
            errors = []
            for path in owned_paths:
                try:
                    remove_owned(path)
                except Exception as error:
                    errors.append(str(error))
            # Never recursively remove a directory or another application's data.
            script = (f"rm -f {shlex.quote(shell_source)} && rmdir {shlex.quote(shell_dir)} "
                      f"&& printf '{nonce}:SHELL_REMOVED\\n'")
            try:
                removed = run(base_cmd + ["shell", script])
                if removed.returncode or str(removed.stdout or "").strip() != f"{nonce}:SHELL_REMOVED":
                    raise RuntimeError(f"ADB sync cleanup unconfirmed for {shell_dir}: {removed.stderr.strip()}")
            except Exception as error:
                keep_shell_dir()
                errors.append(str(error))
            return errors

        try:
            if transferred.returncode or int(terminal[1]) or str(transferred.stderr or "").strip():
                raise RuntimeError(f"Android capture writer failed: {transferred.stderr.strip()}")
            if remote_digest(remote_path) != digest:
                raise RuntimeError("Android capture transfer SHA256 verification failed")
            state.remote_server.TakeOwnershipCapture(remote_path)
            owned_paths.remove(remote_path)
        except BaseException as original:
            errors = cleanup_owned()
            if errors:
                raise RuntimeError(f"{original}; owned capture cleanup failed: {'; '.join(errors)}") from original
            raise
        errors = cleanup_owned()
        if errors:
            raise RuntimeError(f"Owned capture cleanup failed: {'; '.join(errors)}")
        return remote_path

    async def _create_headless_output(self, state: SessionState, controller: Any) -> None:
        rd = _get_rd()
        width = int(state.replay_config.get("width", 1920) or 1920)
        height = int(state.replay_config.get("height", 1080) or 1080)
        windowing_data = await native_calls.offload(rd.CreateHeadlessWindowingData, width, height)
        state.output = await native_calls.offload(controller.CreateOutput, windowing_data, rd.ReplayOutputType.Texture)
        logger.debug("Created headless output (%dx%d) for session %s", width, height, state.session_id)

    async def _cleanup(self, state: SessionState) -> None:
        if state.output is not None:
            await native_calls.offload(state.output.Shutdown)
            state.output = None

        if state.controller is not None:
            if state.backend_type == BackendType.REMOTE and state.remote_server is not None:
                await native_calls.offload(state.remote_server.CloseCapture, state.controller)
            else:
                await native_calls.offload(state.controller.Shutdown)
            state.controller = None

        if state.capture_file is not None:
            if hasattr(state.capture_file, "CloseFile"):
                await native_calls.offload(state.capture_file.CloseFile)
            elif hasattr(state.capture_file, "Shutdown"):
                await native_calls.offload(state.capture_file.Shutdown)
            state.capture_file = None

        if state.remote_server is not None and state.remote_server_owned:
            await native_calls.offload(state.remote_server.ShutdownConnection)
        state.remote_server = None
        state.remote_server_owned = True

        if state.backend_type == BackendType.LOCAL:
            remaining_local = any(s is not state and s.backend_type == BackendType.LOCAL for s in self._sessions.values())
            if not remaining_local and self._replay_initialized:
                rd = _get_rd()
                await native_calls.offload(rd.ShutdownReplay)
                self._replay_initialized = False
                logger.debug("RenderDoc replay subsystem shut down")

