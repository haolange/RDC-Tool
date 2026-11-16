"""Platform-independent preview window fitting."""

from __future__ import annotations


def fit_size_within_bounds(
    content_width: int,
    content_height: int,
    max_width: int,
    max_height: int,
) -> tuple[int, int]:
    width = max(1, int(content_width or 1))
    height = max(1, int(content_height or 1))
    bound_width = max(1, int(max_width or width))
    bound_height = max(1, int(max_height or height))
    scale = min(1.0, float(bound_width) / float(width), float(bound_height) / float(height))
    return (
        max(1, int(round(float(width) * scale))),
        max(1, int(round(float(height) * scale))),
    )
