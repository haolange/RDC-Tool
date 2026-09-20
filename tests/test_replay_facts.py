from types import SimpleNamespace as NS
import hashlib
import struct
from rdc_tool.core.replay_facts import mesh_attributes, shader_content_hash, usage_access


def test_shader_hash_is_content_based_and_missing_is_null():
    assert shader_content_hash(NS(rawBytes=b"shader")) == hashlib.sha256(b"shader").hexdigest()
    assert shader_content_hash(NS()) is None
    assert shader_content_hash(NS(rawBytes=b"")) is None


def test_usage_uses_native_identity_and_keeps_unknown_unknown():
    rd = NS(ResourceUsage=NS(PS_Resource=1, PS_RWResource=2, ColorTarget=3, CopyDst=4, Barrier=5))
    assert usage_access(rd, 1)["is_read"] is True
    assert usage_access(rd, 1)["is_write"] is False
    assert usage_access(rd, 2)["is_write"] is True
    assert usage_access(rd, 3)["is_read"] is None
    assert usage_access(rd, 4)["is_write"] is True
    assert usage_access(rd, 5)["is_write"] is None
    assert usage_access(rd, "PS_RWResource")["is_write"] is None
    assert usage_access(rd, 999)["usage_name"] is None


def test_mesh_only_decodes_proven_layout_and_finite_position():
    rd = NS(CompType=NS(Float=1))
    mesh = NS(format=NS(compType=1, compByteWidth=4, compCount=4))
    rows = [{"vertex_index": 0}]
    result = mesh_attributes(rd, mesh, struct.pack("<ffff", 1, 2, 3, 1), 16, rows)
    assert rows[0]["position"] == [1, 2, 3, 1]
    assert result["position"]["status"] == "present"
    assert result["normal"]["status"] == result["uv"]["status"] == "unsupported"
    result = mesh_attributes(rd, mesh, struct.pack("<ffff", float("nan"), 0, 0, 1), 16, rows)
    assert rows[0]["position"] is None
    assert result["position"]["status"] == "unsupported"
    mesh.format.compType = 999
    assert mesh_attributes(rd, mesh, bytes(16), 16, rows)["position"]["status"] == "unsupported"
