"""Strict read-only interpretation of Android PackageManager active installs."""
from __future__ import annotations
import re


def parse_active_install_sessions(output: str) -> list[dict[str, object]]:
    lines = str(output).splitlines()
    if not lines or lines[0].strip() != "Active install sessions:":
        raise ValueError("PackageManager active install header is missing")
    active = "\n".join(lines[1:])
    active = re.split(r"(?m)^\s*(?:Finalized|Historical|Legacy) install sessions:\s*$", active, maxsplit=1)[0]
    if not active.strip():
        return []
    chunks = re.split(r"(?m)^\s+Active Session ([0-9]+):\s*$", active)
    if chunks[0].strip() or len(chunks) == 1:
        raise ValueError("PackageManager active session layout is unknown")
    sessions = []
    seen = set()
    for index in range(1, len(chunks), 2):
        session_id, block = chunks[index], chunks[index + 1]
        if session_id in seen:
            raise ValueError("PackageManager session identity is duplicated")
        seen.add(session_id)
        packages = re.findall(r"\bappPackageName=(null|[A-Za-z0-9_.]+)(?=\s|$)", block)
        if len(packages) != 1:
            raise ValueError("PackageManager session package is unknown")
        flags = {}
        for name in ("mCommitted", "mSealed", "mStageDirInUse", "mDestroyed", "mSessionApplied", "mSessionFailed"):
            values = re.findall(r"\b" + name + r"=(true|false)(?=\s|$)", block)
            if len(values) > 1:
                raise ValueError("PackageManager session state is ambiguous")
            if values:
                flags[name] = values[0] == "true"
        if "mDestroyed" not in flags:
            raise ValueError("PackageManager session lifetime is unknown")
        final_statuses = re.findall(r"\bmFinalStatus=(-?[0-9]+)(?=\s|$)", block)
        if len(final_statuses) > 1:
            raise ValueError("PackageManager final status is ambiguous")
        final_status = int(final_statuses[0]) if final_statuses else 0
        terminal = bool(flags.get("mSessionApplied") or flags.get("mSessionFailed") or final_status != 0)
        # abandon may mark destroyed while verification still owns the stage.
        # Only an actual outcome plus explicit release proves it is safe.
        if terminal and flags.get("mStageDirInUse") is False:
            continue
        facts: dict[str, object] = {"session_id": session_id, "package_name": None if packages[0] == "null" else packages[0]}
        for native, public in (("mCommitted", "committed"), ("mSealed", "sealed"), ("mStageDirInUse", "stage_dir_in_use")):
            if native in flags:
                facts[public] = flags[native]
        sessions.append(facts)
    return sessions
