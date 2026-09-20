from __future__ import annotations

from rdc_tool.io_utils import safe_json_text


def test_safe_json_text_sanitizes_unpaired_surrogates() -> None:
    payload = {"path": "bad\udcaa.rdc", "nested": ["ok", "also\udcaa"]}

    dumped = safe_json_text(payload)

    assert "\\udcaa" in dumped
    dumped.encode("utf-8")
