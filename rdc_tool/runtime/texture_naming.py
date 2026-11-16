"""Texture naming and export format selection."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from rdc_tool.runtime import coerce

_FILE_SUFFIX_MAP: Dict[str, str] = {
    "png": ".png",
    "jpg": ".jpg",
    "jpeg": ".jpg",
    "dds": ".dds",
    "exr": ".exr",
    "hdr": ".hdr",
    "tga": ".tga",
    "bmp": ".bmp",
    "raw": ".raw",
}

_DEPTH_HINTS = ("depth", "stencil", "d16", "d24", "d32", "dsv", "s8")
_HDR_HINTS = ("16f", "32f", "float", "r11g11b10", "rgb10a2", "bc6")
_COMPRESSED_HINTS = ("bc1", "bc2", "bc3", "bc4", "bc5", "bc6", "bc7", "etc", "astc", "pvrtc", "atc")
_NORMAL_HINTS = ("normal", "nrm", "norm")
_MASK_HINTS = ("rough", "metal", "ao", "orm", "mask", "spec", "gloss", "height")
_COLOR_HINTS = ("albedo", "basecolor", "base_color", "diffuse", "color")


def _resource_id_tokens(resource_id: Any) -> List[str]:
    text = str(resource_id).strip()
    if not text:
        return []
    tokens = [text]
    try:
        tokens.append(str(int(resource_id)))
    except Exception:
        pass
    wrapped = re.fullmatch(r"ResourceId::([0-9]+)", text)
    if wrapped:
        tokens.append(str(int(wrapped.group(1))))
    return list(dict.fromkeys(tokens))


def _resource_id_matches(left: Any, right: Any) -> bool:
    lhs = set(_resource_id_tokens(left))
    rhs = set(_resource_id_tokens(right))
    return bool(lhs and rhs and lhs.intersection(rhs))


def _safe_name_token(value: str, fallback: str = "unnamed") -> str:
    text = str(value or "").strip()
    if not text:
        return fallback
    text = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", text)
    text = re.sub(r"\s+", "_", text).strip(" ._")
    if not text:
        return fallback
    if len(text) > 120:
        text = text[:120].rstrip("._")
    return text or fallback


def _compose_texture_name_info(
    resource_id: Any,
    *,
    resource_name: str = "",
    binding_names: Optional[Sequence[str]] = None,
    alias_name: str = "",
) -> Dict[str, Any]:
    rid = str(resource_id)
    src_name = str(resource_name or "").strip()
    alias = str(alias_name or "").strip()
    clean_binding_names: List[str] = []
    for item in binding_names or []:
        name = str(item or "").strip()
        if not name:
            continue
        if name not in clean_binding_names:
            clean_binding_names.append(name)
    primary_binding = clean_binding_names[0] if clean_binding_names else ""

    base_name = alias or src_name
    if not base_name and primary_binding:
        display_name = primary_binding
    elif base_name and primary_binding and base_name.lower() != primary_binding.lower():
        display_name = f"{base_name}@{primary_binding}"
    elif base_name:
        display_name = base_name
    else:
        digit_chunks = re.findall(r"\d+", rid)
        if digit_chunks:
            rid_token = digit_chunks[-1]
        else:
            rid_token = re.sub(r"\W+", "", rid)[-8:] or "id"
        display_name = f"tex_{rid_token}"

    return {
        "resource_id": rid,
        "resource_name": src_name,
        "alias_name": alias,
        "binding_names": clean_binding_names,
        "display_name": display_name,
        "name_stem": _safe_name_token(display_name),
    }


def _normalize_export_format(value: Any) -> str:
    fmt = str(value or "png").strip().lower()
    if fmt == "jpeg":
        return "jpg"
    return fmt


def _parse_requested_formats(value: Any) -> List[str]:
    parsed = coerce._parse_json_like(value)
    if parsed is None:
        return ["png"]
    if isinstance(parsed, list):
        tokens = [str(item).strip() for item in parsed if str(item).strip()]
    else:
        text = str(parsed).strip()
        if not text:
            tokens = ["png"]
        else:
            tokens = [token for token in re.split(r"[,\s|;/]+", text) if token]
    normalized: List[str] = []
    for token in tokens:
        fmt = _normalize_export_format(token)
        if fmt and fmt not in normalized:
            normalized.append(fmt)
    return normalized or ["png"]


def _texture_format_name(texture_desc: Optional[Any]) -> str:
    if texture_desc is None:
        return ""
    fmt = getattr(texture_desc, "format", None)
    if fmt is None:
        return ""
    try:
        name_fn = getattr(fmt, "Name", None)
        if callable(name_fn):
            return str(name_fn())
    except Exception:
        pass
    return str(fmt)


def _recommend_formats_for_texture(
    texture_desc: Optional[Any],
    *,
    name_info: Optional[Dict[str, Any]] = None,
    for_screenshot: bool = False,
) -> List[str]:
    format_name = _texture_format_name(texture_desc).lower()
    names_blob = " ".join(
        [
            str((name_info or {}).get("resource_name", "")),
            str((name_info or {}).get("alias_name", "")),
            " ".join((name_info or {}).get("binding_names", []) or []),
        ],
    ).lower()
    is_depth = any(h in format_name for h in _DEPTH_HINTS) or any(h in names_blob for h in ("depth", "stencil"))
    is_hdr = any(h in format_name for h in _HDR_HINTS)
    is_compressed = any(h in format_name for h in _COMPRESSED_HINTS)
    is_normal = any(h in names_blob for h in _NORMAL_HINTS)
    is_mask = any(h in names_blob for h in _MASK_HINTS)
    is_color = any(h in names_blob for h in _COLOR_HINTS)
    is_cubemap = bool(getattr(texture_desc, "cubemap", False))
    array_size = int(getattr(texture_desc, "arraysize", getattr(texture_desc, "arraySize", 1)) or 1)
    if array_size >= 6 and "cube" in str(getattr(texture_desc, "type", "")).lower():
        is_cubemap = True

    if for_screenshot:
        if is_hdr or is_cubemap:
            return ["png", "exr", "hdr", "jpg"]
        return ["png", "jpg"]

    if is_depth:
        return ["dds", "raw", "png"]
    if is_hdr or is_cubemap:
        return ["dds", "exr", "hdr", "raw", "png"]
    if is_normal or is_mask:
        return ["png", "tga", "bmp", "dds"]
    if is_compressed and not is_color:
        return ["dds", "png", "tga"]
    return ["png", "jpg", "tga", "bmp", "dds"]


def _select_export_formats(
    requested_formats: Sequence[str],
    *,
    recommended_formats: Sequence[str],
) -> List[str]:
    requested = [_normalize_export_format(item) for item in requested_formats if str(item).strip()]
    if not requested:
        requested = ["png"]
    recommended = [_normalize_export_format(item) for item in recommended_formats if str(item).strip()]
    if not recommended:
        recommended = ["png"]

    if len(requested) == 1 and requested[0] in {"auto", "smart"}:
        return [recommended[0]]
    if len(requested) == 1 and requested[0] in {"all", "*"}:
        return list(dict.fromkeys(recommended))

    if any(item in {"all", "*"} for item in requested):
        for item in recommended:
            if item not in requested:
                requested.append(item)

    selected: List[str] = []
    for item in requested:
        if item in {"auto", "smart", "all", "*"}:
            continue
        if item not in selected:
            selected.append(item)
    return selected or [recommended[0]]


def _resolve_export_output_path(
    base_output_path: Optional[Any],
    *,
    name_stem: str,
    file_format: str,
    multi: bool,
) -> Optional[str]:
    if not base_output_path:
        return None
    fmt = _normalize_export_format(file_format)
    suffix = _FILE_SUFFIX_MAP.get(fmt, f".{fmt}")
    raw = str(base_output_path)
    path = Path(raw)
    is_dir_hint = raw.endswith(("\\", "/")) or path.is_dir() or not path.suffix

    if is_dir_hint:
        output_dir = path
        output_dir.mkdir(parents=True, exist_ok=True)
        return str(output_dir / f"{name_stem}{suffix}")

    if multi:
        path.parent.mkdir(parents=True, exist_ok=True)
        return str(path.parent / f"{_safe_name_token(path.stem)}_{fmt}{suffix}")

    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() != suffix:
        path = path.with_suffix(suffix)
    return str(path)
