"""Native preview window contract.

A preview window is a host capability: hosts without an implementation raise
``PreviewWindowUnsupported`` so callers report a structured capability error.
Headless observation and image export never depend on this module.
"""

from __future__ import annotations

from typing import Callable, Protocol

from rdc_tool.platform import host


class PreviewWindow(Protocol):
    hwnd: int

    def start(self, *, timeout_s: float = 5.0) -> int: ...

    def is_alive(self) -> bool: ...

    def close(self, *, by_user: bool = False, timeout_s: float = 2.0) -> None: ...

    def set_title(self, title: str) -> None: ...

    def geometry_snapshot(self) -> dict[str, object]: ...

    def apply_framebuffer_geometry(
        self, framebuffer_width: int, framebuffer_height: int, *, screen_cap_ratio: float = 0.5, force: bool = False,
    ) -> dict[str, object]: ...


class PreviewWindowUnsupported(RuntimeError):
    def __init__(self, host_target: str) -> None:
        super().__init__(f"Native preview windows are not available on {host_target}; use headless observation or image export.")
        self.host_target = host_target


def preview_window_supported() -> bool:
    return host.IS_WINDOWS


def create_preview_window(*, title: str, on_closed: Callable[[bool], None]) -> PreviewWindow:
    if not host.IS_WINDOWS:
        raise PreviewWindowUnsupported(host.host_target())
    from rdc_tool.platform._windows_preview import PreviewWindowHost

    return PreviewWindowHost(title=title, on_closed=on_closed)
