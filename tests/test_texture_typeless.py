from __future__ import annotations

import asyncio
import io
import json
from types import SimpleNamespace

import numpy as np
import pytest

from rdc_tool.core import render_service
from rdc_tool.core import replay_facts
from rdc_tool.runtime import live_state, renderdoc_api, replay_access, texture_export, truth_matrix
from rdc_tool.runtime.operations import texture as texture_ops


def _setup(monkeypatch, tmp_path, view_name, *, shader_resource=False):
    comp_types = SimpleNamespace(Typeless=0, UNorm=1, UInt=2, Float=3)
    stages = SimpleNamespace(**{name: name for name in ("Vertex", "Hull", "Domain", "Geometry", "Pixel", "Compute")})
    rd = SimpleNamespace(CompType=comp_types, ShaderStage=stages,
                         Subresource=lambda: SimpleNamespace(mip=0, slice=0, sample=0))
    texture = SimpleNamespace(resourceId="texture", width=1, height=1, mips=1, arraysize=1, depth=1, msSamp=1,
                              format=SimpleNamespace(Name=lambda: "B8G8R8A8_TYPELESS", compType=comp_types.Typeless))
    view = SimpleNamespace(resource="texture", format=SimpleNamespace(Name=lambda: view_name, compType=comp_types.UNorm))
    pipe = SimpleNamespace(GetOutputTargets=lambda: [] if shader_resource or view_name is None else [view],
                           GetReadOnlyResources=lambda stage: [SimpleNamespace(descriptor=view)]
                           if shader_resource and view_name is not None and stage == "Pixel" else [],
                           GetReadWriteResources=lambda stage: [])
    calls = []
    controller = SimpleNamespace(
        SetFrameEvent=lambda event, force: calls.append(event),
        GetTextures=lambda: [texture], GetPipelineState=lambda: pipe,
        GetTextureData=lambda resource, sub: bytes([51, 102, 153, 255]))
    async def ensure(session, event):
        return event
    async def resolve(session, resource, **kwargs):
        return resource
    async def truth(*args):
        return {"binding_truth_level": "binding_verified", "evidence_truth_level": "structured_readback"}
    saved = []
    async def store(data, **kwargs):
        saved.append(data)
        return SimpleNamespace(sha256="result")
    monkeypatch.setattr(render_service, "_get_rd", lambda: rd)
    monkeypatch.setattr(renderdoc_api, "_get_rd", lambda: rd)
    monkeypatch.setattr(replay_access, "_ensure_event", ensure)
    monkeypatch.setattr(replay_access, "_resolve_texture_id", resolve)
    monkeypatch.setattr(truth_matrix, "_event_truth_metadata", truth)
    monkeypatch.setattr(live_state, "_render_service", render_service.RenderService())
    monkeypatch.setattr(live_state, "_session_manager", SimpleNamespace(get_controller=lambda session: controller))
    monkeypatch.setattr(live_state, "_artifact_store", SimpleNamespace(store=store, get_path=lambda _: tmp_path / "region.npz"))
    return controller, texture, rd, calls, saved


@pytest.mark.parametrize("shader_resource", [False, True])
def test_typeless_region_uses_bound_view_format(monkeypatch, tmp_path, shader_resource):
    _, _, _, calls, saved = _setup(monkeypatch, tmp_path, "B8G8R8A8_UNORM", shader_resource=shader_resource)
    result = json.loads(asyncio.run(texture_ops.dispatch("get_region_values", {
        "session_id": "session", "event_id": 42, "texture_id": "texture",
        "rect": {"x": 0, "y": 0, "w": 1, "h": 1}})))
    assert result["success"] is True and calls == [42]
    np.testing.assert_allclose(result["values"], [[[153 / 255, 102 / 255, 51 / 255, 1]]])
    assert result["stats"]["source_format"] == "B8G8R8A8_TYPELESS"
    assert result["stats"]["view_format"] == "B8G8R8A8_UNORM"
    with np.load(io.BytesIO(saved[0])) as data:
        np.testing.assert_allclose(data["pixels"], result["values"])


def test_typeless_region_without_bound_view_preserves_raw_unsigned_values(monkeypatch, tmp_path):
    _, _, _, _, saved = _setup(monkeypatch, tmp_path, None)
    result = json.loads(asyncio.run(texture_ops.dispatch("get_region_values", {
        "session_id": "session", "event_id": 42, "texture_id": "texture",
        "rect": {"x": 0, "y": 0, "w": 1, "h": 1}})))
    assert result["values"] == [[[153, 102, 51, 255]]]
    assert result["stats"]["view_format"] is None
    assert result["stats"]["value_interpretation"] == "raw_unsigned_integer"
    assert result["stats"]["interpretation_note"] == "无类型格式，视图格式未知，数值为原始整数"
    with np.load(io.BytesIO(saved[0])) as data:
        assert data["pixels"].dtype == np.uint8
        np.testing.assert_array_equal(data["pixels"], result["values"])


@pytest.mark.parametrize("view_name", ["B8G8R8A8_UNORM", None])
def test_typeless_pixel_history_uses_view_or_explicit_raw_uint(monkeypatch, tmp_path, view_name):
    controller, texture, rd, _, _ = _setup(monkeypatch, tmp_path, view_name)
    calls = []
    color = SimpleNamespace(floatValue=[0.25, 0.5, 0.75, 1.0], uintValue=[1, 2, 3, 4])
    mod = SimpleNamespace(IsValid=lambda: True, col=color, depth=-1.0, stencil=-1)
    item = SimpleNamespace(eventId=42, fragIndex=0, Passed=lambda: True, preMod=mod, shaderOut=mod, postMod=mod)
    controller.PixelHistory = lambda *args: calls.append(args[-1]) or [item]
    async def get_controller(session):
        return controller
    async def get_descriptor(session, resource, **kwargs):
        return resource, texture
    monkeypatch.setattr(replay_access, "_get_controller", get_controller)
    monkeypatch.setattr(replay_access, "_get_texture_descriptor", get_descriptor)
    monkeypatch.setattr(replay_facts, "pixel_history_input_attachment_conflict", lambda *args: None)
    result = json.loads(asyncio.run(texture_ops.dispatch("get_pixel_history", {
        "session_id": "session", "event_id": 42, "texture_id": "texture",
        "x": 0, "y": 0, "include_shaders": False})))
    assert calls == [rd.CompType.UNorm if view_name else rd.CompType.UInt]
    assert result["history"][0]["pre_mod"]["color_rgba"] == (
        [0.25, 0.5, 0.75, 1.0] if view_name else [1, 2, 3, 4])
    assert result["value_interpretation"] == ("view_format" if view_name else "raw_unsigned_integer")


@pytest.mark.parametrize("action,extra", [
    ("get_data", {"texture_id": "texture"}),
    ("get_region_values", {"texture_id": "texture", "rect": {"x": 0, "y": 0, "w": 1, "h": 1}}),
    ("get_histogram", {"texture_id": "texture"}),
    ("compute_stats", {"texture_id": "texture"}),
    ("diff", {"tex_a": {"texture_id": "texture"}, "tex_b": {"texture_id": "texture"}}),
])
def test_texture_decode_failure_restores_event_and_returns_qualified_error(monkeypatch, action, extra):
    active = {"event": 11}
    async def ensure(session, event):
        active["event"] = event
        return event
    async def resolve(session, texture, **kwargs):
        return texture
    async def fail(*args, **kwargs):
        raise render_service.TextureDecodeError("Unsupported texture readback format")
    async def get_controller(session):
        return object()
    async def read_at_state(session, resource, args, reader):
        active["event"] = 42
        return await reader(42), {}
    monkeypatch.setattr(replay_access, "_get_controller", get_controller)
    monkeypatch.setattr(replay_access, "_resolve_resource_id", resolve)
    monkeypatch.setattr(texture_export, "_read_at_capture_state", read_at_state)
    monkeypatch.setattr(replay_access, "_ensure_event", ensure)
    monkeypatch.setattr(replay_access, "_resolve_texture_id", resolve)
    monkeypatch.setattr(replay_access, "_active_event", lambda session: active["event"])
    monkeypatch.setattr(live_state, "_runtime_context_id", lambda: "context")
    monkeypatch.setattr(live_state, "_render_service", SimpleNamespace(read_texture_array=fail))
    result = json.loads(asyncio.run(texture_ops.dispatch(action, {
        "session_id": "session", "event_id": 42, **extra})))
    assert result["code"] == "texture_readback_decode_failed"
    assert result["details"] == {"context_id": "context", "session_id": "session",
        "failure_stage": "decode_texture_readback", "replay_state_restored": True, "restored_event_id": 11}
    assert active["event"] == 11
