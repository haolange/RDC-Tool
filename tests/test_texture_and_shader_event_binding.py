from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import numpy as np

from rdc_tool import server


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
    original_render_service = server.server_runtime._render_service
    original_session_manager = server.server_runtime._session_manager
    try:
        yield
    finally:
        server.server_runtime._render_service = original_render_service
        server.server_runtime._session_manager = original_session_manager


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

    monkeypatch.setattr(server.server_runtime, "_ensure_event", _fake_ensure_event)
    monkeypatch.setattr(server.server_runtime, "_resolve_texture_id", _fake_resolve_texture_id)
    server.server_runtime._session_manager = SimpleNamespace()
    server.server_runtime._render_service = SimpleNamespace(
        pick_pixel=_fake_pick_pixel,
        read_texture_array=_fake_read_texture_array,
    )

    pixel_payload = json.loads(
        asyncio.run(
            server._dispatch_texture(
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
    )
    stats_payload = json.loads(
        asyncio.run(
            server._dispatch_texture(
                "compute_stats",
                {
                    "session_id": "sess_demo",
                    "event_id": 314,
                    "texture_id": "ResourceId::178817",
                },
            )
        )
    )

    assert pixel_payload["success"] is True
    assert pixel_payload["resolved_event_id"] == 314
    assert pixel_payload["pixel"]["event_id"] == 314
    assert pixel_payload["texture_id"] == "ResourceId::178817"
    assert pixel_payload["binding_truth_level"] == "binding_degraded"
    assert stats_payload["success"] is True
    assert stats_payload["resolved_event_id"] == 314
    assert stats_payload["stats"]["event_id"] == 314
    assert stats_payload["stats"]["channels"]["r"]["min"] == 0.25
    assert stats_payload["stats"]["channels"]["r"]["max"] == 0.25
    assert stats_payload["stats"]["channels"]["r"]["nan_count"] == 0
    assert stats_payload["stats"]["channels"]["r"]["inf_count"] == 0
    assert "artifact_path" not in stats_payload
    assert stats_payload["texture_id"] == "ResourceId::178817"
    assert seen_events == [314, 314]


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

    monkeypatch.setattr(server.server_runtime, "_ensure_event", _fake_ensure_event)
    monkeypatch.setattr(server.server_runtime, "_resolve_texture_id", _fake_resolve_texture_id)
    server.server_runtime._session_manager = SimpleNamespace()
    server.server_runtime._render_service = SimpleNamespace(read_texture_array=_fake_read_texture_array)

    histogram = json.loads(
        asyncio.run(
            server._dispatch_texture(
                "get_histogram",
                {"session_id": "sess_demo", "event_id": 41, "texture_id": "tex-a", "channels": "rg", "bins": 2},
            )
        )
    )
    difference = json.loads(
        asyncio.run(
            server._dispatch_texture(
                "diff",
                {
                    "session_id": "sess_demo",
                    "tex_a": {"texture_id": "tex-a", "event_id": 41},
                    "tex_b": {"texture_id": "tex-b", "event_id": 42},
                },
            )
        )
    )

    assert histogram["success"] is True
    assert histogram["resolved_event_id"] == 41
    assert set(histogram["histogram"]) == {"r", "g"}
    assert difference["success"] is True
    assert difference["diff"]["mse"] == pytest.approx(0.0625)
    assert read_calls == [(41, "tex-a"), (41, "tex-a"), (42, "tex-b")]
    assert "artifact_path" not in histogram
    assert "artifact_path" not in difference


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

    monkeypatch.setattr(server.server_runtime, "_ensure_event", _fake_ensure_event)
    monkeypatch.setattr(server.server_runtime, "_resolve_texture_id", _fake_resolve_texture_id)
    server.server_runtime._session_manager = SimpleNamespace()
    server.server_runtime._render_service = SimpleNamespace(read_texture_array=_fake_read_texture_array)

    invalid_bins = json.loads(
        asyncio.run(
            server._dispatch_texture(
                "get_histogram",
                {"session_id": "sess_demo", "texture_id": "same", "bins": 0},
            )
        )
    )
    invalid_range = json.loads(
        asyncio.run(
            server._dispatch_texture(
                "get_histogram",
                {"session_id": "sess_demo", "texture_id": "same", "range": {"min": 2.0, "max": 1.0}},
            )
        )
    )
    nonfinite = json.loads(
        asyncio.run(server._dispatch_texture("get_histogram", {"session_id": "sess_demo", "texture_id": "nan"}))
    )
    identical = json.loads(
        asyncio.run(
            server._dispatch_texture(
                "diff",
                {"session_id": "sess_demo", "tex_a": {"texture_id": "same"}, "tex_b": {"texture_id": "same"}},
            )
        )
    )
    shape_mismatch = json.loads(
        asyncio.run(
            server._dispatch_texture(
                "diff",
                {"session_id": "sess_demo", "tex_a": {"texture_id": "same"}, "tex_b": {"texture_id": "wide"}},
            )
        )
    )
    diff_nonfinite = json.loads(
        asyncio.run(
            server._dispatch_texture(
                "diff",
                {"session_id": "sess_demo", "tex_a": {"texture_id": "same"}, "tex_b": {"texture_id": "nan"}},
            )
        )
    )

    assert invalid_bins["success"] is False and invalid_bins["code"] == "validation_error"
    assert invalid_range["success"] is False and invalid_range["code"] == "validation_error"
    assert nonfinite["success"] is False and nonfinite["code"] == "texture_nonfinite_data"
    assert identical["success"] is True
    assert identical["diff"]["identical"] is True
    assert identical["diff"]["psnr"] is None
    assert identical["diff"]["psnr_status"] == "infinite"
    assert identical["event_a"] == 41 and identical["event_b"] == 41
    assert shape_mismatch["success"] is False and shape_mismatch["code"] == "texture_shape_mismatch"
    assert diff_nonfinite["success"] is False and diff_nonfinite["code"] == "texture_nonfinite_data"


def test_pixel_history_resolves_explicit_output_target_without_framebuffer_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Subresource:
        mip = 0
        slice = 0
        sample = 0

    resolution_calls: list[tuple[int, dict[str, int], bool]] = []

    async def _fake_get_controller(session_id: str) -> object:
        return object()

    async def _fake_ensure_event(session_id: str, event_id: int | None) -> int:
        return int(event_id or 77)

    async def _fake_resolve_visual_target_for_event(
        session_id: str,
        event_id: int,
        *,
        target: dict[str, int],
        allow_framebuffer_fallback: bool,
    ) -> tuple[str, object, dict[str, object], dict[str, object]]:
        resolution_calls.append((event_id, dict(target), allow_framebuffer_fallback))
        return "ResourceId::rt1", object(), {}, {}

    async def _fake_history(*args: object) -> list[object]:
        return []

    async def _fake_truth(session_id: str, event_id: int) -> dict[str, object]:
        return {"binding_truth_level": "binding_verified", "summary_degraded_reasons": []}

    monkeypatch.setattr(server.server_runtime, "_get_controller", _fake_get_controller)
    monkeypatch.setattr(server.server_runtime, "_ensure_event", _fake_ensure_event)
    monkeypatch.setattr(server.server_runtime, "_resolve_visual_target_for_event", _fake_resolve_visual_target_for_event)
    monkeypatch.setattr(server.server_runtime, "_pixel_history_raw_with_timeout", _fake_history)
    monkeypatch.setattr(server.server_runtime, "_event_truth_metadata", _fake_truth)
    monkeypatch.setattr(server.server_runtime, "_get_rd", lambda: SimpleNamespace(Subresource=_Subresource))
    server.server_runtime._render_service = object()

    payload = json.loads(
        asyncio.run(
            server._dispatch_texture(
                "get_pixel_history",
                {"session_id": "sess_demo", "event_id": 77, "target": {"rt_index": 1}, "x": 4, "y": 5},
            )
        )
    )
    conflict = json.loads(
        asyncio.run(
            server._dispatch_texture(
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
    )

    assert payload["success"] is True
    assert payload["texture_id"] == "ResourceId::rt1"
    assert payload["resolved_event_id"] == 77
    assert resolution_calls == [(77, {"rt_index": 1}, False)]
    assert conflict["success"] is False and conflict["code"] == "validation_error"


def test_shader_reflection_and_disassembly_support_stage_only_queries(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _inline_offload(fn, *args, **kwargs):  # type: ignore[no-untyped-def]
        return fn(*args, **kwargs)

    async def _fake_get_controller(session_id: str) -> _FakeShaderController:
        return _FakeShaderController()

    async def _fake_ensure_event(session_id: str, event_id: int | None) -> int:
        return int(event_id or 314)

    monkeypatch.setattr(server.server_runtime, "_offload", _inline_offload)
    monkeypatch.setattr(server.server_runtime, "_get_controller", _fake_get_controller)
    monkeypatch.setattr(server.server_runtime, "_ensure_event", _fake_ensure_event)
    monkeypatch.setattr(server.server_runtime, "_rd_stage", lambda stage: stage)
    monkeypatch.setattr(server.server_runtime, "_is_null_resource_id", lambda rid: str(rid) in {"", "ResourceId::0", "0"})
    monkeypatch.setattr(
        server.server_runtime.PatchEngine,
        "_resolve_source",
        staticmethod(lambda *args, **kwargs: ("disassembly:mock-target", "raw", "mock-target", False)),
    )

    reflection_payload = json.loads(
        asyncio.run(
            server._dispatch_shader(
                "get_reflection",
                {
                    "session_id": "sess_demo",
                    "event_id": 314,
                    "stage": "ps",
                },
            )
        )
    )
    disassembly_payload = json.loads(
        asyncio.run(
            server._dispatch_shader(
                "get_disassembly",
                {
                    "session_id": "sess_demo",
                    "event_id": 314,
                    "stage": "ps",
                },
            )
        )
    )

    assert reflection_payload["success"] is True
    assert reflection_payload["resolved_event_id"] == 314
    assert reflection_payload["shader_id"] == "ResourceId::77"
    assert reflection_payload["reflection"]["entry_points"] == ["main"]
    assert disassembly_payload["success"] is True
    assert disassembly_payload["resolved_event_id"] == 314
    assert disassembly_payload["shader_id"] == "ResourceId::77"
    assert disassembly_payload["target"] == "mock-target"
    assert disassembly_payload["disassembly"] == "disassembly:mock-target"


def test_shader_get_constant_buffer_contents_returns_decoded_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _inline_offload(fn, *args, **kwargs):  # type: ignore[no-untyped-def]
        return fn(*args, **kwargs)

    async def _fake_get_controller(session_id: str):  # type: ignore[no-untyped-def]
        return _FakeShaderController()

    async def _fake_ensure_event(session_id: str, event_id: int | None) -> int:
        return int(event_id or 314)

    async def _fake_collect_constant_buffers(*args, **kwargs):  # type: ignore[no-untyped-def]
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

    monkeypatch.setattr(server.server_runtime, "_offload", _inline_offload)
    monkeypatch.setattr(server.server_runtime, "_get_controller", _fake_get_controller)
    monkeypatch.setattr(server.server_runtime, "_ensure_event", _fake_ensure_event)
    monkeypatch.setattr(server.server_runtime, "_rd_stage", lambda stage: stage)
    monkeypatch.setattr(server.server_runtime, "_collect_constant_buffers", _fake_collect_constant_buffers)

    payload = json.loads(
        asyncio.run(
            server._dispatch_shader(
                "get_constant_buffer_contents",
                {
                    "session_id": "sess_demo",
                    "event_id": 314,
                    "stage": "ps",
                    "slot": 2,
                },
            )
        )
    )

    assert payload["success"] is True
    assert payload["resolved_event_id"] == 314
    assert payload["shader_id"] == "ResourceId::77"
    assert payload["cbuffer"]["slot"] == 2
    assert payload["cbuffer"]["contents"][0]["name"] == "Tint"


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
    monkeypatch.setattr(server.server_runtime, "_resolve_resource_id", resolve)
    monkeypatch.setattr(server.server_runtime, "_get_controller", controller)
    monkeypatch.setattr(server.server_runtime, "_read_at_capture_state", at_state)
    monkeypatch.setattr(server.server_runtime, "_render_service", SimpleNamespace(read_texture_array=read))
    output = tmp_path / "readback.npz"
    payload = json.loads(asyncio.run(server._dispatch_texture("get_data", {
        "session_id": "sess_demo", "event_id": 314, "texture_id": "ResourceId::178817",
        "output_path": str(output), "as_base64": True,
    })))
    assert payload["success"] is True
    assert payload["container_format"] == "npz"
    assert payload["content_kind"] == "texture_readback_container"
    assert payload["artifact_path"] == str(output)
    assert payload["saved_path"] == str(output)
    assert payload["texture_id"] == "ResourceId::178817"
    assert payload["target_metadata"]["texture_id"] == payload["texture_id"]
    assert payload["resolved_event_id"] == 314
    assert payload["restored_event_id"] == 11 and payload["replay_state_restored"] is True
    data = base64.b64decode(payload["base64"])
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

    monkeypatch.setattr(server.server_runtime, "_ensure_event", _fake_ensure_event)
    monkeypatch.setattr(server.server_runtime, "_resolve_texture_id", _fake_resolve_texture_id)
    monkeypatch.setattr(server.server_runtime, "_artifact_path", lambda artifact_ref: str(artifact_path))
    server.server_runtime._session_manager = SimpleNamespace()
    server.server_runtime._render_service = SimpleNamespace(readback_texture=_fake_readback_texture)

    payload = json.loads(
        asyncio.run(
            server._dispatch_texture(
                "get_data",
                {
                    "session_id": "sess_demo",
                    "event_id": 314,
                    "texture_id": "ResourceId::178817",
                    "output_path": str(tmp_path / "preview.png"),
                },
            )
        )
    )

    assert payload["success"] is False
    assert payload["code"] == "texture_output_path_extension_mismatch"


def test_shader_get_constant_buffer_contents_returns_raw_fallback_when_decode_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _inline_offload(fn, *args, **kwargs):  # type: ignore[no-untyped-def]
        return fn(*args, **kwargs)

    class _RawController(_FakeShaderController):
        def GetBufferData(self, resource_id: object, offset: int, size: int) -> bytes:
            assert resource_id == "ResourceId::cb0"
            assert offset == 16
            assert size == 8
            return b"ABCDEFGH"

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

    monkeypatch.setattr(server.server_runtime, "_offload", _inline_offload)
    monkeypatch.setattr(server.server_runtime, "_get_controller", _fake_get_controller)
    monkeypatch.setattr(server.server_runtime, "_ensure_event", _fake_ensure_event)
    monkeypatch.setattr(server.server_runtime, "_rd_stage", lambda stage: stage)
    monkeypatch.setattr(server.server_runtime, "_resolve_resource_id", _fake_resolve_resource_id)
    monkeypatch.setattr(server.server_runtime, "_collect_constant_buffers", _fake_collect_constant_buffers)

    payload = json.loads(
        asyncio.run(
            server._dispatch_shader(
                "get_constant_buffer_contents",
                {
                    "session_id": "sess_demo",
                    "event_id": 314,
                    "stage": "ps",
                    "slot": 2,
                    "max_bytes": 8,
                },
            )
        )
    )

    assert payload["success"] is True
    assert payload["cbuffer"]["decode_status"] == "raw_fallback"
    assert payload["cbuffer"]["raw_fallback"]["byte_size"] == 8
    assert payload["cbuffer"]["raw_fallback"]["hex_preview"] == "4142434445464748"
    assert payload["cbuffer"]["raw_fallback"]["recommended_next_tool"] == "rd.export.buffer"
