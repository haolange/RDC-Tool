# Troubleshooting

## Doctor

Run `rdc-tool --json doctor` first. It reports the tools root, Python runtime, RenderDoc DLL/PYD layout, catalog count, launchers, and daemon status.

## Session State

Use `rdc-tool context status --json` to inspect the active context. If the wrong capture/session is active, run `rdc-tool context clear --json` and reopen the `.rdc`. Use `rdc-tool context update --key notes --value "..." --json` to leave agent-facing recovery notes.

If VFS, facade commands, `diff pipeline`, or `assert pipeline` reports `session_required`, the selected `--daemon-context` has no active session. Open a capture with `capture open --file <rdc>` or pass `--session-id`.

## Remote Lifecycle

If a remote replay fails after `rd.remote.connect`, check whether state says `remote_handle_consumed`. That means the handle was consumed by `rd.capture.open_replay`; reconnect or recover through the remote workflow instead of reusing the old handle.

## Replay Reopen

`rd.capture.open_replay` reuses an existing live session for the same capture in the same context. Use `rd.capture.close_replay` to release replay resources before reopening. After a daemon timeout, check `rdc-tool context status --json` and operation history before clearing or stopping the context. If stale cleanup fails, the runtime returns `stale_session_requires_restart` with recovery commands.

## Shader Replacement

Read `edit_plan` before editing shader text. It is returned by `rd.shader.get_source`, `rd.shader.get_disassembly`, `rd.shader.compile`, and `rd.shader.edit_and_replace`.

When debug source is unavailable, `rd.shader.get_source` returns a format-aware fallback. SPIR-V can point to `rd.shader.get_disassembly` with `target=SPIR-V ASM` and `source_encoding=spirvasm`. If `rd.shader.edit_and_replace` edits raw SPIR-V ASM and the replay backend only accepts binary `SPIRV`, `rdc-tool` uses `spirv-as` to assemble the edited ASM before calling RenderDoc. Check `rdc-tool --json doctor` -> `shader_tools.spirv_as` when the tool returns `shader_build_failed` with `failure_reason=spirv_assembly_failed`.

DXIL/DXBC disassembly is read-only by default. If `edit_plan.captured_source_editable=false`, do not pass that disassembly text to `rd.shader.edit_and_replace`. Full replacement is separate: provide complete HLSL/GLSL through `source_path` or `source_text`, plus `entry` and `target` such as `ps_6_6`. Build failures do not call `ReplaceResource`; replacement failures include `replacement_attempted`, `cleanup_attempted`, and `context_preserved`.

## Texture Export

`rd.export.texture` accepts `file_format`. The removed `format` parameter is rejected. Explicit HDR/EXR/DDS requests fail closed when the runtime cannot produce that format; PNG is display-mapped output and should not be treated as HDR data evidence.

Texture statistics, histograms, and numeric differences read data in memory. An unsupported packed/compressed layout, byte-count mismatch, invalid subresource, non-finite input, invalid histogram range, or backend read failure returns a structured failure. Empty or zero output is not used as a substitute for failed acquisition. Use `rd.texture.get_data` or an export operation only when a persistent artifact is required.

If an operation returns `not_found` after upgrading, run `rdc-tool tools search <term>` and `rdc-tool tools describe <name>`. The current runtime does not execute old names. See [tool-interface-upgrade.md](tool-interface-upgrade.md) for the documented destination, then update the caller.

## Preview

preview 打不开或自动失效：先检查 `session preview status` and the current `session_id` from `context status`.

preview 看着不全、留黑边或像是畸形：检查 `preview.display` and confirm the framebuffer extent is not being confused with viewport / scissor.

## Facade TSV

`--format tsv` is supported only by list/projection commands such as `vfs ls`, `event list`, and `resource list`. Use JSON for nested state such as `pipeline show`, `shader disasm`, `export screenshot`, `pixel history`, and resource details.

## Android connection recovery

RenderDoc Command is normally started by connect; users need not launch it manually or clear all processes. Existing helper processes are reused. ADB query failure, missing socket, ambiguous sockets and actual native busy/incompatible results are separate failures. The requested socket wins when present; otherwise a unique candidate is required. Retry after readiness/network correction; do not force-stop user services or replace their port mappings. A successful PNG does not establish Android screen presentation.

A real remote busy status during open_replay can also result from attempting a second connection while the owning runtime already holds one; replay must reuse that handle. SaveTexture DataNotAvailable after event navigation is a failed readback, not successful observation: preserve requested/applied EIDs, leave image identity absent and report the native failure.

## Restored query failures

Missing embedded thumbnail, missing initialization provenance, unsupported GPU timestamp coverage and readback failure are different outcomes. Never substitute a replay image for a thumbnail, current bytes for initial bytes, or event-duration sums for full replay time. A failed replay restoration requires closing and reopening the isolated session. Native client/server handshake incompatibility requires matching runtime components; helper process presence alone does not prove occupation.

If SaveTexture reports DataNotAvailable after an idle period, inspect the first native transport failure. A server-side five-second idle receive timeout can close the connection before readback; the later empty-data error is secondary. Use the matching rebuilt helper with idle packet polling. Do not mask this with stale images, forced user-service restarts, or unlimited retries. Native SaveTexture diagnostics retain Message() details including the failed mip/slice/sample.
