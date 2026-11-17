# 故障排查

本文按“现象 → 原因 → 恢复”组织。结果字段与错误码的契约见 [public-contract.md](public-contract.md)，context、daemon、worker 与 preview 的生命周期见 [session-model.md](session-model.md)。

## 先运行 doctor

先运行 `rdc-tool --json doctor`。它报告安装根目录（`tools_root`）与主机目标、捆绑 Python、RenderDoc 原生库与绑定的布局、`renderdoc.native_build`（`targets` 中逐目标为 `verified` 或 `absent`，所需目标缺失时给出 `missing_targets`）、`renderdoc.loaded_runtime`、Android helper APK、主机工具与 `shader_tools`、catalog（`fingerprint` 与 `tool_count`）、运行目录、launcher 与 daemon 状态。原生身份的判定规则见 [release-baseline.md](release-baseline.md)，可用的环境变量见 [configuration.md](configuration.md)。

## Context 与 session

用 `rdc-tool context status --json` 查看所选 context。当前 capture 或 session 不对时，执行 `rdc-tool context clear --json`，再重新打开 `.rdc`。用 `rdc-tool context update --key notes --value "..." --json` 留下面向 Agent 的恢复说明。

VFS、facade 命令、`diff pipeline` 或 `assert pipeline` 报告 `session_required`：所选 `--daemon-context` 没有活动 session。用 `capture open --file <rdc>` 打开 capture，或传 `--session-id`。

`rd.session.clear_context` 返回 `context_cleanup_failed`：读取 `details.cleanup_reason_code` 与 `details.cleanup_errors`。session、连接或重启后过期 remote 的清理失败会保留 context；不要删除状态文件，也不要先停 daemon。Android helper 记录的 `owned_pids` 必须与当前进程一致才可停止；旧快照没有该证明且进程仍在时保持隔离。确认原 helper 已退出后，仍须让 Tool 验证并移除自己创建的 ADB forward，再取得成功的 `clear_context` 与 `daemon stop` 回执。

worker 退出后的 `requires_restart` 会话只有在旧 worker 退出身份可核实、没有活动 replacement 且远程归属可确认时才允许继续清理。原生清理失败时保留会话和未确认的句柄；不要把重试或进程身份不可读当作释放证明。

### session 操作超时

`rd.session.*` 的 worker 预算与 65 秒传输截止时间见 [session-model.md](session-model.md)，它们与宿主应用的外层进程超时相互独立。宿主在 65 秒之前就报告超时时，确认它使用的是当前打包的 RDC-Tool，且外层 CLI 截止时间大于 65 秒。不要添加单次调用的超时覆盖，也不要原地修改已安装的包；更新并重新安装 RDC-Tool，让策略与测试保持唯一真源。

## Daemon 启动与状态锁

`daemon_start_lock_timeout`：本调用方 30 秒内未取得该 context 的启动锁，另一调用方可能仍在检查或启动 daemon。查看报告的 context 与等待阶段，等现有启动完成后重试同一 context。不要删除 `.start.lock`、清除 context 状态或停止存活的 owner 来绕过等待。它不同于 daemon 就绪超时与操作响应超时，不能证明现有 owner 已失败。

`state_lock_timeout`：另一写入方在 10 秒内仍持有 context 状态或快照文件的锁。等并发写入完成后重试，不要删除锁文件。

`daemon_owner_unavailable`：无法确认该 context 的 owner，`details.reason` 给出原因。保留 owner 及其状态并重试 `daemon status`；确需替换时，先显式 clear/stop 已识别的 owner 并确认进程退出，再启动新的 daemon。

`legacy_state_identity_unconfirmed` 或 `legacy_state_resources_unconfirmed` 表示旧状态的进程或资源尚不能安全退役。保留该状态及关联 context、worker 登记，按记录核对后再恢复；不清空整个运行目录，也不暴露状态中的认证信息。

## 回放

`rd.capture.open_replay` 复用同一 context 中同一 capture 的 live session。重开前用 `rd.capture.close_replay` 释放回放资源。daemon 超时后，先查看 `rdc-tool context status --json` 与操作历史，再决定是否清除或停止 context。过期清理失败时返回 `stale_session_requires_restart` 与恢复命令。

`rd.capture.open_replay` 返回 `local_replay_unsupported`：本主机的 RenderDoc 运行库不能在本地回放该 capture 的图形 API（例如 Linux 上的 D3D11/D3D12 capture），请求在创建任何回放之前就被拒绝。`details.capture_api` 与 `details.host_target` 给出具体组合，分类见[公共契约](public-contract.md)。改在支持该 API 的主机上回放，或先 `rd.remote.connect`，再通过 `options.remote_id` 远端回放。

`rd.remote.connect` 之后远端回放失败：查看状态是否为 `remote_handle_consumed`。它表示句柄已被 `rd.capture.open_replay` 消费，应经远端工作流重连或恢复，不要复用旧句柄。

### 恢复型查询失败

缺少嵌入缩略图、缺少初始化来源、GPU timestamp 覆盖不支持与读回失败是不同的结果。绝不用回放图像代替缩略图、用当前字节代替初始字节、用事件耗时之和代替完整回放时间。回放恢复失败时，须关闭并重新打开被隔离的 session。原生 client/server 握手不兼容时，须使用配套的运行库组件；仅有 helper 进程存在不能证明服务被占用。

空闲一段时间后 SaveTexture 报告 DataNotAvailable：检查第一个原生传输失败。server 端 5 秒空闲接收超时可能在读回前就关闭了连接，之后的空数据错误只是次生结果。改用配套重建、空闲时轮询数据包的 helper。不要用旧图像、强制重启用户服务或无限重试来掩盖；原生 SaveTexture 诊断保留 Message() 细节，包括失败的 mip/slice/sample。

## 着色器替换

编辑着色器文本前先读 `edit_plan`；`rd.shader.get_source`、`rd.shader.get_disassembly`、`rd.shader.compile` 与 `rd.shader.edit_and_replace` 都会返回它。

调试源码不可用时，`rd.shader.get_source` 返回按格式区分的回退。SPIR-V 可以转到 `rd.shader.get_disassembly`，使用 `target=SPIR-V ASM` 与 `source_encoding=spirvasm`。`rd.shader.edit_and_replace` 编辑原始 SPIR-V ASM 而回放后端只接受二进制 `SPIRV` 时，`rdc-tool` 先用 `spirv-as` 汇编，再调用 RenderDoc。返回 `shader_build_failed` 且 `failure_reason=spirv_assembly_failed` 时，检查 `rdc-tool --json doctor` 的 `shader_tools.spirv_as`。

DXIL/DXBC 反汇编默认只读。`edit_plan.captured_source_editable=false` 时，不要把该反汇编文本传给 `rd.shader.edit_and_replace`。整源替换是另一条路径：通过 `source_path` 或 `source_text` 提供完整的 HLSL/GLSL，并给出 `entry` 与 `target`（如 `ps_6_6`）。构建失败不会调用 `ReplaceResource`；替换失败包含 `replacement_attempted`、`cleanup_attempted` 与 `context_preserved`。

## 纹理导出

### Store 与 Don’t Care 图案

管线显示的原始捕获 load/store 动作、回放归一化后的动作和实际纹理内容需要分别核对。`Store` 说明 pass 结束时保留结果，并不保证开始时已有有效内容；`DONT_CARE` load、undefined layout transition 或单独的深度/模板弃置，可以在未被后续绘制覆盖的区域留下 RenderDoc 的诊断图案。图案本身可能已是纹理像素，而非界面文字叠加。

先固定事件、附件、aspect、子资源和坐标，再用结构化捕获记录、管线状态、`rd.texture.get_pixel_value` 和显式纹理导出对照。原始记录与临时回放 pass 不应混用；不能通过禁用图案或强制 clear 来掩盖内容来源。未定义区域没有固定的正确像素值。

### 格式与读取失败

`rd.export.texture` 接受 `file_format`，已移除的 `format` 参数会被拒绝。运行时无法生成显式请求的 HDR/EXR/DDS 时直接失败；PNG 是显示映射输出，不能当作 HDR 数据证据。

纹理统计、直方图与数值差异在内存中读取数据。不支持的 packed/压缩布局、字节数不符、无效子资源、非有限输入、无效直方图范围或后端读取失败都返回结构化失败，不以空值或零值代替失败的读取。只有需要持久 artifact 时才使用 `rd.texture.get_data` 或导出操作。

## 升级后操作返回 `not_found`

运行 `rdc-tool tools search <term>` 与 `rdc-tool tools describe <name>` 找到当前操作，再更新调用方。当前运行时不执行旧名称，也没有 alias（见 [public-contract.md](public-contract.md)）。

## Preview

preview 打不开或自动失效：先用 `session preview status` 查看状态，并对照 `context status` 中当前的 `session_id`。`rd.session.open_preview` 返回 `preview_unsupported_platform` 时，本主机没有原生 preview 窗口实现（目前只有 Windows 提供），`rd.core.get_capabilities` 的 `preview_window.available` 为 `false`；无窗口观察使用 `rd.session.observe`。

preview 看着不全、留黑边或像是畸形：检查 `preview.display`，确认没有把 framebuffer 尺寸与 viewport / scissor 混为一谈。

`export screenshot` 返回 `preview_event_output_unavailable`：当前事件没有可验证的 Present、输出槽或绑定目标，错误详情保留 Present 解析失败的原因。选择有输出的事件，或在已知资源身份时显式使用 `export texture`。不要把纹理列表中的任意资源当作 framebuffer。

## Facade TSV

`--format tsv` 只支持列表与投影命令，如 `vfs ls`、`event list`、`resource list`。`pipeline show`、`shader disasm`、`export screenshot`、`pixel history` 与资源详情等嵌套状态请使用 JSON。

## Android

Android 准备、借用、未决安装与超时策略的契约见 [public-contract.md](public-contract.md) 的 Android 远端一节，helper 与 forward 的生命周期见 [session-model.md](session-model.md)。

### 设备列表为空与主机工具缺失

先运行 doctor，区分安装依赖缺失、ADB server 查询失败、合法的空设备列表与设备 unauthorized/offline。修复安装内的 ADB，或清除错误的显式覆盖（见 [configuration.md](configuration.md)）后重试；连接前不需要清空设备进程，也不按进程名结束其他用户的服务。正常默认路径不依赖外部 SDK 或 PATH。Agent 菜单提供状态与刷新，展开期间自动检测热插拔，关闭菜单即停止检测。

### ADB 查询与设备状态

Android bootstrap 在同一连接 deadline 与取消范围内，先确保所选 ADB server 就绪，再查询设备状态、准备 helper/socket、forward 与握手。已有明确 serial 时只对该设备执行 `get-state` 并要求 `device`，不重新枚举或自动选择其他设备；只有未指定 serial 的独立 CLI 调用才枚举并严格校验设备列表响应头。错误详情保留有界的实际命令、退出码、stdout 与 stderr。

- `adb_server_start_failed`：server 启动失败，不继续创建 helper。
- `adb_devices_invalid_response`：退出码为零但缺少设备列表响应头，不能当作没有设备。
- `adb_device_invalid_response`：已选设备返回空或异常的状态响应。
- offline、unauthorized、bootloader 等非回放状态：拒绝准备 helper。
- 设备查询本身失败：保留 ADB 原始错误原因，不解析错误文案来推断授权状态。

正常的空设备列表按设备状态报告，不做隐藏重试，也不切换 ADB 来源。

### Windows 首次连接与隐藏进程

daemon 以无窗口方式启动；runtime worker 创建时持有一个隐藏的自有 console，ADB 子进程继承它，并使用独立 process group 与捕获管道，不使用 `DETACHED_PROCESS` 或 `CREATE_NO_WINDOW`。隐藏 console 不能替代输出校验：曾观察到 `get-state` 退出码为 0 而 stdout/stderr 为空，这类响应保留有界诊断并按 invalid_response 拒绝，不能当作设备不存在。一次带诊断的只读核验成功，不能证明间歇故障的根因或稳定性已经解决。超时、取消、kill/join 与资源归属检查继续有效；不要通过反复查询、改用其他 ADB 或操作设备来掩盖失败。设备状态与安装成功回执同样须严格核验，不能凭进程退出码声称成功。

### 连接与回放

设备发现不启动 helper。RDC-Agent 在当前活动会话中选择 Android 后，立即在所属 context 调用 `rd.remote.connect`，依次完成查询、兼容服务复用或自有 helper 准备/启动、就绪探测、forward 与握手，不等待打开 capture；没有活动会话时不连接，之后的 Open 复用同一所属 context 与连接。关闭时先 clear context，再 stop 自有 daemon。

RenderDoc Command 通常由 connect 启动，用户无需手动启动它或清空所有进程。设备列表非空不等于服务就绪；失败保留原生代码与结构化阶段。ADB 查询失败、socket 缺失、socket 含糊以及原生实际报告的 busy/不兼容是不同的失败。请求的 socket 存在时优先使用，否则要求唯一候选。修正就绪或网络问题后重试；不要强制停止用户服务或替换其端口映射作为未经确认的恢复捷径。复用兼容的用户服务不取得停止、重装或改配置的权限，busy 不抢占。PNG 成功不能证明 Android 屏幕已呈现。

open_replay 期间出现真实的远端 busy 状态，也可能是所属运行时已持有连接时又尝试第二个连接；回放必须复用该句柄。事件导航后 SaveTexture 报告 DataNotAvailable 是读回失败，不是成功观察：保留请求与已应用的 EID，不给出图像身份，并报告原生失败。

### 安装未确认

`remote_install_unconfirmed`：安装客户端已退出但缺少明确的 `Success` 或 PackageManager `Failure` 回执时返回，`device_action.observation=unreadable`。退出码为零、stdout/stderr 为空、成功与失败回执相互矛盾，或非零退出码伴随 `Success`，都属于未确认。明确的 PackageManager 安装失败返回 `android_apk_install_failed`。工具不会自动再次安装，也不用附加查询掩盖原回执。消费者先保留未决状态，用 `rd.remote.inspect_installation` 核验后再决定下一步，不能把“未确认”显示成“确定未安装”。

### target 列表与 target control

`rd.remote.list_targets` 的空数组只表示本次成功扫描没有发现 target socket。Android 查询所属连接选定 serial 的 `/proc/net/unix`，区分 target-control socket（38920–38927）与 replay-server socket（39920）；读取失败、空输出或缺失表头都是错误，不能据此断言没有应用。TCP target discovery/control 只使用 host，replay server 的 host:port 不能传给这两个原生接口。

Android target control 为每个实际 target 临时建立带 `--no-rebind` 的自有 forward；公开的 `target_id` 保留设备逻辑 ident，不使用主机临时端口。每次操作无论成功或异常，都先 `Shutdown` control，再核对 serial、local spec 与 remote socket 后回收自有 forward；不停止应用，也不移除外部映射。busy target 不 force-connect，抓帧、复制和删除都拒绝占用。清理失败时保留 ownership 并返回失败；先重试 `rd.remote.disconnect`，不要手工删除 ownership，也不要把失败当作已释放。

### ADB forward 清理

ADB forward 清理只以 ADB server 的 `host:list-forward` 协议应答作为列表真源，不读取 CLI `forward --list`；CLI 即使返回换行或退出码为零，也不能证明列表 payload 完整。一次查询共用 10 秒 deadline，完整读取 `OKAY`、4 位十六进制长度及对应 payload；完整的零长度帧才是合法的空列表。`FAIL`、EOF、超时、无效的长度、UTF-8 或行格式都是 `ADB forward cleanup unconfirmed`，并保留 lease。

查询按 ADB 标准的 server 端点变量优先级选择 server（变量见 [configuration.md](configuration.md)），默认 `localhost:5037`，只支持 TCP 端点；不支持的端点明确报告未确认，不回落到默认 server。同一次清理固定 endpoint，捆绑 ADB 的删除命令通过显式 `-H`/`-P` 绑定该 server；删除后只做一次同协议查询，确认 local spec 已无映射。映射仍在、查询失败或外部重绑都不能退役 ownership，也不会追加删除、自动重试或改用其他查询路径。公开错误沿用 disconnect/context cleanup 的既有错误与 `cleanup_errors`。`context clear` 的成功回执不能替代 forward、helper 与宿主进程各自的终态证据。
