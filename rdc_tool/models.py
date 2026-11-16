"""
rdc-tool 的核心数据模型。
供 runtime tools 与内部服务使用的结构化类型集合。
"""

from __future__ import annotations

import time
import uuid
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _ts() -> float:
    return time.time()


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class BackendType(str, Enum):
    LOCAL = "local"
    REMOTE = "remote"


class GraphicsAPI(str, Enum):
    D3D11 = "D3D11"
    D3D12 = "D3D12"
    VULKAN = "Vulkan"
    OPENGL = "OpenGL"
    OPENGLES = "OpenGLES"
    UNKNOWN = "Unknown"


class ShaderStage(str, Enum):
    VS = "vs"
    HS = "hs"
    DS = "ds"
    GS = "gs"
    PS = "ps"
    CS = "cs"
    MS = "ms"
    AS = "as"


class ArtifactRef(BaseModel):
    uri: str
    sha256: str
    mime: str
    bytes: int = 0
    meta: Dict[str, Any] = Field(default_factory=dict)


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: Optional[Dict[str, Any]] = None


class SessionCapabilities(BaseModel):
    api: GraphicsAPI = GraphicsAPI.UNKNOWN
    shader_debug_supported: bool = False
    counters_supported: bool = False
    patch_supported: bool = False
    remote: bool = False


class SessionInfo(BaseModel):
    session_id: str
    backend_type: BackendType
    capabilities: SessionCapabilities = Field(default_factory=SessionCapabilities)
    created_at: float = Field(default_factory=_ts)


# ---------------------------------------------------------------------------
# Capture
# ---------------------------------------------------------------------------

class CaptureInfo(BaseModel):
    capture_id: str
    session_id: str
    rdc_path: str
    api: GraphicsAPI = GraphicsAPI.UNKNOWN
    driver_name: str = ""
    driver_version: str = ""
    frame_count: int = 1
    total_events: int = 0
    thumbnails: List[ArtifactRef] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Event tree（事件树）
# ---------------------------------------------------------------------------

class EventFlags(BaseModel):
    is_draw: bool = False
    is_dispatch: bool = False
    is_marker: bool = False
    is_copy: bool = False
    is_resolve: bool = False
    is_clear: bool = False
    is_pass_boundary: bool = False


class EventNode(BaseModel):
    event_id: int
    name: str = ""
    flags: EventFlags = Field(default_factory=EventFlags)
    children: List[EventNode] = Field(default_factory=list)
    depth: int = 0
    output_targets: List[str] = Field(default_factory=list)  # ResourceId strings
    inferred_pass: Optional[str] = None


# ---------------------------------------------------------------------------
# Pipeline（管线）
# ---------------------------------------------------------------------------

class ShaderInfo(BaseModel):
    resource_id: str
    stage: ShaderStage
    entry_point: str = "main"
    hash: Optional[str] = None
    debug_name: Optional[str] = None
    resource_name: Optional[str] = None
    debug_source_files: List[str] = Field(default_factory=list)
    encoding: str = ""  # SPIR-V, DXBC, DXIL, GLSL, etc.


class ResourceBindingEntry(BaseModel):
    stage: str = ""
    array_index: int = 0
    binding_source: str = "shader_reflection"
    set_or_space: int = 0
    binding: int = 0
    resource_id: str = ""
    resource_name: str = ""
    type: str = ""  # SRV, UAV, CBV, sampler, etc.
    format: str = ""
    descriptor: Dict[str, Any] = Field(default_factory=dict)
    sampler: Dict[str, Any] = Field(default_factory=dict)
    access: Dict[str, Any] = Field(default_factory=dict)


class BlendState(BaseModel):
    enabled: bool = False
    src_color: str = ""
    dst_color: str = ""
    color_op: str = ""
    src_alpha: str = ""
    dst_alpha: str = ""
    alpha_op: str = ""
    write_mask: Optional[int] = None
    logic_op: Optional[str] = None
    logic_op_enabled: Optional[bool] = None


class DepthStencilState(BaseModel):
    depth_test_enabled: bool = False
    depth_write_enabled: bool = False
    depth_func: str = ""
    stencil_enabled: bool = False
    front: Dict[str, Any] = Field(default_factory=dict)
    back: Dict[str, Any] = Field(default_factory=dict)
    details: Dict[str, Any] = Field(default_factory=dict)


class RenderTargetInfo(BaseModel):
    resource_id: str
    format: str = ""
    width: int = 0
    height: int = 0
    is_srgb: bool = False
    slot: int = 0
    descriptor: Dict[str, Any] = Field(default_factory=dict)


class PipelineSnapshot(BaseModel):
    event_id: int
    api: GraphicsAPI = GraphicsAPI.UNKNOWN
    shaders: List[ShaderInfo] = Field(default_factory=list)
    render_targets: List[RenderTargetInfo] = Field(default_factory=list)
    depth_target: Optional[RenderTargetInfo] = None
    blend_states: List[BlendState] = Field(default_factory=list)
    depth_stencil: DepthStencilState = Field(default_factory=DepthStencilState)
    bindings: List[ResourceBindingEntry] = Field(default_factory=list)
    viewports: List[Dict[str, Any]] = Field(default_factory=list)
    scissors: List[Dict[str, Any]] = Field(default_factory=list)
    blend_options: Dict[str, Any] = Field(default_factory=dict)
    rasterizer: Dict[str, Any] = Field(default_factory=dict)
    multisample: Dict[str, Any] = Field(default_factory=dict)
    push_constants: Dict[str, Any] = Field(default_factory=dict)
    dynamic_state: Dict[str, Any] = Field(default_factory=dict)
    root_signature: Dict[str, Any] = Field(default_factory=dict)
    descriptor_heaps: Dict[str, Any] = Field(default_factory=dict)
    resource_states: Dict[str, Any] = Field(default_factory=dict)
    topology: str = ""
    vertex_inputs: List[Dict[str, Any]] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Patch（补丁）
# ---------------------------------------------------------------------------

class PatchOp(BaseModel):
    op: str  # force_full_precision, insert_guard
    variables: List[str] = Field(default_factory=list)
    range_from: Optional[int] = None  # instruction index
    range_to: Optional[int] = None
    expr_from: Optional[str] = None
    expr_to: Optional[str] = None
    guard_expr: Optional[str] = None
    guard_replacement: Optional[str] = None


class PatchSpec(BaseModel):
    patch_id: str = Field(default_factory=lambda: _new_id("patch"))
    target_event_id: int = 0
    target_stage: ShaderStage = ShaderStage.PS
    target_shader_id: str = ""
    intent: str = "fix_naninf"
    ops: List[PatchOp] = Field(default_factory=list)
    source_text: str = ""
    source_path: str = ""
    diff_text: str = ""
    source_target: str = ""
    source_encoding: str = ""
    entry: str = ""
    target: str = ""
    include_dirs: List[str] = Field(default_factory=list)
    expected_source_hash: str = ""
    max_diff_ops: int = 20
    preserve_outputs: bool = True


class PatchResult(BaseModel):
    patch_id: str
    edit_plan: Dict[str, Any] = Field(default_factory=dict)
    build_input: Dict[str, Any] = Field(default_factory=lambda: {
        "status": "unavailable", "reason": "No successful shader build and replacement observed."
    })
    build_input_bytes: bytes = Field(default=b"", exclude=True)
    applied_to_shader_hash: str = ""
    original_shader_hash: str = ""
    success: bool = True
    error_message: str = ""
    error_code: str = ""
    error_category: str = ""
    error_details: Dict[str, Any] = Field(default_factory=dict)
    messages: List[str] = Field(default_factory=list)
    source_before_text: str = ""
    source_after_text: str = ""
    disassembly_target: str = ""
    encoding: str = ""
    entry_point: str = ""
    compile_flags: List[Dict[str, str]] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Performance（性能）
# ---------------------------------------------------------------------------

class CounterSample(BaseModel):
    event_id: int
    counter_id: int
    counter_name: str = ""
    value: float = 0.0


class CounterSummary(BaseModel):
    counter_name: str
    min_val: float = 0.0
    max_val: float = 0.0
    mean_val: float = 0.0
    p95_val: float = 0.0
    hotspot_event_id: Optional[int] = None


class PerfResult(BaseModel):
    samples: List[CounterSample] = Field(default_factory=list)
    summaries: List[CounterSummary] = Field(default_factory=list)
    anomaly_events: List[int] = Field(default_factory=list)
