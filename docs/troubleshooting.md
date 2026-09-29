# Troubleshooting

## Doctor

Run `rdc-tool --json doctor` first. It reports the tools root, Python runtime, RenderDoc DLL/PYD layout, catalog count, launchers, and daemon status.

## Session State

Use `rdc-tool context status --json` to inspect the active context. If the wrong capture/session is active, run `rdc-tool context clear --json` and reopen the `.rdc`. Use `rdc-tool context update --key notes --value "..." --json` to leave agent-facing recovery notes.

If VFS, facade commands, `diff pipeline`, or `assert pipeline` reports `session_required`, the selected `--daemon-context` has no active session. Open a capture with `capture open --file <rdc>` or pass `--session-id`.

### Session daemon timeout

`rd.session.*` operations have a 60-second worker budget and a 65-second CLI
transport deadline (the shared 5-second response buffer is added by the CLI).
These are separate from the host application's outer process timeout. If a host
reports a timeout before 65 seconds, verify that it is using the current packaged
RDC-Tool and that its outer CLI deadline is greater than 65 seconds. Do not add a
per-call timeout override or edit an installed package in place; update and
reinstall the RDC-Tool build so the policy and tests remain the single source of
truth.

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

`rd.session.clear_context` 若返回 `context_cleanup_failed`，读取 `details.cleanup_reason_code` 和 `details.cleanup_errors`。会话、连接或重启后过期 remote 的清理失败会保留 context；不要删除状态文件或先停 daemon。Android helper 的原始 `owned_pids` 必须与当前进程一致才可停止；旧快照没有该证明且进程仍在时保持隔离。确认原 helper 已退出后，仍须让 Tool 验证并移除自己创建的 ADB forward，再取得成功的 clear_context 与 daemon stop 回执。

## Preview

preview 打不开或自动失效：先检查 `session preview status` and the current `session_id` from `context status`.

preview 看着不全、留黑边或像是畸形：检查 `preview.display` and confirm the framebuffer extent is not being confused with viewport / scissor.

`export screenshot` 返回 `preview_event_output_unavailable`：当前事件没有可验证的 Present、输出槽或绑定目标；错误详情保留 Present 解析失败原因。选择有输出的事件，或在已知资源身份时显式使用 `export texture`。不要把纹理列表中的任意资源当作 framebuffer。

## Facade TSV

`--format tsv` is supported only by list/projection commands such as `vfs ls`, `event list`, and `resource list`. Use JSON for nested state such as `pipeline show`, `shader disasm`, `export screenshot`, `pixel history`, and resource details.

## Android connection recovery

RenderDoc Command is normally started by connect; users need not launch it manually or clear all processes. Existing helper processes are reused. ADB query failure, missing socket, ambiguous sockets and actual native busy/incompatible results are separate failures. The requested socket wins when present; otherwise a unique candidate is required. Retry after readiness/network correction; do not force-stop user services or replace their port mappings. A successful PNG does not establish Android screen presentation.

A real remote busy status during open_replay can also result from attempting a second connection while the owning runtime already holds one; replay must reuse that handle. SaveTexture DataNotAvailable after event navigation is a failed readback, not successful observation: preserve requested/applied EIDs, leave image identity absent and report the native failure.

## Restored query failures

Missing embedded thumbnail, missing initialization provenance, unsupported GPU timestamp coverage and readback failure are different outcomes. Never substitute a replay image for a thumbnail, current bytes for initial bytes, or event-duration sums for full replay time. A failed replay restoration requires closing and reopening the isolated session. Native client/server handshake incompatibility requires matching runtime components; helper process presence alone does not prove occupation.

If SaveTexture reports DataNotAvailable after an idle period, inspect the first native transport failure. A server-side five-second idle receive timeout can close the connection before readback; the later empty-data error is secondary. Use the matching rebuilt helper with idle packet polling. Do not mask this with stale images, forced user-service restarts, or unlimited retries. Native SaveTexture diagnostics retain Message() details including the failed mip/slice/sample.
