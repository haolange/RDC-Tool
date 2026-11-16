"""Argument coercion shared by operations."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional


def _parse_json_like(value: Any) -> Any:
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return value
        if (stripped.startswith("{") and stripped.endswith("}")) or (
            stripped.startswith("[") and stripped.endswith("]")
        ):
            try:
                return json.loads(stripped)
            except json.JSONDecodeError:
                return value
    return value


def _as_dict(value: Any, *, default: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    parsed = _parse_json_like(value)
    if parsed is None:
        return default or {}
    if isinstance(parsed, dict):
        return parsed
    raise ValueError(f"Expected dict-compatible value, got: {type(parsed).__name__}")


def _as_list(value: Any, *, default: Optional[List[Any]] = None) -> List[Any]:
    parsed = _parse_json_like(value)
    if parsed is None:
        return default or []
    if isinstance(parsed, list):
        return parsed
    raise ValueError(f"Expected list-compatible value, got: {type(parsed).__name__}")


def _parse_query_like(value: Any) -> Dict[str, Any]:
    parsed = _parse_json_like(value)
    if parsed is None:
        return {}
    if isinstance(parsed, dict):
        return parsed
    if isinstance(parsed, str):
        query = parsed.strip()
        if not query:
            return {}
        return {"name_contains": query}
    raise ValueError(f"Expected query as dict/str, got: {type(parsed).__name__}")


def _parse_target_like(value: Any) -> Dict[str, Any]:
    parsed = _parse_json_like(value)
    if parsed is None:
        return {}
    if isinstance(parsed, dict):
        return parsed
    if isinstance(parsed, str):
        target_id = parsed.strip()
        if not target_id:
            return {}
        return {"texture_id": target_id}
    if isinstance(parsed, (int, float)) and not isinstance(parsed, bool):
        return {"texture_id": str(parsed)}
    raise ValueError(f"Expected target as dict/str/int, got: {type(parsed).__name__}")


def _as_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return default


def _as_int(value: Any, default: int = 0) -> int:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return int(value)
    return int(value)


def _as_float(value: Any, default: float = 0.0) -> float:
    if value is None or value == "":
        return default
    return float(value)

def _require(fields: Dict[str, Any], *names: str) -> None:
    missing = []
    for name in names:
        value = fields.get(name)
        if value is None:
            missing.append(name)
            continue
        if isinstance(value, str) and not value.strip():
            missing.append(name)
    if missing:
        raise ValueError(f"Missing required parameter(s): {', '.join(missing)}")


def _format_size(value: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(value)
    for unit in units:
        if size < 1024.0 or unit == units[-1]:
            return f"{size:.2f}{unit}"
        size /= 1024.0
    return f"{value}B"


def _sanitize_dict(data: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in data.items() if v is not None}
