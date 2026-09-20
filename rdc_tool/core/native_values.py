"""Lossless JSON projection of RenderDoc value structs (never native handles)."""

from __future__ import annotations

import base64
from enum import Enum
from types import GetSetDescriptorType, MemberDescriptorType
from typing import Any


def native_value(value: Any, *, depth: int = 0) -> Any:
    """Read declared value properties; fail instead of silently dropping data."""
    if depth > 24:
        raise ValueError("Native value exceeds the supported nesting depth")
    if value is None or isinstance(value, (str, bool, float)):
        return value
    if isinstance(value, Enum):
        return value.name
    if isinstance(value, int):
        return value
    if isinstance(value, (bytes, bytearray, memoryview)):
        return {"encoding": "base64", "byte_size": len(value),
                "data": base64.b64encode(value).decode("ascii")}
    if type(value).__name__ == "ResourceId":
        return str(value)
    if isinstance(value, dict):
        return {str(k): native_value(v, depth=depth + 1) for k, v in value.items()}
    if isinstance(value, (list, tuple)) or (hasattr(value, "__len__") and hasattr(value, "__getitem__")):
        if len(value) > 65536:
            raise ValueError("Native value array exceeds 65536 items; use a ranged query")
        return [native_value(v, depth=depth + 1) for v in value]
    fields = {name for cls in type(value).__mro__ for name, member in vars(cls).items()
              if isinstance(member, (property, GetSetDescriptorType, MemberDescriptorType))
              and not name.startswith("_") and name not in {"this", "thisown"}}
    fields.update(name for name in getattr(value, "__dict__", {})
                  if not name.startswith("_") and name not in {"this", "thisown"})
    if not fields:
        raise TypeError(f"Not a supported RenderDoc value struct: {type(value).__name__}")
    result = {}
    for name in sorted(fields):
        member = getattr(value, name)
        if not callable(member):
            result[name] = native_value(member, depth=depth + 1)
    return result
