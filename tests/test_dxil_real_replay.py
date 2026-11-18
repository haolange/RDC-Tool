"""Explicitly enabled real replay of a caller-provided DXIL capture."""
from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path

import pytest

from rdc_tool.core.patch_engine import PatchEngine
from rdc_tool.runtime_paths import HOST_LAYOUTS


@pytest.mark.fixture_integration
def test_dxil_ir_roundtrip_with_real_replay(request):
    if not request.config.getoption("--fixture-integration"):
        pytest.skip("real replay is opt-in via --fixture-integration")
    required = ("RDC_TOOL_DXIL_FIXTURE", "RDC_TOOL_DXIL_EVENT", "RDC_TOOL_DXIL_OUTPUT", "RDC_TOOL_DXIL_RESTORE_EVENT")
    missing = [name for name in required if not os.environ.get(name)]
    if missing:
        pytest.fail("Missing real replay inputs: " + ", ".join(missing))
    root = Path(request.config.getoption("--fixture-root"))
    runtime = root / HOST_LAYOUTS["windows-x64"].runtime_dir
    dll_directory = os.add_dll_directory(str(runtime))
    sys.path.insert(0, str(runtime / "pymodules"))
    import renderdoc as rd

    cap = controller = target = shader = None
    replaced = False
    try:
        rd.InitialiseReplay(rd.GlobalEnvironment(), [])
        cap = rd.OpenCaptureFile()
        assert cap.OpenFile(os.environ["RDC_TOOL_DXIL_FIXTURE"], "", None) == rd.ResultCode.Succeeded
        status, controller = cap.OpenCapture(rd.ReplayOptions(), None)
        assert status == rd.ResultCode.Succeeded and controller is not None
        event = int(os.environ["RDC_TOOL_DXIL_EVENT"])
        output = [t.resourceId for t in controller.GetTextures() if str(t.resourceId) == os.environ["RDC_TOOL_DXIL_OUTPUT"]]
        assert len(output) == 1
        controller.SetFrameEvent(event, True)
        pipe = controller.GetPipelineState()
        shader = pipe.GetShader(rd.ShaderStage.Pixel)
        refl = pipe.GetShaderReflection(rd.ShaderStage.Pixel)
        assert refl.encoding == rd.ShaderEncoding.DXIL
        source = PatchEngine._disassemble_raw_dxil_bytes(refl)
        assert PatchEngine._looks_like_raw_dxil_asm(source)
        binary = PatchEngine._source_bytes_for_build(source, "dxil", "DXIL ASM")
        baseline = bytes(controller.GetTextureData(output[0], rd.Subresource(0, 0, 0)))
        assert baseline
        target, errors = controller.BuildTargetShader(refl.entryPoint, rd.ShaderEncoding.DXIL, binary,
                                                       rd.ShaderCompileFlags(), rd.ShaderStage.Pixel)
        assert target != rd.ResourceId.Null(), str(errors)
        controller.ReplaceResource(shader, target)
        replaced = True
        controller.SetFrameEvent(event, True)
        bound = controller.GetPipelineState().GetShaderReflection(rd.ShaderStage.Pixel)
        assert hashlib.sha256(bytes(bound.rawBytes)).digest() == hashlib.sha256(binary).digest()
        assert bytes(controller.GetTextureData(output[0], rd.Subresource(0, 0, 0))) == baseline
        controller.RemoveReplacement(shader)
        replaced = False
        controller.SetFrameEvent(event, True)
        assert bytes(controller.GetTextureData(output[0], rd.Subresource(0, 0, 0))) == baseline
    finally:
        if controller is not None:
            if replaced:
                controller.RemoveReplacement(shader)
            if target is not None and target != rd.ResourceId.Null():
                controller.FreeTargetResource(target)
            controller.SetFrameEvent(int(os.environ["RDC_TOOL_DXIL_RESTORE_EVENT"]), True)
            controller.Shutdown()
        if cap is not None:
            cap.Shutdown()
        rd.ShutdownReplay()
        dll_directory.close()
