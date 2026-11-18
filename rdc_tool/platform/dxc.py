"""DXC assembly and validation through the host's platform implementation."""
from __future__ import annotations

from pathlib import Path

from rdc_tool.platform import host


class DxcError(RuntimeError):
    def __init__(self, stage: str, diagnostics: str, line: int | None = None) -> None:
        super().__init__(diagnostics)
        self.stage = stage
        self.diagnostics = diagnostics
        self.line = line


def assemble_and_validate(library: Path, source: str) -> bytes:
    return host.backend().assemble_and_validate_dxil(library, source)
