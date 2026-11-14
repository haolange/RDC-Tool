from types import SimpleNamespace

import pytest

from rdc_tool.core.replay_facts import pixel_history_input_attachment_conflict


class Node:
    def __init__(self, name: str, value=None, children=None):
        self.name = name
        self.value = value
        self.children = children or {}

    def FindChild(self, name):
        return self.children.get(name)

    def AsResourceId(self):
        return self.value

    def AsInt(self):
        return self.value


@pytest.mark.parametrize(
    ("api", "flags", "input_event", "output_event", "query_event", "expected"),
    [
        ("vulkan", 0x10, 7, 7, 11, (7, 0x10)),
        ("vulkan", 0x90, 7, 7, 11, None),
        ("vulkan", 0x10, 7, 7, 5, None),
        ("vulkan", 0x10, 7, 8, 11, None),
        ("other", 0x10, 7, 7, 11, None),
    ],
)
def test_attachment_conflict_requires_matching_usage_and_creation_flags(
    api, flags, input_event, output_event, query_event, expected,
):
    rd = SimpleNamespace(GraphicsAPI=SimpleNamespace(Vulkan="vulkan"),
                         ResourceUsage=SimpleNamespace(InputTarget="input", ColorTarget="color",
                                                       DepthStencilTarget="depth"))
    chunk = Node("vkCreateImage", children={
        "Image": Node("Image", "texture"),
        "CreateInfo": Node("CreateInfo", children={"usage": Node("usage", flags)}),
    })
    controller = SimpleNamespace(
        GetAPIProperties=lambda: SimpleNamespace(pipelineType=api),
        GetUsage=lambda resource: [SimpleNamespace(eventId=input_event, usage="input"),
                                   SimpleNamespace(eventId=output_event, usage="color")],
        GetResources=lambda: [SimpleNamespace(resourceId="texture", initialisationChunks=[0])],
        GetStructuredFile=lambda: SimpleNamespace(chunks=[chunk]),
    )
    assert pixel_history_input_attachment_conflict(rd, controller, "texture", query_event) == expected
