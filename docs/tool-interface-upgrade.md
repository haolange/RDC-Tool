# 已删除操作的去向

本文是历史记录，说明已从 catalog 删除的操作该改用什么。它不是当前契约，也不是别名表：运行时从不读取本文，也不接受下表任何旧名称。当前定义以 `rdc_tool/operation_definitions.py` 为准，见 [公共契约](public-contract.md) 与 [生成的参考](tool-reference.md)。

表中只列当前 catalog 中已不存在的操作；删除后又以同名恢复的操作不再列出。替代方式中的 `sections=[...]` 均指 `rd.pipeline.get_state` 的参数。

| 已删除操作 | 替代方式 |
|---|---|
| `rd.core.search_tools` | `rd.core.list_tools(query=...)`；CLI 用 `rdc-tool tools search`。只按领域列出时用 namespace 过滤。 |
| `rd.capture.list_frames` | 帧信息由 `rd.capture.get_info` 与 `rd.replay.get_frame_info` 提供；不承诺多帧捕获。 |
| `rd.session.select_context` | 用 `rd.session.get_context(context_id=...)` 读取指定 daemon context；读取不改变 context 身份。 |
| `rd.event.get_actions` | `rd.event.get_action_tree`（根分页与节点预算）；完整事件索引用 `rd.session.get_replay_events`。 |
| `rd.event.get_drawcall_children` | `rd.event.get_action_details` 返回 `children_event_ids`；`rd.event.get_action_tree(event_id=...)` 读取子树。 |
| `rd.event.get_marker_stack` | `rd.event.get_parent_chain` 中的真实 marker 信息。 |
| `rd.pipeline.get_state_summary` | `rd.pipeline.get_state(detail=summary)`，只请求需要的 `sections`。 |
| `rd.pipeline.get_vertex_input` | `sections=[vertex_input]` 给出顶点属性布局；缓冲与拓扑用 `rd.pipeline.get_vertex_buffers`、`rd.pipeline.get_index_buffer` 与 `sections=[topology]`。 |
| `rd.pipeline.get_primitive_topology` | `sections=[topology]`。 |
| `rd.pipeline.get_viewports_scissors` | `sections=[viewports_scissors]`，返回带索引的完整 viewport/scissor。 |
| `rd.pipeline.get_rasterizer_state` | `sections=[rasterizer]`。 |
| `rd.pipeline.get_multisample_state` | `sections=[multisample]`。 |
| `rd.pipeline.get_blend_state` | `sections=[blend]`。 |
| `rd.pipeline.get_depth_stencil_state` | `sections=[depth_stencil]`，含完整正反面 stencil。 |
| `rd.pipeline.get_output_targets` | `sections=[output_targets]`。 |
| `rd.pipeline.get_render_targets` | `sections=[output_targets]`。 |
| `rd.pipeline.get_depth_target` | `sections=[output_targets]`。 |
| `rd.pipeline.get_uav_bindings` | `rd.pipeline.get_resource_bindings(type=UAV)`。 |
| `rd.pipeline.get_sampler_bindings` | `rd.pipeline.get_resource_bindings(type=Sampler)`。 |
| `rd.pipeline.get_push_constants` | `sections=[push_constants]`。 |
| `rd.pipeline.get_dynamic_state` | `sections=[dynamic_state]`。 |
| `rd.pipeline.get_root_signature` | `sections=[root_signature]`。 |
| `rd.pipeline.get_descriptor_heaps` | `sections=[descriptor_heaps]`；descriptor store 区间用 `rd.resource.get_descriptors`。 |
| `rd.pipeline.get_resource_states` | `sections=[resource_states]`；这是当前状态快照，不是 barrier 历史。 |
| `rd.resource.list_textures` | `rd.resource.list_all(kind=texture)`。 |
| `rd.resource.list_buffers` | `rd.resource.list_all(kind=buffer)`。 |
| `rd.resource.get_history` | `rd.resource.get_usage`，保留真实使用事件与写入分类。 |
| `rd.resource.get_initial_contents` | `rd.texture.get_data(state=capture_initial)` 或 `rd.buffer.get_data(state=capture_initial)` 读取 capture 记录的帧初始内容，读取后恢复原事件。 |
| `rd.resource.get_current_contents` | `rd.texture.get_data` 或 `rd.buffer.get_data`（默认 `state=current`）；只有需要文件时才用导出操作。 |
| `rd.resource.get_descriptor_info` | 资源详情用 `rd.resource.get_details`；descriptor store 区间用 `rd.resource.get_descriptors`。 |
| `rd.resource.get_creation_context` | `rd.resource.get_details(include_initialization=true)` 返回记录的初始化 chunk 与父/派生资源，不代表创建调用栈；最早观察到的使用取 `rd.resource.get_usage` 的首条记录。 |
| `rd.texture.get_subresource_data` | `rd.texture.get_data(subresource={mip,slice,sample})`。 |
| `rd.texture.get_min_max` | `rd.texture.compute_stats` 的有限 min/max 与 NaN/Inf 计数。 |
| `rd.texture.save_mip_chain` | 从 `rd.resource.get_details` 取得 mip 数，再对需要的 subresource 逐个调用 `rd.export.texture(subresource=...)`。 |
| `rd.mesh.get_post_vs_data` | `rd.mesh.get_post_transform_data(stage=vs)`。 |
| `rd.mesh.get_post_gs_data` | `rd.mesh.get_post_transform_data(stage=gs)`。 |
| `rd.mesh.decode_vertex_data` | `rd.buffer.get_structured_data` 配合显式顶点布局；布局取自 `rd.mesh.get_drawcall_mesh_config` 或 `sections=[vertex_input]`。 |
| `rd.mesh.get_mesh_preview` | 可视检查用 `rd.texture.render_overlay(overlay=Wireframe)`；需要几何文件时用 `rd.export.mesh`。 |
| `rd.debug.pixel_history` | `rd.texture.get_pixel_history`，可指定纹理或输出目标。 |
| `rd.debug.explain_test_failure` | 无替代；在 debugger 工作流中解读真实像素历史的测试结果。 |
| `rd.perf.get_pipeline_statistics` | 无同名替代（旧入口返回固定零值）；用 `rd.perf.enumerate_counters`、`rd.perf.describe_counter`、`rd.perf.sample_counters` 读取设备支持的真实计数器。 |
| `rd.export.pipeline_state_json` | 读取 `rd.pipeline.get_state` 的 canonical JSON，需要时由调用方保存。 |
| `rd.export.event_tree_json` | 读取 `rd.event.get_action_tree`，需要时由调用方保存；保存完整树必须遍历分页并核对截断。 |
| `rd.export.resource_list_csv` | `rd.resource.list_all` 的表格投影；CSV 文件由调用方生成。 |
| `rd.export.pixel_history_json` | 读取 `rd.texture.get_pixel_history`，需要时由调用方保存。 |
| `rd.export.repro_bundle_zip` | 由专业工作流挑选证据后自行归档，不按隐藏默认值生成固定包。 |
| `rd.export.markdown_report` | 报告由专业工作流依据显式证据撰写，并标明推断。 |
| `rd.remote.set_overlay_options` | 无替代；不存在对应的远端 RPC。 |
| `rd.diag.check_render_targets` | `rd.diag.scan_common_issues` 的已实现检查，加 `sections=[output_targets]` 作为证据。 |
| `rd.diag.check_depth_stencil` | `rd.diag.scan_common_issues` 与 `sections=[depth_stencil]`。 |
| `rd.diag.check_viewport_scissor` | `rd.diag.scan_common_issues` 与 `sections=[viewports_scissors]`。 |
| `rd.diag.check_culling` | 读取 `sections=[rasterizer]` 的剔除状态，在专业工作流中判断。 |
| `rd.diag.check_blend` | `rd.diag.scan_common_issues` 与 `sections=[blend]`。 |
| `rd.diag.check_srgb` | 在专业工作流中结合资源格式（`rd.resource.get_details`）与 shader 证据判断色彩空间。 |
| `rd.diag.check_resource_bindings` | `rd.diag.scan_common_issues` 与 `rd.pipeline.get_resource_bindings`。 |
| `rd.diag.check_constant_buffers` | 用 `rd.pipeline.get_constant_buffers` 读取，在专业工作流中判断。 |
| `rd.diag.check_d3d12_resource_states` | 读取 `sections=[resource_states]` 的状态快照，合法性由专业工作流判断。 |
| `rd.diag.check_vk_dynamic_state` | 读取 `sections=[dynamic_state]`，判断交给专业工作流。 |
| `rd.macro.summarize_frame` | 专业工作流基于 `rd.session.get_replay_events`、pass、资源与显式测量自行汇总。 |
| `rd.macro.find_pass_by_marker` | `rd.event.search_actions`、`rd.event.list_passes` 与 `rd.event.get_parent_chain` 的 marker 证据。 |
| `rd.macro.explain_pixel` | 在 debugger 工作流中组合 `rd.texture.get_pixel_history`、纹理值、管线状态与 shader 证据。 |
| `rd.macro.resource_dependency_graph` | 由 `rd.resource.get_usage` 与绑定证据推导依赖，因果结论标为推断。 |
| `rd.macro.compare_events_report` | 显式查询两个事件（可用 `rd.event.diff_pipeline_state`），报告由专业工作流组织。 |
| `rd.macro.find_unexpected_clear` | 用 `rd.event.search_actions` 检索真实事件，再在专业工作流中检查 action 详情与资源使用。 |
| `rd.macro.quick_triage_missing_draw` | 按 debugger 检查清单逐项查看事件、管线、资源、纹理、mesh 与 shader 证据。 |
| `rd.macro.build_bug_report_pack` | 报告工作流只选择并导出所需证据。 |
| `rd.macro.shader_hotfix_validate` | 组合真实 shader 替换、观察、测量、回滚与恢复状态检查。 |
| `rd.util.compute_hash` | 用宿主语言或 shell 计算哈希。 |
| `rd.util.diff_text` | 用宿主语言或版本控制工具比较文本。 |
| `rd.util.pack_zip` | 选定 artifact 后用宿主归档工具打包。 |
