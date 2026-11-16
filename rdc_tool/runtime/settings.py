"""Runtime configuration and resource limits applied through rd.core.set_config."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from rdc_tool.config import RdcToolConfig
from rdc_tool.context_snapshot import SnapshotRetentionPolicy
from rdc_tool.runtime import live_state
from rdc_tool.runtime_paths import artifacts_dir, runtime_root


def _snapshot_retention() -> SnapshotRetentionPolicy:
    cfg = live_state._config or RdcToolConfig()
    return SnapshotRetentionPolicy(
        total_limit=int(getattr(cfg.snapshot_retention, "total_limit", 32) or 32),
        per_type_limit=int(getattr(cfg.snapshot_retention, "per_type_limit", 8) or 8),
    )


def _serialize_runtime_config() -> Dict[str, Any]:
    cfg = live_state._config or RdcToolConfig()
    return {
        "artifact_dir": str(getattr(cfg.artifact, "store_path", artifacts_dir())),
        "temp_dir": str(runtime_root().resolve()),
        "log_level": str(getattr(cfg, "log_level", "INFO")).lower(),
        "snapshot_retention": {
            "total_limit": int(getattr(cfg.snapshot_retention, "total_limit", 32) or 32),
            "per_type_limit": int(getattr(cfg.snapshot_retention, "per_type_limit", 8) or 8),
        },
        "runtime_limits": {
            "max_contexts": int(getattr(cfg.runtime_limits, "max_contexts", 8) or 8),
            "max_sessions_per_context": int(getattr(cfg.runtime_limits, "max_sessions_per_context", 4) or 4),
            "max_capture_files": int(getattr(cfg.runtime_limits, "max_capture_files", 8) or 8),
            "max_capture_size_bytes": int(getattr(cfg.runtime_limits, "max_capture_size_bytes", 4 * 1024 * 1024 * 1024) or (4 * 1024 * 1024 * 1024)),
            "max_estimated_replay_memory_bytes": int(
                getattr(cfg.runtime_limits, "max_estimated_replay_memory_bytes", 8 * 1024 * 1024 * 1024)
                or (8 * 1024 * 1024 * 1024)
            ),
            "replay_memory_multiplier": float(getattr(cfg.runtime_limits, "replay_memory_multiplier", 3.0) or 3.0),
            "max_recent_operations": int(getattr(cfg.runtime_limits, "max_recent_operations", 64) or 64),
        },
    }


_RUNTIME_CONFIG_KEYS = frozenset({"artifact_dir", "log_level", "snapshot_retention", "runtime_limits"})


def _apply_runtime_config(cfg: Dict[str, Any]) -> Dict[str, Any]:
    payload = dict(cfg or {})
    unknown = sorted(set(payload) - _RUNTIME_CONFIG_KEYS)
    if unknown:
        raise ValueError(f"Unsupported runtime config keys: {', '.join(unknown)}; supported: {', '.join(sorted(_RUNTIME_CONFIG_KEYS))}")
    if live_state._config is None:
        live_state._config = RdcToolConfig.from_env()
    if "artifact_dir" in payload:
        artifact_dir = Path(str(payload.get("artifact_dir") or artifacts_dir())).resolve()
        artifact_dir.mkdir(parents=True, exist_ok=True)
        live_state._config.artifact.store_path = artifact_dir
    if "log_level" in payload:
        live_state._config.log_level = str(payload.get("log_level") or "INFO").upper()
    snapshot_retention = payload.get("snapshot_retention")
    if isinstance(snapshot_retention, dict):
        if "total_limit" in snapshot_retention:
            live_state._config.snapshot_retention.total_limit = max(1, int(snapshot_retention.get("total_limit") or 32))
        if "per_type_limit" in snapshot_retention:
            live_state._config.snapshot_retention.per_type_limit = max(1, int(snapshot_retention.get("per_type_limit") or 8))
    limits_payload = payload.get("runtime_limits")
    if isinstance(limits_payload, dict):
        if "max_contexts" in limits_payload:
            live_state._config.runtime_limits.max_contexts = max(1, int(limits_payload.get("max_contexts") or 8))
        if "max_sessions_per_context" in limits_payload:
            live_state._config.runtime_limits.max_sessions_per_context = max(1, int(limits_payload.get("max_sessions_per_context") or 4))
        if "max_capture_files" in limits_payload:
            live_state._config.runtime_limits.max_capture_files = max(1, int(limits_payload.get("max_capture_files") or 8))
        if "max_capture_size_bytes" in limits_payload:
            live_state._config.runtime_limits.max_capture_size_bytes = max(1, int(limits_payload.get("max_capture_size_bytes") or (4 * 1024 * 1024 * 1024)))
        if "max_estimated_replay_memory_bytes" in limits_payload:
            live_state._config.runtime_limits.max_estimated_replay_memory_bytes = max(
                1,
                int(limits_payload.get("max_estimated_replay_memory_bytes") or (8 * 1024 * 1024 * 1024)),
            )
        if "replay_memory_multiplier" in limits_payload:
            live_state._config.runtime_limits.replay_memory_multiplier = max(
                1.0,
                float(limits_payload.get("replay_memory_multiplier") or 3.0),
            )
        if "max_recent_operations" in limits_payload:
            live_state._config.runtime_limits.max_recent_operations = max(1, int(limits_payload.get("max_recent_operations") or 64))
    live_state._runtime.config = _serialize_runtime_config()
    return dict(live_state._runtime.config)


def _now_ms() -> int:
    return int(datetime.now(timezone.utc).timestamp() * 1000)


def _runtime_limits() -> Dict[str, Any]:
    cfg = live_state._config or RdcToolConfig()
    return {
        "max_contexts": int(getattr(cfg.runtime_limits, "max_contexts", 8) or 8),
        "max_sessions_per_context": int(getattr(cfg.runtime_limits, "max_sessions_per_context", 4) or 4),
        "max_capture_files": int(getattr(cfg.runtime_limits, "max_capture_files", 8) or 8),
        "max_capture_size_bytes": int(getattr(cfg.runtime_limits, "max_capture_size_bytes", 4 * 1024 * 1024 * 1024) or (4 * 1024 * 1024 * 1024)),
        "max_estimated_replay_memory_bytes": int(
            getattr(cfg.runtime_limits, "max_estimated_replay_memory_bytes", 8 * 1024 * 1024 * 1024)
            or (8 * 1024 * 1024 * 1024)
        ),
        "replay_memory_multiplier": float(getattr(cfg.runtime_limits, "replay_memory_multiplier", 3.0) or 3.0),
        "max_recent_operations": int(getattr(cfg.runtime_limits, "max_recent_operations", 64) or 64),
    }
