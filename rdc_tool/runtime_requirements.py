"""Third-party modules the CLI imports, checked by doctor in the running interpreter."""

from __future__ import annotations

import importlib.util

# (distribution, import name); the distributions are pyproject.toml's dependencies.
REQUIRED_DEPENDENCIES: list[tuple[str, str]] = [
    ("pydantic", "pydantic"),
    ("numpy", "numpy"),
    ("Pillow", "PIL"),
    ("aiofiles", "aiofiles"),
]


def module_available(import_name: str) -> bool:
    try:
        return importlib.util.find_spec(import_name) is not None
    except ModuleNotFoundError:
        return False


def missing_dependencies() -> list[str]:
    return [dist_name for dist_name, import_name in REQUIRED_DEPENDENCIES if not module_available(import_name)]
