from __future__ import annotations

import asyncio
import io
from pathlib import Path
from types import SimpleNamespace

import pytest
import numpy as np

from rdc_tool.core import replay_facts
from rdc_tool.core.errors import CoreError
from rdc_tool.core.patch_engine import PatchEngine
from rdc_tool.runtime import artifact_payloads, context_records, live_state, pixel_trace, renderdoc_api, replay_access, shader_values, texture_export, truth_matrix, visual_target
from rdc_tool.runtime.operations import shader as shader_ops
from rdc_tool.runtime.operations import texture as texture_ops

pytestmark = pytest.mark.usefixtures("fake_renderdoc")


@pytest.fixture
def known_sample_events(monkeypatch):
    async def index(session_id, **kwargs):
        assert session_id == "sess_demo"
        return [], [], {41: object(), 42: object()}
    monkeypatch.setattr(replay_access, "_load_action_index", index)


class _FakeShaderPipe:
    def GetShader(self, stage: object) -> str:
        if stage == "ps":
            return "ResourceId::77"
        return "ResourceId::0"

    def GetShaderReflection(self, stage: object) -> SimpleNamespace:
        return SimpleNamespace(
            entryPoint="main",
            readOnlyResources=[],
            readWriteResources=[],
            constantBlocks=[],
            debugInfo=SimpleNamespace(
                debuggable=False,
                sourceDebugInformation=False,
                debugStatus="The shader uses an unsupported test feature.",
            ),
        )

    def GetGraphicsPipelineObject(self) -> str:
        return "GraphicsPipe"

    def GetComputePipelineObject(self) -> str:
        return "ComputePipe"


class _FakeShaderController:
    def GetPipelineState(self) -> _FakeShaderPipe:
        return _FakeShaderPipe()

    def GetDisassemblyTargets(self, with_pipeline: bool) -> list[str]:
        return ["mock-target"]

    def DisassembleShader(self, pipeline_obj: object, reflection: object, target: str) -> str:
        return f"disassembly:{target}"


@pytest.fixture(autouse=True)
def _restore_runtime_services() -> None:
    original_render_service = live_state._render_service
    original_session_manager = live_state._session_manager
    try:
        yield
    finally:
        live_state._render_service = original_render_service
        live_state._session_manager = original_session_manager


@pytest.mark.parametrize("texture_size", [(800, 600), (0, 0)])
@pytest.mark.usefixtures("known_sample_events")
def test_render_overlay_reports_native_to_image_mapping(
    monkeypatch: pytest.MonkeyPatch, texture_size: tuple[int, int],
) -> None:
    async def descriptor(session_id: str, texture_id: object, *, event_id: int):
        return str(texture_id), SimpleNamespace(width=texture_size[0], height=texture_size[1], name="")

    async def bindings(session_id: str, event_id: int):
        return {}

    async def truth(session_id: str, event_id: int):
        return {"binding_truth_level": "binding_verified", "summary_degraded_reasons": []}

    async def render_event(**kwargs):
        assert kwargs["view_config"]["flip_y"] is True
        return SimpleNamespace(), {"width": 1920, "height": 1080, "scale": 0}

    monkeypatch.setattr(replay_access, "_get_texture_descriptor", descriptor)
    monkeypatch.setattr(replay_access, "_binding_name_index_for_event", bindings)
    monkeypatch.setattr(truth_matrix, "_event_truth_metadata", truth)
    monkeypatch.setattr(artifact_payloads, "_artifact_path", lambda artifact: "overlay.png")
    live_state._session_manager = SimpleNamespace()
    live_state._render_service = SimpleNamespace(render_event=render_event)

    payload = asyncio.run(texture_ops.dispatch("render_overlay", {
        "session_id": "sess_demo", "texture_id": "ResourceId::24",
        "event_id": 42, "overlay": "Drawcall", "flip_y": True,
    }))

    assert payload.ok is True
    mapping = payload.data['image_mapping']
    if texture_size == (0, 0):
        assert mapping == {"status": "unavailable", "reason": "dimensions_unavailable"}
    else:
        assert mapping["status"] == "available"
        assert mapping["source_size"] == {"width": 800, "height": 600}
        assert mapping["effective_scale"] == pytest.approx(1.8)
        assert mapping["content_rect"] == pytest.approx({"x": 240, "y": 0, "width": 1440, "height": 1080})
        assert mapping["flip_y"] is True


def test_texture_event_bound_tools_respect_explicit_event_id(monkeypatch: pytest.MonkeyPatch) -> None:
    seen_events: list[int] = []

    async def _fake_ensure_event(session_id: str, event_id: int | None) -> int:
        resolved = int(event_id or 0)
        seen_events.append(resolved)
        return resolved

    async def _fake_resolve_texture_id(session_id: str, texture_id: object, *, event_id: int | None = None) -> str:
        return str(texture_id)

    async def _fake_pick_pixel(
        *,
        session_id: str,
        event_id: int,
        texture_id: str,
        x: int,
        y: int,
        session_manager: object,
        subresource: dict[str, int],
        value_type: str,
    ) -> dict[str, object]:
        return {
            "event_id": int(event_id),
            "texture_id": texture_id,
            "x": int(x),
            "y": int(y),
            "subresource": subresource,
            "value_type": value_type,
            "r": 1.0,
        }

    async def _fake_read_texture_array(
        session_id: str,
        event_id: int,
        texture_id: str,
        session_manager: object,
        subresource: dict[str, int] | None,
    ) -> tuple[np.ndarray, dict[str, object]]:
        return np.array([[[0.25, 0.5, 0.75, 1.0]]], dtype=np.float32), {
            "texture_id": texture_id,
            "shape": [1, 1, 4],
        }

    monkeypatch.setattr(replay_access, "_ensure_event", _fake_ensure_event)
    monkeypatch.setattr(replay_access, "_resolve_texture_id", _fake_resolve_texture_id)
    live_state._session_manager = SimpleNamespace()
    live_state._render_service = SimpleNamespace(
        pick_pixel=_fake_pick_pixel,
        read_texture_array=_fake_read_texture_array,
    )

    pixel_payload = asyncio.run(
            texture_ops.dispatch(
                "get_pixel_value",
                {
                    "session_id": "sess_demo",
                    "event_id": 314,
                    "texture_id": "ResourceId::178817",
                    "x": 7,
                    "y": 9,
                },
            )
        )
    stats_payload = asyncio.run(
            texture_ops.dispatch(
                "compute_stats",
                {
                    "session_id": "sess_demo",
                    "event_id": 314,
                    "texture_id": "ResourceId::178817",
                },
            )
        )

    assert pixel_payload.ok is True
    assert pixel_payload.data['resolved_event_id'] == 314
    assert pixel_payload.data['pixel']["event_id"] == 314
    assert pixel_payload.data['texture_id'] == "ResourceId::178817"
    assert pixel_payload.data['binding_truth_level'] == "binding_degraded"
    assert stats_payload.ok is True
    assert stats_payload.data['resolved_event_id'] == 314
    assert stats_payload.data['stats']["event_id"] == 314
    assert stats_payload.data['stats']["channels"]["r"]["min"] == 0.25
    assert stats_payload.data['stats']["channels"]["r"]["max"] == 0.25
    assert stats_payload.data['stats']["channels"]["r"]["nan_count"] == 0
    assert stats_payload.data['stats']["channels"]["r"]["inf_count"] == 0
    assert "artifact_path" not in stats_payload.data
    assert stats_payload.data['texture_id'] == "ResourceId::178817"
    assert seen_events == [314, 314]


def test_region_values_stats_describe_exported_stride_samples(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    source = np.full((4, 4, 3), 0.5, dtype=np.float32)
    source[1, 1, 0] = 7.5
    artifact_path = tmp_path / "sampled.npz"

    async def _fake_read_texture_array(
        session_id: str,
        event_id: int,
        texture_id: str,
        session_manager: object,
        subresource: dict[str, int],
        *,
        region: dict[str, int],
    ) -> tuple[np.ndarray, dict[str, object]]:
        assert region == {"x": 0, "y": 0, "width": 4, "height": 4}
        return source, {"shape": [4, 4, 3], "max": 7.5}

    async def _fake_store(data: bytes, *, mime: str, suffix: str) -> SimpleNamespace:
        assert mime == "application/x-npz" and suffix == ".npz"
        artifact_path.write_bytes(data)
        return SimpleNamespace(sha256="sampled")

    async def _fake_ensure_event(session_id: str, event_id: int | None) -> int:
        return int(event_id or 0)

    async def _fake_resolve_texture_id(session_id: str, texture_id: object, *, event_id: int | None = None) -> str:
        return str(texture_id)

    async def _fake_event_truth_metadata(session_id: str, event_id: int) -> dict[str, object]:
        return {"binding_truth_level": "binding_degraded", "evidence_truth_level": "structured_readback"}

    monkeypatch.setattr(replay_access, "_ensure_event", _fake_ensure_event)
    monkeypatch.setattr(replay_access, "_resolve_texture_id", _fake_resolve_texture_id)
    monkeypatch.setattr(truth_matrix, "_event_truth_metadata", _fake_event_truth_metadata)
    monkeypatch.setattr(live_state, "_artifact_store", SimpleNamespace(store=_fake_store, get_path=lambda sha: artifact_path))
    live_state._session_manager = SimpleNamespace()
    live_state._render_service = SimpleNamespace(read_texture_array=_fake_read_texture_array)

    payload = asyncio.run(texture_ops.dispatch("get_region_values", {
        "session_id": "sess_demo",
        "event_id": 314,
        "texture_id": "tex-a",
        "rect": {"x": 0, "y": 0, "w": 4, "h": 4},
        "stride": 2,
    }))

    assert payload.ok is True
    assert payload.data['values_path'] == str(artifact_path)
    with np.load(io.BytesIO(artifact_path.read_bytes())) as artifact:
        exported = artifact["pixels"]
    assert exported.shape == (2, 2, 3)
    assert np.all(exported == 0.5)
    assert payload.data['stats']["shape"] == [2, 2, 3]
    assert payload.data['stats']["stride"] == 2
    assert payload.data['stats']["min"] == payload.data['stats']["max"] == payload.data['stats']["mean"] == 0.5


@pytest.mark.usefixtures("known_sample_events")
def test_texture_histogram_and_diff_reuse_memory_readback_without_artifacts(monkeypatch: pytest.MonkeyPatch) -> None:
    read_calls: list[tuple[int, str]] = []

    async def _fake_ensure_event(session_id: str, event_id: int | None) -> int:
        return int(event_id or 41)

    async def _fake_resolve_texture_id(session_id: str, texture_id: object, *, event_id: int | None = None) -> str:
        return str(texture_id)

    async def _fake_read_texture_array(
        session_id: str,
        event_id: int,
        texture_id: str,
        session_manager: object,
        subresource: dict[str, int] | None,
    ) -> tuple[np.ndarray, dict[str, object]]:
        read_calls.append((event_id, texture_id))
        values = np.array([[[0.0, 0.25], [0.5, 0.75]]], dtype=np.float32)
        if texture_id == "tex-b":
            values = values + 0.25
        return values, {"shape": list(values.shape)}

    monkeypatch.setattr(replay_access, "_ensure_event", _fake_ensure_event)
    monkeypatch.setattr(replay_access, "_resolve_texture_id", _fake_resolve_texture_id)
    live_state._session_manager = SimpleNamespace()
    live_state._render_service = SimpleNamespace(read_texture_array=_fake_read_texture_array)

    histogram = asyncio.run(
            texture_ops.dispatch(
                "get_histogram",
                {"session_id": "sess_demo", "event_id": 41, "texture_id": "tex-a", "channels": "rg", "bins": 2},
            )
        )
    difference = asyncio.run(
            texture_ops.dispatch(
                "diff",
                {
                    "session_id": "sess_demo",
                    "tex_a": {"texture_id": "tex-a", "event_id": 41},
                    "tex_b": {"texture_id": "tex-b", "event_id": 42},
                },
            )
        )

    assert histogram.ok is True
    assert histogram.data['resolved_event_id'] == 41
    assert set(histogram.data['histogram']) == {"r", "g"}
    assert difference.ok is True
    assert difference.data['diff']["mse"] == pytest.approx(0.0625)
    assert read_calls == [(41, "tex-a"), (41, "tex-a"), (42, "tex-b")]
    assert "artifact_path" not in histogram.data
    assert "artifact_path" not in difference.data


def test_texture_histogram_and_diff_fail_closed_and_serialize_identical_psnr(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_ensure_event(session_id: str, event_id: int | None) -> int:
        return int(event_id or 41)

    async def _fake_resolve_texture_id(session_id: str, texture_id: object, *, event_id: int | None = None) -> str:
        return str(texture_id)

    async def _fake_read_texture_array(
        session_id: str,
        event_id: int,
        texture_id: str,
        session_manager: object,
        subresource: dict[str, int] | None,
    ) -> tuple[np.ndarray, dict[str, object]]:
        arrays = {
            "same": np.zeros((1, 2, 1), dtype=np.float32),
            "wide": np.zeros((1, 3, 1), dtype=np.float32),
            "nan": np.array([[[np.nan]]], dtype=np.float32),
        }
        values = arrays[texture_id]
        return values, {"shape": list(values.shape)}

    monkeypatch.setattr(replay_access, "_ensure_event", _fake_ensure_event)
    monkeypatch.setattr(replay_access, "_resolve_texture_id", _fake_resolve_texture_id)
    live_state._session_manager = SimpleNamespace()
    live_state._render_service = SimpleNamespace(read_texture_array=_fake_read_texture_array)

    invalid_bins = asyncio.run(
            texture_ops.dispatch(
                "get_histogram",
                {"session_id": "sess_demo", "texture_id": "same", "bins": 0},
            )
        )
    invalid_range = asyncio.run(
            texture_ops.dispatch(
                "get_histogram",
                {"session_id": "sess_demo", "texture_id": "same", "range": {"min": 2.0, "max": 1.0}},
            )
        )
    nonfinite = asyncio.run(texture_ops.dispatch("get_histogram", {"session_id": "sess_demo", "texture_id": "nan"}))
    identical = asyncio.run(
            texture_ops.dispatch(
                "diff",
                {"session_id": "sess_demo", "tex_a": {"texture_id": "same"}, "tex_b": {"texture_id": "same"}},
            )
        )
    shape_mismatch = asyncio.run(
            texture_ops.dispatch(
                "diff",
                {"session_id": "sess_demo", "tex_a": {"texture_id": "same"}, "tex_b": {"texture_id": "wide"}},
            )
        )
    diff_nonfinite = asyncio.run(
            texture_ops.dispatch(
                "diff",
                {"session_id": "sess_demo", "tex_a": {"texture_id": "same"}, "tex_b": {"texture_id": "nan"}},
            )
        )

    assert invalid_bins.ok is False and invalid_bins.code == "validation_error"
    assert invalid_range.ok is False and invalid_range.code == "validation_error"
    assert nonfinite.ok is False and nonfinite.code == "texture_nonfinite_data"
    assert identical.ok is True
    assert identical.data['diff']["identical"] is True
    assert identical.data['diff']["psnr"] is None
    assert identical.data['diff']["psnr_status"] == "infinite"
    assert identical.data['event_a'] == 41 and identical.data['event_b'] == 41
    assert shape_mismatch.ok is False and shape_mismatch.code == "texture_shape_mismatch"
    assert diff_nonfinite.ok is False and diff_nonfinite.code == "texture_nonfinite_data"


def test_pixel_history_resolves_explicit_output_target(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Subresource:
        mip = 0
        slice = 0
        sample = 0

    resolution_calls: list[tuple[int, dict[str, int]]] = []
    binding_calls: list[int] = []

    async def _fake_get_controller(session_id: str) -> object:
        return object()

    async def _fake_ensure_event(session_id: str, event_id: int | None) -> int:
        return int(event_id or 77)

    async def _fake_resolve_visual_target_for_event(
        session_id: str,
        event_id: int,
        *,
        target: dict[str, int],
    ) -> tuple[str, object, dict[str, object], dict[str, object]]:
        resolution_calls.append((event_id, dict(target)))
        return "ResourceId::rt1", SimpleNamespace(format=SimpleNamespace(compType=1)), {}, {}

    async def _fake_history(*args: object) -> list[object]:
        value = SimpleNamespace(
            IsValid=lambda: True,
            col=SimpleNamespace(floatValue=[0.1, 0.2, 0.3, 1.0]),
            depth=-1.0,
            stencil=-1,
        )
        return [SimpleNamespace(eventId=77, primitiveID=5, fragIndex=0,
                                Passed=lambda: True, preMod=value, shaderOut=value, postMod=value)]

    async def _fake_truth(session_id: str, event_id: int) -> dict[str, object]:
        return {"binding_truth_level": "binding_verified", "summary_degraded_reasons": []}

    async def _fake_bindings(session_id, event_id, history, controller):
        binding_calls.append(event_id)
        return [{"event_id": history[0]["event_id"], "binding_truth_level": "binding_verified"}]

    monkeypatch.setattr(pixel_trace, "_pixel_history_writer_bindings", _fake_bindings)
    monkeypatch.setattr(replay_access, "_get_controller", _fake_get_controller)
    monkeypatch.setattr(replay_access, "_ensure_event", _fake_ensure_event)
    monkeypatch.setattr(visual_target, "_resolve_visual_target_for_event", _fake_resolve_visual_target_for_event)
    monkeypatch.setattr(pixel_trace, "_checked_pixel_history_raw", _fake_history)
    monkeypatch.setattr(replay_facts, "pixel_history_input_attachment_conflict", lambda *args: None)
    monkeypatch.setattr(truth_matrix, "_event_truth_metadata", _fake_truth)
    monkeypatch.setattr(renderdoc_api, "_get_rd", lambda: SimpleNamespace(
        Subresource=_Subresource, CompType=SimpleNamespace(Float=1)))
    live_state._render_service = object()

    payload = asyncio.run(
            texture_ops.dispatch(
                "get_pixel_history",
                {"session_id": "sess_demo", "event_id": 77, "target": {"rt_index": 1}, "x": 4, "y": 5},
            )
        )
    without_bindings = asyncio.run(texture_ops.dispatch("get_pixel_history", {
        "session_id": "sess_demo", "event_id": 77, "target": {"rt_index": 1},
        "x": 4, "y": 5, "include_shaders": False,
    }))
    conflict = asyncio.run(
            texture_ops.dispatch(
                "get_pixel_history",
                {
                    "session_id": "sess_demo",
                    "texture_id": "ResourceId::explicit",
                    "target": {"rt_index": 1},
                    "x": 4,
                    "y": 5,
                },
            )
        )

    assert payload.ok is True
    assert payload.data['texture_id'] == "ResourceId::rt1"
    assert payload.data['resolved_event_id'] == 77
    assert payload.data['history'][0]["shader_out"]["color_rgba"] == [0.1, 0.2, 0.3, 1.0]
    assert payload.data['history'][0]["pre_mod"]["valid"] is True
    assert payload.data['history_bindings'] == [{"event_id": 77, "binding_truth_level": "binding_verified"}]
    assert payload.data['history_bindings_status'] == "complete"
    assert without_bindings.data['history_bindings'] is None
    assert without_bindings.data['history_bindings_status'] == "not_requested"
    assert binding_calls == [77]
    assert resolution_calls == [(77, {"rt_index": 1}), (77, {"rt_index": 1})]
    assert conflict.ok is False and conflict.code == "validation_error"


def test_pixel_history_rejects_invalid_vulkan_attachment_and_restores_entry(monkeypatch: pytest.MonkeyPatch) -> None:
    active = {"event": 19}

    async def get_controller(session_id: str) -> object:
        return SimpleNamespace(GetTextures=lambda: [])

    async def ensure_event(session_id: str, event_id: int | None) -> int:
        active["event"] = int(event_id or active["event"])
        return active["event"]

    async def resolve_texture(session_id: str, texture_id: object, *, event_id: int | None = None) -> object:
        return texture_id

    async def forbidden_native_call(*args: object) -> list[object]:
        raise AssertionError("Pixel History must not run for an invalid input attachment")

    monkeypatch.setattr(replay_access, "_get_controller", get_controller)
    monkeypatch.setattr(replay_access, "_ensure_event", ensure_event)
    monkeypatch.setattr(replay_access, "_active_event", lambda session_id: active["event"])
    monkeypatch.setattr(replay_access, "_resolve_texture_id", resolve_texture)
    monkeypatch.setattr(renderdoc_api, "_get_rd", lambda: SimpleNamespace(Subresource=SimpleNamespace))
    monkeypatch.setattr(live_state, "_runtime_context_id", lambda: "owned-context")
    monkeypatch.setattr(replay_facts, "pixel_history_input_attachment_conflict", lambda *args: (7, 0x10))
    monkeypatch.setattr(pixel_trace, "_pixel_history_raw", forbidden_native_call)
    monkeypatch.setattr(live_state, "_render_service", object())

    payload = asyncio.run(texture_ops.dispatch("get_pixel_history", {
        "session_id": "replay", "texture_id": "texture", "event_id": 5, "x": 1, "y": 2,
    }))
    assert payload.ok is False
    assert payload.category == "runtime"
    assert payload.code == "pixel_history_unsupported_input_attachment"
    assert "context_preserved" not in payload.details
    assert payload.details["replay_state_restored"] is True
    assert payload.details["restored_event_id"] == active["event"] == 19
    assert payload.details["usage_event_id"] == 7



def test_pixel_history_bindings_follow_writer_events_and_restore_query_event(monkeypatch: pytest.MonkeyPatch) -> None:
    observed: list[tuple[object, ...]] = []

    class _Snapshot:
        def model_dump(self, mode: str) -> dict[str, object]:
            return {"api": "Vulkan", "shaders": [{"resource_id": "shader"}],
                    "render_targets": [{"resource_id": "target"}]}

    class _Pipeline:
        async def snapshot_pipeline(self, *, session_id, event_id, session_manager, sections):
            observed.append(("inspect", event_id, tuple(sections)))
            if event_id == 21:
                raise RuntimeError("writer pipeline unavailable")
            return _Snapshot()

    class _Controller:
        def SetFrameEvent(self, event_id: int, force: bool) -> None:
            observed.append(("restore", event_id, force))

    monkeypatch.setattr(live_state, "_pipeline_service", _Pipeline())
    monkeypatch.setattr(truth_matrix, "_session_backend_record", lambda *args, **kwargs: ("remote", {}))
    bindings = asyncio.run(pixel_trace._pixel_history_writer_bindings("session", 50,
        [{"event_id": 11}, {"event_id": 11}, {"event_id": 21}], _Controller()))
    assert observed == [("inspect", 11, ("shaders", "output_targets")),
                        ("inspect", 21, ("shaders", "output_targets")), ("restore", 50, True)]
    assert bindings[0]["event_id"] == 11
    assert bindings[0]["binding_truth_level"] == "binding_verified"
    assert bindings[0]["shaders"] == [{"resource_id": "shader"}]
    assert bindings[0]["render_targets"] == [{"resource_id": "target"}]
    assert bindings[1] == {"event_id": 21, "binding_truth_level": "binding_degraded",
                           "error": {"code": "history_event_binding_unavailable",
                                     "message": "writer pipeline unavailable"}}


def test_pixel_history_writer_binding_restore_failure_marks_session_for_recovery(monkeypatch: pytest.MonkeyPatch) -> None:
    recorded: list[dict[str, object]] = []

    class _Snapshot:
        def model_dump(self, mode: str) -> dict[str, object]:
            return {"api": "Vulkan", "shaders": [{"resource_id": "shader"}],
                    "render_targets": [{"resource_id": "target"}]}

    class _Pipeline:
        async def snapshot_pipeline(self, **kwargs):
            return _Snapshot()

    class _Controller:
        def SetFrameEvent(self, event_id: int, force: bool) -> None:
            raise RuntimeError("restore failed")

    monkeypatch.setattr(live_state, "_pipeline_service", _Pipeline())
    monkeypatch.setattr(truth_matrix, "_session_backend_record", lambda *args, **kwargs: ("remote", {}))
    monkeypatch.setattr(context_records, "_update_context_session_record", lambda session, **fields: recorded.append(fields))
    with pytest.raises(CoreError) as raised:
        asyncio.run(pixel_trace._pixel_history_writer_bindings("session", 50, [{"event_id": 11}], _Controller()))
    assert raised.value.code == "replay_restore_failed"
    assert recorded[0]["recovery_status"] == "requires_restart"


def test_pixel_history_preserves_native_modification_values(monkeypatch: pytest.MonkeyPatch) -> None:
    comp_types = SimpleNamespace(Float=1, UNorm=2, SNorm=3, UInt=4, SInt=5,
                                 UScaled=6, SScaled=7, Depth=8, UNormSRGB=9)
    monkeypatch.setattr(renderdoc_api, "_get_rd", lambda: SimpleNamespace(CompType=comp_types))

    float_target = SimpleNamespace(format=SimpleNamespace(compType=comp_types.Float))
    assert pixel_trace._pixel_history_color_type(float_target) == "float"
    uint_target = SimpleNamespace(format=SimpleNamespace(compType=comp_types.UInt))
    assert pixel_trace._pixel_history_color_type(uint_target) == "uint"
    assert pixel_trace._pixel_history_color_type(object()) == "unknown"

    def modification(*, valid: bool, depth: float, stencil: int) -> SimpleNamespace:
        return SimpleNamespace(
            IsValid=lambda: valid,
            col=SimpleNamespace(floatValue=[0.25, float("nan"), 0.75, 1.0],
                                uintValue=[1, 2, 3, 4]),
            depth=depth,
            stencil=stencil,
        )

    item = SimpleNamespace(
        eventId=72, primitiveID=3, fragIndex=0, Passed=lambda: True,
        preMod=modification(valid=True, depth=-1.0, stencil=-2),
        shaderOut=modification(valid=True, depth=0.4, stencil=2),
        postMod=modification(valid=False, depth=0.5, stencil=3),
    )
    payload = pixel_trace._pixel_history_item_payload(item, "float")
    assert payload["pre_mod"] == {
        "valid": True, "color_type": "float", "color_rgba": [0.25, None, 0.75, 1.0],
        "non_finite_channels": [1], "depth": None, "stencil": None,
        "stencil_status": "undetermined",
    }
    assert payload["shader_out"]["depth"] == 0.4
    assert payload["shader_out"]["stencil"] == 2
    assert payload["post_mod"] == {"valid": False, "unavailable_reason": "native_value_invalid"}
    item.fragIndex = 1
    second_fragment = pixel_trace._pixel_history_item_payload(item, "uint")
    assert second_fragment["pre_mod"] == {"valid": False, "unavailable_reason": "non_first_fragment"}
    assert second_fragment["shader_out"]["color_rgba"] == [1, 2, 3, 4]


def test_shader_reflection_and_disassembly_support_stage_only_queries(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _inline_offload(fn, *args, **kwargs):  # type: ignore[no-untyped-def]
        return fn(*args, **kwargs)

    async def _fake_get_controller(session_id: str) -> _FakeShaderController:
        return _FakeShaderController()

    async def _fake_ensure_event(session_id: str, event_id: int | None) -> int:
        return int(event_id or 314)

    monkeypatch.setattr(renderdoc_api, "_offload", _inline_offload)
    monkeypatch.setattr(replay_access, "_get_controller", _fake_get_controller)
    monkeypatch.setattr(replay_access, "_ensure_event", _fake_ensure_event)
    monkeypatch.setattr(renderdoc_api, "_rd_stage", lambda stage: stage)
    monkeypatch.setattr(renderdoc_api, "_is_null_resource_id", lambda rid: str(rid) in {"", "ResourceId::0", "0"})
    monkeypatch.setattr(
        PatchEngine,
        "_resolve_source",
        staticmethod(lambda *args, **kwargs: ("disassembly:mock-target", "raw", "mock-target", False)),
    )

    reflection_payload = asyncio.run(
            shader_ops.dispatch(
                "get_reflection",
                {
                    "session_id": "sess_demo",
                    "event_id": 314,
                    "stage": "ps",
                },
            )
        )
    disassembly_payload = asyncio.run(
            shader_ops.dispatch(
                "get_disassembly",
                {
                    "session_id": "sess_demo",
                    "event_id": 314,
                    "stage": "ps",
                },
            )
        )

    assert reflection_payload.ok is True
    assert reflection_payload.data['resolved_event_id'] == 314
    assert reflection_payload.data['shader_id'] == "ResourceId::77"
    assert reflection_payload.data['reflection']["entry_points"] == ["main"]
    assert reflection_payload.data['reflection']["debug_info"] == {
        "debuggable": False,
        "source_debug_information": False,
        "status": "The shader uses an unsupported test feature.",
    }
    assert disassembly_payload.ok is True
    assert disassembly_payload.data['resolved_event_id'] == 314
    assert disassembly_payload.data['shader_id'] == "ResourceId::77"
    assert disassembly_payload.data['target'] == "mock-target"
    assert disassembly_payload.data['disassembly'] == "disassembly:mock-target"

    monkeypatch.setattr(
        _FakeShaderPipe,
        "GetShaderReflection",
        lambda self, stage: SimpleNamespace(
            entryPoint="main", readOnlyResources=[], readWriteResources=[], constantBlocks=[]
        ),
    )
    missing_debug_payload = asyncio.run(
            shader_ops.dispatch(
                "get_reflection", {"session_id": "sess_demo", "event_id": 314, "stage": "ps"}
            )
        )
    assert missing_debug_payload.data['reflection']["debug_info"] == {
        "debuggable": None,
        "source_debug_information": None,
        "status": None,
    }

    monkeypatch.setattr(
        _FakeShaderPipe,
        "GetShaderReflection",
        lambda self, stage: SimpleNamespace(
            entryPoint="main", readOnlyResources=[], readWriteResources=[], constantBlocks=[],
            debugInfo=SimpleNamespace(debuggable=True),
        ),
    )
    partial_debug_payload = asyncio.run(
            shader_ops.dispatch(
                "get_reflection", {"session_id": "sess_demo", "event_id": 314, "stage": "ps"}
            )
        )
    assert partial_debug_payload.data['reflection']["debug_info"] == {
        "debuggable": True,
        "source_debug_information": None,
        "status": None,
    }


def test_shader_get_constant_buffer_contents_returns_decoded_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _inline_offload(fn, *args, **kwargs):  # type: ignore[no-untyped-def]
        return fn(*args, **kwargs)

    async def _fake_get_controller(session_id: str):  # type: ignore[no-untyped-def]
        return _FakeShaderController()

    async def _fake_ensure_event(session_id: str, event_id: int | None) -> int:
        return int(event_id or 314)

    class NativeShaderId:
        def __str__(self):
            return "ResourceId::77"

    native_shader = NativeShaderId()
    monkeypatch.setattr(_FakeShaderPipe, "GetShader", lambda self, stage: native_shader if stage == "ps" else "ResourceId::0")

    async def _fake_collect_constant_buffers(*args, **kwargs):  # type: ignore[no-untyped-def]
        assert args[4] is native_shader, "native decoder requires ResourceId, not its serialized string"
        return [
            {
                "stage": "PS",
                "slot": 2,
                "resource_id": "ResourceId::cb0",
                "offset": 16,
                "size": 64,
                "block_name": "Globals",
                "vars": [{"name": "Tint", "type": "float4"}],
                "contents": [{"name": "Tint", "value": {"f32v": [1.0, 0.0, 0.0, 1.0]}}],
                "flattened_contents": {"Tint": [1.0, 0.0, 0.0, 1.0]},
            }
        ]

    monkeypatch.setattr(renderdoc_api, "_offload", _inline_offload)
    monkeypatch.setattr(replay_access, "_get_controller", _fake_get_controller)
    monkeypatch.setattr(replay_access, "_ensure_event", _fake_ensure_event)
    monkeypatch.setattr(renderdoc_api, "_rd_stage", lambda stage: stage)
    monkeypatch.setattr(shader_values, "_collect_constant_buffers", _fake_collect_constant_buffers)

    payload = asyncio.run(
            shader_ops.dispatch(
                "get_constant_buffer_contents",
                {
                    "session_id": "sess_demo",
                    "event_id": 314,
                    "stage": "ps",
                    "slot": 2,
                },
            )
        )

    assert payload.ok is True
    assert payload.data['resolved_event_id'] == 314
    assert payload.data['shader_id'] == "ResourceId::77"
    assert payload.data['cbuffer']["slot"] == 2
    assert payload.data['cbuffer']["contents"][0]["name"] == "Tint"


def test_texture_get_data_defaults_to_npz_container(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import io
    import base64
    import numpy as np

    pixels = np.arange(16, dtype=np.float32).reshape(2, 2, 4)
    async def resolve(session_id, resource_id):
        return resource_id
    async def controller(session_id):
        return SimpleNamespace()
    async def read(session_id, event_id, resource_id, manager, subresource):
        assert event_id == 314
        return pixels, {"event_id": event_id, "pixels": 4}
    async def at_state(session_id, resource_id, args, reader):
        return await reader(314), {"state": "current", "resolved_event_id": 314,
                                  "restored_event_id": 11, "replay_state_restored": True}
    monkeypatch.setattr(replay_access, "_resolve_resource_id", resolve)
    monkeypatch.setattr(replay_access, "_get_controller", controller)
    monkeypatch.setattr(texture_export, "_read_at_capture_state", at_state)
    monkeypatch.setattr(live_state, "_render_service", SimpleNamespace(read_texture_array=read))
    output = tmp_path / "readback.npz"
    payload = asyncio.run(texture_ops.dispatch("get_data", {
        "session_id": "sess_demo", "event_id": 314, "texture_id": "ResourceId::178817",
        "output_path": str(output), "as_base64": True,
    }))
    assert payload.ok is True
    assert payload.data['container_format'] == "npz"
    assert payload.data['content_kind'] == "texture_readback_container"
    assert payload.data['artifact_path'] == str(output)
    assert payload.data['saved_path'] == str(output)
    assert payload.data['texture_id'] == "ResourceId::178817"
    assert payload.data['target_metadata']["texture_id"] == payload.data['texture_id']
    assert payload.data['resolved_event_id'] == 314
    assert payload.data['restored_event_id'] == 11 and payload.data['replay_state_restored'] is True
    data = base64.b64decode(payload.data['base64'])
    assert output.read_bytes() == data
    with np.load(io.BytesIO(data)) as archive:
        np.testing.assert_array_equal(archive["pixels"], pixels)


def test_texture_get_data_rejects_non_npz_output_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    async def _fake_ensure_event(session_id: str, event_id: int | None) -> int:
        return int(event_id or 314)

    async def _fake_resolve_texture_id(session_id: str, texture_id: object, *, event_id: int | None = None) -> str:
        return str(texture_id)

    async def _fake_readback_texture(
        *,
        session_id: str,
        event_id: int,
        texture_id: str,
        session_manager: object,
        artifact_store: object,
        subresource: dict[str, int] | None,
        region: dict[str, int] | None,
    ) -> tuple[SimpleNamespace, dict[str, object]]:
        return SimpleNamespace(sha256="deadbeef", bytes=128), {"event_id": int(event_id)}

    artifact_path = tmp_path / "readback.npz"
    artifact_path.write_bytes(b"npz-payload")

    monkeypatch.setattr(replay_access, "_ensure_event", _fake_ensure_event)
    monkeypatch.setattr(replay_access, "_resolve_texture_id", _fake_resolve_texture_id)
    monkeypatch.setattr(artifact_payloads, "_artifact_path", lambda artifact_ref: str(artifact_path))
    live_state._session_manager = SimpleNamespace()
    live_state._render_service = SimpleNamespace(readback_texture=_fake_readback_texture)

    payload = asyncio.run(
            texture_ops.dispatch(
                "get_data",
                {
                    "session_id": "sess_demo",
                    "event_id": 314,
                    "texture_id": "ResourceId::178817",
                    "output_path": str(tmp_path / "preview.png"),
                },
            )
        )

    assert payload.ok is False
    assert payload.code == "texture_output_path_extension_mismatch"


@pytest.mark.parametrize("budget,expected_size,truncated", [(4, 4, True), (8, 8, False), (0, 8, False)])
def test_shader_get_constant_buffer_contents_returns_raw_fallback_when_decode_unavailable(monkeypatch: pytest.MonkeyPatch, budget, expected_size, truncated) -> None:
    async def _inline_offload(fn, *args, **kwargs):  # type: ignore[no-untyped-def]
        return fn(*args, **kwargs)

    class _RawController(_FakeShaderController):
        def GetBufferData(self, resource_id: object, offset: int, size: int) -> bytes:
            assert resource_id == "ResourceId::cb0"
            assert offset == 16
            assert size == expected_size
            return b"ABCDEFGH"[:expected_size]

    async def _fake_get_controller(session_id: str):  # type: ignore[no-untyped-def]
        return _RawController()

    async def _fake_ensure_event(session_id: str, event_id: int | None) -> int:
        return int(event_id or 314)

    async def _fake_resolve_resource_id(session_id: str, resource_id: object):  # type: ignore[no-untyped-def]
        return str(resource_id)

    async def _fake_collect_constant_buffers(*args, **kwargs):  # type: ignore[no-untyped-def]
        return [
            {
                "stage": "PS",
                "slot": 2,
                "resource_id": "ResourceId::cb0",
                "offset": 16,
                "byte_size": 8,
                "block_name": "Globals",
                "contents": [],
                "flattened_contents": {},
            }
        ]

    monkeypatch.setattr(renderdoc_api, "_offload", _inline_offload)
    monkeypatch.setattr(replay_access, "_get_controller", _fake_get_controller)
    monkeypatch.setattr(replay_access, "_ensure_event", _fake_ensure_event)
    monkeypatch.setattr(renderdoc_api, "_rd_stage", lambda stage: stage)
    monkeypatch.setattr(replay_access, "_resolve_resource_id", _fake_resolve_resource_id)
    monkeypatch.setattr(shader_values, "_collect_constant_buffers", _fake_collect_constant_buffers)

    payload = asyncio.run(
            shader_ops.dispatch(
                "get_constant_buffer_contents",
                {
                    "session_id": "sess_demo",
                    "event_id": 314,
                    "stage": "ps",
                    "slot": 2,
                    "max_bytes": budget,
                },
            )
        )

    assert payload.ok is True
    assert payload.data['cbuffer']["decode_status"] == "raw_fallback"
    assert payload.data['cbuffer']["raw_fallback"]["byte_size"] == expected_size
    assert payload.data['cbuffer']["raw_fallback"]["hex_preview"] == b"ABCDEFGH"[:expected_size].hex()
    assert payload.data['cbuffer']["raw_fallback"]["truncated"] is truncated
    assert payload.data['cbuffer']["raw_fallback"]["preview_truncated"] is False
    assert payload.data['cbuffer']["raw_fallback"]["recommended_next_tool"] == "rd.export.buffer"


def test_constant_buffer_slot_is_reflection_index_not_removed_bindpoint(monkeypatch):
    reads = []
    blocks = [SimpleNamespace(name=f"block{i}", fixedBindNumber=20+i,
                              fixedBindSetOrSpace=2, variables=[], byteSize=16) for i in range(4)]
    def get_block(stage, index, array_index):
        reads.append((stage, index, array_index))
        return SimpleNamespace(descriptor=SimpleNamespace(resource="ResourceId::cb", byteOffset=32, byteSize=16),
                               access=SimpleNamespace(index=index, type=9))
    def get_values(*args):
        assert args[4:8] == (3, "ResourceId::cb", 32, 16)
        return []
    async def offload(fn, *args):
        return fn(*args)
    monkeypatch.setattr(renderdoc_api, "_offload", offload)
    monkeypatch.setattr(renderdoc_api, "_rd_stage", lambda stage: stage)
    monkeypatch.setattr(renderdoc_api, "_get_rd", lambda: SimpleNamespace(ResourceId=lambda: None))
    monkeypatch.setattr(shader_values, "_pipeline_object_for_cbuffer", lambda *_: "pipeline")
    pipe = SimpleNamespace(GetConstantBlock=get_block)
    reflection = SimpleNamespace(constantBlocks=blocks, entryPoint="main")
    result = asyncio.run(shader_values._collect_constant_buffers(
        SimpleNamespace(GetCBufferVariableContents=get_values), pipe, reflection, "ps", "shader",
        slot=3, array_index=1, include_contents=True))
    assert reads == [("ps", 3, 1)]
    assert len(result) == 1
    assert result[0]["slot"] == result[0]["block_index"] == 3
    assert result[0]["set_or_space"] == 2
    assert result[0]["resource_id"] == "ResourceId::cb"
    assert result[0]["offset"] == 32
    assert result[0]["contents"] == []
    assert asyncio.run(shader_values._collect_constant_buffers(
        SimpleNamespace(), pipe, reflection, "ps", "shader", slot=9)) == []


@pytest.mark.parametrize("failure,restore", [("slot", "ok"), ("decode", "ok"),
    ("slot", "raises"), ("slot", "mismatch"), ("slot", "unknown")])
def test_constant_buffer_failure_restores_original_event_without_success(monkeypatch, failure, restore):
    active = [0 if restore == "unknown" else 11]
    events = []
    async def ensure(session_id, event_id):
        events.append(event_id)
        if event_id == 11 and restore == "raises":
            raise RuntimeError("restore failed")
        active[0] = 99 if event_id == 11 and restore == "mismatch" else event_id
        return active[0]
    async def offload(fn, *args):
        return fn(*args)
    async def controller(_):
        return _FakeShaderController()
    async def buffers(*args, **kwargs):
        return [] if failure == "slot" else [{"contents": [], "flattened_contents": {}}]
    monkeypatch.setattr(replay_access, "_active_event", lambda _: active[0])
    monkeypatch.setattr(live_state, "_runtime_context_id", lambda: "owned-context")
    monkeypatch.setattr(replay_access, "_ensure_event", ensure)
    monkeypatch.setattr(renderdoc_api, "_offload", offload)
    monkeypatch.setattr(replay_access, "_get_controller", controller)
    monkeypatch.setattr(renderdoc_api, "_rd_stage", lambda stage: stage)
    monkeypatch.setattr(shader_values, "_collect_constant_buffers", buffers)
    payload = asyncio.run(shader_ops.dispatch("get_constant_buffer_contents",
        {"session_id": "sess_demo", "event_id": 314, "stage": "ps", "slot": 8}))
    assert payload.ok is False
    if restore == "ok":
        assert payload.code == "constant_buffer_data_unavailable"
        assert payload.details["replay_state_restored"] is True
        assert payload.details["restored_event_id"] == active[0] == 11
        assert payload.details["context_id"] == "owned-context"
        assert payload.details["session_id"] == "sess_demo"
    elif restore == "unknown":
        assert payload.code == "constant_buffer_data_unavailable"
        assert "replay_state_restored" not in payload.details
    else:
        assert payload.code == "shader_inspection_recovery_failed"
        assert payload.details["replay_state_restored"] is False
        assert "restored_event_id" not in payload.details
    assert events == ([314] if restore == "unknown" else [314, 11])


@pytest.mark.parametrize("shape,stride,value_type", [
    ((1, 8, 4), 1, "float"), ((8, 8, 4), 1, "float"),
    ((1, 65, 4), 1, "float"), ((4, 4, 3), 2, "uint"),
])
def test_region_inline_view_matches_full_export_and_bound(monkeypatch, tmp_path, shape, stride, value_type) -> None:
    source = np.arange(np.prod(shape), dtype=np.float32).reshape(shape)
    captured = []
    async def read(*args, **kwargs):
        return source, {"source_format": "decoded fixture"}
    async def store(data, **kwargs):
        captured.append(data)
        return SimpleNamespace(sha256="region")
    async def ensure(session, event):
        return event
    async def resolve(session, texture, **kwargs):
        return texture
    async def truth(*args):
        return {"binding_truth_level": "binding_verified", "evidence_truth_level": "structured_readback"}
    monkeypatch.setattr(replay_access, "_ensure_event", ensure)
    monkeypatch.setattr(replay_access, "_resolve_texture_id", resolve)
    monkeypatch.setattr(truth_matrix, "_event_truth_metadata", truth)
    monkeypatch.setattr(live_state, "_render_service", SimpleNamespace(read_texture_array=read))
    monkeypatch.setattr(live_state, "_artifact_store", SimpleNamespace(store=store, get_path=lambda _: tmp_path / "region.npz"))
    result = asyncio.run(texture_ops.dispatch("get_region_values", {
        "session_id": "session", "event_id": 9, "texture_id": "texture",
        "rect": {"x": 3, "y": 5, "w": shape[1], "h": shape[0]}, "stride": stride, "as_type": value_type,
    }))
    expected = source[::stride, ::stride].astype(np.uint32 if value_type == "uint" else np.float64)
    assert result.ok is True
    assert len(captured) == 1
    with np.load(io.BytesIO(captured[0])) as data:
        np.testing.assert_array_equal(data["pixels"], expected)
    assert result.data['inline_value_limit'] == 256
    if expected.size <= 256:
        assert result.data['values_status'] == "complete"
        assert result.data['values'] == expected.tolist()
    else:
        assert result.data['values_status'] == "omitted_limit"
        assert result.data['values'] is None
    assert result.data['stats']["shape"] == list(expected.shape)
    assert result.data['stats']["stride"] == stride
    assert result.data['stats']["channels"]["r"]["min"] == float(expected[..., 0].min())
    assert result.data['stats']["channels"]["r"]["mean"] == float(expected[..., 0].mean())
    assert result.data['target_metadata']["region"] == {"x": 3, "y": 5, "width": shape[1], "height": shape[0]}


def test_region_inline_nonfinite_values_remain_explicit_and_channel_stats_finite(monkeypatch, tmp_path) -> None:
    source = np.array([[[np.nan, np.inf, -np.inf, 1.0], [np.nan, 2.0, 3.0, 1.0]]])
    writes = []
    async def read(*args, **kwargs):
        return source, {}
    async def store(*args, **kwargs):
        writes.append(True)
        return SimpleNamespace(sha256="region")
    async def ensure(session, event):
        return event
    async def resolve(session, texture, **kwargs):
        return texture
    async def truth(*args):
        return {}
    monkeypatch.setattr(replay_access, "_ensure_event", ensure)
    monkeypatch.setattr(replay_access, "_resolve_texture_id", resolve)
    monkeypatch.setattr(truth_matrix, "_event_truth_metadata", truth)
    monkeypatch.setattr(live_state, "_render_service", SimpleNamespace(read_texture_array=read))
    monkeypatch.setattr(live_state, "_artifact_store", SimpleNamespace(store=store, get_path=lambda _: tmp_path / "region.npz"))
    args = {"session_id": "session", "event_id": 9, "texture_id": "texture", "rect": {"x": 0, "y": 0, "w": 2, "h": 1}}
    result = asyncio.run(texture_ops.dispatch("get_region_values", args))
    assert result.data['values'] == [[["NaN", "Infinity", "-Infinity", 1.0], ["NaN", 2.0, 3.0, 1.0]]]
    assert result.data['stats']["channels"]["r"] == {"min": None, "max": None, "mean": None, "nan_count": 2, "inf_count": 0}
    assert result.data['stats']["channels"]["g"]["mean"] == 2.0
    assert result.data['stats']["channels"]["b"]["mean"] == 3.0
    assert result.data['stats']["channels"]["a"]["mean"] == 1.0
    whole = asyncio.run(texture_ops.dispatch("compute_stats", {
        "session_id": "session", "event_id": 9, "texture_id": "texture",
    }))
    assert whole.data['stats']["channels"] == result.data['stats']["channels"]
    assert writes == [True]  # Statistics stay in memory; only explicit region readback exported.
    integer_result = asyncio.run(texture_ops.dispatch("get_region_values", {**args, "as_type": "int"}))
    assert integer_result.ok is False
    assert integer_result.code == "texture_nonfinite_data"
    assert writes == [True]
