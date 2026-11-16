"""Turn artifact candidates in a handler result into canonical artifact records."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from .contracts import make_artifact_from_path, make_artifact_from_url


class ArtifactPublisher:
    async def publish_candidates(self, candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        seen: set[str] = set()
        for item in candidates:
            if not isinstance(item, dict):
                continue
            if item.get("url"):
                url = str(item.get("url"))
                if url in seen:
                    continue
                seen.add(url)
                out.append(make_artifact_from_url(url, artifact_type=str(item.get("type", "file")),
                                                  metadata=dict(item.get("metadata") or {})))
                continue
            path_value = str(item.get("path") or "").strip()
            if not path_value:
                continue
            key = f"path::{Path(path_value)}"
            if key in seen:
                continue
            seen.add(key)
            out.append(make_artifact_from_path(path_value, artifact_type=str(item.get("type", "file")),
                                               metadata=dict(item.get("metadata") or {}), storage_backend="local"))
        return out
