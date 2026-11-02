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

RenderDoc Command is normally started by connect; users need not launch it manually or clear all processes. Compatible running helper processes are reused; incompatible services follow the repair policy below. ADB query failure, missing socket, ambiguous sockets and actual native busy/incompatible results are separate failures. The requested socket wins when present; otherwise a unique candidate is required. Retry after readiness/network correction; do not force-stop user services or replace their port mappings as an unconfirmed recovery shortcut. A successful PNG does not establish Android screen presentation.

A real remote busy status during open_replay can also result from attempting a second connection while the owning runtime already holds one; replay must reuse that handle. SaveTexture DataNotAvailable after event navigation is a failed readback, not successful observation: preserve requested/applied EIDs, leave image identity absent and report the native failure.

## Restored query failures

Missing embedded thumbnail, missing initialization provenance, unsupported GPU timestamp coverage and readback failure are different outcomes. Never substitute a replay image for a thumbnail, current bytes for initial bytes, or event-duration sums for full replay time. A failed replay restoration requires closing and reopening the isolated session. Native client/server handshake incompatibility requires matching runtime components; helper process presence alone does not prove occupation.

If SaveTexture reports DataNotAvailable after an idle period, inspect the first native transport failure. A server-side five-second idle receive timeout can close the connection before readback; the later empty-data error is secondary. Use the matching rebuilt helper with idle packet polling. Do not mask this with stale images, forced user-service restarts, or unlimited retries. Native SaveTexture diagnostics retain Message() details including the failed mip/slice/sample.


## Concurrent daemon startup

`daemon_start_lock_timeout` means this caller could not acquire the context startup lock within 30 seconds. Another caller may still be checking or starting that daemon. Inspect the reported context and waiting stage, let the existing startup finish, then retry the same context. Do not delete `.start.lock`, clear context state or stop a live owner to bypass this wait. The timeout is distinct from daemon readiness and operation-response timeouts; it does not prove the existing owner failed.

## Android 列表为空与主机工具缺失

先运行 doctor，区分安装依赖缺失、ADB server 查询失败、合法空设备列表和设备 unauthorized/offline。修复安装内 ADB 或清除错误的显式覆盖后重试；不要求连接前清空设备进程，不按进程名结束其他用户服务。Agent 菜单提供状态与刷新，展开期间自动检测热插拔；关闭菜单停止检测。正常默认路径不依赖外部 SDK/PATH。


## Windows Android 首次连接与隐藏进程

Windows 无控制台宿主启动 canonical daemon/worker 时，使用显式创建并隐藏的自有控制台；ADB 子进程使用独立 process group 与显式 stdio，连接和清理复用该边界。已有环境曾观察 get-state 退出码0却stdout/stderr为空，应保留有界诊断并按 invalid_response 拒绝，不能冒充设备不存在。一次带诊断的只读核验成功不能证明间歇故障根因或稳定性已解决。超时、取消、kill/join 与资源归属检查继续有效，不通过反复查询、改用其他ADB或操作设备掩盖失败。

设备发现不启动 helper；RDC-Agent 在当前活动会话选择 Android 后立即调用所属 context 的 rd.remote.connect，按查询、兼容服务复用或自有 helper 准备/启动、就绪探测、forward 与握手推进，不等待打开 Capture。无活动会话不得连接；随后 Open 复用同一 owning context/connection。设备列表非空不等于服务就绪，失败保留原生代码与结构化阶段。复用用户服务不取得停止、重装或改配置的权限；不兼容服务只按下述 auto_safe/confirmed 修复策略处理，busy 不抢占。关闭先 clear context，再 stop 自有 daemon。

Android bootstrap 在同一连接 deadline/cancel scope 内先显式确保所选 ADB server 就绪，再查询设备状态、准备 helper/socket、forward 与握手。已有明确 serial 时只执行该设备的 `get-state` 并要求 `device`，不重新枚举或自动选择其它设备；仅未指定 serial 的独立 CLI 调用枚举并严格校验设备列表响应头。错误详情保留有界的实际命令、退出码、stdout 与 stderr。退出码为零但缺少设备列表响应头属于 `adb_devices_invalid_response`，不能冒充无设备；server 启动失败为 `adb_server_start_failed`，不继续创建 helper。正常空设备列表仍按设备状态报告，不做隐藏重试或切换 ADB 来源。

已选设备的空/异常状态响应报告 `adb_device_invalid_response`；offline、unauthorized、bootloader 等非回放状态拒绝 helper 准备。设备查询本身失败保留 ADB 原始错误原因，不解析错误文案来假定授权状态。


## Android remote preparation and repair

`rd.remote.connect` owns Android preparation and connection in the caller's daemon context. It checks the selected device, same-install APK package/versionCode/hash and the actual native handshake. Android versionName may be a source commit hash, not a numeric version. Missing helpers are installed; a stopped older helper can be upgraded with package data preserved. A compatible running helper is borrowed without installation, configuration or launch. A busy endpoint is never repaired or taken over.

Use `options.repair_policy=auto_safe` (the default). A repair needing unknown-service restart, package removal or downgrade returns `remote_repair_required` with `error.details.remote.repair`. Present its impact, then resubmit `repair_policy=confirmed` and `repair_confirmation={fingerprint}`. The fingerprint binds the current serial, package identity, process birth identities, target APK hash, expected runtime and exact actions. Changed facts return `remote_repair_state_changed`; confirmation does not survive state change or authorize another action. Missing/unreadable identities do not grant destructive repair. Recovery snapshots retain only auto_safe, never a prior confirmation.

Diagnostics distinguish device availability, package/install failure, busy, incompatibility and cancellation. `details.remote.stage` identifies checking/installing/starting/verifying; live stages use the existing daemon active_operation reporter. Cancellation joins the owned host native actions and cleans only acquired process/forward resources; host exit is not proof of a device PackageManager terminal outcome. A completed installation is recorded as a fact and is not uninstalled to pretend rollback. Normal reuse and cleanup preserve borrowed helpers and user configuration; an explicitly confirmed destructive repair may replace the identified service or remove package data only with the disclosed actions and unchanged fingerprint. Confirmation is not cleanup ownership or permission to stop an unrelated helper.

Windows runtime worker 在创建时持有隐藏 console，ADB 子进程继承该 console 并使用捕获管道；不对 ADB 使用 `DETACHED_PROCESS` 或 `CREATE_NO_WINDOW`。隐藏 console 不能替代实际输出校验；设备状态与安装成功回执仍须严格核验，任何空白或异常响应均显式失败，不能据进程退出码声称成功。

Android 安装前只读查询 `dumpsys package installs` 的 active sessions。目标包或未知包的未终结 session，以及无法判读的 vendor 状态，返回 `remote_install_unconfirmed`，不继续安装、卸载或 abandon；无关且包名明确的其他安装不影响已有兼容连接。`mDestroyed=true` 不能单独证明结束：必须观察实际成功／失败结果及 stage 不再 in-use。错误只返回必要 session 事实，不回传其他应用历史。

未决状态的唯一结构化标志为 `error.details.device_action`：`kind=android_install`、`state=unconfirmed`，附设备、目标包／APK hash、必要 sessions 和 `observation=pending|unreadable`。安装超时为 `android_apk_install_timeout`；已确认的 `installation.installed_apk`／`uninstalled_existing` 事实仍保留，取消回执亦不得抹去未决状态。包当前不存在、host 进程退出或 abandon 应答成功均不能替代设备端终态证明。

`rd.remote.connect.timeout_policy` 从 `timeout_policy.py` 单源生成，声明 `argument`、`default_timeout_ms`、`worker_grace_ms`、`transport_grace_ms` 和 `process_grace_ms`。调用方显式传入本机 native budget；worker 在该 budget 后保留 85 秒用于 join／清理，CLI transport 再保留 5 秒，宿主进程再保留 5 秒用于接收最终回执。原有 90 秒 transport 余量在 worker／transport 间拆分，不更改用户设置；调用方不得读取描述猜测或在缺失 policy 时默认放行。

应用内解除未决安装使用唯一只读操作 `rd.remote.inspect_installation`，参数仅 `device_serial`，必须经非 default owning context。该操作复用连接前的设备校验、同安装 APK 包名／SHA256 和 PackageManager active-session 检查；不安装、卸载、启动 helper、建立连接或 abandon。结果 `installation_state=clear|pending|unknown` 与 `observation=verified|pending|unreadable` 分别表示可核实的状态和观察范围。`clear` 只证明没有相关未决安装，不证明 helper 已安装、兼容或已连接；应用确认冻结 CLI/catalog 与原目标 APK 身份一致后，才能继续用户本次明确请求的正常准备。pending／unknown 保留原未决事实和设备占用。
