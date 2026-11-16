"""
rdc-tool 运行时配置：只包含运行时实际读取的项。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from rdc_tool.runtime_paths import artifacts_dir


@dataclass
class ArtifactConfig:
    store_path: Path = field(default_factory=lambda: artifacts_dir())


@dataclass
class SnapshotRetentionConfig:
    total_limit: int = 32
    per_type_limit: int = 8


@dataclass
class RuntimeLimitsConfig:
    max_contexts: int = 8
    max_sessions_per_context: int = 4
    max_capture_files: int = 8
    max_capture_size_bytes: int = 4 * 1024 * 1024 * 1024
    max_estimated_replay_memory_bytes: int = 8 * 1024 * 1024 * 1024
    replay_memory_multiplier: float = 3.0
    max_recent_operations: int = 64


@dataclass
class RdcToolConfig:
    artifact: ArtifactConfig = field(default_factory=ArtifactConfig)
    snapshot_retention: SnapshotRetentionConfig = field(default_factory=SnapshotRetentionConfig)
    runtime_limits: RuntimeLimitsConfig = field(default_factory=RuntimeLimitsConfig)
    log_level: str = "INFO"

    @classmethod
    def from_env(cls) -> RdcToolConfig:
        cfg = cls()
        if p := os.environ.get("RDC_TOOL_ARTIFACT_DIR"):
            cfg.artifact.store_path = Path(p)
        if p := os.environ.get("RDC_TOOL_LOG_LEVEL"):
            cfg.log_level = p
        if p := os.environ.get("RDC_TOOL_CONTEXT_ARTIFACT_TOTAL_LIMIT"):
            cfg.snapshot_retention.total_limit = int(p)
        if p := os.environ.get("RDC_TOOL_CONTEXT_ARTIFACT_PER_TYPE_LIMIT"):
            cfg.snapshot_retention.per_type_limit = int(p)
        if p := os.environ.get("RDC_TOOL_MAX_CONTEXTS"):
            cfg.runtime_limits.max_contexts = int(p)
        if p := os.environ.get("RDC_TOOL_MAX_SESSIONS_PER_CONTEXT"):
            cfg.runtime_limits.max_sessions_per_context = int(p)
        if p := os.environ.get("RDC_TOOL_MAX_CAPTURE_FILES"):
            cfg.runtime_limits.max_capture_files = int(p)
        if p := os.environ.get("RDC_TOOL_MAX_CAPTURE_SIZE_BYTES"):
            cfg.runtime_limits.max_capture_size_bytes = int(p)
        if p := os.environ.get("RDC_TOOL_MAX_ESTIMATED_REPLAY_MEMORY_BYTES"):
            cfg.runtime_limits.max_estimated_replay_memory_bytes = int(p)
        if p := os.environ.get("RDC_TOOL_REPLAY_MEMORY_MULTIPLIER"):
            cfg.runtime_limits.replay_memory_multiplier = float(p)
        if p := os.environ.get("RDC_TOOL_MAX_RECENT_OPERATIONS"):
            cfg.runtime_limits.max_recent_operations = int(p)
        return cfg
