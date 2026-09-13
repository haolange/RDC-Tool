from __future__ import annotations

from typing import Any, Dict

from rdx import server_runtime


async def handle(action: str, args: Dict[str, Any], env: Dict[str, Any]) -> Any:
    if action in {"get_replay_events", "observe"}:
        from rdx.replay_observation import handle
        return await handle(action, args)
    return await server_runtime._dispatch_session(action, args)

