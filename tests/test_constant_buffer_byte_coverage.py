from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from rdc_tool import server_runtime as rt


def collect(monkeypatch, *, block=64, bound=64, budget=64, value=7, include=True, supported=True, unbound=False, backed=True):
    calls = []
    shader = object()
    def decode(*args):
        assert args[1] is shader
        calls.append(args[-1])
        return [SimpleNamespace(name="tail", value=value if args[-1] >= block else 0)]
    async def inline(fn, *args):
        return fn(*args)
    pipe = SimpleNamespace(GetConstantBlock=lambda *_: SimpleNamespace(
        descriptor=SimpleNamespace(resource="ResourceId::0" if unbound else "ResourceId::99", byteOffset=8, byteSize=bound),
        access=SimpleNamespace(index=0, type=9)))
    reflection = SimpleNamespace(entryPoint="main", constantBlocks=[SimpleNamespace(
        name="Block", byteSize=block, variables=[], bufferBacked=backed, fixedBindSetOrSpace=0)])
    monkeypatch.setattr(rt, "_offload", inline)
    monkeypatch.setattr(rt, "_get_rd", lambda: SimpleNamespace(ResourceId=lambda: "ResourceId::0"))
    monkeypatch.setattr(rt, "_rd_stage", lambda stage: stage)
    monkeypatch.setattr(rt, "_pipeline_object_for_cbuffer", lambda *_: "pipeline")
    monkeypatch.setattr(rt, "_shader_variable_payload", lambda variable: {"name": variable.name, "value": variable.value})
    monkeypatch.setattr(rt, "_flatten_shader_variable_values", lambda variable, _prefix, out: out.update({variable.name: variable.value}))
    controller = SimpleNamespace(GetCBufferVariableContents=decode) if supported else SimpleNamespace()
    result = asyncio.run(rt._collect_constant_buffers(controller, pipe, reflection, "ps", shader,
        slot=0, include_contents=include, max_bytes=budget, flatten=True))
    return result[0], calls


def test_partial_budget_does_not_publish_padding_as_typed_zero(monkeypatch):
    result, calls = collect(monkeypatch, budget=16)
    assert calls == []
    assert result["contents"] == []
    assert result["flattened_contents"] == {}
    assert result["decode_status"] == "unavailable"
    assert result["decode_input_bytes"] == 0
    assert result["input_coverage"]["status"] == "budget_limited"
    assert result["input_coverage"]["required_bytes"] == 64
    assert result["input_coverage"]["permitted_bytes"] == 16


@pytest.mark.parametrize("budget,bound,expected", [(64, 80, 64), (0, 80, 80), (128, 64, 64)])
def test_full_input_and_zero_unlimited_budget_keep_native_decoding(monkeypatch, budget, bound, expected):
    result, calls = collect(monkeypatch, budget=budget, bound=bound)
    assert calls == [expected]
    assert result["decode_status"] == "decoded"
    assert result["decode_input_bytes"] == expected
    assert result["contents"] == [{"name": "tail", "value": 7}]
    assert result["flattened_contents"] == {"tail": 7}
    assert result["input_coverage"]["complete_range_permitted"] is True


def test_actual_decoded_zero_remains_a_valid_zero(monkeypatch):
    result, calls = collect(monkeypatch, value=0)
    assert calls == [64]
    assert result["decode_status"] == "decoded"
    assert result["contents"][0]["value"] == 0


@pytest.mark.parametrize("block,bound,status", [(64, 32, "binding_limited"), (0, 0, "unknown_extent")])
def test_incomplete_or_unknown_range_never_calls_full_layout_decoder(monkeypatch, block, bound, status):
    result, calls = collect(monkeypatch, block=block, bound=bound, budget=128)
    assert calls == []
    assert result["input_coverage"]["status"] == status
    assert result["decode_status"] == "unavailable"
    assert result["contents"] == []


def test_missing_native_decoder_is_explicit_not_empty_data(monkeypatch):
    result, calls = collect(monkeypatch, supported=False)
    assert calls == []
    assert result["decode_status"] == "unavailable"
    assert "unavailable" in result["decode_error"]


def test_unbound_buffer_backed_block_cannot_become_a_zero_block(monkeypatch):
    result, calls = collect(monkeypatch, unbound=True)
    assert calls == []
    assert result["decode_status"] == "unavailable"
    assert result["decode_error"]


def test_non_buffer_backed_constants_still_use_native_source(monkeypatch):
    result, calls = collect(monkeypatch, unbound=True, backed=False)
    assert calls == [64]
    assert result["decode_status"] == "decoded"


def test_metadata_query_does_not_attempt_or_claim_decoding(monkeypatch):
    result, calls = collect(monkeypatch, include=False, budget=16)
    assert calls == []
    assert "contents" not in result
    assert "input_coverage" not in result


def test_negative_window_budget_is_validation_failure():
    with pytest.raises(rt.CoreError, match="max_bytes"):
        rt._constant_buffer_byte_window(64, 64, -1)


def test_decoded_export_propagates_unavailable_values_as_partial(monkeypatch, tmp_path):
    async def pipeline(_action, _args):
        return json.dumps({"success": True, "constant_buffers": [{"slot": 0, "decode_error": "budget_limited", "contents": []}]})
    monkeypatch.setattr(rt, "_dispatch_pipeline", pipeline)
    result = json.loads(asyncio.run(rt._dispatch_export("cbuffer_dump", {
        "session_id": "test-session", "output_dir": str(tmp_path), "stages": ["ps"], "max_bytes": 16,
    })))
    assert result["success"] is True
    assert result["partial"] is True
    assert result["failures"][0]["code"] == "constant_buffer_decode_unavailable"
    assert json.loads((tmp_path / "cbuffer_ps.json").read_text())[0]["contents"] == []


@pytest.mark.parametrize("budget,expected,partial", [(0, 64, False), (16, 16, True)])
def test_raw_export_budget_zero_means_the_block_not_zero_native_length(monkeypatch, tmp_path, budget, expected, partial):
    requests = []
    async def pipeline(_action, _args):
        return json.dumps({"success": True, "constant_buffers": [{"slot": 0, "resource_id": "ResourceId::99", "offset": 8, "byte_size": 64, "size": 80}]})
    async def export(args):
        requests.append(args)
        return json.dumps({"success": True, "saved_path": args["output_path"]})
    monkeypatch.setattr(rt, "_dispatch_pipeline", pipeline)
    monkeypatch.setattr(rt, "_export_buffer_file", export)
    result = json.loads(asyncio.run(rt._dispatch_export("cbuffer_dump", {
        "session_id": "test-session", "output_dir": str(tmp_path), "stages": ["ps"], "max_bytes": budget,
        "include_decoded": False, "include_raw": True,
    })))
    assert requests[0]["size"] == expected
    assert result["partial"] is partial
    saved = json.loads((tmp_path / "cbuffer_ps.json").read_text())[0]
    assert saved["raw_export_coverage"]["truncated"] is partial
