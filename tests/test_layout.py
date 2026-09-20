from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_catalog_has_unique_tools_and_declared_count() -> None:
    catalog = ROOT / "spec" / "tool_catalog.json"
    payload = json.loads(catalog.read_text(encoding="utf-8"))
    tools = payload.get("tools", [])
    names = [str(t.get("name", "")).strip() for t in tools]
    declared_count = int(payload.get("tool_count") or len(names))
    assert len(names) == declared_count
    assert len(set(names)) == len(names)
    assert all(n.startswith("rd.") for n in names)


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


def test_catalog_boundaries_remove_pre_ga_surfaces_and_expand_export_params() -> None:
    catalog = ROOT / "spec" / "tool_catalog.json"
    payload = json.loads(catalog.read_text(encoding="utf-8"))
    tools = payload.get("tools", [])
    names = {str(t.get("name", "")).strip() for t in tools}
    from rdc_tool.operation_definitions import OPERATIONS
    assert int(payload.get("tool_count") or 0) == len(OPERATIONS)
    assert names == {item["name"] for item in OPERATIONS}

    removed = {
        "rd.resource.rename",
        "rd.shader.save_binary",
        "rd.app.is_available",
        "rd.app.start_frame_capture",
        "rd.app.end_frame_capture",
        "rd.app.trigger_capture",
        "rd.app.set_capture_option",
        "rd.app.get_capture_options",
        "rd.app.push_marker",
        "rd.app.pop_marker",
        "rd.app.set_marker",
        "rd.texture.save_to_file",
        "rd.buffer.save_to_file",
        "rd.mesh.export",
        "rd.analysis.get_frame_stats",
        "rd.analysis.get_event_stats",
        "rd.analysis.get_warnings",
        "rd.analysis.estimate_overdraw",
        "rd.macro.generate_pass_summary",
        "rd.macro.locate_draw_affecting_pixel",
        "rd.macro.trace_resource_lifetime",
        "rd.macro.find_nan_inf_in_targets",
        "rd.core.search_tools",
        "rd.capture.list_frames",
        "rd.session.select_context",
        "rd.event.get_actions",
        "rd.event.get_drawcall_children",
        "rd.event.get_marker_stack",
        "rd.pipeline.get_state_summary",
        "rd.pipeline.get_vertex_input",
        "rd.pipeline.get_primitive_topology",
        "rd.pipeline.get_viewports_scissors",
        "rd.pipeline.get_rasterizer_state",
        "rd.pipeline.get_multisample_state",
        "rd.pipeline.get_blend_state",
        "rd.pipeline.get_depth_stencil_state",
        "rd.pipeline.get_output_targets",
        "rd.pipeline.get_render_targets",
        "rd.pipeline.get_depth_target",
        "rd.pipeline.get_uav_bindings",
        "rd.pipeline.get_sampler_bindings",
        "rd.pipeline.get_push_constants",
        "rd.pipeline.get_dynamic_state",
        "rd.pipeline.get_root_signature",
        "rd.pipeline.get_descriptor_heaps",
        "rd.pipeline.get_resource_states",
        "rd.resource.list_textures",
        "rd.resource.list_buffers",
        "rd.resource.get_history",
        "rd.resource.get_initial_contents",
        "rd.resource.get_current_contents",
        "rd.resource.get_descriptor_info",
        "rd.resource.get_creation_context",
        "rd.texture.get_subresource_data",
        "rd.texture.get_min_max",
        "rd.texture.save_mip_chain",
        "rd.mesh.get_post_vs_data",
        "rd.mesh.get_post_gs_data",
        "rd.mesh.decode_vertex_data",
        "rd.mesh.get_mesh_preview",
        "rd.debug.pixel_history",
        "rd.debug.explain_test_failure",
        "rd.perf.get_pipeline_statistics",
        "rd.diag.check_render_targets",
        "rd.diag.check_depth_stencil",
        "rd.diag.check_viewport_scissor",
        "rd.diag.check_culling",
        "rd.diag.check_blend",
        "rd.diag.check_srgb",
        "rd.diag.check_resource_bindings",
        "rd.diag.check_constant_buffers",
        "rd.diag.check_d3d12_resource_states",
        "rd.diag.check_vk_dynamic_state",
        "rd.export.pipeline_state_json",
        "rd.export.event_tree_json",
        "rd.export.resource_list_csv",
        "rd.export.pixel_history_json",
        "rd.export.repro_bundle_zip",
        "rd.export.markdown_report",
        "rd.remote.set_overlay_options",
        "rd.macro.summarize_frame",
        "rd.macro.find_pass_by_marker",
        "rd.macro.explain_pixel",
        "rd.macro.resource_dependency_graph",
        "rd.macro.compare_events_report",
        "rd.macro.find_unexpected_clear",
        "rd.macro.quick_triage_missing_draw",
        "rd.macro.build_bug_report_pack",
        "rd.macro.shader_hotfix_validate",
        "rd.util.compute_hash",
        "rd.util.diff_text",
        "rd.util.pack_zip",
    }
    assert not (removed & names)
    assert "rd.mesh.get_post_transform_data" in names

    export_texture = next(tool for tool in tools if tool.get("name") == "rd.export.texture")
    export_buffer = next(tool for tool in tools if tool.get("name") == "rd.export.buffer")
    export_mesh = next(tool for tool in tools if tool.get("name") == "rd.export.mesh")
    core_init = next(tool for tool in tools if tool.get("name") == "rd.core.init")

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
    assert "enable_app_api" not in set(core_init.get("param_names", []))


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
        ROOT / "intermediate" / "runtime" / "rdc_tool_cli",
        ROOT / "intermediate" / "runtime" / "worker-state",
        ROOT / "intermediate" / "artifacts",
        ROOT / "intermediate" / "pytest",
        ROOT / "intermediate" / "logs",
    ]
    for p in required:
        assert p.is_dir(), str(p)
    assert (ROOT / "bin" / "rdc-tool").is_file()


def test_runtime_manifest_declares_bundled_python_and_required_runtime_files() -> None:
    manifest = ROOT / "binaries" / "windows" / "x64" / "manifest.runtime.json"
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    files = payload.get("files")
    assert isinstance(files, list) and files

    bundled_python = payload.get("bundled_python")
    assert isinstance(bundled_python, dict)
    for key in (
        "python_version",
        "python_entry",
        "pythonw_entry",
        "python3_dll",
        "python_dll",
        "stdlib_layout",
        "site_packages",
        "dll_dir",
        "pth_file",
    ):
        assert str(bundled_python.get(key) or "").strip(), key

    indexed = {str(item.get("path") or ""): item for item in files if isinstance(item, dict)}
    assert str(bundled_python["python_entry"]) in indexed
    assert str(bundled_python["python_dll"]) in indexed
    assert "renderdoc.dll" in indexed
    assert "pymodules/renderdoc.pyd" in indexed
    removed_field = "worker_" + "materialize"
    assert all(removed_field not in item for item in files if isinstance(item, dict))
