# Tool interface upgrade

This is a historical disposition record, not the current contract or an alias map. Current definitions are owned by `rdc_tool/operation_definitions.py`; see [public contract](public-contract.md) and [generated reference](tool-reference.md). Runtime aliases are not provided.

| Previous operation | Disposition |
|---|---|
| `rd.core.init` | Retained. |
| `rd.core.shutdown` | Retained. |
| `rd.core.get_version` | Retained. |
| `rd.core.get_capabilities` | Retained. |
| `rd.core.set_config` | Retained. |
| `rd.core.get_config` | Retained. |
| `rd.core.set_log_level` | Retained. |
| `rd.core.get_logs` | Retained. |
| `rd.core.healthcheck` | Retained. |
| `rd.capture.open_file` | Retained. |
| `rd.capture.close_file` | Retained. |
| `rd.capture.get_info` | Retained. |
| `rd.capture.get_thumbnail` | Removed. The entry never had a working implementation; request an explicit screenshot or observation after opening a replay. |
| `rd.capture.list_frames` | Removed. Capture and replay metadata now carry the available frame information; use `rd.capture.get_info` and `rd.replay.get_frame_info`. |
| `rd.capture.open_replay` | Retained. |
| `rd.capture.close_replay` | Retained. |
| `rd.replay.set_frame` | Retained. |
| `rd.replay.get_frame_info` | Retained. |
| `rd.event.set_active` | Retained. |
| `rd.event.get_active` | Retained. |
| `rd.replay.get_api_properties` | Retained. |
| `rd.replay.get_driver_info` | Retained. |
| `rd.event.get_actions` | Removed. Use `rd.event.get_action_tree` with root pagination and a node budget. |
| `rd.event.get_action_tree` | Retained. |
| `rd.event.get_action_details` | Retained. |
| `rd.event.get_drawcall_children` | Removed. `rd.event.get_action_details` returns direct child event IDs, and `rd.event.get_action_tree(event_id=...)` reads the subtree. |
| `rd.event.get_parent_chain` | Retained. |
| `rd.event.search_actions` | Retained. |
| `rd.event.list_passes` | Retained. |
| `rd.event.get_marker_stack` | Removed. Use the real marker information in `rd.event.get_parent_chain`. |
| `rd.event.get_api_calls` | Removed. RenderDoc does not provide the promised call stream through this runtime, so there is no replacement operation. |
| `rd.event.get_callstack` | Retained. |
| `rd.event.diff_pipeline_state` | Retained. |
| `rd.event.get_resource_usage` | Retained. |
| `rd.pipeline.get_state` | Retained. |
| `rd.pipeline.get_state_summary` | Removed. Use `rd.pipeline.get_state(detail=summary)` and request only the needed sections. |
| `rd.pipeline.get_stage_state` | Retained. |
| `rd.pipeline.get_vertex_input` | Removed. Use `rd.pipeline.get_vertex_buffers`, `rd.pipeline.get_index_buffer`, and the `topology` section of `rd.pipeline.get_state`. |
| `rd.pipeline.get_vertex_buffers` | Retained. |
| `rd.pipeline.get_index_buffer` | Retained. |
| `rd.pipeline.get_primitive_topology` | Removed. Use `rd.pipeline.get_state(sections=[topology])`. |
| `rd.pipeline.get_viewports_scissors` | Removed. Use `rd.pipeline.get_state(sections=[viewports_scissors])`. |
| `rd.pipeline.get_rasterizer_state` | Removed. The old entry did not return a complete, supported rasterizer contract; no replacement is advertised. |
| `rd.pipeline.get_multisample_state` | Removed. The old entry did not return supported multisample state; no replacement is advertised. |
| `rd.pipeline.get_blend_state` | Removed. Use `rd.pipeline.get_state(sections=[blend])`. |
| `rd.pipeline.get_depth_stencil_state` | Removed. Use `rd.pipeline.get_state(sections=[depth_stencil])`. |
| `rd.pipeline.get_output_targets` | Removed. Use `rd.pipeline.get_state(sections=[output_targets])`. |
| `rd.pipeline.get_render_targets` | Removed. Use `rd.pipeline.get_state(sections=[output_targets])`. |
| `rd.pipeline.get_depth_target` | Removed. Use `rd.pipeline.get_state(sections=[output_targets])`. |
| `rd.pipeline.get_resource_bindings` | Retained. |
| `rd.pipeline.get_uav_bindings` | Removed. Use `rd.pipeline.get_resource_bindings` and filter returned bindings by UAV type. |
| `rd.pipeline.get_sampler_bindings` | Removed. Use `rd.pipeline.get_resource_bindings` and filter returned bindings by sampler type. |
| `rd.pipeline.get_constant_buffers` | Retained. |
| `rd.pipeline.get_push_constants` | Removed. The runtime did not provide a truthful cross-API implementation; no replacement is advertised. |
| `rd.pipeline.get_dynamic_state` | Removed. The runtime did not provide a truthful cross-API implementation; no replacement is advertised. |
| `rd.pipeline.get_root_signature` | Removed. The runtime did not expose a complete root-signature contract; no replacement is advertised. |
| `rd.pipeline.get_descriptor_heaps` | Removed. The runtime did not expose descriptor heaps through a supported contract; no replacement is advertised. |
| `rd.pipeline.get_resource_states` | Removed. The runtime did not expose reliable resource-state transitions; no replacement is advertised. |
| `rd.pipeline.get_shader` | Retained. |
| `rd.resource.list_all` | Retained. |
| `rd.resource.list_textures` | Removed. Use `rd.resource.list_all(kind=texture)`. |
| `rd.resource.list_buffers` | Removed. Use `rd.resource.list_all(kind=buffer)`. |
| `rd.resource.get_details` | Retained. |
| `rd.resource.get_usage` | Retained. |
| `rd.resource.get_history` | Removed. Use `rd.resource.get_usage`, which preserves real usage events and write classification. |
| `rd.resource.get_initial_contents` | Removed. Initial contents were not available through a truthful implementation. |
| `rd.resource.get_current_contents` | Removed. Read texture content with `rd.texture.get_data` or buffer content with `rd.buffer.get_data`; use export operations only when a file is required. |
| `rd.resource.set_alias` | Retained. |
| `rd.resource.get_descriptor_info` | Removed. Use the descriptor-backed entries returned by `rd.pipeline.get_resource_bindings` when the runtime exposes them. |
| `rd.resource.estimate_memory` | Retained. |
| `rd.resource.get_creation_context` | Removed. Use the first real entry from `rd.resource.get_usage` as the earliest observed use; do not label it initial contents. |
| `rd.texture.get_data` | Retained. |
| `rd.texture.get_subresource_data` | Removed. Use `rd.texture.get_data(subresource={mip,slice,sample})`. |
| `rd.texture.get_pixel_value` | Retained. |
| `rd.texture.get_region_values` | Retained. |
| `rd.texture.get_pixel_history` | Retained. |
| `rd.texture.get_min_max` | Removed. Use the finite min/max and NaN/Inf counts from `rd.texture.compute_stats`. |
| `rd.texture.get_histogram` | Retained. |
| `rd.texture.compute_stats` | Retained. |
| `rd.texture.render_overlay` | Retained. |
| `rd.texture.save_mip_chain` | Removed. The old action path was broken. Export explicitly selected subresources only when files are required. |
| `rd.texture.diff` | Retained. |
| `rd.buffer.get_data` | Retained. |
| `rd.buffer.get_structured_data` | Retained. |
| `rd.buffer.search_pattern` | Retained. |
| `rd.mesh.get_post_vs_data` | Removed. Use `rd.mesh.get_post_transform_data(stage=vs)`. |
| `rd.mesh.get_post_gs_data` | Removed. Use `rd.mesh.get_post_transform_data(stage=gs)`. |
| `rd.mesh.decode_vertex_data` | Removed. Use `rd.buffer.get_structured_data` with an explicit vertex layout. |
| `rd.mesh.decode_index_data` | Retained. |
| `rd.mesh.get_drawcall_mesh_config` | Retained. |
| `rd.mesh.get_mesh_preview` | Removed. Use `rd.texture.render_overlay(overlay=Wireframe)` for visual inspection. |
| `rd.shader.get_reflection` | Retained. |
| `rd.shader.get_disassembly` | Retained. |
| `rd.shader.get_source` | Retained. |
| `rd.shader.extract_binary` | Retained. |
| `rd.shader.list_entry_points` | Retained. |
| `rd.shader.get_bindpoint_mapping` | Retained. |
| `rd.shader.get_constant_block_layout` | Retained. |
| `rd.shader.get_constant_buffer_contents` | Retained. |
| `rd.shader.edit_and_replace` | Retained. |
| `rd.shader.revert_replacement` | Retained. |
| `rd.shader.list_replacements` | Retained. |
| `rd.shader.get_messages` | Retained. |
| `rd.shader.compile` | Retained. |
| `rd.shader.debug_start` | Retained. |
| `rd.shader.get_debug_state` | Retained. |
| `rd.debug.step` | Retained. |
| `rd.debug.continue` | Retained. |
| `rd.debug.run_to` | Retained. |
| `rd.debug.set_breakpoints` | Retained. |
| `rd.debug.clear_breakpoints` | Retained. |
| `rd.debug.get_variables` | Retained. |
| `rd.debug.evaluate_expression` | Retained. |
| `rd.debug.get_callstack` | Retained. |
| `rd.debug.finish` | Retained. |
| `rd.debug.pixel_history` | Removed. Use `rd.texture.get_pixel_history`, with either an explicit texture or an output target. |
| `rd.debug.explain_test_failure` | Removed. Interpret real pixel-history tests in the debugger workflow; no string-only explanation operation remains. |
| `rd.perf.enumerate_counters` | Retained. |
| `rd.perf.describe_counter` | Retained. |
| `rd.perf.sample_counters` | Retained. |
| `rd.perf.get_event_durations` | Retained. |
| `rd.perf.get_frame_timing` | Removed. Use `rd.perf.get_event_durations` or real counters; hotspot sums are not reported as whole-frame time. |
| `rd.perf.get_pipeline_statistics` | Removed. The entry returned fixed zero values rather than driver statistics, so there is no replacement. |
| `rd.export.screenshot` | Retained. |
| `rd.export.texture` | Retained. |
| `rd.export.buffer` | Retained. |
| `rd.export.mesh` | Retained. |
| `rd.export.pipeline_state_json` | Removed. Read `rd.pipeline.get_state` as canonical JSON and let the caller persist it only when needed. |
| `rd.export.event_tree_json` | Removed. Read `rd.event.get_action_tree` as canonical JSON and let the caller persist it only when needed. |
| `rd.export.resource_list_csv` | Removed. Use `rd.resource.list_all` with a tabular projection; the caller owns any CSV file. |
| `rd.export.pixel_history_json` | Removed. Read `rd.texture.get_pixel_history` as canonical JSON and let the caller persist it only when needed. |
| `rd.export.shader_bundle` | Retained. |
| `rd.export.cbuffer_dump` | Retained. |
| `rd.export.repro_bundle_zip` | Removed. Assemble selected evidence in a specialist workflow instead of creating a fixed archive from hidden defaults. |
| `rd.export.markdown_report` | Removed. Reports are authored by the specialist workflow from explicit evidence and clearly marked inference. |
| `rd.remote.connect` | Retained. |
| `rd.remote.disconnect` | Retained. |
| `rd.remote.ping` | Retained. |
| `rd.remote.list_targets` | Retained. |
| `rd.remote.launch_app` | Retained. |
| `rd.remote.set_capture_options` | Retained. |
| `rd.remote.set_overlay_options` | Removed. No matching remote RPC existed, so there is no replacement. |
| `rd.remote.trigger_capture` | Retained. |
| `rd.remote.queue_capture` | Retained. |
| `rd.remote.list_captures` | Retained. |
| `rd.remote.copy_capture` | Retained. |
| `rd.remote.delete_capture` | Retained. |
| `rd.diag.scan_common_issues` | Retained. |
| `rd.diag.check_render_targets` | Removed. Use `rd.diag.scan_common_issues` for implemented checks and inspect `rd.pipeline.get_state(sections=[output_targets])` for evidence. |
| `rd.diag.check_depth_stencil` | Removed. Use `rd.diag.scan_common_issues` and `rd.pipeline.get_state(sections=[depth_stencil])`. |
| `rd.diag.check_viewport_scissor` | Removed. Use `rd.diag.scan_common_issues` and `rd.pipeline.get_state(sections=[viewports_scissors])`. |
| `rd.diag.check_culling` | Removed. The old wrapper did not implement a supported culling diagnosis; inspect available pipeline evidence in the specialist workflow. |
| `rd.diag.check_blend` | Removed. Use `rd.diag.scan_common_issues` and `rd.pipeline.get_state(sections=[blend])`. |
| `rd.diag.check_srgb` | Removed. The old wrapper did not implement a supported color-space diagnosis; inspect resource format and shader evidence in the specialist workflow. |
| `rd.diag.check_resource_bindings` | Removed. Use `rd.diag.scan_common_issues` and `rd.pipeline.get_resource_bindings`. |
| `rd.diag.check_constant_buffers` | Removed. Use `rd.pipeline.get_constant_buffers` and interpret values in the specialist workflow. |
| `rd.diag.check_d3d12_resource_states` | Removed. Reliable resource-state transitions are not exposed by this runtime. |
| `rd.diag.check_vk_dynamic_state` | Removed. A truthful Vulkan dynamic-state contract is not exposed by this runtime. |
| `rd.macro.summarize_frame` | Removed. Build the summary in a specialist workflow from `rd.session.get_replay_events`, passes, resources, and explicit measurements. |
| `rd.macro.find_pass_by_marker` | Removed. Use `rd.event.search_actions`, `rd.event.list_passes`, and real parent-chain marker evidence. |
| `rd.macro.explain_pixel` | Removed. Use `rd.texture.get_pixel_history`, texture values, pipeline state, and shader evidence in the debugger workflow. |
| `rd.macro.resource_dependency_graph` | Removed. Derive dependencies from real `rd.resource.get_usage` and binding evidence, marking causal conclusions as inference. |
| `rd.macro.find_state_change_point` | Retained. |
| `rd.macro.compare_events_report` | Removed. Query both events explicitly and compose a report in the specialist workflow. |
| `rd.macro.find_unexpected_clear` | Removed. Search real events and inspect action details and resource usage in the specialist workflow. |
| `rd.macro.quick_triage_missing_draw` | Removed. Run the debugger checklist over event, pipeline, resource, texture, mesh, and shader evidence. |
| `rd.macro.build_bug_report_pack` | Removed. Select and export only the evidence required by the report workflow. |
| `rd.macro.shader_hotfix_validate` | Removed. Use real shader replacement, observation, measurement, rollback, and restored-state checks. |
| `rd.util.compute_hash` | Removed. Use the host language or shell for generic hashing. |
| `rd.util.diff_text` | Removed. Use the host language or source-control tooling for generic text differences. |
| `rd.util.diff_images` | Retained. |
| `rd.util.pack_zip` | Removed. Use the host archive tooling after selecting explicit artifacts. |
| `rd.util.list_artifacts` | Retained. |
| `rd.util.cleanup_artifacts` | Retained. |
| `rd.session.get_replay_events` | Retained. |
| `rd.session.observe` | Retained. |
| `rd.session.get_context` | Retained. |
| `rd.session.update_context` | Retained. |
| `rd.session.create_context` | Retained. |
| `rd.session.list_contexts` | Retained. |
| `rd.session.select_context` | Removed. Read an explicit daemon context with `rd.session.get_context(context_id=...)`; context identity is not mutated by a read. |
| `rd.session.clear_context` | Retained. |
| `rd.session.open_preview` | Retained. |
| `rd.session.close_preview` | Retained. |
| `rd.session.list_sessions` | Retained. |
| `rd.session.select_session` | Retained. |
| `rd.session.resume` | Retained. |
| `rd.core.get_operation_history` | Retained. |
| `rd.core.get_runtime_metrics` | Retained. |
| `rd.core.list_tools` | Retained. |
| `rd.core.search_tools` | Removed. Use `rd.core.list_tools(query=...)`, or `rdc-tool tools search` from the CLI. Search matches names, descriptions, and parameter text; use namespace filtering for a domain-only list. |
| `rd.core.get_tool_graph` | Retained. |
| `rd.vfs.ls` | Retained. |
| `rd.vfs.cat` | Retained. |
| `rd.vfs.tree` | Retained. |
| `rd.vfs.resolve` | Retained. |

New operation: `rd.mesh.get_post_transform_data(stage=vs|gs)`. This table is explanatory upgrade material. It is not an alias map, and none of the removed names are accepted by the runtime.

## 73 个删除入口的产品能力复审

用户要求逐域审查是否删过头。本节纠正上表将“旧入口未实现”当成删除充分依据的表述；上表仍用于解释已发生的接口变化，不能视为产品完整性验收。旧代码基线为 Git HEAD 7f5b085（本轮实现前），当前实现为未提交工作区。只改审查文档与原 Task，不恢复入口、不改运行代码。

分类只使用 **合理 / 删过头**。判断对象是删除入口后是否丢掉本产品必要且不可由现有 primitive 取得的底层数据或独立操作，不要求一个旧入口对应一个新入口。

- **合理**：底层事实和操作仍能获得；筛选、聚合、计数、循环、图构建、比较、报告、归档与实验编排交给 Skill + programmable tool calls 或宿主执行。组合需要多次调用、需要代码计算、没有同名一键入口，均不是删过头的理由。
- **删过头**：必要原始数据或独立操作没有可用入口；LLM 即使编排和计算能力足够强，也无法从已有结果可靠取得。应补 primitive 的参数、结果或实现；适合时合并，不适合时新增独立操作，不以恢复旧名称或维持124个为目标。
- 产品必要性须对应 Debugger/Analyzer/Optimizer 的实际问题或 capture 工作流，不能只因底层 API 有成员、旧目录有名称，便把它列为必需。旧空壳既不能证明需求无用，也不能证明必须恢复旧入口。
- 实验身份、审批、取消、自有资源清理和真实回滚回执由执行层保证；这些不是恢复流程宏的理由。Skill 完整度和真实模型效果属于执行验证，不能混入删除合理性分类。

计数：合理 55 项；删过头 18 项。全部 73 个旧名均匹配旧 dispatch 分支。宏、诊断包装和报告不重复计入底层缺口。沿用用户确定的两分类与 primitive/Skill 边界。本次重新核对全部旧参数/结果约定和实际替代字段，发现先前漏判 viewport/scissor、blend、depth/stencil 三项；18/55 取代此前15/58，不预设最终 Tool 数量。

| 删除入口 | 复审结论 | 旧代码位置 | 原因与应有去向 |
|---|---|---|---|
| `rd.core.search_tools` | 合理 | HEAD:rdc_tool/server_runtime.py:6019 | 旧为目录过滤；list_tools(query=...) 保留搜索，CLI search 仍在。 |
| `rd.capture.get_thumbnail` | 删过头 | HEAD:rdc_tool/server_runtime.py:6969 | 旧始终报 unavailable，但绑定存在 CaptureFile.GetThumbnail。截图需要回放，不等价于读取嵌入缩略图；应补 capture 级缩略图能力。 |
| `rd.capture.list_frames` | 合理 | HEAD:rdc_tool/server_runtime.py:6987 | 旧固定返回单帧0和空时间；capture/replay 元数据承接实际单帧信息，不承诺多帧捕获。 |
| `rd.session.select_context` | 合理 | HEAD:rdc_tool/server_runtime.py:6705 | 旧仅读取指定 context，没有切换 daemon；明确 context 的 get_context 承接真实读取语义。 |
| `rd.event.get_actions` | 合理 | HEAD:rdc_tool/server_runtime.py:7325 | 旧为带过滤和预算的根树；get_action_tree 保留过滤、子树、分页和投影；完整索引另有 get_replay_events。 |
| `rd.event.get_drawcall_children` | 合理 | HEAD:rdc_tool/server_runtime.py:7431 | 旧仅返回直接孩子 ID；get_action_details.children_event_ids 和子树查询可承接。 |
| `rd.event.get_marker_stack` | 合理 | HEAD:rdc_tool/server_runtime.py:7516 | 旧从父链筛 marker 名称；get_parent_chain 的真实标记可承接。 |
| `rd.event.get_api_calls` | 删过头 | HEAD:rdc_tool/server_runtime.py:7523 | 旧返回空数组，但 GetStructuredFile/GetStructuredData 提供结构化捕获源。应补有界事件关联 API/chunk 查询；不能承诺捕获之外的完整进程调用流。 |
| `rd.pipeline.get_state_summary` | 合理 | HEAD:rdc_tool/server_runtime.py:7618 | 显式请求需要的 sections 后可在调用方计算 binding_count 和摘要。默认字段变化不影响 primitive 可组合性，无需保留摘要包装。 |
| `rd.pipeline.get_vertex_input` | 删过头 | HEAD:rdc_tool/server_runtime.py:7675 | 旧误把普通 bindings 当 vertex_buffers；新 VB/IB/topology 仍缺顶点属性布局。绑定存在 GetVertexInputs，应补属性、槽位、偏移、格式等输入证据。 |
| `rd.pipeline.get_primitive_topology` | 合理 | HEAD:rdc_tool/server_runtime.py:7705 | get_state(sections=[topology]) 承接同一拓扑数据。 |
| `rd.pipeline.get_viewports_scissors` | 删过头 | HEAD:rdc_tool/server_runtime.py:7707 | 旧、新都只提取 viewport/scissor 第0项，且忽略 enabled；存在多个有效区域时无法取得其他区域。旧能力未完成不等于产品不需要，应提供完整数组/索引和有效状态。当前 section 名称存在不构成完整承接。 |
| `rd.pipeline.get_rasterizer_state` | 删过头 | HEAD:rdc_tool/server_runtime.py:7709 | 旧空对象；当前 sections 无 rasterizer。剔除、正反面、填充和偏置是渲染错误定位所需原始证据，应接入 API 状态。 |
| `rd.pipeline.get_multisample_state` | 删过头 | HEAD:rdc_tool/server_runtime.py:7711 | 旧空对象；当前缺 sample mask/alpha-to-coverage 等完整状态。纹理 sample 数不能替代；绑定 VKState.multisample 提供接入线索。 |
| `rd.pipeline.get_blend_state` | 删过头 | HEAD:rdc_tool/server_runtime.py:7713 | 当前模型和采集器仅保留 enabled 与颜色/alpha 混合方程，遗漏 writeMask、blendFactor、logicOperation 等原始状态。颜色完全禁止写入仍与正常写入返回相同信息，无法用 Skill 从方程还原，必须补状态字段。 |
| `rd.pipeline.get_depth_stencil_state` | 删过头 | HEAD:rdc_tool/server_runtime.py:7715 | 当前只有 depth test/write/function 和 stencil enabled，缺少正反面 stencil function/reference/compareMask/writeMask/fail/depthFail/pass 操作等。开启标志不能解释模板测试，应补原始状态。 |
| `rd.pipeline.get_output_targets` | 合理 | HEAD:rdc_tool/server_runtime.py:7717 | get_state(sections=[output_targets]) 保留目标和可视目标真值元数据，结果包层变化。 |
| `rd.pipeline.get_render_targets` | 合理 | HEAD:rdc_tool/server_runtime.py:7729 | 同一 output_targets section 提供 render_targets，不需重复入口。 |
| `rd.pipeline.get_depth_target` | 合理 | HEAD:rdc_tool/server_runtime.py:7735 | 同一 output_targets section 提供 depth_target，不需重复入口。 |
| `rd.pipeline.get_uav_bindings` | 合理 | HEAD:rdc_tool/server_runtime.py:7740 | 统一 bindings 的 type=UAV 使用相同采集器筛选，旧只是同样筛选。 |
| `rd.pipeline.get_sampler_bindings` | 删过头 | HEAD:rdc_tool/server_runtime.py:7744 | 旧空数组；新 schema 接受 Sampler，但采集器只调用 RO/RW/ConstantBlocks，没有 GetSamplers。反射名称也不是实际采样器状态；现有迁移承诺不成立。 |
| `rd.pipeline.get_push_constants` | 删过头 | HEAD:rdc_tool/server_runtime.py:7763 | 定位 Vulkan 常量错误需要真实 push-constant 字节、范围与阶段信息。当前通用常量块可能解码部分值，但未提供完整原始范围/状态，VKState.pushconsts 是接入线索；应补到统一常量或状态查询。 |
| `rd.pipeline.get_dynamic_state` | 删过头 | HEAD:rdc_tool/server_runtime.py:7765 | 定位 Vulkan 状态问题需要实际生效状态及可获得的动态声明信息；当前 sections 只提供其中一部分，组合 viewport 等不能生成缺失字段。应按 API 补必要状态，不要求完整历史。 |
| `rd.pipeline.get_root_signature` | 删过头 | HEAD:rdc_tool/server_runtime.py:7767 | 旧空对象；绑定 D3D12State.rootSignature 存在，普通绑定列表不等价于 root 参数/表布局。应补 API 专属查询。 |
| `rd.pipeline.get_descriptor_heaps` | 删过头 | HEAD:rdc_tool/server_runtime.py:7769 | 旧空数组；绑定 D3D12State.descriptorHeaps 存在。已访问资源绑定不能替代 heap 身份、范围和表关系。 |
| `rd.pipeline.get_resource_states` | 删过头 | HEAD:rdc_tool/server_runtime.py:7771 | 旧空数组；绑定 D3D12State.resourceStates、VKState.images 可作为读取线索。应提供当前状态与可证变化；不能把快照说成完整 barrier 历史。 |
| `rd.resource.list_textures` | 合理 | HEAD:rdc_tool/server_runtime.py:7890 | list_all(kind=texture) 承接分类枚举。 |
| `rd.resource.list_buffers` | 合理 | HEAD:rdc_tool/server_runtime.py:7892 | list_all(kind=buffer) 承接分类枚举。 |
| `rd.resource.get_history` | 合理 | HEAD:rdc_tool/server_runtime.py:7916 | 旧实为 GetUsage 记录和字符串写入判定；get_usage 保留事件记录与写入分类，不是真正逐版本内容历史。 |
| `rd.resource.get_initial_contents` | 删过头 | HEAD:rdc_tool/server_runtime.py:7931 | 判断 capture 中数据是否在首次写入前已错误，需要可证明的初始/事件前读取语义。当前内容和首次使用不能生成此前字节；应补时间点读取能力并明确 capture 未记录的边界，不恢复旧假 initial 包装。 |
| `rd.resource.get_current_contents` | 合理 | HEAD:rdc_tool/server_runtime.py:7931 | 旧转发 texture/buffer 读取或导出；新按资源类型直接调用，保持事件、subresource、范围参数。 |
| `rd.resource.get_descriptor_info` | 删过头 | HEAD:rdc_tool/server_runtime.py:8010 | 旧实际转发 get_details，这部分未丢；但迁移承诺 descriptor-backed bindings 未保留完整 view/subresource/range/sampler 信息。应补描述符证据，不必恢复重复 get_details 包装。 |
| `rd.resource.get_creation_context` | 删过头 | HEAD:rdc_tool/server_runtime.py:8030 | 旧只返回首次使用，不是创建；ResourceDescription.initialisationChunks/parentResources/derivedResources 存在。应补初始化/派生来源，缺失时未知，不能承诺创建调用栈总可得。 |
| `rd.texture.get_subresource_data` | 合理 | HEAD:rdc_tool/server_runtime.py:8680 | get_data 的 subresource={mip,slice,sample} 承接旧读取。 |
| `rd.texture.get_min_max` | 合理 | HEAD:rdc_tool/server_runtime.py:8802 | compute_stats 承接统计并区分 NaN/Inf；不是删掉最值计算。 |
| `rd.texture.save_mip_chain` | 合理 | HEAD:rdc_tool/server_runtime.py:8985 | 纹理详情取得 mip 数后，循环 export.texture 指定 subresource 即可。循环、结果收集与重试属于可编程调用，无需批量宏。 |
| `rd.mesh.get_post_vs_data` | 合理 | HEAD:rdc_tool/server_runtime.py:8518 | get_post_transform_data(stage=vs) 保留实际 GetPostVSData、事件、instance、view 和数量控制。 |
| `rd.mesh.get_post_gs_data` | 合理 | HEAD:rdc_tool/server_runtime.py:8518 | get_post_transform_data(stage=gs) 保留 GS 输出与未绑定状态区分。 |
| `rd.mesh.decode_vertex_data` | 合理 | HEAD:rdc_tool/server_runtime.py:8589 | 旧本就转发 buffer.get_structured_data；显式 layout/offset/count 可承接解码。自动取得 layout 的缺口另记 vertex_input。 |
| `rd.mesh.get_mesh_preview` | 合理 | HEAD:rdc_tool/server_runtime.py:8634 | 旧能力只是 wireframe overlay；查询输出目标再调用 render_overlay 可组合实现。独立几何相机查看器从未由旧入口提供，不借审查扩充产品要求。 |
| `rd.debug.pixel_history` | 合理 | HEAD:rdc_tool/server_runtime.py:11140 | texture.get_pixel_history 统一显式纹理与当前输出目标，旧只是转发。 |
| `rd.debug.explain_test_failure` | 合理 | HEAD:rdc_tool/server_runtime.py:11156 | 旧拼接 flags 字符串，没有新增诊断；原始测试证据留在像素历史，解释由 Debugger 方法承担。 |
| `rd.perf.get_frame_timing` | 删过头 | HEAD:rdc_tool/server_runtime.py:11338 | Optimizer 判断整帧收益需要覆盖整帧的真实测量。现有事件耗时未提供完整帧时间边界，top20 或全部事件相加都不能自行证明等价；应补底层测量语义，分析和报告仍交 Skill。 |
| `rd.perf.get_pipeline_statistics` | 合理 | HEAD:rdc_tool/server_runtime.py:11342 | enumerate/describe/sample 可读取设备支持的真实计数器；事件树可统计 draw/dispatch。聚合交调用方，设备不支持某计数器属于能力限制，不需恢复固定统计包装。 |
| `rd.diag.check_render_targets` | 合理 | HEAD:rdc_tool/server_runtime.py:11750 | 输出目标 primitive 提供事实，目标检查由 Skill 或程序化条件完成；无需每个诊断主题一个 Tool。 |
| `rd.diag.check_depth_stencil` | 合理 | HEAD:rdc_tool/server_runtime.py:11752 | depth_stencil 数据查询加业务条件足以承载检查；诊断规则不必硬编码为独立入口。 |
| `rd.diag.check_viewport_scissor` | 合理 | HEAD:rdc_tool/server_runtime.py:11756 | viewport/scissor 原始值可查，空范围与越界可由调用方计算；不要求恢复专项诊断 Tool。 |
| `rd.diag.check_culling` | 合理 | HEAD:rdc_tool/server_runtime.py:11760 | 剔除诊断是流程包装，应留给 Skill。缺失的原始状态只在 get_rasterizer_state 记为删过头，不把其上层诊断也算一次。 |
| `rd.diag.check_blend` | 合理 | HEAD:rdc_tool/server_runtime.py:11764 | blend 数据可查，结合像素历史与假设进行判断是专业流程。scan 没有同名规则不构成删除过头。 |
| `rd.diag.check_srgb` | 合理 | HEAD:rdc_tool/server_runtime.py:11768 | 目标格式、纹理和 shader 是事实输入；格式计数及颜色空间推理可编程组合，不需固定诊断入口。 |
| `rd.diag.check_resource_bindings` | 合理 | HEAD:rdc_tool/server_runtime.py:11772 | 绑定查询后计数、对照反射和验证假设属于组合。sampler 原始数据缺口记在 pipeline，不保留诊断包装。 |
| `rd.diag.check_constant_buffers` | 合理 | HEAD:rdc_tool/server_runtime.py:11776 | 常量读取与解码 primitive 保留，值是否异常由上下文和方法判断，无需固定检查包装。 |
| `rd.diag.check_d3d12_resource_states` | 合理 | HEAD:rdc_tool/server_runtime.py:11780 | 状态合法性判断可以组合数据和规则；底层状态缺口记在 get_resource_states，不恢复这个旧 unsupported 包装。 |
| `rd.diag.check_vk_dynamic_state` | 合理 | HEAD:rdc_tool/server_runtime.py:11782 | 动态状态诊断交 Skill；底层必要状态缺口记在 get_dynamic_state，不重复恢复诊断入口。 |
| `rd.export.pipeline_state_json` | 合理 | HEAD:rdc_tool/server_runtime.py:11553 | 旧为状态查询后 JSON 写文件；canonical JSON 可由调用方显式保存。输出结构变化不等于数据消失。 |
| `rd.export.event_tree_json` | 合理 | HEAD:rdc_tool/server_runtime.py:11563 | 旧为树查询后写文件；新查询后保存可承接，但必须遍历分页/核对截断，不能只保存第一页称完整树。 |
| `rd.export.resource_list_csv` | 合理 | HEAD:rdc_tool/server_runtime.py:11573 | list_all 提供记录，调用方可用标准序列化生成 CSV；格式转换不是 RenderDoc 独立能力。TSV 不等于 CSV，但不需要为转换恢复 Tool。 |
| `rd.export.pixel_history_json` | 合理 | HEAD:rdc_tool/server_runtime.py:11587 | 旧为像素历史查询后 JSON 写文件；直接查询后显式保存可承接。 |
| `rd.export.repro_bundle_zip` | 合理 | HEAD:rdc_tool/server_runtime.py:11698 | 选取证据、生成 manifest 和 ZIP 是可编程组织工作；底层导出保留，不需固定复现包布局 Tool。 |
| `rd.export.markdown_report` | 合理 | HEAD:rdc_tool/server_runtime.py:11705 | 报告组织由 Skill/调用方完成；CLI 提供数据与导出，不要求 CLI 自身具备每一种报告模板。 |
| `rd.remote.set_overlay_options` | 合理 | HEAD:rdc_tool/server_runtime.py:13044 | 旧仅报无 RPC；未发现它是当前回放分析、观察或捕获链路必需操作。运行中修改目标端 HUD 属于另一个控制需求，不因旧名称存在便要求纳入本轮产品。 |
| `rd.macro.summarize_frame` | 合理 | HEAD:rdc_tool/server_runtime.py:11809 | 完整事件索引、状态查询加程序化计数和聚合即可；programmable tool calls 可以执行计算，不要求 LLM 心算，也不需固定摘要 Tool。 |
| `rd.macro.find_pass_by_marker` | 合理 | HEAD:rdc_tool/server_runtime.py:11835 | 事件树/父链提供名称与路径，调用方可做路径正则、大小写与筛选。单次 search 不完全等价，不影响组合足够。 |
| `rd.macro.explain_pixel` | 合理 | HEAD:rdc_tool/server_runtime.py:11883 | 旧只说修改次数并截前20条；像素历史保留，解释责任迁给专业方法合理，不声称真实模型效果已通过。 |
| `rd.macro.resource_dependency_graph` | 合理 | HEAD:rdc_tool/server_runtime.py:11893 | 资源使用、事件与绑定提供事实，调用方可程序化建立生产者/消费者关系和图，再区分观察与因果。图构建不是新增底层读取，不应强制留在 Tool。更细状态/范围缺口只记对应 primitive。 |
| `rd.macro.compare_events_report` | 合理 | HEAD:rdc_tool/server_runtime.py:11973 | 旧 diff_pipeline_state 加 Markdown 排版；原始 diff 仍在，报告由消费者组织，不需固定宏。 |
| `rd.macro.find_unexpected_clear` | 合理 | HEAD:rdc_tool/server_runtime.py:11989 | 旧仅 search name_contains=clear，没有 unexpected 判定；原始检索保留，是否异常由证据与任务约束判断。 |
| `rd.macro.quick_triage_missing_draw` | 合理 | HEAD:rdc_tool/server_runtime.py:11993 | 事件、管线、资源、像素和 shader 的排查顺序属于 Skill；原始数据缺口分别修对应 primitive，不能据此恢复整体宏。 |
| `rd.macro.build_bug_report_pack` | 合理 | HEAD:rdc_tool/server_runtime.py:12003 | 读取摘要/context、选择证据再归档属于可编程流程；无需与其他报告包并存独立宏。 |
| `rd.macro.shader_hotfix_validate` | 合理 | HEAD:rdc_tool/server_runtime.py:12014 | 观察、替换、测量、差异与恢复 primitive 可组合；身份/审批/回执由执行层保证，流程由 Skill 组织。不能用缺少一键宏代替生命周期缺陷判断。 |
| `rd.util.compute_hash` | 合理 | HEAD:rdc_tool/server_runtime.py:12106 | 旧通用文件哈希，宿主语言/系统可做；移出 RDC-Tool 专业工具面合理，Agent 的证据哈希仍须由可信代码产生。 |
| `rd.util.diff_text` | 合理 | HEAD:rdc_tool/server_runtime.py:12123 | 旧通用 unified diff，宿主工具可承接；不是 RenderDoc 专属能力。 |
| `rd.util.pack_zip` | 合理 | HEAD:rdc_tool/server_runtime.py:12169 | 通用归档可交宿主执行；宿主执行环境的配置与验证不属于 RenderDoc primitive，不因需要另一次调用而恢复 Tool。 |

### 关键代码证据与验证边界

- 当前 pipeline dispatcher 的 sections 只包含 shaders/output_targets/topology/viewports_scissors/blend/depth_stencil/bindings。VB 输出只有 slot/resource_id/offset/stride；不能替代 vertex attributes。
- 当前 pipeline_service._collect_bindings_for_stage 调用 GetReadOnlyResources/GetReadWriteResources/GetConstantBlocks，未调用 GetSamplers；接受 Sampler 参数不是实际采集成功证据。GetStageState 中反射 sampler 名称也不能补齐运行绑定与过滤/寻址参数。
- 本次加载随库 renderdoc.pyd，只检查公开成员与本地 docstring，没有打开 capture 或写临时图像。确认 CaptureFile.GetThumbnail 的契约为提取嵌入缩略图；GetStructuredFile 提供 SDFile；GetSamplers 提供真实阶段采样器；GetVertexInputs 提供顶点属性。
- D3D12State 暴露 rasterizer/rootSignature/descriptorHeaps/resourceStates；VKState 暴露 rasterizer/multisample/pushconsts/images。ResourceDescription 暴露 initialisationChunks/parentResources/derivedResources。成员存在证明原来的“不暴露”断言过强，不证明所有 API、capture、版本均可可靠读取。结构化 chunk 不是捕获之外的完整 API trace，状态快照不是 barrier 历史，初始化块不是资源初始字节。
- GPUCounter 枚举包含 IA/VS/PS/CS 等统计项；保留的 enumerate/describe/sample 承载设备支持的原始统计；驱动实际支持属于运行验证，聚合不需要固定 Tool。
- 当前 scan_common_issues 只有无 render target、无 shader、空 topology 三类判断，不能宣传覆盖全部旧诊断主题。
- 已读三个专业 Skill 和共享 CLI/execution Skill。流程与计算可由 Skill + programmable tool calls 组织；手册与真实执行仍要验收，但验收未覆盖不能反推应恢复宏。执行层安全约束继续独立保证。

本节是源码与产品职责审查，不是恢复方案实施或新增真实 GPU 验收。优先纠正 thumbnail、vertex input、sampler 与管线/API 状态读取缺口，再明确结构化调用/资源来源和 frame 测量边界；报表、归档、批量调用和图构建交给 Skill/调用方，不要求补成固定 Tool。最终工具数不得反向约束必要能力。

### 再核验：为什么从15项修正为18项

本次重新读取基线196项catalog中全部73个删除入口的参数/结果约定，并与当前定义集合计算差集；旧名差集恰为73，新增只有get_post_transform_data。沿用逐项旧dispatch证据，再核对当前组合是否保留足够原始数据，不以旧实现曾经残缺为排除依据。

上一轮对空壳入口按产品必要能力判断，对已合并入口却只比较旧输出是否还在，标准不一致。新增三项不是“删除代码导致原先工作能力倒退”，而是已有缺口在合并时没有补齐却被宣称承接完成；此前15项中多数也属于这种能力缺口。修复计划应统一按必要能力覆盖验收。

| 补充缺口 | 当前实现证据 | 本次内存反例 | 产品任务 |
|---|---|---|---|
| viewport/scissor | pipeline_service._extract_viewport/_extract_scissor 对数组使用[0]，未返回enabled | 保持第0项不变，把第1项宽度640改为1，两个提取结果仍完全相同 | 定位多viewport、分屏/多视图区域与裁剪问题 |
| blend | models.BlendState及_extract_blend_state 无写掩码/混合常量/逻辑操作字段 | writeMask从15改为0并改变blendFactor，输出模型完全相同 | 定位像素未写入、通道缺失及常量混合错误 |
| depth/stencil | models.DepthStencilState仅4个字段，_extract_depth_stencil未读取StencilFace | 改变frontFace.reference及backFace.function，输出模型完全相同 | 定位模板遮罩、正反面测试与写入错误 |

以上反例实际调用当前提取函数，使用SimpleNamespace模拟可区分的状态与真实Pydantic输出模型；未打开GPU回放，不宣称是真实设备通过。随库native绑定另外确认ColorBlend.writeMask/logicOperation、D3D12BlendState.blendFactor、StencilFace参考值/掩码/操作和Viewport/Scissor.enabled存在。全rdx源码搜索未找到另一个公开路径补齐这些字段。

对其余55项重新挑战的结果：树遍历/路径regex、完整索引计数、mip循环导出、CSV/报告/归档、依赖图和实验编排仍可由primitive加程序化调用完成，不恢复包装。mesh原始行保留bytes_hex并提供格式/步长，解码与几何图形生成不自动要求专门preview Tool；旧preview目录中的solid/normals/uv声明不证明原实现具备独立mesh viewer。普通计数器可经enumerate/describe/sample取得设备支持的真实数据，聚合属于调用方；只有整帧测量边界单列为缺口。远端运行HUD开关仍不是既定capture/replay分析核心的必要操作，不因无RPC或旧目录存在而扩充范围。

output-target view/subresource/slot元数据的覆盖纳入既有描述符能力修复；采样器与绑定视图也是同一证据链，避免按上层包装重复计数。动态状态项专指还未暴露的API有效状态/声明信息，不用它笼统取代这次明确列出的viewport、blend和stencil事实。

最终18项按域为capture 1、event 1、pipeline 12、resource 3、perf 1；55项合理。这个数字统计旧入口对应的必要能力缺口，不预先决定恢复多少名称、新增多少Tool，也不把未涉及的124项全面质量验收包含进来。

## Necessary-capability restoration status

The approved 18-gap repair keeps the 55 reasonable deletions. Four operations now exist in the canonical definitions: capture thumbnail, event structured calls, resource descriptors and complete replay timing. Other gaps expand pipeline/resource/texture/buffer contracts. Generated reference documents their current arguments; the review table remains historical rationale, not a runtime mapping.

Implementation is not equivalent to full acceptance. Real Vulkan fixture checks cover embedded thumbnail, full pipeline sections, descriptors, structured calls, differing initial/current contents with restoration and GPU frame samples. For dated Android matching-runtime and repeated-observation evidence, see the restoration tasks in [tool-convergence-tasks.md](https://github.com/haolange/RDC-Tool/blob/main/docs/tool-convergence-tasks.md).
