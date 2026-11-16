from __future__ import annotations

import asyncio

import pytest

from rdc_tool.core.errors import CoreError
from rdc_tool.platform import host, preview
from rdc_tool.runtime import dispatch, live_state, preview_sync


def test_non_windows_host_reports_structured_preview_unsupported(monkeypatch):
    monkeypatch.setattr(host, "IS_WINDOWS", False)
    assert preview.preview_window_supported() is False
    with pytest.raises(preview.PreviewWindowUnsupported) as caught:
        preview.create_preview_window(title="t", on_closed=lambda by_user: None)
    assert caught.value.host_target == host.host_target()


def test_preview_binding_maps_unsupported_host_to_capability_error(monkeypatch):
    monkeypatch.setattr(host, "IS_WINDOWS", False)
    with pytest.raises(CoreError) as caught:
        asyncio.run(preview_sync._create_preview_binding("ctx-preview", title="t"))
    assert caught.value.code == "preview_unsupported_platform"
    assert caught.value.category == "capability"
    assert caught.value.details["capability"] == "preview_window"
    assert caught.value.details["alternative"] == "rd.session.observe"
    assert "ctx-preview" not in live_state._runtime.previews


def test_capabilities_declare_preview_window(monkeypatch):
    monkeypatch.setattr(host, "IS_WINDOWS", False)
    result = asyncio.run(dispatch.dispatch_operation("rd.core.get_capabilities", {}, transport="test"))
    assert result["ok"] is True
    entry = result["data"]["capabilities"]["preview_window"]
    assert entry["available"] is False
    assert entry["source"] == "platform"
    assert entry["host_target"] == host.host_target()
