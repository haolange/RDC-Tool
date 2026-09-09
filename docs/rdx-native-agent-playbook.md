# rdx-native Agent Playbook

This playbook is the canonical rdx-native SOP for agents using `rdx-tools`. It is intentionally a plain repository document, not a host-specific skill file. The runtime contract stays CLI-only and JSON-first.

## Trigger Boundary

Use this playbook when an agent needs to inspect, triage, export, or debug a RenderDoc `.rdc` capture through `rdx` on Windows x64, including remote Android replay sessions. Do not use it for unrelated GPU tools or for platforms outside the supported product scope.

Use `rdx call <rd.*> --format json` when the exact catalog operation matters. Use the human facade commands for high-frequency inspection only: `event`, `pipeline`, `shader`, `export`, `pixel`, and `resource`. The facade commands still call the same canonical `rd.*` tools.

## Ground Rules

- Run `rdx --json doctor` when runtime readiness is unknown or the environment has changed; reuse a current successful result otherwise.
- Use `--daemon-context <id>` for non-trivial capture tasks and keep it consistent across calls so state does not leak between agent jobs.
- Before operations that depend on session state, inspect the selected context with `rdx context status --json`. Write notes with `rdx context update --key notes --value "..." --json` when it helps task continuity. Use `rdx context clear --json` for intentional cleanup of that task's context, following the recovery sequence below when state is stale.
- When the target is unknown, use bounded VFS exploration as needed: `rdx vfs ls --path / --format tsv`, `rdx vfs cat --path /context --format json`, or a bounded tree such as `rdx vfs tree --path /draws --depth 2 --max-nodes 2000 --format json`. When the event, resource, or required tool is known, query it directly. Broad `/draws` tree nodes intentionally defer full event details with `detail_deferred=true`; use `event show`, targeted `vfs cat`, or canonical tools for a chosen event. Do not broad-expand `/resources`, `/textures`, or `/buffers`; use `vfs ls`, targeted `vfs cat`, or canonical tools.
- Treat JSON as canonical. TSV is only a projection for list/navigation surfaces.
- Keep output bounded. Prefer summaries, VFS paths, and specific resource/event IDs before requesting large payloads.
- Never guess a session. Open a capture or pass `--session-id` when the selected daemon context has no active session.

## Output Size Management

Use list and summary commands to locate unknown targets or bound large payloads; query a known target directly:

```bat
rdx --daemon-context case-1 event list --format tsv
rdx --daemon-context case-1 pipeline show --event-id 42 --format json
rdx --daemon-context case-1 resource list --format tsv
```

Use raw `rdx call` for catalog options such as `max_nodes`, `max_events`, projections, or filters when a facade intentionally hides low-frequency parameters. Store large artifacts under `intermediate/artifacts` or a task-specific output directory instead of printing them. Use `--args-file` for complex JSON, especially multiline HLSL/GLSL replacement source.

## Failure Recovery

If a command returns `session_required`, run `rdx context status --json` for that `--daemon-context`; then either reopen the capture or pass the intended `--session-id`.

If preview, remote replay, shader replacement, or export fails, preserve the failing JSON payload. The payload usually includes `failure_stage`, `failure_reason`, `resolved_event_id`, `binding_truth_level`, or `edit_plan`. Do not retry by changing encodings or targets unless the payload recommends a next tool.

If context looks stale, first inspect status and close replay through the canonical replay resource path. If cleanup fails or `stale_session_requires_restart` is returned, restart that daemon context. Run:

```bat
rdx --daemon-context case-1 context status --json
rdx --daemon-context case-1 call rd.capture.close_replay --args-file close_replay_args.json --format json
rdx --daemon-context case-1 context clear --json
rdx --daemon-context case-1 daemon stop
```

## Recipes

Choose the relevant recipe and run only the steps needed for the task. Readiness checks and exploration follow the conditions above; the examples are not a mandatory sequence across recipes.

### 1. Open Capture

```bat
rdx --daemon-context case-1 --json doctor
rdx --daemon-context case-1 capture open --file "C:\captures\case.rdc" --frame-index 0
rdx --daemon-context case-1 context status --json
rdx --daemon-context case-1 vfs ls --path / --format tsv
```

Success means context state contains a `session_locator` with capture, session, frame, and active event identifiers.

### 2. Unknown Frame Triage

```bat
rdx --daemon-context case-1 event list --format tsv
rdx --daemon-context case-1 vfs tree --path /draws --depth 2 --max-nodes 2000 --format json
rdx --daemon-context case-1 context update --key focus --value "unknown frame triage" --json
```

Find suspicious markers/drawcalls first, then inspect only the candidate event IDs.

### 3. Pipeline And Resource Inspect

```bat
rdx --daemon-context case-1 pipeline show --event-id 42 --format json
rdx --daemon-context case-1 pipeline section --event-id 42 --stage ps --format json
rdx --daemon-context case-1 resource list --format tsv
rdx --daemon-context case-1 resource show --resource-id <resource-id> --format json
rdx --daemon-context case-1 resource usage --resource-id <resource-id> --format json
```

Use `pipeline show` for the compact state, `pipeline section` for one shader stage, and resource usage to prove where a texture/buffer is bound or written.

### 4. Visual Export And Preview

```bat
rdx --daemon-context case-1 session preview on
rdx --daemon-context case-1 session preview status
rdx --daemon-context case-1 export screenshot --event-id 42 --out intermediate\artifacts\case-1\event42.png
```

Inspect `preview.display` in `context status --json` when geometry matters. It is the stable preview state surface for framebuffer, fit, and window dimensions.

### 5. Pixel Debug

```bat
rdx --daemon-context case-1 pixel value --event-id 42 --resource-id <texture-id> --x 320 --y 180 --format json
rdx --daemon-context case-1 pixel history --event-id 42 --resource-id <texture-id> --x 320 --y 180 --format json
```

Use explicit `texture_id`, `x`, and `y`. If the target texture is unknown, inspect pipeline outputs or VFS draw nodes first.

### 6. Shader Edit With edit_plan

```bat
rdx --daemon-context case-1 shader source --event-id 42 --stage ps --format json
rdx --daemon-context case-1 shader disasm --event-id 42 --stage ps --format json
rdx --daemon-context case-1 shader constants --event-id 42 --stage ps --slot 0 --format json
```

Read `edit_plan` before editing. `captured_source_editable=false` means captured disassembly is read-only. For DXIL/DXBC full replacement, provide complete HLSL through `source_path` or `source_text` with `entry` and `target` such as `ps_6_6`; build failures do not call `ReplaceResource`, and replace failures report cleanup/context evidence. If `runtime_full_replace_supported=false`, follow the returned failure reason instead of inventing a source encoding.

### 7. Android Remote Open And Replay

Use the remote tools explicitly through `rdx call` because device, package, activity, and capture paths are environment-specific:

```bat
rdx --daemon-context android-1 call rd.remote.connect --args-file intermediate\logs\remote_connect_args.json --format json
rdx --daemon-context android-1 call rd.remote.ping --args-file intermediate\logs\remote_ping_args.json --format json
rdx --daemon-context android-1 call rd.capture.open_replay --args-file intermediate\logs\remote_open_replay_args.json --format json
rdx --daemon-context android-1 context status --json
```

After `rd.capture.open_replay`, a consumed remote handle must not be reused as a free connection. Reconnect or recover through the remote lifecycle tools when state reports `remote_handle_consumed`.

### 8. Bug Report Pack

Collect the smallest reproducible evidence set:

```bat
rdx --daemon-context case-1 version --json
rdx --daemon-context case-1 --json doctor
rdx --daemon-context case-1 context status --json
rdx --daemon-context case-1 event show --event-id 42 --format json
rdx --daemon-context case-1 pipeline show --event-id 42 --format json
rdx --daemon-context case-1 export screenshot --event-id 42 --out intermediate\artifacts\case-1\bug-event42.png
```

Include exact commands, JSON payloads, artifact paths, capture SHA256 when shareable, and whether the session was local Windows or remote Android. Do not include private captures or machine-local absolute paths in committed docs or release metadata.
