from __future__ import annotations

import asyncio
import functools
import hashlib
import logging
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from rdx.core.renderdoc_status import build_renderdoc_error_details, status_ok as _rd_status_ok, status_text as _rd_status_text
from rdx.models import (
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
    capabilities: SessionCapabilities = field(default_factory=SessionCapabilities)
    capture_id: Optional[str] = None
    is_initialized: bool = False
    rdc_path: Optional[str] = None
    replay_config: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)


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

    @staticmethod
    async def _offload(fn: Any, *args: Any, **kwargs: Any) -> Any:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, functools.partial(fn, *args, **kwargs))

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
                props = await self._offload(controller.GetAPIProperties)
            except Exception:
                props = None
            state.capabilities.api = _map_graphics_api(props)
            state.capabilities.remote = state.backend_type == BackendType.REMOTE
            state.capabilities.shader_debug_supported = bool(getattr(props, "shaderDebugging", False)) if props is not None else False
            state.capabilities.patch_supported = _controller_patch_supported(controller)
            state.capabilities.counters_supported = True

            try:
                roots = await self._offload(controller.GetRootActions)
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
            state = self._sessions.pop(session_id, None)
        if state is None:
            raise SessionError(code="session_not_found", message=f"Unknown session_id: {session_id}")
        await self._cleanup(state)

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

    async def get_session(self, session_id: str) -> SessionInfo:
        state = self._require_state(session_id)
        return SessionInfo(
            session_id=state.session_id,
            backend_type=state.backend_type,
            capabilities=state.capabilities,
            created_at=state.created_at,
        )

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
        status, sequence = await self._offload(state.remote_server.PresentReplay, event_id, resource)
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
        await self._offload(rd.InitialiseReplay, rd.GlobalEnvironment(), [])
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

        status, remote = await self._offload(rd.CreateRemoteServerConnection, url)
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
        cap = await self._offload(rd.OpenCaptureFile)
        status = await self._offload(cap.OpenFile, rdc_path, "", None)
        _check_status(
            status,
            f"OpenFile({rdc_path})",
            backend_type="local",
            capture_context={"session_id": state.session_id, "capture_path": str(rdc_path)},
            classification="rdc_invalid_or_unsupported",
            fix_hint="Verify that the .rdc file is valid and supported by this RenderDoc runtime.",
        )
        state.capture_file = cap

        status, controller = await self._offload(cap.OpenCapture, rd.ReplayOptions(), None)
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
            remote_server, remote_rdc_path, controller = await self._offload(self._open_remote_capture_sync, state, rdc_path)
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
        config_remote_path = str(
            getattr(bootstrap_result, "config_remote_path", "") or bootstrap.get("config_remote_path") or ""
        ).strip()
        if not adb_path or not device_serial:
            return ""
        if config_remote_path and "/" in config_remote_path:
            remote_root = config_remote_path.rsplit("/", 1)[0]
        elif package_name:
            remote_root = f"/sdcard/Android/data/{package_name}/files"
        else:
            return ""
        remote_dir = f"{remote_root.rstrip('/')}/rdx_captures"
        with Path(rdc_path).open("rb") as source:
            digest = hashlib.file_digest(source, "sha256").hexdigest()
        remote_name = f"{digest}.rdc"
        remote_path = f"{remote_dir}/{remote_name}".replace("\\", "/")
        base_cmd = [adb_path]
        if device_serial:
            base_cmd.extend(["-s", device_serial])
        def remote_digest() -> str:
            result = subprocess.run(base_cmd + ["shell", "sha256sum", remote_path],
                                    check=False, capture_output=True, text=True, timeout=30)
            if result.returncode == 0 and result.stdout.split():
                return result.stdout.split()[0]
            # Only an explicit missing-file response permits creating a path.
            # An ADB failure or unreadable existing file must never mean absent.
            if "No such file or directory" in result.stderr:
                return ""
            raise RuntimeError(f"Cannot verify Android capture path: {result.stderr.strip() or 'empty SHA256 response'}")

        existing = remote_digest()
        if existing:
            if existing != digest:
                raise RuntimeError("Remote capture cache content does not match its digest; refusing overwrite")
            return remote_path
        subprocess.run(base_cmd + ["shell", "mkdir", "-p", remote_dir],
                       check=True, capture_output=True, text=True, timeout=30)
        # Register only a path created by this connection. RenderDoc deletes it
        # when the owning connection closes, including failed/cancelled opens.
        state.remote_server.TakeOwnershipCapture(remote_path)
        try:
            subprocess.run(base_cmd + ["push", str(rdc_path), remote_path],
                           check=True, capture_output=True, text=True, timeout=240)
            if remote_digest() != digest:
                raise RuntimeError("Android capture transfer SHA256 verification failed")
        except BaseException as original:
            try:
                cleanup = subprocess.run(base_cmd + ["shell", "rm", "-f", remote_path],
                                         check=False, capture_output=True, text=True, timeout=30)
                if cleanup.returncode:
                    raise RuntimeError(cleanup.stderr.strip() or "ADB removal failed")
            except Exception as cleanup_error:
                raise RuntimeError(f"{original}; owned capture cleanup failed: {cleanup_error}") from original
            raise
        return remote_path

    async def _create_headless_output(self, state: SessionState, controller: Any) -> None:
        rd = _get_rd()
        width = int(state.replay_config.get("width", 1920) or 1920)
        height = int(state.replay_config.get("height", 1080) or 1080)
        windowing_data = await self._offload(rd.CreateHeadlessWindowingData, width, height)
        state.output = await self._offload(controller.CreateOutput, windowing_data, rd.ReplayOutputType.Texture)
        logger.debug("Created headless output (%dx%d) for session %s", width, height, state.session_id)

    async def _cleanup(self, state: SessionState) -> None:
        errors: List[str] = []

        if state.output is not None:
            try:
                await self._offload(state.output.Shutdown)
            except Exception as exc:
                errors.append(f"output.Shutdown: {exc}")
            state.output = None

        if state.controller is not None:
            try:
                if state.backend_type == BackendType.REMOTE and state.remote_server is not None:
                    await self._offload(state.remote_server.CloseCapture, state.controller)
                else:
                    await self._offload(state.controller.Shutdown)
            except Exception as exc:
                errors.append(f"controller.Shutdown: {exc}")
            state.controller = None

        if state.capture_file is not None:
            try:
                if hasattr(state.capture_file, "CloseFile"):
                    await self._offload(state.capture_file.CloseFile)
                elif hasattr(state.capture_file, "Shutdown"):
                    await self._offload(state.capture_file.Shutdown)
            except Exception as exc:
                errors.append(f"capture_file.CloseFile/Shutdown: {exc}")
            state.capture_file = None

        if state.remote_server is not None and state.remote_server_owned:
            try:
                await self._offload(state.remote_server.ShutdownConnection)
            except Exception as exc:
                errors.append(f"remote.ShutdownConnection: {exc}")
        state.remote_server = None
        state.remote_server_owned = True

        if state.backend_type == BackendType.LOCAL:
            remaining_local = any(s.backend_type == BackendType.LOCAL for s in self._sessions.values())
            if not remaining_local and self._replay_initialized:
                try:
                    rd = _get_rd()
                    await self._offload(rd.ShutdownReplay)
                    self._replay_initialized = False
                    logger.debug("RenderDoc replay subsystem shut down")
                except Exception as exc:
                    errors.append(f"ShutdownReplay: {exc}")

        if errors:
            logger.warning("Errors during cleanup of session %s: %s", state.session_id, '; '.join(errors))

