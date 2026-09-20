# Agent Model

Agents should treat `rdc-tool` as CLI-only. Use the `rdc-tool` command through the agent shell tool.

Run `rdc-tool --json doctor` when runtime readiness is unknown or the environment has changed; reuse a current successful result otherwise. Before operations that depend on session state, inspect the selected context with `rdc-tool context status`. Use `rdc-tool context update` for scoped notes or focus when it helps task continuity. `session_locator` summarizes the active capture/session/event for the selected daemon context. Multiple daemon contexts are isolated from each other; use an explicit `--daemon-context <id>` for non-trivial capture tasks and keep it consistent across calls.

Discover narrowly: `rdc-tool tools search <term>` finds related operations, `rdc-tool tools list --namespace <domain>` lists an exact domain, and `rdc-tool tools describe <rd.*>` returns one complete parameter/result/effect contract. Search may cross domains because it matches descriptions and parameters. A declared scope or effect informs orchestration but never grants permission; the embedding host still validates identity, session ownership, paths, and operation effects before execution.

When the target is unknown, use bounded VFS exploration as needed: `rdc-tool vfs ls --path / --format tsv`, `rdc-tool vfs cat --path /context --format json`, or a bounded tree such as `rdc-tool vfs tree --path /draws --depth 2 --max-nodes 2000 --format json`. When the event, resource, or required tool is known, query it directly. Broad `/draws` tree nodes are summaries; when a node reports `detail_deferred=true`, use `event show`, targeted `vfs cat`, or the canonical `rd.event.get_action_details` tool for that event. Do not broad-expand `/resources`, `/textures`, or `/buffers`; use `vfs ls` and targeted `vfs cat` or canonical `rd.*` tools. JSON is canonical; TSV is only for tabular navigation and list projections.

Use `rd.pipeline.get_state(detail=summary, sections=[...])` for bounded pipeline reads; request `full` only when the complete state is needed. `rd.event.get_action_tree` reports pagination, emitted nodes, and truncation for browsing. Do not treat it as a complete frame index; embedded hosts use `rd.session.get_replay_events`. Resource history is `rd.resource.get_usage`, whose entries retain raw event IDs and identify writes. Statistical texture queries remain in memory; persist data only on an explicit readback/export request.

When remote state reports `remote_handle_consumed`, do not reuse that remote handle. Use the remote lifecycle tools to reconnect, ping, or reopen replay as needed.

For shader edits, always read `edit_plan` from `rd.shader.get_source`, `rd.shader.get_disassembly`, `rd.shader.compile`, or `rd.shader.edit_and_replace` before deciding how to modify text. If debug source is unavailable, `edit_plan.recommended_next_tool` tells the agent whether to inspect IR through `rd.shader.get_disassembly` or export a raw container through `rd.shader.extract_binary`. SPIR-V ASM can be text-editable when the plan allows it. DXIL/DXBC disassembly is captured_source_editable=false and must not be edited as text; full replacement is a separate path where the user provides complete HLSL/GLSL through `source_text` or `source_path`, plus `entry` and `target`, and the runtime reports `runtime_full_replace_supported`.

`source_target` names the representation returned by RenderDoc, such as `SPIR-V ASM` or `DXIL`. `source_encoding` names how replacement input will be interpreted by the replay backend. These are related but not interchangeable; use the values from `edit_plan` and returned tool payloads.

Agents use `rd.session.open_preview` through CLI commands when a human observer needs the preview window. `preview.display` is the stable state surface for window and framebuffer geometry.

For the task-level rdc-tool-native SOP, use [rdc-tool-native agent playbook](rdc-tool-native-agent-playbook.md). For exact catalog coverage, use [Tool reference](tool-reference.md), generated from `spec/tool_catalog.json`.

Embedded consumers use `rd.session.get_replay_events` and `rd.session.observe`
for complete event navigation and window-free PNG observation. See
[session-model.md](session-model.md#embedded-replay-observations) for the atomic
apply and partial-failure contract. These operations do not replace the independent
CLI `rd.session.open_preview` / `preview.display` window workflow.

## Restored data queries

Capture-scoped thumbnail reads use the application's owning capture identity. Structured calls, descriptors, initialization relationships and pipeline sections provide primitive facts; Skills compose causal analysis and reports. Temporary replay reads return restoration proof and remain under the application's serial lease. Frame evidence compares the native method, full range, sampling conditions and capture identity, with the actual replacement state checked by the host.
