"""Reject retired configuration instead of silently changing runtime paths."""
from __future__ import annotations

import os
from collections.abc import Mapping


def validate_environment(environ: Mapping[str, str] | None = None) -> None:
    values = os.environ if environ is None else environ
    retired = sorted(key for key in values if key.upper().startswith('RDX_'))
    if retired:
        replacements = [
            f"{key} -> {'RDC_TOOL_ROOT' if key.upper() == 'RDX_TOOLS_ROOT' else 'RDC_TOOL_' + key[4:].upper()}"
            for key in retired
        ]
        raise ValueError('Retired environment configuration: ' + ', '.join(replacements))
