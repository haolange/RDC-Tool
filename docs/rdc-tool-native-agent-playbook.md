# rdc-tool-native Agent Playbook

This playbook is the canonical rdc-tool-native SOP for agents using `rdc-tool`. It is intentionally a plain repository document, not a host-specific skill file. The runtime contract stays CLI-only and JSON-first.

## Trigger Boundary

Use this playbook when an agent needs to inspect, triage, export, or debug a RenderDoc `.rdc` capture through `rdc-tool` on Windows x64, including remote Android replay sessions. Do not use it for unrelated GPU tools or for platforms outside the supported product scope.

Use `rdc-tool call <rd.*> --format json` when the exact catalog operation matters. Use the human facade commands for high-frequency inspection only: `event`, `pipeline`, `shader`, `export`, `pixel`, and `resource`. The facade commands still call the same canonical `rd.*` tools.

## Ground Rules

- Run `rdc-tool --json doctor` when runtime readiness is unknown or the environment has changed; reuse a current successful result otherwise.
- Discover narrowly. Use `rdc-tool tools search <term>` for semantic search, `rdc-tool tools list --namespace <domain>` for an exact domain, and `rdc-tool tools describe <rd.*> --json` before using an unfamiliar operation. Search can return related operations from several domains.
- Use `--daemon-context <id>` for non-trivial capture tasks and keep it consistent across calls so state does not leak between agent jobs.
- Before operations that depend on session state, inspect the selected context with `rdc-tool context status --json`. Write notes with `rdc-tool context update --key notes --value "..." --json` when it helps task continuity. Use `rdc-tool context clear --json` for intentional cleanup of that task's context, following the recovery sequence below when state is stale.
- When the target is unknown, use bounded VFS exploration as needed: `rdc-tool vfs ls --path / --format tsv`, `rdc-tool vfs cat --path /context --format json`, or a bounded tree such as `rdc-tool vfs tree --path /draws --depth 2 --max-nodes 2000 --format json`. When the event, resource, or required tool is known, query it directly. Broad `/draws` tree nodes intentionally defer full event details with `detail_deferred=true`; use `event show`, targeted `vfs cat`, or canonical tools for a chosen event. Do not broad-expand `/resources`, `/textures`, or `/buffers`; use `vfs ls`, targeted `vfs cat`, or canonical tools.
- Treat JSON as canonical. TSV is only a projection for list/navigation surfaces.
- Keep output bounded. Prefer summaries, VFS paths, and specific resource/event IDs before requesting large payloads.
- Never guess a session. Open a capture or pass `--session-id` when the selected daemon context has no active session.

## Output Size Management

Use list and summary commands to locate unknown targets or bound large payloads; query a known target directly:

```bat
rdc-tool --daemon-context case-1 event list --format tsv
rdc-tool --daemon-context case-1 pipeline show --event-id 42 --format json
rdc-tool --daemon-context case-1 resource list --format tsv
```

Use raw `rdc-tool call` for catalog options such as `max_nodes`, `max_events`, projections, or filters when a facade intentionally hides low-frequency parameters. Texture statistics, histograms, differences, and base64 buffer reads remain in memory. Store files under the configured `RDC_TOOL_INTERMEDIATE_ROOT` only when an export or evidence request requires persistence. Use `--args-file` for complex JSON, especially multiline HLSL/GLSL replacement source.

## Failure Recovery

If a command returns `session_required`, run `rdc-tool context status --json` for that `--daemon-context`; then either reopen the capture or pass the intended `--session-id`.

If preview, remote replay, shader replacement, or export fails, preserve the failing JSON payload. The payload usually includes `failure_stage`, `failure_reason`, `resolved_event_id`, `binding_truth_level`, or `edit_plan`. Do not retry by changing encodings or targets unless the payload recommends a next tool.

If context looks stale, first inspect status and close replay through the canonical replay resource path. If cleanup fails or `stale_session_requires_restart` is returned, restart that daemon context. Run:

```bat
rdc-tool --daemon-context case-1 context status --json
rdc-tool --daemon-context case-1 call rd.capture.close_replay --args-file close_replay_args.json --format json
rdc-tool --daemon-context case-1 context clear --json
rdc-tool --daemon-context case-1 daemon stop
```

## Recipes

Choose the relevant recipe and run only the steps needed for the task. Readiness checks and exploration follow the conditions above; the examples are not a mandatory sequence across recipes.

### 1. Open Capture

```bat
rdc-tool --daemon-context case-1 --json doctor
rdc-tool --daemon-context case-1 capture open --file "C:\captures\case.rdc" --frame-index 0
rdc-tool --daemon-context case-1 context status --json
rdc-tool --daemon-context case-1 vfs ls --path / --format tsv
```

Success means context state contains a `session_locator` with capture, session, frame, and active event identifiers.

### 2. Unknown Frame Triage

```bat
rdc-tool --daemon-context case-1 event list --format tsv
rdc-tool --daemon-context case-1 vfs tree --path /draws --depth 2 --max-nodes 2000 --format json
rdc-tool --daemon-context case-1 context update --key focus --value "unknown frame triage" --json
```

Find suspicious markers/drawcalls first, then inspect only the candidate event IDs.

### 3. Pipeline And Resource Inspect

```bat
rdc-tool --daemon-context case-1 pipeline show --event-id 42 --format json
rdc-tool --daemon-context case-1 pipeline section --event-id 42 --stage ps --format json
rdc-tool --daemon-context case-1 resource list --format tsv
rdc-tool --daemon-context case-1 resource show --resource-id <resource-id> --format json
rdc-tool --daemon-context case-1 resource usage --resource-id <resource-id> --format json
```

Use `pipeline show` for compact state and `pipeline section` for one shader stage. Raw callers can bound `rd.pipeline.get_state` with `detail=summary|full` and `sections`. Resource discovery is `rd.resource.list_all(kind=all|texture|buffer)`; resource usage preserves real event IDs and write classification.

### 4. Visual Export And Preview

```bat
rdc-tool --daemon-context case-1 session preview on
rdc-tool --daemon-context case-1 session preview status
rdc-tool --daemon-context case-1 export screenshot --event-id 42 --out intermediate\artifacts\case-1\event42.png
```

Inspect `preview.display` in `context status --json` when geometry matters. It is the stable preview state surface for framebuffer, fit, and window dimensions.

`rd.export.mesh` writes post-VS positions or `space=vs_input` geometry as OBJ. For `vs_input`, `include_attributes=true` exports explicitly decoded float POSITION/NORMAL/TEXCOORD0 with matching v/vn/vt face indices in original input coordinates. Packed normal encodings, ambiguous semantics, mixed instance attributes, unsupported topology and incomplete readback are rejected without a placeholder. Post-VS OBJ remains positions only; it cannot borrow input normals.

### 5. Pixel Debug

```bat
rdc-tool --daemon-context case-1 pixel value --event-id 42 --resource-id <texture-id> --x 320 --y 180 --format json
rdc-tool --daemon-context case-1 pixel history --event-id 42 --resource-id <texture-id> --x 320 --y 180 --format json
```

Use explicit `texture_id`, `x`, and `y`. If the target texture is unknown, inspect pipeline outputs or VFS draw nodes first.

### 6. Shader Edit With edit_plan

```bat
rdc-tool --daemon-context case-1 shader source --event-id 42 --stage ps --format json
rdc-tool --daemon-context case-1 shader disasm --event-id 42 --stage ps --format json
rdc-tool --daemon-context case-1 shader constants --event-id 42 --stage ps --slot 0 --format json
```

Read `edit_plan` before editing. `captured_source_editable=false` means captured disassembly is read-only. For DXIL/DXBC full replacement, provide complete HLSL through `source_path` or `source_text` with `entry` and `target` such as `ps_6_6`; build failures do not call `ReplaceResource`, and replace failures report cleanup/context evidence. If `runtime_full_replace_supported=false`, follow the returned failure reason instead of inventing a source encoding.

### 7. Android Remote Open And Replay

Use the remote tools explicitly through `rdc-tool call` because device, package, activity, and capture paths are environment-specific:

```bat
rdc-tool --daemon-context android-1 call rd.remote.connect --args-file intermediate\logs\remote_connect_args.json --format json
rdc-tool --daemon-context android-1 call rd.remote.ping --args-file intermediate\logs\remote_ping_args.json --format json
rdc-tool --daemon-context android-1 call rd.capture.open_replay --args-file intermediate\logs\remote_open_replay_args.json --format json
rdc-tool --daemon-context android-1 context status --json
```

After `rd.capture.open_replay`, a consumed remote handle must not be reused as a free connection. Reconnect or recover through the remote lifecycle tools when state reports `remote_handle_consumed`.

### 8. Bug Report Evidence

Collect the smallest reproducible evidence set. There is no fixed report-pack operation; the specialist workflow chooses each observation and export explicitly:

```bat
rdc-tool --daemon-context case-1 version --json
rdc-tool --daemon-context case-1 --json doctor
rdc-tool --daemon-context case-1 context status --json
rdc-tool --daemon-context case-1 event show --event-id 42 --format json
rdc-tool --daemon-context case-1 pipeline show --event-id 42 --format json
rdc-tool --daemon-context case-1 export screenshot --event-id 42 --out intermediate\artifacts\case-1\bug-event42.png
```

Include exact commands, JSON payloads, artifact paths, capture SHA256 when shareable, and whether the session was local Windows or remote Android. Do not include private captures or machine-local absolute paths in committed docs or release metadata.

## Two captures and read-only batch (standalone CLI)

This recipe is for human/standalone CLI use. RDC-Agent's General must instead follow the owning-session application flow in its Analyzer method Skill.

1. In one `--daemon-context compare`, call `rd.capture.open_file` for A and B, keeping each returned `capture_file_id` separately.
2. Call `rd.capture.open_replay` for each handle; retain both `session_id` values. Different captures have different sessions. Reopening the same **handle** reuses its replay; another `open_file` call creates a new capture identity even for the same file.
3. Query each explicit session with `rd.session.get_replay_events`, action details and pipeline state. Keep capture file hash, context, session and event identity with each observation. Never compare ResourceId across files as a stable key.
4. Compare observations using marker paths plus shader content hashes, native debug names and pipeline facts. Missing keys stay null; duplicate marker names do not imply a unique match. Without markers, topology, attachments and event neighbourhood are heuristics requiring counterexamples.

Predetermined queries can share one client process:

```jsonl
{"operation":"rd.session.get_replay_events","args":{"session_id":"session-A"}}
{"operation":"rd.session.get_replay_events","args":{"session_id":"session-B"}}
```

Save as `queries.jsonl`, then `rdc-tool --daemon-context compare batch queries.jsonl`. Use discovered IDs, not these placeholders. Batch accepts only catalog effects with no writes or lifecycle changes; replay-position effects remain serialized by the existing worker. Canonical `ok=false`, parse/validation/transport errors stop immediately with nonzero exit, preserving earlier and failing envelopes. Valid empty data continues. Ctrl-C stops scheduling after the in-flight request completes or returns its timeout/error; a cancellation request is not evidence that native work has stopped. Borrowed daemons remain running.

Discovery: `tools list --namespace mesh --json`, `tools search usage --json`, then `tools describe <operation> --json`. Describe is authoritative; do not duplicate catalog allowlists.

Assertions and evidence organization belong to the caller: state an expected fact, retain the original envelope and capture identity/hash, then compare actual fields. Group regression observations by capture/event/operation and retain unsupported/error boundaries. Do not invent runtime assertion, DAG or evidence-bundle operations.

Mesh `get_drawcall_mesh_config` returns bounded VS input rows (default 128 draw indices) with explicit input semantics, formats, bindings and instance provenance. NORMAL and TEXCOORD0 values come from actual input bytes; normalized integer values are shader inputs, not an inferred normal vector. Post-transform rows remain separate: native positions plus verified D3D11/12 stream-zero float signature outputs. TEXCOORD output labels do not prove a normal semantic. OBJ attributes require `space=vs_input` and float semantics; unbound GS is a successful explicitly unbound result, not a complete mesh. `truncated=null` means total size cannot be established from an unbounded native view. Shader hash uses recorded rawBytes; debug_name excludes autogenerated names, and both may be null. resource_name retains native shader display names; debug_source_files are source filenames, never substitute debug names. Resource names such as mesh/texture labels are not shader names. Shader source/binary encodings follow the operation's current enum; never retry with guessed encodings.

Usage `usage_name` maps exact native enum values; read/write may be null, and binding-only access is not observable. Color/depth attachments and resolvable event IDs support a knowledge-layer resource-version graph, not proof of an engine RenderGraph, per-pixel access or unused resources. Record observation separately from inferred dependencies.

Release only your context first, then stop only your owned daemon. Check its termination receipt. Temporary replay-position queries require restoration evidence; a failed restoration isolates the replay and blocks subsequent claims.
