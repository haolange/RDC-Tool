from __future__ import annotations

import json
import math

from rdc_tool.io_utils import safe_json_text


def test_safe_json_text_sanitizes_unpaired_surrogates() -> None:
    payload = {"path": "bad\udcaa.rdc", "nested": ["ok", "also\udcaa"]}

    dumped = safe_json_text(payload)

    assert "\\udcaa" in dumped
    dumped.encode("utf-8")


def test_safe_json_text_preserves_nonfinite_values_as_explicit_markers() -> None:
    payload = {"values": [1.25, float("nan"), float("inf"), -float("inf")], "nested": (float("nan"),)}

    dumped = safe_json_text(payload)
    parsed = json.loads(dumped, parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))

    assert parsed == {"values": [1.25, "NaN", "Infinity", "-Infinity"], "nested": ["NaN"]}
    assert math.isfinite(parsed["values"][0])


def test_safe_json_text_sanitizes_custom_default_payload() -> None:
    class NativeValue:
        pass

    dumped = safe_json_text({"value": NativeValue()}, default=lambda _: {"samples": [float("nan")]})

    assert json.loads(dumped, parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value))) == {
        "value": {"samples": ["NaN"]}
    }
