"""Code-owned operation discovery, independent of GPU/runtime startup."""
from __future__ import annotations
from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from typing import Any
from rdc_tool.operation_definitions import OPERATIONS
from rdc_tool.runtime_paths import tools_root


def tool_catalog_path() -> Path:
    return tools_root() / "spec" / "tool_catalog.json"


def load_tool_catalog() -> list[dict[str, Any]]:
    names = [tool["name"] for tool in OPERATIONS]
    if len(set(names)) != len(names):
        raise RuntimeError("Duplicate public operation definition")
    return deepcopy(OPERATIONS)


def catalog_payload() -> dict[str, Any]:
    tools = load_tool_catalog()
    digest = hashlib.sha256(json.dumps(tools, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
    return {"schema_version": "1", "source_path": "rdc_tool/operation_definitions.py", "fingerprint": digest,
            "tool_count": len(tools), "groups": dict(Counter(t["group"] for t in tools)), "tools": tools}


def describe_operation(name: str) -> dict[str, Any]:
    for tool in OPERATIONS:
        if tool["name"] == name:
            return deepcopy(tool)
    raise ValueError(f"Unknown operation: {name}")


def validate_operation_arguments(name: str, arguments: dict[str, Any]) -> None:
    """Validate the same constraints exported through discovery before invoking a handler."""
    definition = describe_operation(name)

    def validate(value: Any, schema: dict[str, Any], path: str) -> None:
        def matches(candidate: dict[str, Any]) -> bool:
            try:
                validate(value, candidate, path)
            except ValueError:
                return False
            return True

        if "oneOf" in schema and sum(matches(candidate) for candidate in schema["oneOf"]) != 1:
            raise ValueError(f"{path} must match exactly one allowed argument combination")
        if "not" in schema and matches(schema["not"]):
            raise ValueError(f"{path} contains a forbidden argument combination")
        expected = schema.get("type")
        types = expected if isinstance(expected, list) else [expected] if expected else []
        checks = {"object": lambda: isinstance(value, dict), "array": lambda: isinstance(value, list),
                  "string": lambda: isinstance(value, str), "integer": lambda: isinstance(value, int) and not isinstance(value, bool),
                  "number": lambda: isinstance(value, (int, float)) and not isinstance(value, bool),
                  "boolean": lambda: isinstance(value, bool), "null": lambda: value is None}
        if types and not any(kind in checks and checks[kind]() for kind in types):
            raise ValueError(f"{path} must have type {expected}")
        if "enum" in schema and value not in schema["enum"]:
            raise ValueError(f"{path} must be one of {schema['enum']}")
        if isinstance(value, (str, list)):
            lower, upper = ("minLength", "maxLength") if isinstance(value, str) else ("minItems", "maxItems")
            if lower in schema and len(value) < schema[lower]:
                raise ValueError(f"{path} length must be >= {schema[lower]}")
            if upper in schema and len(value) > schema[upper]:
                raise ValueError(f"{path} length must be <= {schema[upper]}")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if "minimum" in schema and value < schema["minimum"]:
                raise ValueError(f"{path} must be >= {schema['minimum']}")
            if "maximum" in schema and value > schema["maximum"]:
                raise ValueError(f"{path} must be <= {schema['maximum']}")
        if isinstance(value, dict):
            properties = schema.get("properties", {})
            missing = [key for key in schema.get("required", []) if key not in value]
            if missing:
                raise ValueError(f"{path} missing required parameters: {', '.join(missing)}")
            if schema.get("additionalProperties") is False:
                unknown = sorted(set(value) - set(properties))
                if unknown:
                    raise ValueError(f"{path} unknown parameters: {', '.join(unknown)}")
            for key, item in value.items():
                if key in properties:
                    validate(item, properties[key], f"{path}.{key}")
        if isinstance(value, list):
            for index, item in enumerate(value):
                validate(item, schema.get("items", {}), f"{path}[{index}]")
    validate(arguments, definition["input_schema"], name)
