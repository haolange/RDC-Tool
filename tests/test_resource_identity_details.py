from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from rdc_tool import server
from test_server_event_pipeline_resource import (
    _FakeAction, _FakeController, _install_common_env, _seed_capture, _seed_session,
)


class ResourceId:
    def __init__(self, value: int) -> None:
        self.value = value

    def __str__(self) -> str:
        return f"ResourceId::{self.value}"

    def __int__(self) -> int:
        return self.value


def install(monkeypatch: pytest.MonkeyPatch, kind: str, value: int):
    rid = ResourceId(value)
    controller = _FakeController(roots=[_FakeAction(101)])
    _install_common_env(monkeypatch, controller)
    _seed_capture()
    _seed_session(101)
    controller.current_event = 101
    texture = SimpleNamespace(resourceId=rid, name="captured", width=8, height=8,
                              depth=1, mips=1, format=SimpleNamespace(Name=lambda: "RGBA8"))
    buffer = SimpleNamespace(resourceId=rid, name="captured", length=64)
    store = SimpleNamespace(resourceId=rid, descriptorCount=2, descriptorByteSize=8)
    description = SimpleNamespace(resourceId=rid, name="captured", initialisationChunks=[2, 4],
                                  parentResources=[ResourceId(7)], derivedResources=[ResourceId(9)])
    monkeypatch.setattr(controller, "GetTextures", lambda: [texture] if kind == "texture" else [])
    monkeypatch.setattr(controller, "GetBuffers", lambda: [buffer] if kind == "buffer" else [])
    monkeypatch.setattr(controller, "GetDescriptorStores", lambda: [store] if kind == "descriptor_store" else [])
    monkeypatch.setattr(controller, "GetResources", lambda: [description])
    binding_calls = []

    async def bindings(*args):
        binding_calls.append(args)
        return {}

    monkeypatch.setattr(server.server_runtime, "_binding_name_index_for_event", bindings)
    return controller, rid, binding_calls


@pytest.mark.parametrize("kind", ["texture", "buffer", "descriptor_store", "description_only"])
@pytest.mark.parametrize("value", [203, 2**53 + 29])
@pytest.mark.parametrize("wrapped", [False, True])
def test_resource_details_resolves_exact_native_identity(monkeypatch, kind, value, wrapped):
    controller, rid, _ = install(monkeypatch, kind, value)
    result = asyncio.run(server.dispatch_operation("rd.resource.get_details", {
        "session_id": "sess_demo", "resource_id": str(rid) if wrapped else str(value),
        "include_initialization": True,
    }, transport="test"))
    assert result["ok"] is True
    details = result["data"]["details"]
    assert details["resource_id"] == str(rid)
    assert details["initialization"] == {
        "status": "available", "chunk_indices": [2, 4],
        "parent_resources": ["ResourceId::7"], "derived_resources": ["ResourceId::9"],
        "scope": "captured_initialization",
    }
    assert controller.current_event == 101
    assert controller.set_frame_calls == []


def test_completed_inventory_miss_has_pre_effect_proof_before_binding_queries(monkeypatch):
    controller, _, binding_calls = install(monkeypatch, "texture", 203)
    result = asyncio.run(server.dispatch_operation("rd.resource.get_details", {
        "session_id": "sess_demo", "resource_id": "1203",
    }, transport="test"))
    assert result["ok"] is False
    assert result["error"]["code"] == "resource_not_found"
    assert result["error"]["category"] == "validation"
    assert result["error"]["details"] == {
        "session_id": "sess_demo", "failure_stage": "resolve_resource",
        "effects_attempted": False, "context_preserved": True,
    }
    assert binding_calls == []
    assert controller.current_event == 101
    assert controller.set_frame_calls == []


@pytest.mark.parametrize("method", ["GetTextures", "GetBuffers", "GetDescriptorStores", "GetResources"])
def test_incomplete_native_inventory_never_claims_pre_effect_proof(monkeypatch, method):
    controller, _, _ = install(monkeypatch, "texture", 203)

    def fail():
        raise RuntimeError("native inventory read failed")

    monkeypatch.setattr(controller, method, fail)
    result = asyncio.run(server.dispatch_operation("rd.resource.get_details", {
        "session_id": "sess_demo", "resource_id": "203",
    }, transport="test"))
    assert result["ok"] is False
    assert result["error"]["category"] != "validation"
    proof = result["error"].get("details") or {}
    assert proof.get("effects_attempted") is not False
    assert proof.get("context_preserved") is not True
