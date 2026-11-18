from __future__ import annotations

import asyncio
import difflib
import hashlib
from types import SimpleNamespace

import pytest

from rdc_tool.core import patch_engine as patch_engine_mod
from rdc_tool.models import PatchOp, PatchResult, PatchSpec, ShaderStage
from rdc_tool.runtime import artifact_payloads, context_records, dispatch, live_state, remote_records, remote_session, renderdoc_api, replay_access, session_recovery, shader_patches
from rdc_tool.runtime.operations import shader as shader_ops

pytestmark = pytest.mark.usefixtures("fake_renderdoc")


class _FakePipe:
    def GetShader(self, stage: object) -> str:
        if stage == "ps":
            return "ResourceId::77"
        return "ResourceId::0"

    def GetShaderReflection(self, stage: object) -> SimpleNamespace:
        return SimpleNamespace(entryPoint="main")


class _SupportedController:
    def GetPipelineState(self) -> _FakePipe:
        return _FakePipe()

    def BuildTargetShader(self, *args, **kwargs) -> tuple[str, str]:  # type: ignore[no-untyped-def]
        return "ResourceId::99", ""

    def ReplaceResource(self, original: object, replacement: object) -> None:
        return None

    def RemoveReplacement(self, shader_id: object) -> None:
        return None

    def FreeTargetResource(self, shader_id: object) -> None:
        return None


class _EncodingPipe(_FakePipe):
    def __init__(self, encoding: object) -> None:
        self.encoding = encoding

    def GetShaderReflection(self, stage: object) -> SimpleNamespace:
        return SimpleNamespace(entryPoint="main", encoding=self.encoding,
                               debugInfo=SimpleNamespace(files=[], encoding="HLSL"))


class _EncodingController(_SupportedController):
    def __init__(self, encoding: object) -> None:
        self.encoding = encoding

    def GetPipelineState(self) -> _EncodingPipe:
        return _EncodingPipe(self.encoding)


class _UnsupportedController:
    def GetPipelineState(self) -> _FakePipe:
        return _FakePipe()


class _FakePatchEngine:
    def __init__(
        self,
        *,
        success: bool,
        error_code: str = "",
        error_category: str = "",
        error_details: dict[str, object] | None = None,
        messages: list[str] | None = None,
    ) -> None:
        self.success = success
        self.error_code = error_code
        self.error_category = error_category
        self.error_details = dict(error_details or {})
        self.messages = list(messages or [])
        self.calls: list[dict[str, object]] = []

    async def apply_patch(
        self,
        *,
        session_id: str,
        event_id: int,
        stage: object,
        session_manager: object,
        patch_spec: object,
    ) -> PatchResult:
        self.calls.append(
            {
                "session_id": session_id,
                "event_id": int(event_id),
                "stage": stage,
                "session_manager": session_manager,
                "patch_spec": patch_spec,
            }
        )
        if self.success:
            return PatchResult(
                patch_id=str(getattr(patch_spec, "patch_id", "")),
                applied_to_shader_hash="hash_after",
                original_shader_hash="hash_before",
                success=True,
                messages=list(self.messages),
                source_before_text="before",
                source_after_text="after",
                disassembly_target="SPIR-V (RenderDoc)",
                encoding="spirvasm",
                entry_point="main",
                compile_flags=[{"name": "optimization", "value": "0"}],
            )
        return PatchResult(
            patch_id=str(getattr(patch_spec, "patch_id", "")),
            success=False,
            error_message="patch failed",
            error_code=self.error_code,
            error_category=self.error_category,
            error_details=dict(self.error_details),
            messages=list(self.messages),
        )


class _FakeSessionManager:
    def __init__(self) -> None:
        self.state = SimpleNamespace(capabilities=SimpleNamespace(patch_supported=False))

    def get_state(self, session_id: str) -> SimpleNamespace:
        return self.state


@pytest.fixture(autouse=True)
def _reset_shader_replace_runtime() -> None:
    original_patch_engine = live_state._patch_engine
    original_session_manager = live_state._session_manager
    original_replacements = dict(live_state._runtime.shader_replacements)
    try:
        live_state._runtime.shader_replacements.clear()
        yield
    finally:
        live_state._patch_engine = original_patch_engine
        live_state._session_manager = original_session_manager
        live_state._runtime.shader_replacements = original_replacements


def _install_shader_replace_env(monkeypatch: pytest.MonkeyPatch, controller: object) -> None:
    async def _inline_offload(fn, *args, **kwargs):  # type: ignore[no-untyped-def]
        return fn(*args, **kwargs)

    async def _fake_get_controller(session_id: str) -> object:
        return controller

    async def _fake_ensure_event(session_id: str, event_id: int | None) -> int:
        return int(event_id or 101)

    monkeypatch.setattr(renderdoc_api, "_offload", _inline_offload)
    monkeypatch.setattr(replay_access, "_get_controller", _fake_get_controller)
    monkeypatch.setattr(replay_access, "_ensure_event", _fake_ensure_event)
    monkeypatch.setattr(renderdoc_api, "_rd_stage", lambda stage: stage)
    monkeypatch.setattr(renderdoc_api, "_is_null_resource_id", lambda rid: str(rid) in {"", "ResourceId::0", "0"})


def test_edit_and_replace_records_real_applied_replacement(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_engine = _FakePatchEngine(success=True)
    session_manager = _FakeSessionManager()
    _install_shader_replace_env(monkeypatch, _SupportedController())
    live_state._patch_engine = patch_engine
    live_state._session_manager = session_manager

    payload = asyncio.run(
            shader_ops.dispatch(
                "edit_and_replace",
                {
                    "session_id": "sess_demo",
                    "event_id": 101,
                    "stage": "ps",
                    "ops": [
                        {
                            "op": "force_full_precision",
                            "variables": [],
                        }
                    ],
                },
            )
        )

    assert payload.ok is True
    assert payload.data['status'] == "applied"
    assert payload.data['resolved_event_id'] == 101
    assert payload.data['replacement']["status"] == "applied"
    assert payload.data['replacement']["original_shader_id"] == "ResourceId::77"
    assert "mock_applied" not in repr(payload)
    assert len(patch_engine.calls) == 1
    patch_spec = patch_engine.calls[0]["patch_spec"]
    assert getattr(patch_spec, "target_event_id") == 101
    assert str(getattr(patch_spec, "target_shader_id")) == "ResourceId::77"
    assert live_state._runtime.shader_replacements["sess_demo"][0]["status"] == "applied"
    persisted_spec = live_state._runtime.shader_replacements["sess_demo"][0]["patch_spec"]
    assert persisted_spec["patch_id"] == payload.data['replacement_id']
    assert persisted_spec["target_event_id"] == 101
    assert persisted_spec["target_stage"] == "ps"
    assert persisted_spec["target_shader_id"] == "ResourceId::77"
    assert persisted_spec["ops"][0]["op"] == "force_full_precision"
    assert session_manager.state.capabilities.patch_supported is True


def test_edit_and_replace_noop_patch_is_not_recorded_as_active_replacement(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_engine = _FakePatchEngine(
        success=True,
        messages=["Patch operations produced no source changes before recompilation."],
    )
    session_manager = _FakeSessionManager()
    _install_shader_replace_env(monkeypatch, _SupportedController())
    live_state._patch_engine = patch_engine
    live_state._session_manager = session_manager

    async def _noop_apply_patch(**kwargs) -> PatchResult:  # type: ignore[no-untyped-def]
        patch_engine.calls.append(dict(kwargs))
        return PatchResult(
            patch_id=str(getattr(kwargs.get("patch_spec"), "patch_id", "")),
            applied_to_shader_hash="hash_same",
            original_shader_hash="hash_same",
            success=True,
            messages=["Patch operations produced no source changes before recompilation."],
        )

    patch_engine.apply_patch = _noop_apply_patch  # type: ignore[method-assign]

    payload = asyncio.run(
            shader_ops.dispatch(
                "edit_and_replace",
                {
                    "session_id": "sess_demo",
                    "event_id": 101,
                    "stage": "ps",
                    "ops": [
                        {
                            "op": "force_full_precision",
                            "variables": [],
                        }
                    ],
                },
            )
        )

    assert payload.ok is True
    assert payload.data['status'] == "noop"
    assert payload.data['replacement']["status"] == "noop"
    assert live_state._runtime.shader_replacements.get("sess_demo", []) == []


def test_edit_and_replace_can_emit_patch_artifacts(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_engine = _FakePatchEngine(success=True)
    session_manager = _FakeSessionManager()
    _install_shader_replace_env(monkeypatch, _SupportedController())
    live_state._patch_engine = patch_engine
    live_state._session_manager = session_manager

    async def _fake_store_text_artifact_payload(text: str, **kwargs) -> dict[str, object]:
        stem = str(kwargs.get("stem") or "")
        return {
            "title": str(kwargs.get("title") or stem),
            "saved_path": f"H:/fake/{stem}{kwargs.get('suffix')}",
            "type": "saved_path",
        }

    monkeypatch.setattr(
        artifact_payloads,
        "_store_text_artifact_payload",
        _fake_store_text_artifact_payload,
    )

    payload = asyncio.run(
            shader_ops.dispatch(
                "edit_and_replace",
                {
                    "session_id": "sess_demo",
                    "event_id": 101,
                    "stage": "ps",
                    "emit_patch_artifacts": True,
                    "ops": [
                        {
                            "op": "force_full_precision",
                            "variables": [],
                        }
                    ],
                },
            )
        )

    assert payload.ok is True
    assert len(payload.data['replacement']['artifacts']) == 3
    replacement = payload.data['replacement']
    assert replacement["compile"]["encoding"] == "spirvasm"
    assert replacement["compile"]["disassembly_target"] == "SPIR-V (RenderDoc)"
    assert replacement["artifacts"]["source_before"]["saved_path"].endswith("_before.txt")
    assert replacement["artifacts"]["source_after"]["saved_path"].endswith("_after.txt")
    assert replacement["artifacts"]["patch_diff"]["saved_path"].endswith("_diff.diff")


def test_edit_and_replace_accepts_source_text_workflow_inputs(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_engine = _FakePatchEngine(success=True)
    session_manager = _FakeSessionManager()
    _install_shader_replace_env(monkeypatch, _SupportedController())
    live_state._patch_engine = patch_engine
    live_state._session_manager = session_manager

    payload = asyncio.run(
            shader_ops.dispatch(
                "edit_and_replace",
                {
                    "session_id": "sess_demo",
                    "event_id": 101,
                    "stage": "ps",
                    "source_text": "OpCapability Shader\n",
                    "source_target": "SPIR-V ASM",
                    "source_encoding": "spirvasm",
                    "expected_source_hash": "hash_demo",
                },
            )
        )

    assert payload.ok is True
    patch_spec = patch_engine.calls[0]["patch_spec"]
    assert getattr(patch_spec, "source_text") == "OpCapability Shader\n"
    assert getattr(patch_spec, "source_target") == "SPIR-V ASM"
    assert getattr(patch_spec, "source_encoding") == "spirvasm"
    assert getattr(patch_spec, "expected_source_hash") == "hash_demo"
    assert getattr(patch_spec, "ops") == []


def test_edit_and_replace_rejects_multiple_edit_inputs(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_shader_replace_env(monkeypatch, _SupportedController())
    live_state._patch_engine = _FakePatchEngine(success=True)
    live_state._session_manager = _FakeSessionManager()

    payload = asyncio.run(
            shader_ops.dispatch(
                "edit_and_replace",
                {
                    "session_id": "sess_demo",
                    "event_id": 101,
                    "stage": "ps",
                    "ops": [{"op": "force_full_precision", "variables": []}],
                    "source_text": "OpCapability Shader\n",
                },
            )
        )

    assert payload.ok is False
    assert payload.code == "validation_error"


def test_edit_and_replace_rejects_replace_expr_patch_op(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_shader_replace_env(monkeypatch, _SupportedController())
    live_state._patch_engine = _FakePatchEngine(success=True)
    live_state._session_manager = _FakeSessionManager()

    payload = asyncio.run(
            shader_ops.dispatch(
                "edit_and_replace",
                {
                    "session_id": "sess_demo",
                    "event_id": 101,
                    "stage": "ps",
                    "ops": [{"op": "replace_expr", "expr_from": "a", "expr_to": "b"}],
                },
            )
        )

    assert payload.ok is False
    assert payload.code == "validation_error"
    assert payload.details["unsupported_ops"] == ["replace_expr"]
    assert payload.details["agent_text_edit_inputs"] == ["source_text", "diff_text"]


@pytest.mark.parametrize("revert_ok", [True, False])
def test_revert_replacement_preserves_live_remote_replay(monkeypatch: pytest.MonkeyPatch, revert_ok: bool) -> None:
    class Engine:
        async def revert_patch(self, session_id, patch_id, manager):
            return revert_ok

    _install_shader_replace_env(monkeypatch, _SupportedController())
    lifecycle_calls = []
    updates = []
    live_replay = object()
    async def close_session(session_id):
        lifecycle_calls.append(("close", session_id))
    async def recover(context_id, session_id):
        lifecycle_calls.append(("recover", session_id))
    manager = _FakeSessionManager()
    manager.close_session = close_session
    monkeypatch.setattr(live_state, "_patch_engine", Engine())
    monkeypatch.setattr(live_state, "_session_manager", manager)
    monkeypatch.setattr(context_records, "_context_state", lambda *args: {
        "sessions": {"sess_demo": {"backend_type": "remote"}}})
    monkeypatch.setattr(session_recovery, "_recover_single_session_from_state", recover)
    monkeypatch.setattr(remote_session, "_release_remote_session_lease", lambda *args, **kwargs: None)
    monkeypatch.setattr(shader_patches, "_sync_context_session_replacements",
        lambda session_id, remaining: updates.append((session_id, list(remaining))))
    monkeypatch.setitem(live_state._runtime.replays, "sess_demo", live_replay)
    original = {"replacement_id": "repl_demo", "stage": "PS", "resolved_event_id": 314,
        "original_shader_id": "ResourceId::77", "status": "applied"}
    live_state._runtime.shader_replacements["sess_demo"] = [original]
    payload = asyncio.run(shader_ops.dispatch("revert_replacement", {
        "session_id": "sess_demo", "replacement_id": "repl_demo"}))
    assert payload.ok is revert_ok
    assert lifecycle_calls == []
    assert live_state._runtime.replays["sess_demo"] is live_replay
    if revert_ok:
        assert payload.data['reverted'] is True
        assert live_state._runtime.shader_replacements["sess_demo"] == []
        assert updates == [("sess_demo", [])]
    else:
        assert payload.code == "replacement_not_found"
        assert live_state._runtime.shader_replacements["sess_demo"] == [original]
        assert updates == []


def test_catalog_explains_targeted_spirv_precision_patch() -> None:
    from rdc_tool.runtime_catalog import describe_operation, validate_operation_arguments

    tool = describe_operation("rd.shader.edit_and_replace")
    description = tool["input_schema"]["properties"]["ops"]["description"]
    assert "only for the IDs listed in variables" in description
    assert "an empty variables list applies to all RelaxedPrecision decorations" in description
    validate_operation_arguments("rd.shader.edit_and_replace", {
        "session_id": "sess_example", "stage": "ps", "event_id": 1,
        "ops": [{"op": "force_full_precision", "variables": ["7"]}],
    })


def test_edit_and_replace_returns_capability_failure_without_mock_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_engine = _FakePatchEngine(success=True)
    session_manager = _FakeSessionManager()
    _install_shader_replace_env(monkeypatch, _UnsupportedController())
    live_state._patch_engine = patch_engine
    live_state._session_manager = session_manager

    payload = asyncio.run(
            shader_ops.dispatch(
                "edit_and_replace",
                {
                    "session_id": "sess_demo",
                    "event_id": 101,
                    "stage": "ps",
                    "ops": [
                        {
                            "op": "force_full_precision",
                            "variables": [],
                        }
                    ],
                },
            )
        )

    assert payload.ok is False
    assert payload.code == "shader_replace_backend_unsupported"
    assert payload.category == "runtime"
    assert "context_preserved" not in payload.details
    assert payload.details["capability"] == "shader_replace"
    assert "mock_applied" not in repr(payload)
    assert "status" not in payload.details
    assert patch_engine.calls == []
    assert session_manager.state.capabilities.patch_supported is False


def test_edit_and_replace_preserves_patch_engine_error_details(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_engine = _FakePatchEngine(
        success=False,
        error_code="shader_build_failed",
        error_category="runtime",
        error_details={
            "failure_stage": "build",
            "compiler_output": "compile error",
        },
    )
    session_manager = _FakeSessionManager()
    _install_shader_replace_env(monkeypatch, _SupportedController())
    live_state._patch_engine = patch_engine
    live_state._session_manager = session_manager

    payload = asyncio.run(
            shader_ops.dispatch(
                "edit_and_replace",
                {
                    "session_id": "sess_demo",
                    "event_id": 101,
                    "stage": "ps",
                    "ops": [
                        {
                            "op": "force_full_precision",
                            "variables": [],
                        }
                    ],
                },
            )
        )

    assert payload.ok is False
    assert payload.code == "shader_build_failed"
    assert payload.category == "runtime"
    assert payload.details["failure_stage"] == "build"
    assert payload.details["compiler_output"] == "compile error"


@pytest.mark.parametrize("restore_ok", [True, False])
def test_rejected_encoding_restores_entry_event_before_returning(monkeypatch: pytest.MonkeyPatch, restore_ok: bool) -> None:
    _install_shader_replace_env(monkeypatch, _SupportedController())
    monkeypatch.setattr(live_state._runtime, "replays", {
        "sess_demo": live_state.ReplayHandle(session_id="sess_demo", capture_file_id="capture", active_event_id=11),
    })
    monkeypatch.setattr(live_state._runtime, "captures", {
        "capture": live_state.CaptureFileHandle(capture_file_id="capture", file_path="fixture.rdc", read_only=True),
    })
    context_id = live_state._runtime_context_id()
    monkeypatch.setattr(live_state._runtime, "context_states", {context_id: {
        "current_session_id": "sess_demo", "backend": "local", "captures": {},
        "sessions": {"sess_demo": {"active_event_id": 11, "updated_at_ms": 1}},
    }})
    monkeypatch.setattr(live_state._runtime, "context_snapshots", {context_id: {
        "runtime": {"active_event_id": 11}, "updated_at_ms": 1,
    }})
    live_state._patch_engine = _FakePatchEngine(
        success=False, error_code="shader_patch_op_unsupported_for_encoding", error_category="validation",
        error_details={"failure_stage": "validate_edit_plan", "failure_reason": "source_encoding_not_safely_replaceable",
                       "replacement_attempted": False, "context_preserved": True},
    )
    live_state._session_manager = _FakeSessionManager()
    events = []

    async def set_event(session_id: str, event_id: int | None) -> int:
        event = int(event_id or 0)
        events.append(event)
        replay_access._event_effect_attempted()
        if event == 11 and not restore_ok:
            raise RuntimeError("replay connection lost")
        live_state._runtime.replays[session_id].active_event_id = event
        record = live_state._runtime.context_states[context_id]["sessions"][session_id]
        record.update(active_event_id=event, updated_at_ms=record["updated_at_ms"] + 1)
        snapshot = live_state._runtime.context_snapshots[context_id]
        snapshot["runtime"]["active_event_id"] = event
        snapshot["updated_at_ms"] += 1
        return event

    monkeypatch.setattr(replay_access, "_ensure_event", set_event)
    scope = replay_access._event_rejection_snapshot("sess_demo")
    token = live_state._CURRENT_EVENT_REJECTION_SCOPE.set(scope)
    try:
        payload = asyncio.run(shader_ops.dispatch("edit_and_replace", {
            "session_id": "sess_demo", "event_id": 101, "stage": "ps",
            "ops": [{"op": "force_full_precision", "variables": []}],
        }))
        payload = replay_access._qualify_claimed_preservation(payload, scope, "sess_demo")
    finally:
        live_state._CURRENT_EVENT_REJECTION_SCOPE.reset(token)

    assert events == [101, 11]
    assert payload.ok is False
    assert payload.details["replacement_attempted"] is False
    if restore_ok:
        assert payload.code == "shader_patch_op_unsupported_for_encoding"
        assert payload.category == "validation"
        assert payload.details["replay_state_restored"] is True
        assert payload.details["restored_event_id"] == 11
        assert live_state._runtime.replays["sess_demo"].active_event_id == 11
    else:
        assert payload.code == "shader_edit_recovery_failed"
        assert payload.category == "runtime"
        assert payload.details["replay_state_restored"] is False


def test_get_source_reports_ir_fallback_when_debug_source_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_shader_replace_env(monkeypatch, _EncodingController("SPIRV"))
    live_state._session_manager = _FakeSessionManager()

    payload = asyncio.run(
            shader_ops.dispatch(
                "get_source",
                {
                    "session_id": "sess_demo",
                    "event_id": 101,
                    "shader_id": "ResourceId::77",
                },
            )
        )

    assert payload.ok is True
    assert payload.data['source'] is None
    assert payload.data['files'] == []
    assert payload.data['source_available'] is False
    assert payload.data['failure_reason'] == "source_debug_info_unavailable"
    assert payload.data['fallback_tool'] == "rd.shader.get_disassembly"
    assert payload.data['fallback_args']["target"] == "SPIR-V ASM"
    assert payload.data['fallback_args']["source_encoding"] == "spirvasm"
    assert payload.data['fallback_args']["shader_id"] == "ResourceId::77"
    assert payload.data['edit_plan']["input_kind"] == "source_unavailable"
    assert payload.data['edit_plan']["recommended_next_tool"] == "rd.shader.get_disassembly"
    assert payload.data['edit_plan']["can_replace"] is False
    assert payload.data['edit_plan']["allowed_ops"] == []
    assert "target='SPIR-V ASM'" in payload.data['edit_plan']["blocked_reason"]


@pytest.mark.parametrize("restore_fails", [False, True])
def test_get_source_unbound_event_proves_restoration_or_reports_failure(
    monkeypatch: pytest.MonkeyPatch, restore_fails: bool,
) -> None:
    current_event = {"value": 1248}
    transitions: list[int] = []

    class Controller(_SupportedController):
        def GetPipelineState(self) -> SimpleNamespace:
            return SimpleNamespace(
                GetShader=lambda _stage: "ResourceId::0" if current_event["value"] == 3029 else "ResourceId::77",
                GetShaderReflection=lambda _stage: SimpleNamespace(entryPoint="main"),
            )

    _install_shader_replace_env(monkeypatch, Controller())

    async def set_event(_session_id: str, event_id: int | None) -> int:
        requested = int(event_id or 0)
        transitions.append(requested)
        if restore_fails and requested == 1248:
            raise RuntimeError("native restore failed")
        current_event["value"] = requested
        return requested

    monkeypatch.setattr(replay_access, "_ensure_event", set_event)
    monkeypatch.setattr(replay_access, "_active_event", lambda _session_id: current_event["value"])
    monkeypatch.setattr(live_state, "_runtime_context_id", lambda: "owned-context")
    payload = asyncio.run(shader_ops.dispatch(
        "get_source", {"session_id": "sess_demo", "event_id": 3029, "stage": "ps"},
    ))

    assert payload.ok is False
    assert transitions == [3029, 1248]
    assert payload.details["context_id"] == "owned-context"
    assert payload.details["session_id"] == "sess_demo"
    if restore_fails:
        assert payload.code == "shader_inspection_recovery_failed"
        assert payload.details["replay_state_restored"] is False
        assert current_event["value"] == 3029
    else:
        assert payload.code == "shader_binding_lookup_failed"
        assert payload.details["replay_state_restored"] is True
        assert payload.details["restored_event_id"] == 1248
        assert current_event["value"] == 1248


def test_get_source_reports_editable_dxil_fallback_when_debug_source_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_shader_replace_env(monkeypatch, _EncodingController("DXIL"))
    live_state._session_manager = _FakeSessionManager()

    payload = asyncio.run(
            shader_ops.dispatch(
                "get_source",
                {
                    "session_id": "sess_demo",
                    "event_id": 101,
                    "shader_id": "ResourceId::77",
                },
            )
        )

    assert payload.ok is True
    assert payload.data['source_available'] is False
    assert payload.data['fallback_tool'] == "rd.shader.get_disassembly"
    assert payload.data['fallback_args']["target"] == "DXIL ASM"
    assert payload.data['fallback_args']["source_encoding"] == "dxilasm"
    assert payload.data['edit_plan']["shader_format"]["container"] == "dxil"
    assert payload.data['edit_plan']["input_kind"] == "source_unavailable"
    assert payload.data['edit_plan']["can_replace"] is False
    assert payload.data['edit_plan']["allowed_edit_inputs"] == []
    assert "rd.shader.extract_binary" in payload.data['edit_plan']["fallback_tools"]


def test_missing_captured_dxil_source_distinguishes_full_source_replacement(monkeypatch: pytest.MonkeyPatch) -> None:
    class Controller(_EncodingController):
        def GetTargetShaderEncodings(self) -> list[str]:
            return ["DXIL", "HLSL"]

    _install_shader_replace_env(monkeypatch, Controller("DXIL"))
    live_state._session_manager = _FakeSessionManager()
    payload = asyncio.run(shader_ops.dispatch("get_source", {
        "session_id": "sess_demo", "event_id": 101, "shader_id": "ResourceId::77",
    }))

    assert payload.ok is True
    plan = payload.data["edit_plan"]
    assert plan["can_replace"] is False
    replacement = plan["full_source_replacement"]
    assert replacement["available"] is True
    assert replacement["supported_text_encodings"] == ["hlsl"]
    assert replacement["allowed_edit_inputs"] == ["source_text", "source_path"]
    assert "matching semantics" in replacement["note"]


def test_remote_replacement_validation_uses_live_outputs_without_recovery(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Controller:
        def __init__(self) -> None:
            self.set_frame_event_calls: list[tuple[int, bool]] = []

        def SetFrameEvent(self, event_id: int, force: bool) -> None:
            self.set_frame_event_calls.append((event_id, force))

    controller = _Controller()
    previous_replays = dict(live_state._runtime.replays)
    try:
        live_state._runtime.replays["sess_remote"] = live_state.ReplayHandle(
            session_id="sess_remote",
            capture_file_id="capf_remote",
            frame_index=0,
            active_event_id=1248,
        )
        monkeypatch.setattr(
            context_records,
            "_context_state",
            lambda ctx: {
                "sessions": {
                    "sess_remote": {
                        "backend_type": "remote",
                        "remote": {"endpoint": "127.0.0.1:38920", "remote_id": "remote_demo"},
                    }
                }
            },
        )
        monkeypatch.setattr(
            remote_records,
            "_session_record_remote_metadata",
            lambda record: {"endpoint": "127.0.0.1:38920"},
        )

        async def _fake_get_controller(session_id: str) -> object:
            return controller

        async def _fake_output_target_resource_ids(session_id: str, event_id: int) -> list[tuple[str, int]]:
            return [("ResourceId::208592", 0)]

        async def _fail_recovery(*args, **kwargs):  # type: ignore[no-untyped-def]
            raise AssertionError("live replacement validation must not recover/reopen the remote capture")

        async def _inline_offload(fn, *args, **kwargs):  # type: ignore[no-untyped-def]
            return fn(*args, **kwargs)

        monkeypatch.setattr(replay_access, "_get_controller", _fake_get_controller)
        monkeypatch.setattr(replay_access, "_output_target_resource_ids", _fake_output_target_resource_ids)
        monkeypatch.setattr(session_recovery, "_recover_single_session_from_state", _fail_recovery)
        monkeypatch.setattr(renderdoc_api, "_offload", _inline_offload)

        asyncio.run(
            shader_patches._validate_remote_replacement_persistence(
                "sess_remote",
                {
                    "replacement_id": "repl_demo",
                    "resolved_event_id": 1248,
                    "patch_spec": {
                        "target_event_id": 1248,
                        "preserve_outputs": True,
                    },
                },
            )
        )

        assert controller.set_frame_event_calls == [(1248, True)]
    finally:
        live_state._runtime.replays = previous_replays


class _FakeShaderCompileFlag:
    def __init__(self) -> None:
        self.name = ""
        self.value = ""


class _FakeShaderCompileFlags:
    def __init__(self) -> None:
        self.flags: list[_FakeShaderCompileFlag] = []


class _PatchEnginePipe:
    def __init__(self, outputs: list[str] | None = None) -> None:
        self.outputs = list(outputs if outputs is not None else ["ResourceId::208592"])

    def GetShader(self, stage: object) -> str:
        return "ResourceId::77"

    def GetShaderReflection(self, stage: object) -> SimpleNamespace:
        return SimpleNamespace(
            entryPoint="main",
            debugInfo=SimpleNamespace(
                compileFlags=[
                    SimpleNamespace(name="optimization", value="0"),
                    SimpleNamespace(name="target", value="spirv"),
                ]
            ),
        )

    def GetGraphicsPipelineObject(self) -> str:
        return "ResourceId::9001"

    def GetOutputTargets(self) -> list[SimpleNamespace]:
        return [SimpleNamespace(resourceId=rid) for rid in self.outputs]


class _PatchEngineController:
    def __init__(
        self,
        *,
        build_errors: str = "",
        build_shader_id: str = "ResourceId::99",
        replace_error: Exception | None = None,
        output_sequences: list[list[str]] | None = None,
    ) -> None:
        self.build_errors = build_errors
        self.build_shader_id = build_shader_id
        self.replace_error = replace_error
        self.build_calls: list[tuple[object, object, bytes, object, object]] = []
        self.replace_calls: list[tuple[object, object]] = []
        self.set_frame_event_calls: list[tuple[int, bool]] = []
        self.free_calls: list[object] = []
        self.remove_calls: list[object] = []
        self.output_sequences = list(output_sequences or [])

    def SetFrameEvent(self, event_id: int, force: bool) -> None:
        self.set_frame_event_calls.append((event_id, force))
        return None

    def GetPipelineState(self) -> _PatchEnginePipe:
        outputs = self.output_sequences.pop(0) if self.output_sequences else None
        return _PatchEnginePipe(outputs)

    def GetDisassemblyTargets(self, include_unsupported: bool) -> list[str]:
        return ["SPIR-V (RenderDoc)"]

    def GetTargetShaderEncodings(self) -> list[str]:
        return ["SPIRVAsm"]

    def DisassembleShader(self, pipeline: object, refl: object, target: str) -> str:
        return "OpEntryPoint Fragment %main \"main\""

    def BuildTargetShader(self, *args) -> tuple[str, str]:  # type: ignore[no-untyped-def]
        self.build_calls.append(args)
        if self.build_errors:
            return self.build_shader_id, self.build_errors
        return self.build_shader_id, ""

    def ReplaceResource(self, original: object, replacement: object) -> None:
        if self.replace_error is not None:
            raise self.replace_error
        self.replace_calls.append((original, replacement))

    def RemoveReplacement(self, shader_id: object) -> None:
        self.remove_calls.append(shader_id)
        return None

    def FreeTargetResource(self, shader_id: object) -> None:
        self.free_calls.append(shader_id)
        return None


class _PatchEngineSessionManager:
    def __init__(self, controller: _PatchEngineController) -> None:
        self.controller = controller

    def get_controller(self, session_id: str) -> _PatchEngineController:
        return self.controller


def test_list_replacements_filters_stale_metadata_when_patch_engine_has_no_live_patch(monkeypatch: pytest.MonkeyPatch) -> None:
    class _ListingPatchEngine:
        def list_patches(self, session_id: str):  # type: ignore[no-untyped-def]
            return []

    _install_shader_replace_env(monkeypatch, _SupportedController())
    live_state._patch_engine = _ListingPatchEngine()
    live_state._session_manager = _FakeSessionManager()
    live_state._runtime.shader_replacements["sess_demo"] = [
        {
            "replacement_id": "repl_stale",
            "stage": "PS",
            "resolved_event_id": 314,
            "original_shader_id": "ResourceId::77",
            "status": "applied",
        }
    ]

    payload = asyncio.run(shader_ops.dispatch("list_replacements", {"session_id": "sess_demo"}))

    assert payload.ok is True
    assert payload.data['replacements'] == []
    assert live_state._runtime.shader_replacements["sess_demo"] == []


def test_patch_engine_rebinds_target_event_after_success(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_rd = SimpleNamespace(
        ResourceId=lambda: "ResourceId::0",
        ShaderCompileFlags=_FakeShaderCompileFlags,
        ShaderCompileFlag=_FakeShaderCompileFlag,
    )
    monkeypatch.setattr(patch_engine_mod, "_get_rd", lambda: fake_rd)
    monkeypatch.setattr(patch_engine_mod, "_to_rd_stage", lambda stage: "ps")
    monkeypatch.setattr(
        patch_engine_mod.PatchEngine,
        "_get_best_encoding",
        staticmethod(lambda controller, session_id: ("SPIRVAsm", "SPIR-V (RenderDoc)")),
    )

    controller = _PatchEngineController()
    session_manager = _PatchEngineSessionManager(controller)
    engine = patch_engine_mod.PatchEngine()

    result = asyncio.run(
        engine.apply_patch(
            session_id="sess_demo",
            event_id=314,
            stage=ShaderStage.PS,
            session_manager=session_manager,
            patch_spec=PatchSpec(
                patch_id="repl_demo",
                target_event_id=314,
                target_stage=ShaderStage.PS,
                target_shader_id="ResourceId::77",
                source_text='OpEntryPoint Fragment %main_changed "main"',
            ),
        )
    )

    assert result.success is True
    assert controller.set_frame_event_calls == [(314, True), (314, True), (314, True)]


def test_patch_engine_rolls_back_when_replacement_removes_event_outputs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_rd = SimpleNamespace(
        ResourceId=lambda: "ResourceId::0",
        ShaderCompileFlags=_FakeShaderCompileFlags,
        ShaderCompileFlag=_FakeShaderCompileFlag,
    )
    monkeypatch.setattr(patch_engine_mod, "_get_rd", lambda: fake_rd)
    monkeypatch.setattr(patch_engine_mod, "_to_rd_stage", lambda stage: "ps")
    monkeypatch.setattr(
        patch_engine_mod.PatchEngine,
        "_get_best_encoding",
        staticmethod(lambda controller, session_id: ("SPIRVAsm", "SPIR-V (RenderDoc)")),
    )

    controller = _PatchEngineController(
        output_sequences=[
            ["ResourceId::208592"],
            [],
            [],
        ],
    )
    session_manager = _PatchEngineSessionManager(controller)
    engine = patch_engine_mod.PatchEngine()

    result = asyncio.run(
        engine.apply_patch(
            session_id="sess_demo",
            event_id=314,
            stage=ShaderStage.PS,
            session_manager=session_manager,
            patch_spec=PatchSpec(
                patch_id="repl_demo",
                target_event_id=314,
                target_stage=ShaderStage.PS,
                target_shader_id="ResourceId::77",
                source_text='OpEntryPoint Fragment %main_changed "main"',
                preserve_outputs=True,
            ),
        )
    )

    assert result.success is False
    assert result.error_code == "shader_replace_preserve_outputs_failed"
    assert result.error_details["output_targets_before"] == ["ResourceId::208592"]
    assert result.error_details["output_targets_after"] == []
    assert controller.replace_calls == [("ResourceId::77", "ResourceId::99")]
    assert controller.remove_calls == ["ResourceId::77"]
    assert controller.free_calls == ["ResourceId::99"]


def test_patch_engine_build_target_shader_uses_shader_compile_flags(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_rd = SimpleNamespace(
        ResourceId=lambda: "ResourceId::0",
        ShaderCompileFlags=_FakeShaderCompileFlags,
        ShaderCompileFlag=_FakeShaderCompileFlag,
    )
    monkeypatch.setattr(patch_engine_mod, "_get_rd", lambda: fake_rd)
    monkeypatch.setattr(patch_engine_mod, "_to_rd_stage", lambda stage: "ps")
    monkeypatch.setattr(
        patch_engine_mod.PatchEngine,
        "_get_best_encoding",
        staticmethod(lambda controller, session_id: ("SPIRVAsm", "SPIR-V (RenderDoc)")),
    )

    controller = _PatchEngineController()
    session_manager = _PatchEngineSessionManager(controller)
    engine = patch_engine_mod.PatchEngine()

    result = asyncio.run(
        engine.apply_patch(
            session_id="sess_demo",
            event_id=314,
            stage=ShaderStage.PS,
            session_manager=session_manager,
                patch_spec=PatchSpec(
                    patch_id="repl_demo",
                    target_event_id=314,
                    target_stage=ShaderStage.PS,
                    target_shader_id="ResourceId::77",
                    source_text='OpEntryPoint Fragment %main_changed "main"',
                ),
            )
    )

    assert result.success is True
    assert result.messages == ["Applied source_text replacement."]
    assert len(controller.build_calls) == 1
    compile_flags = controller.build_calls[0][3]
    assert isinstance(compile_flags, _FakeShaderCompileFlags)
    assert [(item.name, item.value) for item in compile_flags.flags] == [
        ("optimization", "0"),
        ("target", "spirv"),
    ]
    assert controller.replace_calls == [("ResourceId::77", "ResourceId::99")]


def test_patch_engine_assembles_raw_spirv_asm_when_backend_accepts_binary_spirv(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_rd = SimpleNamespace(
        ResourceId=lambda: "ResourceId::0",
        ShaderCompileFlags=_FakeShaderCompileFlags,
        ShaderCompileFlag=_FakeShaderCompileFlag,
    )
    monkeypatch.setattr(patch_engine_mod, "_get_rd", lambda: fake_rd)
    monkeypatch.setattr(patch_engine_mod, "_to_rd_stage", lambda stage: "ps")
    monkeypatch.setattr(
        patch_engine_mod.PatchEngine,
        "_assemble_spirv_asm",
        staticmethod(lambda source: b"\x03\x02\x23\x07assembled"),
    )

    class _BinarySpirvController(_PatchEngineController):
        def GetDisassemblyTargets(self, include_unsupported: bool) -> list[str]:
            return ["SPIR-V ASM"]

        def GetTargetShaderEncodings(self) -> list[str]:
            return ["SPIRV"]

        def DisassembleShader(self, pipeline: object, refl: object, target: str) -> str:
            return "; SPIR-V\nOpCapability Shader\nOpEntryPoint Fragment %main \"main\"\n"

    controller = _BinarySpirvController()
    session_manager = _PatchEngineSessionManager(controller)
    engine = patch_engine_mod.PatchEngine()

    result = asyncio.run(
        engine.apply_patch(
            session_id="sess_demo",
            event_id=314,
            stage=ShaderStage.PS,
            session_manager=session_manager,
            patch_spec=PatchSpec(
                patch_id="repl_demo",
                target_event_id=314,
                target_stage=ShaderStage.PS,
                target_shader_id="ResourceId::77",
                source_text="; SPIR-V\nOpCapability Shader\nOpEntryPoint Fragment %main_changed \"main\"\n",
                source_target="SPIR-V ASM",
                source_encoding="spirvasm",
            ),
        )
    )

    assert result.success is True
    build_call = controller.build_calls[0]
    assert build_call[1] == "SPIRV"
    assert build_call[2] == b"\x03\x02\x23\x07assembled"


def test_patch_engine_build_compile_flags_supports_renderdoc_flag_container(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_rd = SimpleNamespace(
        ResourceId=lambda: "ResourceId::0",
        ShaderCompileFlags=_FakeShaderCompileFlags,
        ShaderCompileFlag=_FakeShaderCompileFlag,
    )
    monkeypatch.setattr(patch_engine_mod, "_get_rd", lambda: fake_rd)

    refl = SimpleNamespace(
        debugInfo=SimpleNamespace(
            compileFlags=SimpleNamespace(
                flags=[
                    SimpleNamespace(name="optimization", value="0"),
                    SimpleNamespace(name="target", value="spirv"),
                ]
            )
        )
    )

    compile_flags = patch_engine_mod.PatchEngine._build_compile_flags(refl)

    assert [(item.name, item.value) for item in compile_flags.flags] == [
        ("optimization", "0"),
        ("target", "spirv"),
    ]


def test_patch_engine_skips_build_and_replace_when_patch_is_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_rd = SimpleNamespace(
        ResourceId=lambda: "ResourceId::0",
        ShaderCompileFlags=_FakeShaderCompileFlags,
        ShaderCompileFlag=_FakeShaderCompileFlag,
    )
    monkeypatch.setattr(patch_engine_mod, "_get_rd", lambda: fake_rd)
    monkeypatch.setattr(patch_engine_mod, "_to_rd_stage", lambda stage: "ps")
    monkeypatch.setattr(
        patch_engine_mod.PatchEngine,
        "_get_best_encoding",
        staticmethod(lambda controller, session_id: ("SPIRVAsm", "SPIR-V (RenderDoc)")),
    )

    controller = _PatchEngineController()
    session_manager = _PatchEngineSessionManager(controller)
    engine = patch_engine_mod.PatchEngine()

    result = asyncio.run(
        engine.apply_patch(
            session_id="sess_demo",
            event_id=314,
            stage=ShaderStage.PS,
            session_manager=session_manager,
                patch_spec=PatchSpec(
                    patch_id="repl_demo",
                    target_event_id=314,
                    target_stage=ShaderStage.PS,
                    target_shader_id="ResourceId::77",
                    source_text='OpEntryPoint Fragment %main "main"',
                ),
            )
        )

    assert result.success is True
    assert result.applied_to_shader_hash == result.original_shader_hash
    assert controller.build_calls == []
    assert controller.replace_calls == []


def test_patch_engine_supports_source_text_replacement(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_rd = SimpleNamespace(
        ResourceId=lambda: "ResourceId::0",
        ShaderCompileFlags=_FakeShaderCompileFlags,
        ShaderCompileFlag=_FakeShaderCompileFlag,
    )
    monkeypatch.setattr(patch_engine_mod, "_get_rd", lambda: fake_rd)
    monkeypatch.setattr(patch_engine_mod, "_to_rd_stage", lambda stage: "ps")
    monkeypatch.setattr(
        patch_engine_mod.PatchEngine,
        "_get_best_encoding",
        staticmethod(lambda controller, session_id: ("SPIRVAsm", "SPIR-V (RenderDoc)")),
    )

    controller = _PatchEngineController()
    session_manager = _PatchEngineSessionManager(controller)
    engine = patch_engine_mod.PatchEngine()

    result = asyncio.run(
        engine.apply_patch(
            session_id="sess_demo",
            event_id=314,
            stage=ShaderStage.PS,
            session_manager=session_manager,
            patch_spec=PatchSpec(
                patch_id="repl_demo",
                target_event_id=314,
                target_stage=ShaderStage.PS,
                target_shader_id="ResourceId::77",
                source_text="OpCapability Shader\nOpEntryPoint Fragment %main_changed \"main\"\n",
            ),
        )
    )

    assert result.success is True
    assert controller.build_calls
    assert controller.build_calls[0][2] == b"OpCapability Shader\nOpEntryPoint Fragment %main_changed \"main\"\n"


def test_patch_engine_supports_diff_text_replacement(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_rd = SimpleNamespace(
        ResourceId=lambda: "ResourceId::0",
        ShaderCompileFlags=_FakeShaderCompileFlags,
        ShaderCompileFlag=_FakeShaderCompileFlag,
    )
    monkeypatch.setattr(patch_engine_mod, "_get_rd", lambda: fake_rd)
    monkeypatch.setattr(patch_engine_mod, "_to_rd_stage", lambda stage: "ps")
    monkeypatch.setattr(
        patch_engine_mod.PatchEngine,
        "_get_best_encoding",
        staticmethod(lambda controller, session_id: ("SPIRVAsm", "SPIR-V (RenderDoc)")),
    )

    controller = _PatchEngineController()
    session_manager = _PatchEngineSessionManager(controller)
    engine = patch_engine_mod.PatchEngine()
    before = "OpEntryPoint Fragment %main \"main\""
    after = "OpEntryPoint Fragment %main_changed \"main\""
    diff_text = "".join(
        difflib.unified_diff(
            [before + "\n"],
            [after + "\n"],
            fromfile="before",
            tofile="after",
        )
    )

    result = asyncio.run(
        engine.apply_patch(
            session_id="sess_demo",
            event_id=314,
            stage=ShaderStage.PS,
            session_manager=session_manager,
            patch_spec=PatchSpec(
                patch_id="repl_demo",
                target_event_id=314,
                target_stage=ShaderStage.PS,
                target_shader_id="ResourceId::77",
                diff_text=diff_text,
            ),
        )
    )

    assert result.success is True
    assert controller.build_calls[0][2] == (after + "\n").encode("utf-8")


@pytest.mark.parametrize("removed", ['OpEntryPoint Fragment %wrong "main"', ' OpEntryPoint Fragment %main "main"'])
def test_patch_engine_diff_rejection_proves_no_replacement_and_can_retry(
    monkeypatch: pytest.MonkeyPatch, removed: str,
) -> None:
    fake_rd = SimpleNamespace(
        ResourceId=lambda: "ResourceId::0",
        ShaderCompileFlags=_FakeShaderCompileFlags,
        ShaderCompileFlag=_FakeShaderCompileFlag,
    )
    monkeypatch.setattr(patch_engine_mod, "_get_rd", lambda: fake_rd)
    monkeypatch.setattr(patch_engine_mod, "_to_rd_stage", lambda stage: "ps")
    monkeypatch.setattr(
        patch_engine_mod.PatchEngine, "_get_best_encoding",
        staticmethod(lambda controller, session_id: ("SPIRVAsm", "SPIR-V (RenderDoc)")),
    )
    controller = _PatchEngineController()
    engine = patch_engine_mod.PatchEngine()
    manager = _PatchEngineSessionManager(controller)
    after = 'OpEntryPoint Fragment %main_changed "main"'
    def apply(before: str) -> PatchResult:
        diff = "".join(difflib.unified_diff(
            [before + "\n"], [after + "\n"], fromfile="before", tofile="after",
        ))
        return asyncio.run(engine.apply_patch(
            session_id="sess_demo", event_id=314, stage=ShaderStage.PS,
            session_manager=manager, patch_spec=PatchSpec(
                patch_id="repl_demo", target_event_id=314, target_stage=ShaderStage.PS,
                target_shader_id="ResourceId::77", diff_text=diff,
            ),
        ))
    rejected = apply(removed)
    assert rejected.success is False
    assert rejected.error_code == "shader_patch_diff_failed"
    assert rejected.error_category == "validation"
    assert rejected.error_details["failure_stage"] == "apply_patch"
    assert rejected.error_details["replacement_attempted"] is False
    assert rejected.error_details["context_preserved"] is True
    assert "effects_attempted" not in rejected.error_details  # Event navigation already occurred.
    assert controller.build_calls == []
    assert controller.replace_calls == []
    assert engine._patches == {}
    retry = apply('OpEntryPoint Fragment %main "main"')
    assert retry.success is True
    assert controller.build_calls[0][2] == (after + "\n").encode("utf-8")
    assert len(controller.replace_calls) == 1


@pytest.mark.parametrize("hash_kind", ["original", "replacement", "mismatch"])
def test_patch_engine_source_hash_binds_original(monkeypatch: pytest.MonkeyPatch, hash_kind: str) -> None:
    fake_rd = SimpleNamespace(
        ResourceId=lambda: "ResourceId::0",
        ShaderCompileFlags=_FakeShaderCompileFlags,
        ShaderCompileFlag=_FakeShaderCompileFlag,
    )
    monkeypatch.setattr(patch_engine_mod, "_get_rd", lambda: fake_rd)
    monkeypatch.setattr(patch_engine_mod, "_to_rd_stage", lambda stage: "ps")
    monkeypatch.setattr(
        patch_engine_mod.PatchEngine,
        "_get_best_encoding",
        staticmethod(lambda controller, session_id: ("SPIRVAsm", "SPIR-V (RenderDoc)")),
    )

    controller = _PatchEngineController()
    session_manager = _PatchEngineSessionManager(controller)
    engine = patch_engine_mod.PatchEngine()

    result = asyncio.run(
        engine.apply_patch(
            session_id="sess_demo",
            event_id=314,
            stage=ShaderStage.PS,
            session_manager=session_manager,
            patch_spec=PatchSpec(
                patch_id="repl_demo",
                target_event_id=314,
                target_stage=ShaderStage.PS,
                target_shader_id="ResourceId::77",
                source_text="OpCapability Shader\n",
                expected_source_hash=(hashlib.sha256(b'OpEntryPoint Fragment %main "main"').hexdigest()
                                      if hash_kind == "original" else hashlib.sha256(b"OpCapability Shader\n").hexdigest()
                                      if hash_kind == "replacement" else "mismatch"),
            ),
        )
    )

    if hash_kind == "original":
        assert result.success is True
        assert len(controller.build_calls) == 1
        assert controller.replace_calls == [("ResourceId::77", "ResourceId::99")]
        return
    assert result.success is False
    assert result.error_code == "shader_source_mismatch"
    assert result.error_category == "validation"
    assert result.error_details["replacement_attempted"] is False
    assert result.error_details["context_preserved"] is True
    assert controller.build_calls == []
    assert controller.replace_calls == []


@pytest.mark.parametrize("variables, expected", [
    (["7"], "\nOpDecorate %8 RelaxedPrecision\nOpDecorate %7 Location 0\n%7 = OpLoad %2 %3\n"),
    ([], "\n\nOpDecorate %7 Location 0\n%7 = OpLoad %2 %3\n"),
    (["9"], "OpDecorate %7 RelaxedPrecision\nOpDecorate %8 RelaxedPrecision\nOpDecorate %7 Location 0\n%7 = OpLoad %2 %3\n"),
])
def test_precision_patch_selection_preserves_other_instructions(variables, expected) -> None:
    source = "OpDecorate %7 RelaxedPrecision\nOpDecorate %8 RelaxedPrecision\nOpDecorate %7 Location 0\n%7 = OpLoad %2 %3\n"
    assert patch_engine_mod.PatchEngine._apply_precision_patch(source, "spirvasm", variables) == expected


def test_apply_precision_patch_supports_renderdoc_spirv_relaxedprecision_annotations() -> None:
    source = (
        'float3 _213 = CompositeConstruct({_1192, _1192, _1192}) : [[RelaxedPrecision]];\n'
        'float _421 = Dot(_404, _404) : [[RelaxedPrecision]];\n'
    )

    modified = patch_engine_mod.PatchEngine._apply_precision_patch(
        source,
        "spirv",
        ["213", "404"],
    )

    assert "[[RelaxedPrecision]]" not in modified
    assert "float3 _213 = CompositeConstruct({_1192, _1192, _1192});" in modified
    assert "float _421 = Dot(_404, _404);" in modified


def test_apply_precision_patch_removes_spirv_member_relaxedprecision_annotations() -> None:
    source = (
        "OpDecorate %3 RelaxedPrecision\n"
        "OpMemberDecorate %12 22 RelaxedPrecision\n"
        "OpMemberDecorate %12 22 Offset 3732\n"
    )

    modified = patch_engine_mod.PatchEngine._apply_precision_patch(
        source,
        "spirvasm",
        [],
    )

    assert "RelaxedPrecision" not in modified
    assert "OpMemberDecorate %12 22 Offset 3732" in modified


def test_insert_guard_wraps_hlsl_expression() -> None:
    source = "float value = lighting;"

    modified = patch_engine_mod.PatchEngine._apply_guard_patch(
        source,
        "hlsl",
        "lighting",
        "0.0",
    )

    assert modified == "float value = (isnan(lighting) || isinf(lighting) ? 0.0 : lighting);"


def test_insert_guard_wraps_glsl_expression() -> None:
    source = "vec3 color = lighting;"

    modified = patch_engine_mod.PatchEngine._apply_guard_patch(
        source,
        "glsl",
        "lighting",
        "vec3(0.0)",
    )

    assert modified == "vec3 color = (isnan(lighting) || isinf(lighting) ? vec3(0.0) : lighting);"


def test_insert_guard_requires_guard_expr(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_rd = SimpleNamespace(
        ResourceId=lambda: "ResourceId::0",
        ShaderCompileFlags=_FakeShaderCompileFlags,
        ShaderCompileFlag=_FakeShaderCompileFlag,
    )
    monkeypatch.setattr(patch_engine_mod, "_get_rd", lambda: fake_rd)
    monkeypatch.setattr(patch_engine_mod, "_to_rd_stage", lambda stage: "ps")
    monkeypatch.setattr(
        patch_engine_mod.PatchEngine,
        "_get_best_encoding",
        staticmethod(lambda controller, session_id: ("SPIRVAsm", "SPIR-V (RenderDoc)")),
    )

    controller = _PatchEngineController()
    session_manager = _PatchEngineSessionManager(controller)
    engine = patch_engine_mod.PatchEngine()

    result = asyncio.run(
        engine.apply_patch(
            session_id="sess_demo",
            event_id=314,
            stage=ShaderStage.PS,
            session_manager=session_manager,
            patch_spec=PatchSpec(
                patch_id="repl_demo",
                target_event_id=314,
                target_stage=ShaderStage.PS,
                target_shader_id="ResourceId::77",
                ops=[PatchOp(op="insert_guard")],
            ),
        )
    )

    assert result.success is False
    assert result.error_code == "validation_error"
    assert result.error_details["failure_reason"] == "missing_guard_expr"
    assert controller.build_calls == []


def test_insert_guard_rejects_spirv_asm(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_rd = SimpleNamespace(
        ResourceId=lambda: "ResourceId::0",
        ShaderCompileFlags=_FakeShaderCompileFlags,
        ShaderCompileFlag=_FakeShaderCompileFlag,
    )
    monkeypatch.setattr(patch_engine_mod, "_get_rd", lambda: fake_rd)
    monkeypatch.setattr(patch_engine_mod, "_to_rd_stage", lambda stage: "ps")
    monkeypatch.setattr(
        patch_engine_mod.PatchEngine,
        "_get_best_encoding",
        staticmethod(lambda controller, session_id: ("SPIRVAsm", "SPIR-V (RenderDoc)")),
    )

    controller = _PatchEngineController()
    session_manager = _PatchEngineSessionManager(controller)
    engine = patch_engine_mod.PatchEngine()

    result = asyncio.run(
        engine.apply_patch(
            session_id="sess_demo",
            event_id=314,
            stage=ShaderStage.PS,
            session_manager=session_manager,
            patch_spec=PatchSpec(
                patch_id="repl_demo",
                target_event_id=314,
                target_stage=ShaderStage.PS,
                target_shader_id="ResourceId::77",
                ops=[PatchOp(op="insert_guard", guard_expr="lighting")],
            ),
        )
    )

    assert result.success is False
    assert result.error_code == "shader_patch_op_unsupported_for_encoding"
    assert result.error_details["agent_text_edit_inputs"] == ["source_text", "diff_text"]
    assert controller.build_calls == []


def test_collect_spirv_precision_targets_matches_exact_tokens_only() -> None:
    source = (
        "float3 _213 = CompositeConstruct({_1192, _1192, _1192}) : [[RelaxedPrecision]];\n"
        "float _2130 = Dot(_2138, {0.3000, 0.5898, 0.1100}) : [[RelaxedPrecision]];\n"
    )

    matches = patch_engine_mod.PatchEngine._collect_spirv_precision_targets(
        source,
        ["213"],
    )

    assert matches == [
        (
            1,
            "float3 _213 = CompositeConstruct({_1192, _1192, _1192}) : [[RelaxedPrecision]];",
        )
    ]


def test_patch_engine_encoding_name_maps_numeric_spirv_encoding() -> None:
    assert patch_engine_mod.PatchEngine._encoding_name(3) == "spirv"
    assert patch_engine_mod.PatchEngine._encoding_name(4) == "spirvasm"


def test_patch_engine_reports_structured_build_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_rd = SimpleNamespace(
        ResourceId=lambda: "ResourceId::0",
        ShaderCompileFlags=_FakeShaderCompileFlags,
        ShaderCompileFlag=_FakeShaderCompileFlag,
    )
    monkeypatch.setattr(patch_engine_mod, "_get_rd", lambda: fake_rd)
    monkeypatch.setattr(patch_engine_mod, "_to_rd_stage", lambda stage: "ps")
    monkeypatch.setattr(
        patch_engine_mod.PatchEngine,
        "_get_best_encoding",
        staticmethod(lambda controller, session_id: ("SPIRVAsm", "SPIR-V (RenderDoc)")),
    )

    controller = _PatchEngineController(build_errors="compile error")
    session_manager = _PatchEngineSessionManager(controller)
    engine = patch_engine_mod.PatchEngine()

    result = asyncio.run(
        engine.apply_patch(
            session_id="sess_demo",
            event_id=314,
            stage=ShaderStage.PS,
            session_manager=session_manager,
            patch_spec=PatchSpec(
                patch_id="repl_demo",
                target_event_id=314,
                target_stage=ShaderStage.PS,
                target_shader_id="ResourceId::77",
                source_text='OpEntryPoint Fragment %main_changed "main"',
            ),
        )
    )

    assert result.success is False
    assert result.error_code == "shader_build_failed"
    assert result.error_category == "runtime"
    assert result.error_details["compiler_output"] == "compile error"
    assert result.error_details["compile_flags"] == [
        {"name": "optimization", "value": "0"},
        {"name": "target", "value": "spirv"},
    ]


def test_patch_engine_does_not_replace_when_compiler_reports_fatal_diagnostics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_rd = SimpleNamespace(
        ResourceId=lambda: "ResourceId::0",
        ShaderCompileFlags=_FakeShaderCompileFlags,
        ShaderCompileFlag=_FakeShaderCompileFlag,
    )
    monkeypatch.setattr(patch_engine_mod, "_get_rd", lambda: fake_rd)
    monkeypatch.setattr(patch_engine_mod, "_to_rd_stage", lambda stage: "ps")
    monkeypatch.setattr(
        patch_engine_mod.PatchEngine,
        "_get_best_encoding",
        staticmethod(lambda controller, session_id: ("SPIRVAsm", "SPIR-V (RenderDoc)")),
    )

    controller = _PatchEngineController(
        build_errors="error: invalid SPIR-V after source edit",
        build_shader_id="ResourceId::99",
    )
    session_manager = _PatchEngineSessionManager(controller)
    engine = patch_engine_mod.PatchEngine()

    result = asyncio.run(
        engine.apply_patch(
            session_id="sess_demo",
            event_id=314,
            stage=ShaderStage.PS,
            session_manager=session_manager,
            patch_spec=PatchSpec(
                patch_id="repl_demo",
                target_event_id=314,
                target_stage=ShaderStage.PS,
                target_shader_id="ResourceId::77",
                source_text='OpEntryPoint Fragment %main_changed "main"',
            ),
        )
    )

    assert result.success is False
    assert result.error_code == "shader_build_failed"
    assert result.error_details["replacement_attempted"] is False
    assert result.error_details["cleanup_attempted"] is True
    assert controller.replace_calls == []
    assert controller.free_calls == ["ResourceId::99"]


def test_patch_engine_rejects_dxil_disassembly_before_build_or_replace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_rd = SimpleNamespace(
        ResourceId=lambda: "ResourceId::0",
        ShaderCompileFlags=_FakeShaderCompileFlags,
        ShaderCompileFlag=_FakeShaderCompileFlag,
    )
    monkeypatch.setattr(patch_engine_mod, "_get_rd", lambda: fake_rd)
    monkeypatch.setattr(patch_engine_mod, "_to_rd_stage", lambda stage: "ps")
    monkeypatch.setattr(
        patch_engine_mod.PatchEngine,
        "_get_best_encoding",
        staticmethod(lambda controller, session_id: ("DXIL", "DXIL")),
    )

    controller = _PatchEngineController()
    session_manager = _PatchEngineSessionManager(controller)
    engine = patch_engine_mod.PatchEngine()

    result = asyncio.run(
        engine.apply_patch(
            session_id="sess_demo",
            event_id=314,
            stage=ShaderStage.PS,
            session_manager=session_manager,
            patch_spec=PatchSpec(
                patch_id="repl_demo",
                target_event_id=314,
                target_stage=ShaderStage.PS,
                target_shader_id="ResourceId::77",
                source_text="// edited DXIL disassembly",
            ),
        )
    )

    assert result.success is False
    assert result.error_code == "shader_replace_backend_unsupported"
    assert result.error_details["failure_stage"] == "validate_edit_plan"
    assert result.error_details["replacement_attempted"] is False
    assert result.error_details["edit_plan"]["shader_format"]["container"] == "dxil"
    assert controller.build_calls == []
    assert controller.replace_calls == []


def test_revert_patch_rebinds_target_event(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_rd = SimpleNamespace(
        ResourceId=lambda: "ResourceId::0",
        ShaderCompileFlags=_FakeShaderCompileFlags,
        ShaderCompileFlag=_FakeShaderCompileFlag,
    )
    monkeypatch.setattr(patch_engine_mod, "_get_rd", lambda: fake_rd)
    monkeypatch.setattr(patch_engine_mod, "_to_rd_stage", lambda stage: "ps")
    monkeypatch.setattr(
        patch_engine_mod.PatchEngine,
        "_get_best_encoding",
        staticmethod(lambda controller, session_id: ("SPIRVAsm", "SPIR-V (RenderDoc)")),
    )

    controller = _PatchEngineController()
    session_manager = _PatchEngineSessionManager(controller)
    engine = patch_engine_mod.PatchEngine()

    result = asyncio.run(
        engine.apply_patch(
            session_id="sess_demo",
            event_id=314,
            stage=ShaderStage.PS,
            session_manager=session_manager,
            patch_spec=PatchSpec(
                patch_id="repl_demo",
                target_event_id=314,
                target_stage=ShaderStage.PS,
                target_shader_id="ResourceId::77",
                source_text='OpEntryPoint Fragment %main_changed "main"',
            ),
        )
    )

    assert result.success is True
    assert asyncio.run(engine.revert_patch("sess_demo", "repl_demo", session_manager)) is True
    assert controller.set_frame_event_calls[-1] == (314, True)


def test_get_disassembly_rejects_unknown_target_before_replay_effects(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(live_state._runtime, "replays", {
        "sess_demo": live_state.ReplayHandle(session_id="sess_demo", capture_file_id="capture", active_event_id=101),
    })
    monkeypatch.setattr(live_state._runtime, "captures", {
        "capture": live_state.CaptureFileHandle(capture_file_id="capture", file_path="fixture.rdc", read_only=True),
    })
    class _TargetsController(_SupportedController):
        def GetDisassemblyTargets(self, include_custom: bool) -> list[str]:
            assert include_custom is True
            return ["SPIR-V ASM", "GLSL"]

    _install_shader_replace_env(monkeypatch, _TargetsController())

    async def _unexpected_ensure_event(session_id: str, event_id: int | None) -> int:
        raise AssertionError("validation must not set a replay event")

    monkeypatch.setattr(replay_access, "_ensure_event", _unexpected_ensure_event)
    payload = asyncio.run(shader_ops.dispatch(
        "get_disassembly", {"session_id": "sess_demo", "event_id": 101, "stage": "ps", "target": "unknown"},
    ))

    assert payload.ok is False
    assert payload.code == "shader_disassembly_unavailable"
    assert payload.category == "validation"
    assert payload.details["effects_attempted"] is False
    assert payload.details["context_preserved"] is True
    assert payload.details["available_targets"] == ["SPIR-V ASM", "GLSL"]


@pytest.mark.parametrize("action", ["get_source", "get_disassembly", "compile", "edit_and_replace"])
def test_shader_operations_reject_noncanonical_stage_before_replay_effects(
    monkeypatch: pytest.MonkeyPatch, action: str,
) -> None:
    monkeypatch.setattr(live_state._runtime, "replays", {
        "sess_demo": live_state.ReplayHandle(session_id="sess_demo", capture_file_id="capture", active_event_id=101),
    })
    monkeypatch.setattr(live_state._runtime, "captures", {
        "capture": live_state.CaptureFileHandle(capture_file_id="capture", file_path="fixture.rdc", read_only=True),
    })
    async def _unexpected_get_controller(session_id: str) -> object:
        raise AssertionError("stage validation must precede controller access")

    async def _unexpected_ensure_event(session_id: str, event_id: int | None) -> int:
        raise AssertionError("stage validation must not set a replay event")

    monkeypatch.setattr(replay_access, "_get_controller", _unexpected_get_controller)
    monkeypatch.setattr(replay_access, "_ensure_event", _unexpected_ensure_event)
    payload = asyncio.run(shader_ops.dispatch(
        action, {"session_id": "sess_demo", "event_id": 101, "stage": "pixel"},
    ))

    assert payload.ok is False
    assert payload.code == "invalid_shader_stage"
    assert payload.category == "validation"
    assert payload.details["requested_stage"] == "pixel"
    assert payload.details["allowed_stages"] == ["vs", "hs", "ds", "gs", "ps", "cs", "ms", "as"]
    assert payload.details["effects_attempted"] is False
    assert payload.details["context_preserved"] is True


def test_get_disassembly_reports_raw_spirv_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_shader_replace_env(monkeypatch, _SupportedController())
    live_state._session_manager = _FakeSessionManager()

    monkeypatch.setattr(
        patch_engine_mod.PatchEngine,
        "_resolve_source",
        classmethod(lambda cls, controller, pipe, refl, stage, session_id, **kwargs: ("OpCapability Shader\n", "SPIRVAsm", "SPIR-V ASM", True)),
    )

    payload = asyncio.run(
            shader_ops.dispatch(
                "get_disassembly",
                {
                    "session_id": "sess_demo",
                    "event_id": 101,
                    "stage": "ps",
                    "target": "SPIR-V ASM",
                },
            )
        )

    assert payload.ok is True
    assert payload.data['target'] == "SPIR-V ASM"
    assert payload.data['source_encoding'] == "spirvasm"
    assert payload.data['is_raw_spirv_asm'] is True
    assert payload.data['source_hash']
    assert payload.data['edit_plan']["input_kind"] == "text_ir"
    assert payload.data['edit_plan']["can_replace"] is True
    assert payload.data['edit_plan']["allowed_ops"] == ["force_full_precision"]


def test_renderdoc_spirv_view_points_to_raw_asm_without_claiming_editability() -> None:
    plan = patch_engine_mod.PatchEngine._edit_plan_for_source(
        encoding_name="SPIRV", disassembly_target="SPIR-V (RenderDoc)", source="SPIR-V 1.0 module",
    )
    assert plan["can_replace"] is False
    assert plan["recommended_next_tool"] == "rd.shader.get_disassembly"
    assert "target='SPIR-V ASM'" in plan["blocked_reason"]


def test_get_disassembly_reports_dxil_readonly_edit_plan(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_shader_replace_env(monkeypatch, _EncodingController("DXIL"))
    live_state._session_manager = _FakeSessionManager()

    monkeypatch.setattr(
        patch_engine_mod.PatchEngine,
        "_resolve_source",
        classmethod(lambda cls, controller, pipe, refl, stage, session_id, **kwargs: ("// DXIL disassembly\n", "DXIL", "DXIL", False)),
    )

    payload = asyncio.run(
            shader_ops.dispatch(
                "get_disassembly",
                {
                    "session_id": "sess_demo",
                    "event_id": 101,
                    "stage": "ps",
                    "target": "auto",
                },
            )
        )

    assert payload.ok is True
    assert payload.data['target'] == "DXIL"
    assert payload.data['source_encoding'] == "dxil"
    assert payload.data['edit_plan']["shader_format"]["container"] == "dxil"
    assert payload.data['edit_plan']["input_kind"] == "renderdoc_disassembly"
    assert payload.data['edit_plan']["can_edit_text"] is False
    assert payload.data['edit_plan']["can_replace"] is False
    assert payload.data['edit_plan']["recommended_next_tool"] == "rd.shader.extract_binary"


def test_patch_engine_hlsl_full_replacement_builds_and_replaces_without_editing_dxil(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_rd = SimpleNamespace(
        ResourceId=lambda: "ResourceId::0",
        ShaderCompileFlags=_FakeShaderCompileFlags,
        ShaderCompileFlag=_FakeShaderCompileFlag,
    )
    monkeypatch.setattr(patch_engine_mod, "_get_rd", lambda: fake_rd)
    monkeypatch.setattr(patch_engine_mod, "_to_rd_stage", lambda stage: "ps")

    class _HlslController(_PatchEngineController):
        def GetTargetShaderEncodings(self) -> list[str]:
            return ["HLSL"]

    controller = _HlslController()
    session_manager = _PatchEngineSessionManager(controller)
    engine = patch_engine_mod.PatchEngine()

    result = asyncio.run(
        engine.apply_patch(
            session_id="sess_demo",
            event_id=314,
            stage=ShaderStage.PS,
            session_manager=session_manager,
            patch_spec=PatchSpec(
                patch_id="repl_hlsl",
                target_event_id=314,
                target_stage=ShaderStage.PS,
                target_shader_id="ResourceId::77",
                source_text="float4 main() : SV_Target { return 1; }",
                source_encoding="hlsl",
                entry="main",
                target="ps_6_6",
            ),
        )
    )

    assert result.success is True
    assert result.error_code == ""
    assert controller.build_calls
    assert controller.replace_calls == [("ResourceId::77", "ResourceId::99")]
    build_args = controller.build_calls[0]
    assert build_args[0] == "main"
    assert build_args[1] == "HLSL"
    assert b"float4 main" in build_args[2]
    assert result.messages[0] == "Applied full source replacement input."
    assert result.original_shader_hash == ""
    assert result.source_before_text == ""
    assert result.applied_to_shader_hash == hashlib.sha256(build_args[2]).hexdigest()
    assert result.edit_plan["input_kind"] == "user_full_source"
    assert result.edit_plan["can_build"] is True
    assert result.edit_plan["can_replace"] is True
    assert any("original_shader_hash is unknown" in message for message in result.messages)


@pytest.mark.parametrize("entry_source, expected_hash, accepted", [
    ("float4 main() : SV_Target { return 0; }", "", True),
    ("float4 main() : SV_Target { return 0; }", "original", True),
    ("float4 main() : SV_Target { return 0; }", "replacement", False),
    ("float4 main() : SV_Target { return 0; }", "mismatch", False),
    ("", "", True),
    ("", "original", False),
    (None, "", True),
    (None, "original", False),
])
def test_catalog_full_source_replacement_keeps_source_provenance_and_runtime_plan(
    monkeypatch: pytest.MonkeyPatch, entry_source: str | None, expected_hash: str, accepted: bool,
) -> None:

    original_source = "float4 main() : SV_Target { return 0; }"
    replacement_source = "float4 main() : SV_Target { return 1; }"
    original_hash = hashlib.sha256(original_source.encode()).hexdigest()
    replacement_hash = hashlib.sha256(replacement_source.encode()).hexdigest()
    include_source = "not the entry shader source"
    fake_rd = SimpleNamespace(ResourceId=lambda: "ResourceId::0",
                              ShaderCompileFlags=_FakeShaderCompileFlags, ShaderCompileFlag=_FakeShaderCompileFlag)
    monkeypatch.setattr(patch_engine_mod, "_get_rd", lambda: fake_rd)
    monkeypatch.setattr(patch_engine_mod, "_to_rd_stage", lambda stage: "ps")

    class Pipe(_PatchEnginePipe):
        def GetShader(self, stage: object) -> str:
            return "ResourceId::77" if stage == "ps" else "ResourceId::0"

        def GetShaderReflection(self, stage: object) -> SimpleNamespace:
            refl = super().GetShaderReflection(stage)
            if entry_source is not None:
                refl.debugInfo.files = [SimpleNamespace(filename="entry.hlsl", contents=entry_source),
                                        SimpleNamespace(filename="include.hlsl", contents=include_source)]
            return refl

    class Controller(_PatchEngineController):
        def GetTargetShaderEncodings(self) -> list[str]:
            return ["HLSL"]

        def GetPipelineState(self) -> Pipe:
            return Pipe()

        def DisassembleShader(self, *args):
            pytest.fail("Full-source original provenance must not be guessed from disassembly")

    controller = Controller()
    engine = patch_engine_mod.PatchEngine()
    _install_shader_replace_env(monkeypatch, controller)
    live_state._patch_engine = engine
    live_state._session_manager = _PatchEngineSessionManager(controller)
    args = {"session_id": "sess_demo", "event_id": 314, "stage": "ps", "shader_id": "ResourceId::77",
            "source_text": replacement_source, "source_encoding": "hlsl", "entry": "main", "target": "ps_6_6"}
    if expected_hash:
        args["expected_source_hash"] = {"original": original_hash, "replacement": replacement_hash,
                                        "mismatch": "f" * 64}[expected_hash]
    result = asyncio.run(dispatch._execute("rd.shader.edit_and_replace", args, live_state.ExecutionContext()))
    assert result["ok"] is accepted
    if not accepted:
        assert result["error"]["code"] == "shader_source_mismatch"
        details = result["error"]["details"]
        assert details["actual_source_hash"] == (original_hash if entry_source else "")
        assert details["failure_reason"] == ("source_hash_mismatch" if entry_source else "source_hash_unavailable")
        assert details["replacement_attempted"] is False
        assert controller.build_calls == controller.replace_calls == []
        assert engine.list_patches("sess_demo") == []
        return
    data = result["data"]
    assert data["status"] == "applied"
    replacement = data["replacement"]
    assert replacement["original_shader_hash"] == (original_hash if entry_source else "")
    assert replacement["applied_to_shader_hash"] == replacement_hash
    assert replacement["original_shader_hash"] != hashlib.sha256(include_source.encode()).hexdigest()
    assert replacement["compile"]["build_input"]["sha256"] == replacement_hash
    assert replacement["compile"]["build_input"]["target_shader_id"] == "ResourceId::99"
    assert data["edit_plan"] == replacement["edit_plan"]
    assert data["edit_plan"]["input_kind"] == "user_full_source"
    assert data["edit_plan"]["can_build"] is data["edit_plan"]["can_replace"] is True
    assert data["edit_plan"]["runtime_full_replace_supported"] is True
    assert live_state._runtime.shader_replacements["sess_demo"][0]["edit_plan"] == data["edit_plan"]
    assert controller.build_calls[0][2] == replacement_source.encode()
    restored = asyncio.run(dispatch._execute("rd.shader.revert_replacement", {
        "session_id": "sess_demo", "event_id": 314, "replacement_id": data["replacement_id"]}, live_state.ExecutionContext()))
    assert restored["ok"] is True
    assert restored["data"]["reverted"] is True
    assert controller.remove_calls == ["ResourceId::77"]
    assert controller.free_calls == ["ResourceId::99"]


def test_patch_engine_hlsl_compile_failure_does_not_replace(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_rd = SimpleNamespace(
        ResourceId=lambda: "ResourceId::0",
        ShaderCompileFlags=_FakeShaderCompileFlags,
        ShaderCompileFlag=_FakeShaderCompileFlag,
    )
    monkeypatch.setattr(patch_engine_mod, "_get_rd", lambda: fake_rd)
    monkeypatch.setattr(patch_engine_mod, "_to_rd_stage", lambda stage: "ps")

    class _HlslController(_PatchEngineController):
        def GetTargetShaderEncodings(self) -> list[str]:
            return ["HLSL"]

    controller = _HlslController(build_errors="syntax error", build_shader_id="ResourceId::99")
    session_manager = _PatchEngineSessionManager(controller)
    engine = patch_engine_mod.PatchEngine()

    result = asyncio.run(
        engine.apply_patch(
            session_id="sess_demo",
            event_id=314,
            stage=ShaderStage.PS,
            session_manager=session_manager,
            patch_spec=PatchSpec(
                patch_id="repl_hlsl",
                target_event_id=314,
                target_stage=ShaderStage.PS,
                target_shader_id="ResourceId::77",
                source_text="float4 main() : SV_Target { return ; }",
                source_encoding="hlsl",
                entry="main",
                target="ps_6_6",
            ),
        )
    )

    assert result.success is False
    assert result.error_code == "shader_build_failed"
    assert result.error_details["replacement_attempted"] is False
    assert result.error_details["cleanup_attempted"] is True
    assert controller.replace_calls == []
    assert controller.free_calls == ["ResourceId::99"]


@pytest.mark.parametrize("mode", ["complete", "empty", "error", "missing"])
def test_disassembly_success_discovers_native_targets_truthfully(monkeypatch, mode) -> None:
    class Controller(_SupportedController):
        def GetDisassemblyTargets(self, with_pipeline):
            assert with_pipeline is True
            if mode == "error":
                raise RuntimeError("native target query failed")
            return [] if mode == "empty" else ["SPIR-V (RenderDoc)", "GPU ISA"]
    controller = Controller()
    if mode == "missing":
        controller.GetDisassemblyTargets = None
    _install_shader_replace_env(monkeypatch, controller)
    live_state._session_manager = _FakeSessionManager()
    monkeypatch.setattr(patch_engine_mod.PatchEngine, "_resolve_source", classmethod(
        lambda cls, *args, **kwargs: ("OpCapability Shader\n", "SPIRVAsm", "SPIR-V ASM", True)))
    payload = asyncio.run(shader_ops.dispatch("get_disassembly", {
        "session_id": "sess_demo", "event_id": 101, "stage": "ps", "target": "SPIR-V ASM",
    }))
    assert payload.ok is True
    assert payload.data['available_targets_status'] == ({"error": "unavailable", "missing": "unsupported"}.get(mode, "complete"))
    assert payload.data['available_targets'] == (["SPIR-V (RenderDoc)", "GPU ISA"] if mode == "complete" else [])
    assert payload.data['available_targets_error'] == ("native target query failed" if mode == "error" else None)
    assert payload.data['target'] == "SPIR-V ASM"
    assert payload.data['is_raw_spirv_asm'] is True


@pytest.mark.parametrize("mode", ["error", "missing"])
def test_disassembly_target_probe_failure_precedes_event_effects(monkeypatch, mode) -> None:
    monkeypatch.setattr(live_state._runtime, "replays", {
        "sess_demo": live_state.ReplayHandle(session_id="sess_demo", capture_file_id="capture", active_event_id=101),
    })
    monkeypatch.setattr(live_state._runtime, "captures", {
        "capture": live_state.CaptureFileHandle(capture_file_id="capture", file_path="fixture.rdc", read_only=True),
    })
    class Controller(_SupportedController):
        def GetDisassemblyTargets(self, with_pipeline):
            raise RuntimeError("target query failed")
    controller = Controller()
    if mode == "missing":
        controller.GetDisassemblyTargets = None
    _install_shader_replace_env(monkeypatch, controller)
    async def unexpected(*args):
        raise AssertionError("target query failure must not set event")
    monkeypatch.setattr(replay_access, "_ensure_event", unexpected)
    result = asyncio.run(shader_ops.dispatch("get_disassembly", {
        "session_id": "sess_demo", "event_id": 101, "stage": "ps", "target": "GPU ISA",
    }))
    assert result.ok is False
    assert result.details["failure_reason"] == "target_discovery_failed"
    if mode == "error":
        assert result.category == "runtime"
        assert "effects_attempted" not in result.details
        assert "context_preserved" not in result.details
    else:
        assert result.category == "validation"
        assert result.details["effects_attempted"] is False
        assert result.details["context_preserved"] is True
    assert result.details["available_targets_status"] == ("unavailable" if mode == "error" else "unsupported")


@pytest.mark.parametrize("text", [
    "; SPIR-V disassembly not supported; external tool missing",
    "; SPIR-V\n; OpCapability Shader\n; OpDecorate %1 RelaxedPrecision",
    "diagnostic mentioning OpCapability without an instruction",
    "; SPIR-V\n",
])
def test_spirv_diagnostic_or_comment_is_not_raw_assembly(text) -> None:
    assert patch_engine_mod.PatchEngine._looks_like_raw_spirv_asm(text) is False
    for encoding in ("SPIRV", "SPIRVAsm"):
        plan = patch_engine_mod.PatchEngine._edit_plan_for_source(
            encoding_name=encoding, disassembly_target="external ISA", source=text,
        )
        assert plan["can_build"] is False
        assert plan["can_replace"] is False
        assert plan["allowed_edit_inputs"] == []


@pytest.mark.parametrize("text", ["; SPIR-V\nOpCapability Shader", "%name = OpTypeFloat 32", "  OpEntryPoint Fragment %main \"main\""])
def test_spirv_actual_opcode_lines_are_recognized(text) -> None:
    assert patch_engine_mod.PatchEngine._looks_like_raw_spirv_asm(text) is True
    plan = patch_engine_mod.PatchEngine._edit_plan_for_source(
        encoding_name="SPIRVAsm", disassembly_target="SPIR-V ASM", source=text,
    )
    assert plan["can_replace"] is True


def test_disassembly_diagnostic_is_observed_text_without_raw_edit_authority(monkeypatch) -> None:
    diagnostic = "; SPIR-V disassembly not supported, external compiler unavailable"
    class Controller(_PatchEngineController):
        def GetDisassemblyTargets(self, with_pipeline):
            return ["external ISA"]
        def DisassembleShader(self, *args):
            return diagnostic
    monkeypatch.setattr(patch_engine_mod, "_get_rd", lambda: SimpleNamespace(ResourceId=lambda: "ResourceId::0"))
    monkeypatch.setattr(patch_engine_mod.PatchEngine, "_get_best_encoding", staticmethod(lambda *_: ("SPIRV", "external ISA")))
    _install_shader_replace_env(monkeypatch, Controller())
    live_state._session_manager = _FakeSessionManager()
    result = asyncio.run(shader_ops.dispatch("get_disassembly", {
        "session_id": "sess_demo", "event_id": 101, "stage": "ps", "target": "external ISA",
    }))
    assert result.ok is True  # Native text is preserved, not asserted to be executable ISA.
    assert result.data['disassembly'] == diagnostic
    assert result.data['is_raw_spirv_asm'] is False
    assert result.data['edit_plan']["can_replace"] is False
    assert result.data['edit_plan']["can_build"] is False


def test_explicit_raw_target_requires_actual_instructions_before_build(monkeypatch) -> None:
    class Controller(_PatchEngineController):
        def GetDisassemblyTargets(self, with_pipeline):
            return ["SPIR-V ASM"]
        def DisassembleShader(self, *args):
            return "; SPIR-V raw target unavailable"
    monkeypatch.setattr(patch_engine_mod, "_get_rd", lambda: SimpleNamespace(ResourceId=lambda: "ResourceId::0"))
    monkeypatch.setattr(patch_engine_mod.PatchEngine, "_disassemble_raw_spirv_bytes", staticmethod(lambda _: "; SPIR-V fallback unavailable"))
    with pytest.raises(RuntimeError, match="Raw SPIR-V ASM disassembly is unavailable"):
        patch_engine_mod.PatchEngine._resolve_source(
            Controller(), _PatchEnginePipe(), SimpleNamespace(), ShaderStage.PS, "sess_demo", requested_target="SPIR-V ASM",
        )


@pytest.mark.parametrize("action", ["apply", "revert"])
def test_patch_engine_native_thread_affinity(monkeypatch: pytest.MonkeyPatch, action: str) -> None:
    import threading
    from concurrent.futures import ThreadPoolExecutor

    fake_rd = SimpleNamespace(ResourceId=lambda: "ResourceId::0",
        ShaderCompileFlags=_FakeShaderCompileFlags, ShaderCompileFlag=_FakeShaderCompileFlag)
    monkeypatch.setattr(patch_engine_mod, "_get_rd", lambda: fake_rd)
    monkeypatch.setattr(patch_engine_mod, "_to_rd_stage", lambda stage: "ps")

    class Controller(_PatchEngineController):
        def __init__(self) -> None:
            super().__init__()
            self.native_thread = threading.get_ident()

        def GetTargetShaderEncodings(self) -> list[str]:
            return ["HLSL"]

        def __getattribute__(self, name: str):
            value = super().__getattribute__(name)
            if name[:1].isupper() and callable(value):
                def checked(*args, **kwargs):
                    assert threading.get_ident() == self.native_thread, "native controller accessed outside replay thread"
                    return value(*args, **kwargs)
                return checked
            return value

    async def scenario() -> None:
        loop = asyncio.get_running_loop()
        loop.set_default_executor(ThreadPoolExecutor(max_workers=1, thread_name_prefix="test-replay"))
        controller = await loop.run_in_executor(None, Controller)
        manager = _PatchEngineSessionManager(controller)
        engine = patch_engine_mod.PatchEngine()
        spec = PatchSpec(patch_id="thread-bound", target_event_id=314,
            target_stage=ShaderStage.PS, target_shader_id="ResourceId::77",
            source_text="float4 main() : SV_Target { return 1; }",
            source_encoding="hlsl", entry="main", target="ps_6_6")
        if action == "apply":
            result = await engine.apply_patch("sess_demo", 314, ShaderStage.PS, manager, spec)
            assert result.success, result.error_message
            assert controller.replace_calls == [("ResourceId::77", "ResourceId::99")]
            assert [item.patch_id for item in engine.list_patches("sess_demo")] == ["thread-bound"]
        else:
            engine._patches[spec.patch_id] = SimpleNamespace(session_id="sess_demo", spec=spec,
                original_shader_id="ResourceId::77", replacement_shader_id="ResourceId::99")
            assert await engine.revert_patch("sess_demo", spec.patch_id, manager)
            assert controller.remove_calls == ["ResourceId::77"]
            assert controller.free_calls == ["ResourceId::99"]
            assert controller.set_frame_event_calls[-1] == (314, True)
            assert engine.list_patches("sess_demo") == []

    asyncio.run(scenario())



def _provenance_patch(monkeypatch, *, mode="source_text", encoding="SPIRV", build_errors=""):
    import struct

    before = '; SPIR-V\nOpCapability Shader\nOpEntryPoint Fragment %1 "main"\nOpDecorate %2 RelaxedPrecision\n'
    after = before.replace('OpDecorate %2 RelaxedPrecision\n', '')
    module = struct.pack('<6I', 0x07230203, 0x00010000, 7, 17, 0, 0x00010000)
    fake_rd = SimpleNamespace(ResourceId=lambda: "ResourceId::0", ShaderCompileFlags=_FakeShaderCompileFlags,
                              ShaderCompileFlag=_FakeShaderCompileFlag)
    monkeypatch.setattr(patch_engine_mod, '_get_rd', lambda: fake_rd)
    monkeypatch.setattr(patch_engine_mod, '_to_rd_stage', lambda stage: 'ps')
    monkeypatch.setattr(patch_engine_mod.PatchEngine, '_assemble_spirv_asm', staticmethod(lambda text: module))

    class Controller(_PatchEngineController):
        def GetDisassemblyTargets(self, include_unsupported):
            return ['SPIR-V ASM']

        def GetTargetShaderEncodings(self):
            return [encoding]

        def DisassembleShader(self, pipeline, reflection, target):
            return before

    controller = Controller(build_errors=build_errors, build_shader_id='ResourceId::99')
    kwargs = {'source_text': after}
    if mode == 'diff_text':
        kwargs = {'diff_text': ''.join(difflib.unified_diff(before.splitlines(True), after.splitlines(True)))}
    elif mode == 'ops':
        kwargs = {'ops': [PatchOp(op='force_full_precision', variables=['2'])]}
    elif mode == 'noop':
        kwargs = {'ops': [PatchOp(op='force_full_precision', variables=['999'])]}
    result = asyncio.run(patch_engine_mod.PatchEngine().apply_patch(
        session_id='sess_build', event_id=314, stage=ShaderStage.PS,
        session_manager=_PatchEngineSessionManager(controller),
        patch_spec=PatchSpec(patch_id='repl_build', target_event_id=314, target_stage=ShaderStage.PS,
                             target_shader_id='ResourceId::77', source_target='SPIR-V ASM',
                             source_encoding='spirvasm', **kwargs)))
    return result, controller, module


@pytest.mark.parametrize('mode', ['source_text', 'diff_text', 'ops'])
def test_actual_build_input_is_bound_to_applied_target(monkeypatch, mode):
    import hashlib

    result, controller, module = _provenance_patch(monkeypatch, mode=mode)
    assert result.success is True
    assert controller.replace_calls == [('ResourceId::77', 'ResourceId::99')]
    actual = controller.build_calls[0][2]
    assert actual == module
    assert result.build_input_bytes == actual
    proof = result.build_input
    assert proof['status'] == 'available'
    assert proof['scope'] == 'BuildTargetShader-input'
    assert proof['original_shader_id'] == controller.replace_calls[0][0]
    assert proof['target_shader_id'] == controller.replace_calls[0][1]
    assert proof['sha256'] == hashlib.sha256(actual).hexdigest()
    assert proof['byte_size'] == len(actual)
    assert proof['byte_kind'] == 'spirv-module'
    assert proof['spirv_header']['id_bound'] == 17
    assert proof['spirv_header']['status'] == 'available'
    assert proof['device_binary_observed'] is False
    assert 'build_input_bytes' not in result.model_dump(mode='json')


def test_text_build_input_does_not_claim_compiled_binary_or_bound(monkeypatch):
    result, controller, _ = _provenance_patch(monkeypatch, encoding='SPIRVAsm')
    assert result.success is True
    assert result.build_input_bytes == controller.build_calls[0][2]
    assert result.build_input['byte_kind'] == 'source-text'
    assert result.build_input['spirv_header']['status'] == 'unavailable'
    assert 'id_bound' not in result.build_input['spirv_header']
    assert result.build_input['device_binary_observed'] is False


@pytest.mark.parametrize('mode,errors', [('noop', ''), ('source_text', 'error: invalid module')])
def test_noop_and_failed_build_have_no_applied_build_proof(monkeypatch, mode, errors):
    result, controller, _ = _provenance_patch(monkeypatch, mode=mode, build_errors=errors)
    assert controller.replace_calls == []
    assert result.build_input_bytes == b''
    assert result.build_input['status'] == 'unavailable'
    assert 'target_shader_id' not in result.build_input


def test_emitted_build_input_preserves_exact_bytes_and_registry_binding(monkeypatch, tmp_path):
    import hashlib
    import struct
    from pathlib import Path

    module = struct.pack('<6I', 0x07230203, 0x00010000, 7, 17, 0, 0x00010000)
    proof = {'status': 'available', 'scope': 'BuildTargetShader-input', 'encoding': 'spirv',
             'sha256': hashlib.sha256(module).hexdigest(), 'byte_size': len(module),
             'original_shader_id': 'ResourceId::77', 'target_shader_id': 'ResourceId::99',
             'byte_kind': 'spirv-module', 'spirv_header': {'status': 'available', 'id_bound': 17},
             'device_binary_observed': False}
    engine = _FakePatchEngine(success=True)
    original_apply = engine.apply_patch

    async def apply(**kwargs):
        result = await original_apply(**kwargs)
        return result.model_copy(update={'build_input': proof, 'build_input_bytes': module})

    engine.apply_patch = apply
    _install_shader_replace_env(monkeypatch, _SupportedController())
    monkeypatch.setattr(live_state, '_patch_engine', engine)
    monkeypatch.setattr(live_state, '_session_manager', _FakeSessionManager())
    monkeypatch.setattr(live_state, '_artifact_store', None)
    payload = asyncio.run(shader_ops.dispatch('edit_and_replace', {
        'session_id': 'sess_demo', 'event_id': 101, 'stage': 'ps', 'source_text': 'changed',
        'emit_patch_artifacts': True, 'output_dir': str(tmp_path)}))
    assert payload.ok is True
    replacement = payload.data['replacement']
    assert replacement['compile']['build_input'] == proof
    binary = replacement['artifacts']['build_input']
    actual = (tmp_path / Path(binary['saved_path']).name).read_bytes()
    assert actual == module
    assert hashlib.sha256(actual).hexdigest() == proof['sha256']
    assert len(payload.data['replacement']['artifacts']) == 4
    assert live_state._runtime.shader_replacements['sess_demo'][0]['compile']['build_input'] == proof



@pytest.mark.parametrize('module', [b'', b'not a module', b'\x03\x02\x23\x07',
    bytes.fromhex('0302230700000100000000000000000000000000'),
    bytes.fromhex('0302230700000100000000001100000001000000')])
def test_unavailable_build_header_does_not_invent_zero_bound(module):
    proof = patch_engine_mod._shader_build_input_provenance(
        module, encoding='SPIRV', original_shader_id='ResourceId::77', target_shader_id='ResourceId::99')
    assert proof['spirv_header']['status'] == 'unavailable'
    assert 'id_bound' not in proof['spirv_header']
    assert proof['device_binary_observed'] is False


def test_big_endian_build_header_preserves_observed_word_values():
    import struct
    module = struct.pack('>6I', 0x07230203, 0x00010000, 7, 17, 0, 0x00010000)
    proof = patch_engine_mod._shader_build_input_provenance(
        module, encoding='SPIRV', original_shader_id='ResourceId::77', target_shader_id='ResourceId::99')
    assert proof['spirv_header'] == {'status': 'available', 'byte_order': 'big',
        'version': 0x00010000, 'generator': 7, 'id_bound': 17, 'schema': 0}


def test_build_input_without_artifact_request_does_not_write(monkeypatch):
    engine = _FakePatchEngine(success=True)
    original_apply = engine.apply_patch

    async def apply(**kwargs):
        result = await original_apply(**kwargs)
        return result.model_copy(update={'build_input': {'status': 'available'}, 'build_input_bytes': b'bytes'})

    async def unexpected_store(*args, **kwargs):
        pytest.fail('No artifact was requested')

    engine.apply_patch = apply
    _install_shader_replace_env(monkeypatch, _SupportedController())
    monkeypatch.setattr(live_state, '_patch_engine', engine)
    monkeypatch.setattr(live_state, '_session_manager', _FakeSessionManager())
    monkeypatch.setattr(artifact_payloads, '_store_bytes_artifact_payload', unexpected_store)
    payload = asyncio.run(shader_ops.dispatch('edit_and_replace', {
        'session_id': 'sess_demo', 'event_id': 101, 'stage': 'ps', 'source_text': 'changed'}))
    assert payload.ok is True
    assert 'artifacts' not in payload.data['replacement']
    assert payload.data['replacement']['compile']['build_input']['status'] == 'available'


def test_build_input_artifact_write_failure_never_becomes_success(monkeypatch):
    engine = _FakePatchEngine(success=True)
    original_apply = engine.apply_patch

    async def apply(**kwargs):
        result = await original_apply(**kwargs)
        return result.model_copy(update={'build_input': {'status': 'available'}, 'build_input_bytes': b'bytes'})

    async def store(data, **kwargs):
        if kwargs.get('title') == 'shader_build_input':
            raise OSError('artifact storage unavailable')
        return {'saved_path': 'fixture:' + kwargs['title']}

    engine.apply_patch = apply
    _install_shader_replace_env(monkeypatch, _SupportedController())
    monkeypatch.setattr(live_state, '_patch_engine', engine)
    monkeypatch.setattr(live_state, '_session_manager', _FakeSessionManager())
    monkeypatch.setattr(artifact_payloads, '_store_bytes_artifact_payload', store)
    with pytest.raises(OSError, match='artifact storage unavailable'):
        asyncio.run(shader_ops.dispatch('edit_and_replace', {
            'session_id': 'sess_demo', 'event_id': 101, 'stage': 'ps', 'source_text': 'changed',
            'emit_patch_artifacts': True}))
    assert len(engine.calls) == 1


@pytest.mark.parametrize('source', ['first\nsecond\n', 'first\r\nsecond\r\n', '颜色\n', '混合\r\n内容\n'])
def test_text_artifact_saved_bytes_match_content_addressed_store(monkeypatch, tmp_path, source):
    import hashlib
    from pathlib import Path
    from rdc_tool.utils.artifact_store import ArtifactStore
    monkeypatch.setattr(live_state, '_artifact_store', ArtifactStore(tmp_path / 'store'))
    text = asyncio.run(artifact_payloads._store_text_artifact_payload(
        source, stem='source', suffix='.txt', output_dir=str(tmp_path)))
    binary = asyncio.run(artifact_payloads._store_bytes_artifact_payload(
        b'first\nsecond\n', stem='build', suffix='.spv', output_dir=str(tmp_path)))
    saved = Path(text['saved_path']).read_bytes()
    stored = Path(text['artifact_path']).read_bytes()
    assert saved == stored == source.encode('utf-8')
    assert hashlib.sha256(saved).hexdigest() == hashlib.sha256(stored).hexdigest()
    assert Path(binary['saved_path']).read_bytes() == b'first\nsecond\n'


class _EmbeddedSourceController(_EncodingController):
    def __init__(self, debug_info: object, encoding: str = "SPIRV") -> None:
        super().__init__(encoding)
        self.debug_info = debug_info

    def GetPipelineState(self) -> _EncodingPipe:
        info, encoding = self.debug_info, self.encoding

        class _Pipe(_EncodingPipe):
            def GetShaderReflection(self, stage: object) -> SimpleNamespace:
                return SimpleNamespace(entryPoint="exported_main", encoding=encoding, debugInfo=info)

        return _Pipe("SPIRV")


def _embedded_source_result(monkeypatch: pytest.MonkeyPatch, info: object, encoding: str = "SPIRV") -> dict[str, object]:
    _install_shader_replace_env(monkeypatch, _EmbeddedSourceController(info, encoding))
    live_state._session_manager = _FakeSessionManager()
    return asyncio.run(shader_ops.dispatch(
        "get_source", {"session_id": "sess_demo", "event_id": 101, "stage": "ps", "shader_id": "ResourceId::77"},
    ))


def test_get_source_reads_embedded_source_files_without_source_level_debugging(monkeypatch: pytest.MonkeyPatch) -> None:
    source = '#include "color.h"\r\nfloat4 Entry() : SV_Target { return Color(); } // 颜色\r\n'
    files = [
        SimpleNamespace(filename="C:/original/入口.hlsl", contents=source),
        SimpleNamespace(filename="color.h", contents="float4 Color() { return 1; }\n"),
    ]
    info = SimpleNamespace(files=files, encoding="HLSL", entrySourceName="Entry", sourceDebugInformation=False,
                           compileFlags=SimpleNamespace(flags=[SimpleNamespace(name="optimization", value="0")]))
    payload = _embedded_source_result(monkeypatch, info)
    assert payload.ok is True
    assert payload.data['source_available'] is True
    assert payload.data['source'] == source
    assert payload.data['files'] == [{"filename": f.filename, "contents": f.contents} for f in files]
    assert payload.data['source_encoding'].lower() == "hlsl"
    assert payload.data['entry_point'] == "Entry"
    assert payload.data['source_debug_information'] is False
    assert payload.data['compile_flags'] == [{"name": "optimization", "value": "0"}]
    assert payload.data['edit_plan']["input_kind"] == "debug_source"
    assert "fallback_tool" not in payload.data
    assert "failure_reason" not in payload.data


@pytest.mark.parametrize("shader_encoding", ["SPIRV", "HLSL", "GLSL", "DXIL"])
def test_get_source_retains_include_text_when_entry_contents_are_unavailable(monkeypatch: pytest.MonkeyPatch, shader_encoding: str) -> None:
    files = [SimpleNamespace(filename="entry.hlsl", contents=""), SimpleNamespace(filename="helper.h", contents="float Value;\n")]
    payload = _embedded_source_result(monkeypatch, SimpleNamespace(files=files, encoding="HLSL"), shader_encoding)
    assert payload.ok is True
    assert payload.data['source_available'] is False
    assert payload.data['source'] is None
    assert payload.data['files'] == [{"filename": f.filename, "contents": f.contents} for f in files]
    assert payload.data['failure_reason'] == "entry_source_contents_unavailable"
    assert payload.data['edit_plan']["can_replace"] is False


@pytest.mark.parametrize("bad_contents", [None, b"not native text"])
def test_get_source_does_not_turn_invalid_native_source_into_absence(monkeypatch: pytest.MonkeyPatch, bad_contents: object) -> None:
    info = SimpleNamespace(files=[SimpleNamespace(filename="entry.hlsl", contents=bad_contents)], encoding="HLSL")
    payload = _embedded_source_result(monkeypatch, info)
    assert payload.ok is False
    assert payload.code == "shader_source_lookup_failed"
    assert payload.details["failure_stage"] == "source_lookup"
    assert "source_available" not in payload.details


def test_get_source_reports_native_source_read_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    class _UnreadableDebugInfo:
        @property
        def files(self) -> object:
            raise RuntimeError("native source read failed")

    payload = _embedded_source_result(monkeypatch, _UnreadableDebugInfo())
    assert payload.ok is False
    assert payload.code == "shader_source_lookup_failed"
    assert "native source read failed" in payload.message


def test_get_source_reports_missing_native_metadata_separately_from_empty_files(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = _embedded_source_result(monkeypatch, None)
    assert payload.ok is False
    assert payload.code == "shader_source_metadata_unavailable"
    assert payload.category == "runtime"
    assert "context_preserved" not in payload.details


@pytest.mark.parametrize("restore_fails", [False, True])
def test_get_source_native_read_failure_restores_prior_event(monkeypatch: pytest.MonkeyPatch, restore_fails: bool) -> None:
    class _UnreadableDebugInfo:
        @property
        def files(self) -> object:
            raise RuntimeError("native source read failed")

    _install_shader_replace_env(monkeypatch, _EmbeddedSourceController(_UnreadableDebugInfo()))
    live_state._session_manager = _FakeSessionManager()
    current_event = {"value": 3029}
    transitions: list[int] = []

    async def set_event(_session_id: str, event_id: int | None) -> int:
        requested = int(event_id or 0)
        transitions.append(requested)
        if restore_fails and requested == 3029:
            raise RuntimeError("native restore failed")
        current_event["value"] = requested
        return requested

    monkeypatch.setattr(replay_access, "_ensure_event", set_event)
    monkeypatch.setattr(replay_access, "_active_event", lambda _session_id: current_event["value"])
    monkeypatch.setattr(live_state, "_runtime_context_id", lambda: "owned-source-context")
    payload = asyncio.run(shader_ops.dispatch(
        "get_source", {"session_id": "sess_demo", "event_id": 1248, "stage": "ps"},
    ))
    assert payload.ok is False
    assert transitions == [1248, 3029]
    assert payload.details["context_id"] == "owned-source-context"
    if restore_fails:
        assert payload.code == "shader_inspection_recovery_failed"
        assert payload.details["original_error_code"] == "shader_source_lookup_failed"
        assert payload.details["replay_state_restored"] is False
        assert current_event["value"] == 1248
    else:
        assert payload.code == "shader_source_lookup_failed"
        assert payload.details["replay_state_restored"] is True
        assert payload.details["restored_event_id"] == 3029
        assert current_event["value"] == 3029


@pytest.mark.parametrize("encoding", [None, "Unknown"])
def test_get_source_does_not_invent_missing_source_metadata(monkeypatch: pytest.MonkeyPatch, encoding: object) -> None:
    info = SimpleNamespace(files=[SimpleNamespace(filename="main.hlsl", contents="float4 Entry() { return 1; }")],
                           encoding=encoding, entrySourceName="")
    payload = _embedded_source_result(monkeypatch, info)
    assert payload.ok is True
    assert payload.data['source_available'] is True
    assert payload.data['source_encoding'] is None
    assert payload.data['entry_point'] is None
    assert payload.data['compile_flags'] is None
    assert payload.data['source_debug_information'] is None
    assert payload.data['edit_plan']["can_replace"] is False


@pytest.mark.parametrize("target", ["7", "%7", " %7 "])
def test_spirv_precision_id_operand_matches_and_edits_same_exact_target(target: str) -> None:
    source = "OpDecorate %7 RelaxedPrecision\nOpDecorate %70 RelaxedPrecision\nOpDecorate %17 RelaxedPrecision\n"
    matches = patch_engine_mod.PatchEngine._collect_spirv_precision_targets(source, [target])
    assert matches == [(1, "OpDecorate %7 RelaxedPrecision")]
    edited = patch_engine_mod.PatchEngine._apply_precision_patch(source, "spirvasm", [target])
    assert "OpDecorate %7 RelaxedPrecision" not in edited
    assert "OpDecorate %70 RelaxedPrecision" in edited
    assert "OpDecorate %17 RelaxedPrecision" in edited


@pytest.mark.parametrize("target", ["%", "", "7 8", "%%7"])
def test_invalid_spirv_precision_id_never_becomes_a_global_edit(target: str) -> None:
    source = "OpDecorate %7 RelaxedPrecision\n"
    with pytest.raises(ValueError, match="SPIR-V precision target"):
        patch_engine_mod.PatchEngine._collect_spirv_precision_targets(source, [target])
    with pytest.raises(ValueError, match="SPIR-V precision target"):
        patch_engine_mod.PatchEngine._apply_precision_patch(source, "spirvasm", [target])
