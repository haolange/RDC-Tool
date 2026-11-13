"""Persist process-bound replay invalidation before starting a new owner."""
from rdc_tool.runtime_state import load_context_state, save_context_state


def mark_replay_requires_restart(context: str, message: str) -> None:
    state = load_context_state(context)
    sessions = state.get("sessions") or {}
    for record in sessions.values():
        record["state"] = "degraded"
        record["is_live"] = False
        record["last_error"] = message
        record["recovery"] = {**dict(record.get("recovery") or {}),
            "status": "requires_restart", "last_error": message}
    if sessions:
        state["recovery"] = {**dict(state.get("recovery") or {}),
            "status": "degraded", "last_error": message,
            "recovered_session_ids": [], "deferred_session_ids": [],
            "degraded_session_ids": list(sessions)}
        save_context_state(state, context)
