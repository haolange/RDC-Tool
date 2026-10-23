from __future__ import annotations

import asyncio
import json
from enum import IntEnum
from types import SimpleNamespace

import pytest
from rdc_tool import server_runtime as runtime
from rdc_tool.core import patch_engine


class Encoding(IntEnum):
    HLSL = 1
    GLSL = 2
    SPIRV = 3
    SPIRVAsm = 4


MODULE = bytes.fromhex("0302230700000100000000000200000000000000")
ASM = "OpCapability Shader\nOpMemoryModel Logical GLSL450\n"


@pytest.fixture
def compile_env(monkeypatch):
    calls = []
    controller = SimpleNamespace(
        GetTargetShaderEncodings=lambda: [Encoding.SPIRV],
        BuildTargetShader=lambda *args: (calls.append(args) or ("ResourceId::99", "")),
        GetShaderEntryPoints=lambda rid: [],
    )
    async def offload(fn, *args, **kwargs):
        return fn(*args, **kwargs)
    async def get_controller(session_id):
        return controller
    monkeypatch.setattr(runtime, "_get_controller", get_controller)
    monkeypatch.setattr(runtime, "_offload", offload)
    monkeypatch.setattr(runtime, "_get_rd", lambda: SimpleNamespace(ShaderEncoding=Encoding, ShaderCompileFlags=lambda: [], ResourceId=lambda: "ResourceId::0"))
    monkeypatch.setattr(runtime, "_rd_stage", lambda stage: stage)
    monkeypatch.setattr(runtime, "_is_null_resource_id", lambda rid: rid in (None, "ResourceId::0"))
    monkeypatch.setattr(runtime, "_session_replace_capability", lambda *args: (True, ""))
    monkeypatch.setattr(runtime._runtime, "replays", {"live": object()})
    monkeypatch.setattr(patch_engine.PatchEngine, "_assemble_spirv_asm", staticmethod(lambda source: MODULE))
    return controller, calls


def compile_shader(**args):
    return json.loads(asyncio.run(runtime._dispatch_shader("compile", dict(session_id="live", stage="ps", source_encoding="spirvasm", **args))))


def test_raw_asm_compiles_as_native_spirv_build_input(compile_env, tmp_path):
    controller, calls = compile_env
    source = tmp_path / "input.spvasm"
    source.write_text(ASM, encoding="utf-8")
    out = tmp_path / "compiled.spv"
    result = compile_shader(source_path=str(source), output_path=str(out))
    assert result["success"] is True
    assert calls[0][1:3] == (Encoding.SPIRV, MODULE)
    assert out.read_bytes() == MODULE
    assert result["source_encoding"] == "spirvasm"
    assert result["build_encoding"] == "spirv"
    assert result["artifact_kind"] == "assembled-spirv-build-input"
    assert result["build_input"]["device_binary_observed"] is False


def test_native_asm_encoding_uses_text_without_local_assembly(compile_env, monkeypatch):
    controller, calls = compile_env
    controller.GetTargetShaderEncodings = lambda: [Encoding.SPIRVAsm]
    def forbidden(source):
        raise AssertionError("native ASM must not use local assembly")
    monkeypatch.setattr(patch_engine.PatchEngine, "_assemble_spirv_asm", staticmethod(forbidden))
    result = compile_shader(source_text=ASM)
    assert result["success"] is True
    assert calls[0][1:3] == (Encoding.SPIRVAsm, ASM.encode())


@pytest.mark.parametrize("mode", ["missing", "unsupported", "assembler"])
def test_prebuild_failures_prove_no_replay_effects(compile_env, monkeypatch, mode):
    controller, calls = compile_env
    args = dict(source_text=ASM)
    if mode == "missing":
        args = dict(source_path="/nonexistent/compile-fixture.spvasm")
    elif mode == "unsupported":
        controller.GetTargetShaderEncodings = lambda: [Encoding.GLSL]
    else:
        def fail(source):
            raise RuntimeError("spirv-as failed: invalid assembly")
        monkeypatch.setattr(patch_engine.PatchEngine, "_assemble_spirv_asm", staticmethod(fail))
    result = compile_shader(**args)
    assert result["success"] is False
    assert not calls
    assert result["details"]["effects_attempted"] is False
    assert result["details"]["context_preserved"] is True


def test_native_build_exception_never_claims_preservation(compile_env):
    controller, calls = compile_env
    def fail(*args):
        raise RuntimeError("native connection lost")
    controller.BuildTargetShader = fail
    with pytest.raises(RuntimeError, match="native connection lost"):
        compile_shader(source_text=ASM)


@pytest.mark.parametrize("operation", ["assemble", "disassemble"])
@pytest.mark.parametrize("outcome", ["success", "error", "timeout"])
def test_spirv_tools_use_scoped_runtime_and_cleanup(monkeypatch, tmp_path, operation, outcome):
    import subprocess
    from pathlib import Path
    root = tmp_path / "owned-runtime"
    monkeypatch.setattr(patch_engine, "cli_runtime_dir", lambda: root)
    monkeypatch.setattr(patch_engine.shutil, "which", lambda name: name)
    paths = []
    def run(argv, **kwargs):
        source = Path(argv[1]); output = Path(argv[argv.index("-o") + 1])
        assert source.parent == root / "patch_engine"
        assert output.parent == source.parent
        paths.extend([source, output])
        output.write_bytes(MODULE if operation == "assemble" else ASM.encode())
        if outcome == "timeout":
            raise subprocess.TimeoutExpired(argv, 20)
        return SimpleNamespace(returncode=0 if outcome == "success" else 1, stderr="invalid fixture", stdout="")
    monkeypatch.setattr(patch_engine.subprocess, "run", run)
    def invoke():
        if operation == "assemble":
            return patch_engine.PatchEngine._assemble_spirv_asm(ASM)
        return patch_engine.PatchEngine._disassemble_raw_spirv_bytes(SimpleNamespace(rawBytes=MODULE))
    if outcome == "timeout" or (operation == "assemble" and outcome == "error"):
        with pytest.raises((RuntimeError, subprocess.TimeoutExpired)):
            invoke()
    else:
        result = invoke()
        assert result == ((MODULE if operation == "assemble" else ASM) if outcome == "success" else "")
    assert len(paths) == 2
    assert all(not path.exists() for path in paths)


def test_native_null_build_does_not_assert_context_preserved(compile_env):
    controller, calls = compile_env
    controller.BuildTargetShader = lambda *args: ("ResourceId::0", "error: invalid shader")
    result = compile_shader(source_text=ASM)
    assert result["success"] is False
    assert result["code"] == "shader_compile_failed"
    assert "context_preserved" not in result["details"]


def test_nonnull_shader_with_fatal_diagnostic_is_released_not_success(compile_env):
    controller, calls = compile_env
    released = []
    controller.BuildTargetShader = lambda *args: ("ResourceId::99", "error: invalid shader")
    controller.FreeTargetResource = released.append
    result = compile_shader(source_text=ASM)
    assert result["success"] is False
    assert result["code"] == "shader_compile_failed"
    assert released == ["ResourceId::99"]
    assert "context_preserved" not in result["details"]
