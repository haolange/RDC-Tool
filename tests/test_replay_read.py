import asyncio
from types import SimpleNamespace as NS

import pytest

from rdc_tool.core.replay_read import InitialContentsUnavailable, ReplayRestoreError, initial_provenance, preserving_event
from rdc_tool.runtime_catalog import validate_operation_arguments


def test_read_failure_restores_event_before_propagating():
    async def scenario():
        restored = []
        controller = NS(SetFrameEvent=lambda event, force: restored.append((event, force)))

        async def read():
            raise ValueError("readback failed")

        with pytest.raises(ValueError, match="readback failed"):
            await preserving_event(controller, 11, read)
        assert restored == [(11, True)]


    asyncio.run(scenario())

def test_cancellation_drains_native_work_then_restores():
    async def scenario():
        started, finish = asyncio.Event(), asyncio.Event()
        order = []
        controller = NS(SetFrameEvent=lambda event, force: order.append(("restore", event)))

        async def read():
            started.set()
            await finish.wait()
            order.append("read finished")
            return b"data"

        task = asyncio.create_task(preserving_event(controller, 14, read))
        await started.wait()
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
        task.cancel()
        finish.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert order == ["read finished", ("restore", 14)]


    asyncio.run(scenario())

def test_restore_failure_never_returns_success():
    async def scenario():
        def restore(event, force):
            raise RuntimeError("device disconnected")

        async def read():
            return b"data"

        with pytest.raises(ReplayRestoreError, match="device disconnected"):
            await preserving_event(NS(SetFrameEvent=restore), 11, read)


    asyncio.run(scenario())

def test_api_query_exclusive_selection_and_bounds():
    valid = {"session_id": "s", "chunk_indices": [0]}
    validate_operation_arguments("rd.event.get_api_calls", valid)
    for invalid in ({"session_id": "s"}, {**valid, "event_id": 1},
                    {**valid, "chunk_indices": []}, {**valid, "chunk_indices": [0] * 1025}):
        with pytest.raises(ValueError):
            validate_operation_arguments("rd.event.get_api_calls", invalid)


@pytest.mark.parametrize("operation,resource", [("rd.texture.get_data", "texture_id"),
                                               ("rd.buffer.get_data", "buffer_id")])
def test_initial_state_rejects_event_override(operation, resource):
    with pytest.raises(ValueError):
        validate_operation_arguments(operation, {"session_id": "s", resource: "1",
                                               "state": "capture_initial", "event_id": 11})


def initial_fixture(fields, *, creation=0, parent=False, kind="Buffer"):
    class Field:
        def __init__(self, value):
            self.value = value

        def AsInt(self):
            return self.value

        def AsBool(self):
            return bool(self.value)

        def AsResourceId(self):
            return self.value

        def NumChildren(self):
            return len(self.value)

        def GetChild(self, index):
            return Field(self.value[index])

    values = {key: Field(value) for key, value in fields.items()}
    initial = NS(name="Internal::Initial Contents", FindChild=values.get)
    resource = NS(resourceId="resource", type=NS(name=kind), parentResources=["memory"] if parent else [],
                  initialisationChunks=[creation] if parent else [creation, 1])
    memory = NS(resourceId="memory", type=NS(name="Memory"), initialisationChunks=[0, 1])
    return NS(GetResources=lambda: [resource, memory],
              GetBuffers=lambda: [NS(resourceId="resource", length=16)],
              GetStructuredFile=lambda: NS(chunks=[NS(name="Create"), initial]),
              GetRootActions=lambda: [NS(events=[NS(chunkIndex=10)], children=[])])


def test_initial_provenance_requires_saved_complete_bytes_and_matching_resource():
    fields = {"id": "resource", "ContentsSize": 8, "Contents": b"saved", "IsSparse": False}
    assert initial_provenance(initial_fixture(fields), "resource")["chunk_indices"] == [1]
    for changed in ({"id": "other"}, {"ContentsSize": 0}, {"IsSparse": True}):
        with pytest.raises(InitialContentsUnavailable):
            initial_provenance(initial_fixture({**fields, **changed}), "resource")


def test_initial_parent_memory_cannot_prove_frame_created_resource():
    fields = {"id": "memory", "ContentsSize": 8, "Contents": b"saved"}
    assert initial_provenance(initial_fixture(fields, parent=True), "resource")["source_resource_id"] == "memory"
    with pytest.raises(InitialContentsUnavailable, match="did not exist"):
        initial_provenance(initial_fixture(fields, creation=12, parent=True), "resource")


def test_d3d12_initial_provenance_rejects_partial_subresource_coverage():
    fields = {"id": "resource", "ContentsLength": 16, "ResourceContents": b"saved",
              "subresourcesIncluded": [0xFFFFFFFF]}
    assert initial_provenance(initial_fixture(fields, kind="Texture"), "resource")["chunk_indices"] == [1]
    for coverage in ([], [0], [1, 2]):
        with pytest.raises(InitialContentsUnavailable):
            initial_provenance(initial_fixture({**fields, "subresourcesIncluded": coverage}, kind="Texture"), "resource")


def test_d3d12_buffer_coverage_uses_saved_length_not_texture_subresource_list():
    fields = {"id": "resource", "ContentsLength": 16, "ResourceContents": b"saved", "subresourcesIncluded": []}
    assert initial_provenance(initial_fixture(fields), "resource")["chunk_indices"] == [1]
    with pytest.raises(InitialContentsUnavailable):
        initial_provenance(initial_fixture({**fields, "ContentsLength": 8}), "resource")


@pytest.mark.parametrize("dimension,layer,format_type,coverage,accepted", [
    (2, 1, "Regular", [3], True),
    (2, 0, "Regular", [3], False),
    (2, 1, "D24S8", [3], False),
    (2, 1, "D24S8", [3, 7], True),
    (2, 1, "YUV8", [3], False),
    (2, 1, "YUV8", [3, 7], True),
    (3, 1, "Regular", [1], True),
    (3, 4, "Regular", [1], False),
])
def test_d3d12_selected_initial_subresource_requires_all_readback_planes(dimension, layer, format_type, coverage, accepted):
    fields = {"id": "resource", "ContentsLength": 16, "ResourceContents": b"saved", "subresourcesIncluded": coverage}
    controller = initial_fixture(fields, kind="Texture")
    controller.GetTextures = lambda: [NS(resourceId="resource", mips=2, arraysize=2 if dimension == 2 else 1,
        dimension=dimension, depth=4, format=NS(type=NS(name=format_type), YUVPlaneCount=lambda: 2))]
    selected = {"mip": 1, "slice": layer}
    if accepted:
        assert initial_provenance(controller, "resource", selected)["chunk_indices"] == [1]
    else:
        with pytest.raises(InitialContentsUnavailable):
            initial_provenance(controller, "resource", selected)


def test_read_and_restore_failures_both_survive():
    async def scenario():
        async def read():
            raise ValueError("readback unavailable")
        def restore(event, force):
            raise RuntimeError("device disconnected")
        with pytest.raises(ReplayRestoreError, match="device disconnected.*readback unavailable"):
            await preserving_event(NS(SetFrameEvent=restore), 11, read)
    asyncio.run(scenario())
