"""In-process runtime objects: handles, service singletons and per-call context variables."""

from __future__ import annotations

import contextvars
import logging
import os
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from rdc_tool.config import RdcToolConfig
from rdc_tool.context_snapshot import default_preview_display_state, normalize_context_id
from rdc_tool.core.event_graph import EventGraphService
from rdc_tool.core.patch_engine import PatchEngine
from rdc_tool.core.perf_service import PerfService
from rdc_tool.core.pipeline_service import PipelineService
from rdc_tool.core.render_service import RenderService
from rdc_tool.core.session_manager import SessionManager
from rdc_tool.platform import preview as platform_preview
from rdc_tool.progress import ProgressReporter
from rdc_tool.utils.artifact_store import ArtifactStore

logger = logging.getLogger("rdc_tool.runtime")
_CURRENT_REPLAY_HEALTH_SCOPE: contextvars.ContextVar[Dict[str, Any] | None] = contextvars.ContextVar("rdc_tool_replay_health_scope", default=None)
_CURRENT_EVENT_REJECTION_SCOPE: contextvars.ContextVar[Dict[str, Any] | None] = contextvars.ContextVar("rdc_tool_event_rejection_scope", default=None)
_CURRENT_CONTEXT_ID: contextvars.ContextVar[str | None] = contextvars.ContextVar('rdc_tool_current_context_id', default=None)
_CURRENT_PROGRESS_REPORTER: contextvars.ContextVar[ProgressReporter | None] = contextvars.ContextVar(
    "rdc_tool_current_progress_reporter",
    default=None,
)


def _runtime_context_id() -> str:
    current = _CURRENT_CONTEXT_ID.get()
    if current:
        return normalize_context_id(current)
    return normalize_context_id(os.environ.get("RDC_TOOL_CONTEXT_ID") or "default")


def _normalize_backend(value: Any, *, default: str = "local") -> str:
    backend = str(value or default).strip().lower()
    if backend not in {"local", "remote"}:
        return default
    return backend


@dataclass
class ExecutionContext:
    """One operation call: how it arrived, its trace id and progress reporter."""

    transport: str = "core"
    remote: bool = False
    trace_id: str = field(default_factory=lambda: f"trc_{uuid.uuid4().hex[:12]}")
    metadata: Dict[str, Any] = field(default_factory=dict)
    progress_reporter: Optional[ProgressReporter] = None


@dataclass
class CaptureFileHandle:
    capture_file_id: str
    file_path: str
    read_only: bool
    driver: str = ""
    opened_at_ms: int = field(default_factory=lambda: int(datetime.now(timezone.utc).timestamp() * 1000))


@dataclass
class ReplayHandle:
    session_id: str
    capture_file_id: str
    frame_index: int = 0
    active_event_id: int = 0


@dataclass
class RemoteHandle:
    remote_id: str
    host: str
    port: int
    connected: bool
    origin_context_id: str = ""
    context_locality: str = "strict"
    reuse_policy: str = "must_reconnect"
    transport: str = "renderdoc"
    remote_server: Any = None
    server_info: Dict[str, Any] = field(default_factory=dict)
    bootstrap: Dict[str, Any] = field(default_factory=dict)
    bootstrap_result: Any = None
    leased_session_id: str = ""
    leased_session_ids: List[str] = field(default_factory=list)
    requested_host: str = ""
    requested_port: int = 0
    device_serial: str = ""
    detail: Dict[str, Any] = field(default_factory=dict)
    default_capture_options: Dict[str, Any] = field(default_factory=dict)
    overlay_options: Dict[str, Any] = field(default_factory=dict)
    known_targets: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    known_captures: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    last_target_scan_ms: int = 0
    target_control_leases: List[Any] = field(default_factory=list)


@dataclass
class ConsumedRemoteHandle:
    remote_id: str
    endpoint: str
    origin_context_id: str = ""
    context_locality: str = "strict"
    reuse_policy: str = "must_reconnect"
    transport: str = "renderdoc"
    consumed_by_session_id: str = ""
    consumed_at_ms: int = field(default_factory=lambda: int(datetime.now(timezone.utc).timestamp() * 1000))
    server_info: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ShaderDebugHandle:
    shader_debug_id: str
    session_id: str
    mode: str
    event_id: int
    trace: Any
    debugger: Any
    current_state: Any = None
    resolved_context: Dict[str, Any] = field(default_factory=dict)
    selected_target_source: str = ""
    pixel_history_summary: Dict[str, Any] = field(default_factory=dict)
    pending_states: deque[Any] = field(default_factory=deque)
    variables: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    breakpoints: List[Dict[str, Any]] = field(default_factory=list)
    stopped_reason: str = "running"


@dataclass
class RuntimeState:
    config: Dict[str, Any] = field(default_factory=dict)
    logs: List[Dict[str, Any]] = field(default_factory=list)
    captures: Dict[str, CaptureFileHandle] = field(default_factory=dict)
    replays: Dict[str, ReplayHandle] = field(default_factory=dict)
    aliases: Dict[str, str] = field(default_factory=dict)
    remotes: Dict[str, RemoteHandle] = field(default_factory=dict)
    session_owned_remotes: Dict[str, RemoteHandle] = field(default_factory=dict)
    consumed_remotes: Dict[str, ConsumedRemoteHandle] = field(default_factory=dict)
    context_snapshots: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    context_states: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    hydrated_contexts: set[str] = field(default_factory=set)
    previews: Dict[str, "PreviewBinding"] = field(default_factory=dict)
    shader_debugs: Dict[str, ShaderDebugHandle] = field(default_factory=dict)
    shader_replacements: Dict[str, List[Dict[str, Any]]] = field(default_factory=dict)
    restored_shader_sessions: set[str] = field(default_factory=set)
    initialized: bool = False
    enable_remote: bool = True


@dataclass
class PreviewBinding:
    context_id: str
    host: platform_preview.PreviewWindow
    output: Any | None = None
    bound_session_id: str = ""
    bound_capture_file_id: str = ""
    bound_event_id: int = 0
    backend: str = "local"
    last_error: str = ""
    display: Dict[str, Any] = field(default_factory=default_preview_display_state)


_config: Optional[RdcToolConfig] = None
_session_manager: Optional[SessionManager] = None
_event_graph_service: Optional[EventGraphService] = None
_render_service: Optional[RenderService] = None
_pipeline_service: Optional[PipelineService] = None
_perf_service: Optional[PerfService] = None
_artifact_store: Optional[ArtifactStore] = None
_patch_engine: Optional[PatchEngine] = None
_runtime: RuntimeState = RuntimeState()
_runtime_bootstrapped: bool = False
_PREVIEW_SCREEN_CAP_RATIO = 0.5
_PREVIEW_FIT_MODE = "fit_with_screen_cap"
_PREVIEW_REGION_MARKER_MODE = "viewport_scissor_overlay"

def _current_progress_reporter() -> ProgressReporter | None:
    return _CURRENT_PROGRESS_REPORTER.get()
