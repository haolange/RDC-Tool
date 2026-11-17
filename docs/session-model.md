# 会话模型

本文描述 context、daemon、worker、回放会话与 preview 的生命周期。调用方可依赖的结果字段与错误码见 [public-contract.md](public-contract.md)，现象与恢复步骤见 [troubleshooting.md](troubleshooting.md)，分层结构见 [ARCHITECTURE.md](../ARCHITECTURE.md)。

## 进程模型

CLI → daemon（每个 `--daemon-context` 一个）→ worker。CLI 只解析参数、发现 daemon 并转发请求；daemon 拥有该 context 的状态文件、IPC endpoint、owner 锁与唯一的 worker；worker 是唯一加载 RenderDoc 的进程，在 `rdc_tool/runtime/` 中按 dispatch → routing → `operations/<namespace>.py` 执行 `rd.*` 操作，并返回 canonical 结果信封。

## Context

`rdc-tool context status` 返回所选 context 的当前状态；`rdc-tool context update` 修改面向 Agent 的字段，如 notes 与 focus。`session_locator` 汇总当前的 `.rdc`、session、frame 与 event。

`--daemon-context <id>` 选择持续的运行时命名空间，不是 daemon 模式开关；省略时为 `default`。`rdc-tool context list` 列出已知命名空间，`rdc-tool context clear` 清除所选命名空间。读取其他命名空间时，在该 daemon context 下调用 `rd.session.get_context`；不存在修改隐式“当前命名空间”的选择操作。

新建命名空间受实时占用上限 `max_contexts` 限制，与磁盘上残留的状态文件数量无关；复用已有命名空间不额外占用名额。占用的计算方式见 [configuration.md](configuration.md)。

`context clear` 释放 replay、preview、remote 与快照状态，成功时删除该命名空间的状态文件，但不停止 daemon 或 worker。拥有进程的宿主须传 `--owner-pid`，结束时对同一 context 执行 `daemon stop`；context 仍持有资源时 `daemon stop` 拒绝执行，须先 clear。daemon 异常退出后，`daemon stop` 仍会回收该 context 记录的 worker；worker 也会在父 daemon 退出时自行退出。

多个 daemon context 相互隔离，由调用方选择要操作的 context。远端句柄保持 context 局部性与生命周期保护：`remote_handle_consumed` 表示句柄已转入 session 所有权，重连须创建或恢复新的句柄。

## Daemon 所有权与状态

daemon 状态位于 `<intermediate>/runtime/rdc_tool_cli/`，由 `rdc_tool/daemon/state.py` 唯一管理；context 状态与快照文件也在该目录。状态文件是私有的（POSIX 上为 0600）。

每个 daemon 持有该 context 的排他 owner 锁直到进程退出。短暂的启动锁与它分开，调用方等待子进程就绪时不会阻塞其获取所有权。状态发布原子且串行，其中的 PID、IPC endpoint 与 IPC 密钥必须指向同一 owner；迟到的客户端响应从不写入 daemon 状态。

每个 daemon 监听自己的本机 endpoint：Windows 为 named pipe，POSIX 为私有 0700 目录中的 Unix socket。每个连接先用该 daemon 的密钥完成 HMAC challenge 认证，之后才解码请求。密钥经 stdin 交给 daemon，不出现在命令行，只保存在 owner 私有的状态文件中。`daemon start` 与 `daemon status` 的输出报告 `endpoint`，daemon 响应与 CLI 输出从不包含密钥。确认 owner 退出的一方同时移除其 endpoint。

owner 锁仍被持有而状态文件缺失或无效，或者存活 owner 的 status 探测失败时，返回 `daemon_owner_unavailable`，不停止、清除或替换 owner。显式关闭须确认 daemon 与记录的 worker 都已终止，才移除其状态或允许替代者；仅有状态文件缺失不能证明进程已退出。

## 进程身份与终止

daemon、worker、owner 与 attached client 记录都在 PID 旁保存 OS 进程诞生标识，每次存活或终止判断都比较 `(pid, birth)`：PID 复用或僵尸进程视为已退出；身份不可读视为未知，既不证明退出，也不授权终止。POSIX daemon 在自己的 session 中启动并领导进程组，worker 留在该组内，终止时按进程组结束；Windows 在确认身份后用 `taskkill /T` 结束进程树。worker 向调用方报告的进程身份见 [public-contract.md](public-contract.md)。

## 锁与启动串行化

daemon 启动按 canonical context 状态路径跨 CLI 进程串行执行状态检查、创建与就绪发布：并发调用方复用已发布的 owner，不会创建相互竞争、分裂文件与回放句柄的多个 daemon。启动锁只锁这个 context，不替代运行时已有的操作串行化。`daemon stop` 在同一把锁内执行，新的启动者要等 daemon 与 worker 都确认退出。

获取启动锁使用一个单调的 30 秒截止时间，覆盖进程内 mutex 与跨进程文件锁（Windows 为字节范围锁，POSIX 为 `flock`），以不超过 50 ms 的间隔非阻塞重试。持久化的 context 状态与快照文件使用同一锁契约，截止时间为 10 秒，超时报告 `state_lock_timeout`，不会无限阻塞。只重试有记载的锁争用；文件打开、描述符与参数错误立即失败。截止时间只限制获取，不限制受保护的检查、创建与就绪段。等待者从不删除锁或停止活动 owner。CLI 启动在同一已获取的边界内做过期状态检查。成功、失败与中断都会释放已取得的资源；进程退出时由 OS 释放锁，不另设 owner 恢复机制。错误字段见 [public-contract.md](public-contract.md)。

## 资源释放与空闲

客户端清理与 daemon 生命周期共用同一“未释放资源”检查。仅因空闲不能停止仍持有 capture、replay、远端所有权或活动请求的 daemon；丢失 owner 的租约过期后仍允许清理。不可读的所有权状态保留给受控恢复。

新启动或替换的 worker 在分派请求前把持久化的 replay session 标记为 `requires_restart` 并保留其元数据；请求从不隐式拉起替代 worker。显式 context 清理始终可用。worker 替换前后，持久化的 session ID 与相同的图像哈希都不能证明连续性。

## Worker 与回放执行

worker 跨请求保留一个 event loop 与 replay executor，以保持原生线程亲和性。着色器 patch 的检查、编译、应用与回滚（含事件重绑定与目标资源释放）都在同一 replay executor 上执行，异步 patch API 不得在 event-loop 线程访问原生 controller 对象。管线快照中的 controller 资源同样在 replay executor 上获取。

回放操作只跟踪自己实际访问的 controller，作用域限于自身的 async context。首次访问与最终结果边界都在持久 replay executor 上轮询原生 fatal 状态；不访问 controller 的校验错误不会打开或探测回放。fatal 或无法观察的健康状态会把所属 session 标记为 `requires_restart`，并在发布成功结果或 artifact 之前拒绝该结果；失败或取消时作用域同样重置。catalog 中的生命周期操作保留清理路径。一次成功的健康检查只是瞬时观察，不保证之后的连接，也不是恢复回执。

正常的着色器回滚在现有 live replay controller 上移除 replacement、重绑定事件并释放目标资源，不关闭或重开回放与远端连接。worker 回复丢失或 worker 意外出错属于未知结果：daemon 从不重新提交该请求，停止自有 worker，并把所属 context 的 session、capture 与 replacement 元数据保留为 `requires_restart`。初始化与恢复扫描维持这一隔离，不会把它变成 ready 或 deferred；显式 context 清理仍可用。新 worker、空注册表或重新打开的 capture 都不是回滚或恢复的证据。

## 回放生命周期

同一 daemon context 中同一 capture 已有 live session 时，`rd.capture.open_replay` 是幂等的，返回 `reused_session=true`，不会再开第二个回放。`rd.capture.close_replay` 是规范的资源释放路径。过期 session 清理失败时返回 `stale_session_requires_restart` 与恢复命令，不会静默创建另一个回放。本地回放的 API 支持检查（`local_replay_unsupported`）见 [public-contract.md](public-contract.md)。

`capture_initial` 纹理/缓冲读取与完整回放 GPU 计时在串行回放边界内执行。取消时先排空原生工作，再恢复原事件。context 选择与着色器 replacement 仍归 session 所有。恢复失败会设置 session 的重启要求并拒绝后续操作，消费者不得签发成功证据。capture 初始字节需要记录的来源证明，不能假定任意更早的事件持有原始数据。

## Preview 状态

session context 包含 `preview` 状态。preview 几何必须描述完整 framebuffer，并区分 viewport / scissor 与 preview 窗口适配。`preview.display` 是 framebuffer 尺寸、viewport 矩形、窗口矩形、适配模式与屏幕上限设置的稳定观察面。

不自行管理 preview 的操作在成功后自动同步启用的 preview；失败不会由分发器额外触发同步。拒绝时的保全证明见[公共契约](public-contract.md#rejection-proof)。

原生 preview 窗口只在 Windows 提供；其他主机上 `rd.session.open_preview` 返回 `preview_unsupported_platform`，`rd.core.get_capabilities` 报告 `preview_window.available=false`。`rd.session.open_preview`、`rd.session.close_preview` 与 `preview.display` 保持独立的 CLI 窗口契约与几何 smoke 覆盖；无窗口观察见下一节。

<a id="embedded-replay-observations"></a>
## 内嵌回放观察

`rd.session.get_replay_events` 返回所选 live context 的完整离散 action 索引（`complete: true`），不受浏览 API 的节点上限约束，也不改变当前事件。

`rd.event.get_action_tree` 是有界的交互式浏览器：支持根页或事件子树、过滤、深度/节点预算与表格投影，并显式报告截断。`rd.event.get_action_details` 包含直接子事件 ID；marker 路径来自真实父链。

`rd.session.observe` 在所有主机可用，接受全新的绝对 PNG 路径 `out_path`、可选的 `event_id` 与可选的 `target`（`texture_id` 或实际 `rt_index` 附件槽）。不给事件时观察当前 context 事件，包括被分析、调试或着色器操作改变的事件。打开时使用 `final_output: true`，它不能与事件或目标选择组合。只有最后一个实际 Present action 经 copyDestination 指向唯一 SwapBuffer 时才声明最终图像；否则 `final_output_error` 说明缺少的证据，当前可用的颜色输出明确不标为 final。

daemon 把 apply、颜色选择与 PNG 导出与同一 context 的其他调用串行化。apply 成功但导出失败时，返回已应用的 `event_id`、为 null 的 `image_path`/`image_event_id` 与 `image_error`，从不复用旧 PNG。`revision` 按 live context/session 的观察递增；消费者还须在原生重启之间跟踪自己的绑定代次。

图像错误区分 `no_color_output`（事件没有颜色附件）、`missing_target`（显式目标不存在）与 `export_failure`（获取图像失败）；只有获取失败值得重试同一请求。显式选择 Present 事件时，用与 final-output 打开相同的解析器解析其经过验证的 copyDestination swap buffer；final 标签要求它就是实际的最后一个 Present。

session-context 操作使用 60 秒 worker 预算；CLI daemon 传输再加共享的 5 秒响应余量，截止时间为 65 秒。预算由操作策略选择，调用方不传第二个单请求超时；宿主的外层 CLI 进程截止时间应大于 65 秒。

这条路径不创建桌面 preview 窗口。它与独立 preview 共用同一原生回放 controller，但内嵌消费者不得启用独立窗口的生命周期。

观察结果包含原生 revision、实际的 baseline/intervention/restored 着色器 replacement 状态，以及 PNG 子资源/范围参数。传输阶段只来自远端 CopyCaptureToRemote 回调，经现有 daemon 进度通道报告。观察在同步测量命令返回后才应用事件，不承诺整个多命令实验零扰动。

观察 PNG 是过程结果，不自动成为 Agent 调查 trace。宿主只在实际操作之后、性能测量事务之外记录它们；读取已保存的 trace 不得调用 observe 或修改回放。宿主负责输出文件清理与项目/session 保留。内嵌观察直接导出到宿主拥有的 PNG 路径，不向原生 artifact store 重复发布；独立纹理导出经同一纹理写入器保留 artifact 发布契约。

### 设备呈现

设备端呈现与 PNG 成功无关。配对的原生 RemoteServer `PresentReplay(eventId, textureId)` 校验已应用的回放事件，经现有原生 preview 窗口渲染该纹理，只有在可见前台 surface 上 GPU 呈现成功后才返回新的序号；null 纹理清空 surface。客户端与 Android helper 必须使用匹配的协议，旧 helper 在握手时失败，不做回退。

每个 `remote_display` 含 `status`、`event_id`、`texture_id`、`sequence` 与 `reason`。`presented` 要求正的单调序号与匹配的所选目标；本地观察为 `not_applicable`；绑定缺少能力为 `unsupported`；surface、传输或渲染失败为 `unavailable`，且不带过期的完成序号。无颜色事件返回 `unavailable` 与 `reason=no_color_output`，此时正序号只证明原生 surface 已清空，不证明呈现了纹理。新的原生回放句柄会重置回执跟踪。导出成功或连通性都不能证明设备屏幕已同步，验收还须记录实际屏幕采样。

## Android helper 生命周期

准备、借用与修复策略见 [public-contract.md](public-contract.md) 的 Android 远端一节；本节只描述连接内与跨 daemon 重启的资源归属。

一次连接只记录本次尝试的 `started_activity`、`owned_pids` 与 `created_forward`。断开、打开失败与取消会关闭本连接，只移除经验证的自有 forward；正常清理从不关闭借用的 server。持久化的 bootstrap 元数据不授予对新观察到进程的所有权。被取消的连接 worker 先 join，再发布任何句柄；清理错误随原始失败一并返回。

所属快照与规范化的远端 session 记录保存本连接启动 helper 时捕获的 PID 及所建 forward 的身份。daemon 重启后，恢复流程先核验旧 context、设备、endpoint 与 forward，再移除该映射并分配新的映射；恢复出的句柄保留经核验的来源 context，使 `clear_context` 能释放新 forward。helper PID 仍是记录值时，新连接保留原有的清理所有权；PID 改变则从不认领。forward 所有权缺失、不一致或已改变时阻止重连，不留下无人跟踪的映射。`clear_context` 对延迟的 remote 做同样的身份检查；清理失败时保留 context 以便恢复。正常恢复与清理从不停止借用的 helper；替换不兼容服务只发生在 `rd.remote.connect` 的准备流程中，不属于清理动作。

远端回放使用所属运行时连接完成传输与 OpenCapture。`clear_context` 只关闭属于所请求 context 的 session 与 remote，再重置其快照；清理失败时保留恢复身份并返回失败。

worker 改变后，daemon 只在确认旧进程退出时记录其身份。`requires_restart` 的非 live 远端 session 需再次核实该身份，并确认没有活动 replay、remote lease 或 replacement，才可进入所属 remote 与 ADB 清理。session 原生关闭失败时保留会话和未确认的句柄；daemon 的 context clear 与核心 shutdown 复用同一清理检查。

worker 中的操作阶段通过 request 绑定的 `ProgressEvent` 转发到 daemon `active_operation`，设备准备的检查、安装、启动与验证因此使用同一真实阶段。事件必须匹配当前 request 与 operation/trace，迟到事件不得污染后续请求；进度发布失败不替代操作的最终回执。取消后已提交的安装事实仍保留在所属 context 的操作历史中。

原生远端 server 在用户空闲时等待下一个数据包；接收截止时间从数据包到达后才开始计算，不覆盖 CLI 操作之间的间隔。server 关闭仍可中断。

### Android capture 传输

Android capture 传输以 helper 的应用 UID 通过 ADB `run-as` 读写匹配 helper 私有的 `files/rdc_tool_captures` 目录，并在 OpenCapture 之前校验 SHA256。shell 可读的外部存储不能证明 helper 可读。已验证的现有私有副本直接复用，不取得其所有权；现有外部副本不会被隐式迁移或删除。

新字节先经 ADB sync（`push`）写入独占创建、shell 所有、权限 0700 的临时目录；shell 端 SHA256 校验后，由设备本地管道以应用 UID 和 noclobber 独占打开写入规范私有缓存路径。二进制 capture 数据从不经过主机 shell 的 stdin/stdout，因为换行转换可能损坏数据。本连接必须同时收到与 nonce 绑定的创建回执与写入完成回执，并校验应用侧 SHA256，才把新路径交给原生清理所有权或用于回放。独占创建失败后，并发出现的文件或目录不会被替换、认领、删除或自动复用。

确证复制以失败终结后，清理只移除本连接新建的私有文件、shell 源文件及其空目录；成功的副本交给原生连接清理。sync 未确认、源校验不可读或缺少设备写入完成回执时，保留准确的恢复路径，不声称完成，也不删除可能仍在使用的文件。已有内容不可读或不匹配（包括残留的部分文件）时失败，不会覆盖。非 Android 远端传输使用 RenderDoc RPC。
