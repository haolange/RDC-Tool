"""Storing operation outputs as artifacts."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from rdc_tool.runtime import live_state, texture_naming


def _artifact_path(artifact_ref: Any) -> Optional[str]:
    if artifact_ref is None or live_state._artifact_store is None:
        return None
    sha256 = getattr(artifact_ref, "sha256", None)
    if not sha256:
        return None
    return str(live_state._artifact_store.get_path(sha256))


async def _store_bytes_artifact_payload(
    data: bytes,
    *,
    stem: str,
    suffix: str,
    output_dir: str = "",
    title: str = "",
    mime: str = "text/plain",
    text_mode: bool = False,
) -> Dict[str, Any]:
    if not data:
        return {}
    saved_path = ""
    if output_dir:
        out_dir = Path(str(output_dir))
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{texture_naming._safe_name_token(stem)}{suffix}"
        if text_mode:
            out_path.write_text(data.decode("utf-8"), encoding="utf-8")
        else:
            out_path.write_bytes(data)
        saved_path = str(out_path)
    artifact_path = ""
    if live_state._artifact_store is not None:
        artifact = await live_state._artifact_store.store(
            data,
            mime=mime,
            suffix=suffix,
        )
        artifact_path = str(_artifact_path(artifact) or "")
    payload: Dict[str, Any] = {}
    if title:
        payload["title"] = str(title)
    if artifact_path:
        payload["artifact_path"] = artifact_path
    if saved_path:
        payload["saved_path"] = saved_path
    elif artifact_path:
        payload["saved_path"] = artifact_path
    if payload:
        payload["type"] = "saved_path"
    return payload


async def _store_text_artifact_payload(
    text: str, *, stem: str, suffix: str, output_dir: str = "", title: str = "", mime: str = "text/plain",
) -> Dict[str, Any]:
    return await _store_bytes_artifact_payload(
        text.encode("utf-8"), stem=stem, suffix=suffix, output_dir=output_dir, title=title, mime=mime,
        text_mode=True,
    )
