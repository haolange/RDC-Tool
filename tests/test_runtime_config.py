from __future__ import annotations

import asyncio

from rdc_tool import server


def _call(operation, args):
    return asyncio.run(server.dispatch_operation(operation, args, transport="test"))


def test_set_config_rejects_unsupported_keys_instead_of_ignoring_them():
    result = _call("rd.core.set_config", {"config": {"default_image_format": "png"}})
    assert result["ok"] is False
    assert "default_image_format" in result["error"]["message"]


def test_get_config_reports_only_effective_sections():
    result = _call("rd.core.get_config", {})
    assert result["ok"] is True
    config = result["data"]["config"]
    assert {"artifact_dir", "log_level", "snapshot_retention", "runtime_limits"} <= set(config)
    assert not {"bisect", "confidence_weights", "adaptive_bisect"} & set(config)
