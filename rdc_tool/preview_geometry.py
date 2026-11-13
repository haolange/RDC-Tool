"""Platform-independent preview layout calculations."""
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


def fit_content_rect(
    client_width: int,
    client_height: int,
    content_width: int,
    content_height: int,
) -> dict[str, int]:
    target_width = max(1, int(client_width or 1))
    target_height = max(1, int(client_height or 1))
    content_fit_width, content_fit_height = fit_size_within_bounds(
        content_width,
        content_height,
        target_width,
        target_height,
    )
    offset_x = max(0, (target_width - content_fit_width) // 2)
    offset_y = max(0, (target_height - content_fit_height) // 2)
    return {
        "x": int(offset_x),
        "y": int(offset_y),
        "width": int(content_fit_width),
        "height": int(content_fit_height),
    }
