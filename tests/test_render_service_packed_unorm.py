from __future__ import annotations

import asyncio
from types import SimpleNamespace

import numpy as np
import pytest

from rdc_tool.core import render_service


def _pack(r: int, g: int, b: int, a: int) -> bytes:
    return (r | (g << 10) | (b << 20) | (a << 30)).to_bytes(4, "little")


def _manager(monkeypatch: pytest.MonkeyPatch, name: str, raw: bytes, **overrides):
    texture = SimpleNamespace(resourceId="texture", width=2, height=1, mips=1,
                              arraysize=1, depth=1, msSamp=1,
                              format=SimpleNamespace(Name=lambda: name))
    texture.__dict__.update(overrides)
    reads = []
    controller = SimpleNamespace(SetFrameEvent=lambda event, force: None,
                                 GetTextures=lambda: [texture],
                                 GetTextureData=lambda resource, sub: reads.append((resource, sub.mip, sub.slice, sub.sample)) or raw)
    monkeypatch.setattr(render_service, "_get_rd", lambda: SimpleNamespace(
        Subresource=lambda: SimpleNamespace(mip=0, slice=0, sample=0)))
    return SimpleNamespace(get_controller=lambda session: controller), reads


@pytest.mark.parametrize("order", ["R10G10B10A2", "B10G10R10A2"])
def test_packed_unorm_preserves_ten_bit_color_and_two_bit_alpha(monkeypatch, order):
    raw = _pack(0, 513, 1023, 1) + _pack(1023, 0, 512, 3)
    manager, reads = _manager(monkeypatch, order + "_UNORM", raw)
    values, stats = asyncio.run(render_service.RenderService().read_texture_array("session", 42, "texture", manager))
    expected = np.array([[[0, 513 / 1023, 1, 1 / 3], [1, 0, 512 / 1023, 1]]])
    if order.startswith("B"):
        expected = expected[..., [2, 1, 0, 3]]
    np.testing.assert_allclose(values, expected, rtol=0, atol=1e-15)
    assert reads == [("texture", 0, 0, 0)]
    assert stats["shape"] == [1, 2, 4]
    assert stats["min"] == 0 and stats["max"] == 1
    assert stats["mean"] == pytest.approx(expected.mean())
    assert stats["nan_count"] == 0 and stats["inf_count"] == 0


def test_packed_unorm_keeps_subresource_and_region_selection(monkeypatch):
    raw = _pack(0, 0, 0, 0) + _pack(10, 20, 30, 2)
    manager, reads = _manager(monkeypatch, "R10G10B10A2_UNORM", raw,
                              width=4, height=2, mips=2, arraysize=2, msSamp=2)
    values, stats = asyncio.run(render_service.RenderService().read_texture_array(
        "session", 42, "texture", manager, {"mip": 1, "slice": 1, "sample": 1},
        region={"x": 1, "y": 0, "width": 1, "height": 1}))
    np.testing.assert_allclose(values, [[[10 / 1023, 20 / 1023, 30 / 1023, 2 / 3]]])
    assert stats["shape"] == [1, 1, 4]
    assert reads == [("texture", 1, 1, 1)]


def test_packed_unorm_rejects_short_readback(monkeypatch):
    manager, _ = _manager(monkeypatch, "R10G10B10A2_UNORM", _pack(1, 2, 3, 1))
    with pytest.raises(ValueError, match="Texture readback size mismatch"):
        asyncio.run(render_service.RenderService().read_texture_array("session", 42, "texture", manager))


@pytest.mark.parametrize("suffix", ["FLOAT", "TYPELESS"])
def test_packed_unorm_does_not_guess_unknown_component_semantics(monkeypatch, suffix):
    manager, _ = _manager(monkeypatch, "R10G10B10A2_" + suffix, _pack(1, 2, 3, 1) * 2)
    with pytest.raises(ValueError, match="Unsupported texture readback format"):
        asyncio.run(render_service.RenderService().read_texture_array("session", 42, "texture", manager))