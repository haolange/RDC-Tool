from __future__ import annotations

from typing import Any, Dict

from rdc_tool import server_runtime


async def handle(action: str, args: Dict[str, Any], env: Dict[str, Any]) -> Any:
    return await server_runtime._dispatch_diag(action, args)

