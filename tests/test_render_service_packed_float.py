from __future__ import annotations

import asyncio
from types import SimpleNamespace

import numpy as np
import pytest

from rdc_tool.core import render_service


def _pack(r: int, g: int, b: int) -> bytes:
    return (r | (g << 11) | (b << 22)).to_bytes(4, "little")


def test_r11g11b10_float_readback_decodes_normal_subnormal_and_nonfinite(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # E=15,M=0 is 1.0; E=0 is subnormal; E=31 is Inf/NaN.
    raw = _pack(15 << 6, 16 << 6, 14 << 5) + _pack(1, (31 << 6), (31 << 5) | 1)
    texture = SimpleNamespace(
        resourceId="texture", width=2, height=1, mips=1, arraysize=1, depth=1, msSamp=1,
        format=SimpleNamespace(Name=lambda: "R11G11B10_FLOAT"),
    )
    events: list[int] = []
    controller = SimpleNamespace(
        SetFrameEvent=lambda event_id, force: events.append(event_id),
        GetTextures=lambda: [texture],
        GetTextureData=lambda resource_id, subresource: raw,
    )
    manager = SimpleNamespace(get_controller=lambda session_id: controller)
    monkeypatch.setattr(render_service, "_get_rd", lambda: SimpleNamespace(
        Subresource=lambda: SimpleNamespace(mip=0, slice=0, sample=0),
    ))

    pixels, stats = asyncio.run(render_service.RenderService().read_texture_array(
        "session", 42, "texture", manager,
    ))
    assert events == [42]
    assert pixels.shape == (1, 2, 3)
    np.testing.assert_allclose(pixels[0, 0], [1.0, 2.0, 0.5])
    assert pixels[0, 1, 0] == 2 ** -20
    assert np.isinf(pixels[0, 1, 1])
    assert np.isnan(pixels[0, 1, 2])
    assert stats["nan_count"] == 1
    assert stats["inf_count"] == 1
    assert stats["mean"] == pytest.approx((1.0 + 2.0 + 0.5 + 2 ** -20) / 4)


def test_r11g11b10_float_readback_rejects_incomplete_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    texture = SimpleNamespace(
        resourceId="texture", width=2, height=1, mips=1, arraysize=1, depth=1, msSamp=1,
        format=SimpleNamespace(Name=lambda: "R11G11B10_FLOAT"),
    )
    controller = SimpleNamespace(
        SetFrameEvent=lambda event_id, force: None,
        GetTextures=lambda: [texture],
        GetTextureData=lambda resource_id, subresource: _pack(15 << 6, 15 << 6, 15 << 5),
    )
    manager = SimpleNamespace(get_controller=lambda session_id: controller)
    monkeypatch.setattr(render_service, "_get_rd", lambda: SimpleNamespace(
        Subresource=lambda: SimpleNamespace(mip=0, slice=0, sample=0),
    ))
    with pytest.raises(ValueError, match="Texture readback size mismatch"):
        asyncio.run(render_service.RenderService().read_texture_array("session", 42, "texture", manager))
