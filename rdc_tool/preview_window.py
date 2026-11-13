"""Native preview host availability, independent from headless replay."""
import os
from rdc_tool.preview_geometry import fit_size_within_bounds, fit_content_rect

if os.name == "nt":
    from rdc_tool.preview_win32 import PreviewWindowHost
else:
    PreviewWindowHost = None
