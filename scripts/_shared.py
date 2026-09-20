from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path, PureWindowsPath
from typing import Any


def tools_root(anchor_file: str) -> Path:
    env_root = os.environ.get("RDC_TOOL_ROOT", "").strip()
    if env_root:
        env_path = Path(env_root).expanduser().resolve()
        if env_path.is_dir():
            return env_path
    return Path(anchor_file).resolve().parents[1]


def resolve_repo_path(root: Path, raw_path: str) -> Path:
    text = str(raw_path or "").strip()
    candidate = Path(text)
    windows_candidate = PureWindowsPath(text)
    if candidate.is_absolute() or (windows_candidate.drive and windows_candidate.root):
        return candidate.resolve()
    return (root / candidate).resolve()


def ensure_within_root(root: Path, path: Path, *, label: str) -> Path:
    resolved = path.resolve()
    root_resolved = root.resolve()
    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise ValueError(f"{label} escapes tools root: {resolved}") from exc
    return resolved


def write_text(path: Path, text: str, *, encoding: str = "utf-8") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding=encoding)


def load_json(path: Path, *, encoding: str = "utf-8") -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding=encoding))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def extract_json_payload(text: str) -> dict[str, Any] | None:
    if not text:
        return None
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        payload = json.loads(text[start : end + 1])
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def trim_text(text: str, *, limit: int = 8000) -> str:
    value = (text or "").replace("\r", "").strip()
    return value if len(value) <= limit else value[: limit - 3] + "..."


def run_subprocess(
    cmd: list[str],
    *,
    cwd: Path,
    timeout_s: float | None = None,
    env: dict[str, str] | None = None,
    shell: bool = False,
) -> tuple[int, str, str]:
    proc = subprocess.run(
        cmd,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout_s,
        env=env,
        shell=shell,
        check=False,
    )
    return proc.returncode, proc.stdout or "", proc.stderr or ""