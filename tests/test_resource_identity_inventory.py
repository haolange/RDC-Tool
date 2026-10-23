from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from rdc_tool import server
from test_resource_identity_details import ResourceId, install


def invoke(**args):
    return asyncio.run(server.dispatch_operation("rd.resource.list_all", {
        "session_id": "sess_demo", **args,
    }, transport="test"))


def test_unfiltered_inventory_covers_description_only_identity_without_losing_rows(monkeypatch):
    controller, rid, _ = install(monkeypatch, "texture", 203)
    other = ResourceId(2**53 + 29)
    monkeypatch.setattr(controller, "GetResources", lambda: [
        SimpleNamespace(resourceId=rid, name="captured"),
        SimpleNamespace(resourceId=other, name="shader"),
    ])
    result = invoke()
    assert result["ok"] is True
    assert [row["resource_id"] for row in result["data"]["resources"]] == [str(rid)]
    inventory = result["data"]["identity_inventory"]
    assert inventory == {
        "scope": "all_native_resource_identities", "complete": True,
        "resource_ids": [str(rid), str(other)], "count": 2,
        "source_counts": {"textures": 1, "buffers": 0, "descriptor_stores": 0, "descriptions": 2},
    }
    assert controller.set_frame_calls == []


@pytest.mark.parametrize("kind", ["texture", "buffer", "descriptor_store", "description_only"])
def test_identity_inventory_covers_each_native_source_once(monkeypatch, kind):
    controller, rid, _ = install(monkeypatch, kind, 203)
    calls = {}
    for name in ("GetTextures", "GetBuffers", "GetDescriptorStores", "GetResources"):
        original = getattr(controller, name)
        def read(original=original, name=name):
            calls[name] = calls.get(name, 0) + 1
            return original()
        monkeypatch.setattr(controller, name, read)
    result = invoke()
    assert result["ok"] is True
    assert result["data"]["identity_inventory"]["resource_ids"] == [str(rid)]
    assert calls == {name: 1 for name in ("GetTextures", "GetBuffers", "GetDescriptorStores", "GetResources")}


def test_filtered_rows_do_not_claim_global_identity_completeness(monkeypatch):
    controller, _, _ = install(monkeypatch, "texture", 203)
    def forbidden():
        raise AssertionError("filtered resource rows must not fetch a global description inventory")
    monkeypatch.setattr(controller, "GetResources", forbidden)
    result = invoke(kind="texture")
    assert result["ok"] is True
    assert "identity_inventory" not in result["data"]


@pytest.mark.parametrize("method", ["GetTextures", "GetBuffers", "GetDescriptorStores", "GetResources"])
def test_incomplete_native_inventory_is_an_error_not_a_complete_empty_set(monkeypatch, method):
    controller, _, _ = install(monkeypatch, "texture", 203)
    def fail():
        raise RuntimeError("native census unavailable")
    monkeypatch.setattr(controller, method, fail)
    result = invoke()
    assert result["ok"] is False
    assert result.get("data") is None or "identity_inventory" not in result["data"]
