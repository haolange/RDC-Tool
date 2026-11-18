from pathlib import Path

import pytest

from rdc_tool.core import patch_engine
from rdc_tool.host_tools import HostToolUnavailableError


SOURCE = "define void @Main() {\n  %x = call float @dx.op.unary.f32(i32 7, float 1.000000e+00)\n  ret void\n}\n"


@pytest.mark.parametrize("available", [True, False])
def test_dxil_edit_plan_records_required_toolchain_without_hiding_capability(monkeypatch, available):
    def resolve(name):
        if not available:
            raise HostToolUnavailableError(f"{name} not found in selected directory")
        return Path(name)
    monkeypatch.setattr(patch_engine, "resolve_host_tool", resolve)
    plan = patch_engine.PatchEngine._edit_plan_for_source(
        encoding_name="dxilasm", disassembly_target="DXIL ASM", source=SOURCE)
    assert plan["input_kind"] == "text_ir" and plan["can_replace"] is True
    assert plan["build_input_kind"] == "binary_dxil"
    assert plan["requires_toolchain"] == ["dxc", "dxcompiler"]
    assert plan["toolchain_available"] is available
    assert bool(plan["missing_toolchain"]) is not available
    assert plan["allowed_edit_inputs"] == ["source_text", "diff_text"] and plan["allowed_ops"] == []


def test_legacy_dxbc_disassembly_remains_read_only():
    plan = patch_engine.PatchEngine._edit_plan_for_source(
        encoding_name="dxbc", disassembly_target="DXBC/DXIL", source="ps_5_0\nret")
    assert plan["shader_format"]["container"] == "dxbc"
    assert plan["can_edit_text"] is False and plan["can_replace"] is False


@pytest.mark.parametrize("text, expected", [
    (SOURCE, True),
    ("; define void @Main() {\n; call void @dx.op.storeOutput.f32()\nerror: invalid", False),
])
def test_dxil_recognition_requires_real_function_and_dx_operation(text, expected):
    assert patch_engine.PatchEngine._looks_like_raw_dxil_asm(text) is expected
