from __future__ import annotations

import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def test_pipeline_stage_schema_defers_names_to_structured_runtime_validation() -> None:
    from rdc_tool.runtime_catalog import describe_operation, validate_operation_arguments

    for action in ("get_shader", "get_stage_state", "get_constant_buffers", "get_resource_bindings"):
        operation = f"rd.pipeline.{action}"
        stage = describe_operation(operation)["input_schema"]["properties"]["stage"]
        assert stage["type"] == "string"
        assert "enum" not in stage
        for value in ("PS", "ps", "RT", "rt", "not-a-stage"):
            validate_operation_arguments(operation, {"session_id": "sess_demo", "stage": value, "event_id": 1248})
        with pytest.raises(ValueError, match="must have type string"):
            validate_operation_arguments(operation, {"session_id": "sess_demo", "stage": 1})


def test_shader_disassembly_keeps_canonical_stage_vocabulary() -> None:
    from rdc_tool.runtime_catalog import describe_operation, validate_operation_arguments

    for operation in ("rd.shader.get_disassembly",):
        stage = describe_operation(operation)["input_schema"]["properties"]["stage"]
        assert stage["enum"] == ["vs", "hs", "ds", "gs", "ps", "cs", "ms", "as"]
        validate_operation_arguments(operation, {"session_id": "sess_demo", "stage": "ps", "event_id": 1248})
        with pytest.raises(ValueError, match="must be one of"):
            validate_operation_arguments(operation, {"session_id": "sess_demo", "stage": "pixel", "event_id": 1248})


def test_catalog_has_unique_tools_and_declared_count() -> None:
    catalog = ROOT / "spec" / "tool_catalog.json"
    payload = json.loads(catalog.read_text(encoding="utf-8"))
    tools = payload.get("tools", [])
    names = [str(t.get("name", "")).strip() for t in tools]
    declared_count = int(payload.get("tool_count") or len(names))
    assert len(names) == declared_count
    assert len(set(names)) == len(names)
    assert all(n.startswith("rd.") for n in names)


def test_read_only_replay_queries_do_not_claim_a_position_change() -> None:
    from rdc_tool.operation_definitions import OPERATIONS

    effects = {item["name"]: item["effects"] for item in OPERATIONS}
    for name in (
        "rd.event.get_active",
        "rd.event.get_action_details",
        "rd.resource.get_details",
    ):
        assert effects[name] == []
    assert "replay_position" in effects["rd.event.set_active"]
    assert "replay_position" in effects["rd.export.screenshot"]


def test_catalog_uses_repo_relative_source_path_and_readable_groups() -> None:
    catalog = ROOT / "spec" / "tool_catalog.json"
    payload = json.loads(catalog.read_text(encoding="utf-8"))
    assert payload.get("source_path") == "rdc_tool/operation_definitions.py"
    assert isinstance(payload.get("fingerprint"), str) and len(payload["fingerprint"]) == 64
    groups = payload.get("groups", {})
    assert isinstance(groups, dict)
    assert groups
    for group_name in groups:
        text = str(group_name)
        assert "?" not in text
        assert "\ufffd" not in text
        assert "Context Snapshot Tools" in text or "????" not in text


def test_catalog_matches_definitions_and_export_params() -> None:
    catalog = ROOT / "spec" / "tool_catalog.json"
    payload = json.loads(catalog.read_text(encoding="utf-8"))
    tools = payload.get("tools", [])
    names = {str(t.get("name", "")).strip() for t in tools}
    from rdc_tool.operation_definitions import OPERATIONS
    assert int(payload.get("tool_count") or 0) == len(OPERATIONS)
    assert names == {item["name"] for item in OPERATIONS}

    assert "rd.mesh.get_post_transform_data" in names

    export_texture = next(tool for tool in tools if tool.get("name") == "rd.export.texture")
    export_buffer = next(tool for tool in tools if tool.get("name") == "rd.export.buffer")
    export_mesh = next(tool for tool in tools if tool.get("name") == "rd.export.mesh")

    assert {"channels", "flip_y", "subresource", "file_format", "remap"} <= set(export_texture.get("param_names", []))
    assert {"buffer_id", "offset", "size", "output_path"} <= set(export_buffer.get("param_names", []))
    assert {"include_attributes", "space", "format", "output_path"} <= set(export_mesh.get("param_names", []))
    mesh_properties = export_mesh["input_schema"]["properties"]
    assert mesh_properties["format"]["enum"] == ["obj"]
    assert mesh_properties["space"] == {"type": "string", "enum": ["postvs", "vs_input"], "default": "postvs"}
    assert mesh_properties["include_attributes"] == {"type": "boolean", "default": False}
    mesh_input = next(tool for tool in tools if tool.get("name") == "rd.mesh.get_drawcall_mesh_config")
    assert mesh_input["input_schema"]["properties"]["instance"] == {"type": "integer", "minimum": 0, "default": 0}
    assert mesh_input["input_schema"]["properties"]["max_vertices"] == {"type": "integer", "minimum": 0, "default": 128}


def test_required_directories_exist() -> None:
    required = [
        ROOT / "rdc_tool",
        ROOT / "bin",
        ROOT / "cli",
        ROOT / "spec",
        ROOT / "policy",
        ROOT / "docs",
        ROOT / "tests",
        ROOT / "binaries" / "windows" / "x64" / "python",
        ROOT / "binaries" / "windows" / "x64" / "pymodules",
    ]
    for p in required:
        assert p.is_dir(), str(p)
    assert (ROOT / "bin" / "rdc-tool").is_file()


@pytest.mark.parametrize("override", [False, True])
def test_runtime_directories_are_created_on_demand(tmp_path, monkeypatch, override):
    from rdc_tool import runtime_paths as paths

    monkeypatch.setattr(paths, "tools_root", lambda: tmp_path / "checkout")
    monkeypatch.delenv("RDC_TOOL_INTERMEDIATE_ROOT", raising=False)
    state = tmp_path / ("owned-state" if override else "checkout/intermediate")
    if override:
        monkeypatch.setenv("RDC_TOOL_INTERMEDIATE_ROOT", str(state))
    assert not state.exists()
    paths.ensure_runtime_dirs()
    for directory in (paths.runtime_root(), paths.cli_runtime_dir(), paths.worker_state_dir(),
                      paths.artifacts_dir(), paths.pytest_dir(), paths.logs_dir()):
        assert directory.is_relative_to(state)
        assert directory.is_dir()
    if override:
        assert not (tmp_path / "checkout/intermediate").exists()


def test_runtime_manifest_records_bundled_python_provenance_and_layout_files() -> None:
    from rdc_tool.python_runtime import PROVENANCE_FIELDS
    from rdc_tool.runtime_paths import HOST_LAYOUTS, PYTHON_DIRECTORIES
    manifest = ROOT / "binaries" / "windows" / "x64" / "manifest.runtime.json"
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    files = payload.get("files")
    assert isinstance(files, list) and files
    bundled_python = payload.get("bundled_python")
    assert isinstance(bundled_python, dict)
    assert set(bundled_python) == set(PROVENANCE_FIELDS)
    assert all(str(bundled_python[key]).strip() for key in PROVENANCE_FIELDS)
    indexed = {str(item.get("path") or "") for item in files if isinstance(item, dict)}
    layout = HOST_LAYOUTS["windows-x64"]
    assert {relative for role, relative in layout.python.items() if role not in PYTHON_DIRECTORIES} <= indexed
    assert {"renderdoc.dll", "pymodules/renderdoc.pyd"} <= indexed
