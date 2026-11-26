# RDC-Tool 架构

本文描述 `rdc-tool` 的分层、依赖方向和跨进程模型，是实现与评审的结构基准；行为契约见 [docs/public-contract.md](docs/public-contract.md)，会话生命周期见 [docs/session-model.md](docs/session-model.md)，发布与原生运行库身份见 [docs/release-baseline.md](docs/release-baseline.md)。

## 进程模型

```
rdc-tool（CLI 进程，短命）
  └─ daemon（每个 --daemon-context 一个，长驻；持有 owner lock 与 state 文件）
       └─ runtime worker（加载 RenderDoc 原生库与 Python binding，执行 rd.* 操作）
```

- CLI 只做参数解析、daemon 发现与请求转发，不加载 RenderDoc。
- daemon 拥有一个 context：它的 state 文件、IPC endpoint、owner lock 与唯一的 worker。
- worker 是唯一触碰原生库的进程；它随 daemon 退出而退出。
- 跨进程的存活与归属一律以进程身份 `(pid, birth)` 判断，见下文平台层。

一次操作请求的生命周期：

- CLI 把 `exec`（携带 `request_id`、`no_progress_ms` 与 `stream`）发给 daemon，并保持连接等待回复，不设总截止时间；daemon 在该连接上每 2 秒发送心跳，并按需转发 progress 与 native_call 帧。daemon 的 `(pid, birth)` 退出或心跳中断时 CLI 返回 `daemon_lost` / `daemon_unresponsive`。
- daemon 以一把执行锁串行化请求；排队的请求以 1 秒切片等待，期间可被取消。`cancel` 与只读的 `context_status` 不占用执行锁。
- worker 每收到一个帧，daemon 就把该请求的截止时间前移一个无进展预算；到期时 daemon 等待 worker 的 faulthandler 栈转储，终止 worker 进程树并确认退出，回放被隔离为 `requires_restart`。worker 的 stdin 由独立线程读取，取消控制行不排在它所取消的请求之后。
- 预算与各控制期限只在 `rdc_tool/timeout_policy.py` 声明；daemon 与 worker 的 stderr 写入各自有界轮转的 `daemon.log` / `worker.log`。

## 分层与依赖方向

依赖只能自上而下：

| 层 | 模块 | 职责 |
|---|---|---|
| 入口 | `bin/rdc-tool`、`bin/rdc-tool.cmd`、`cli/run_cli.py`、`rdc_tool/cli.py` | 选择同安装的 Python，解析命令，输出 canonical JSON |
| daemon | `rdc_tool/daemon/` | context 所有权、state 文件（`daemon/state.py` 唯一所有者）、IPC 服务、worker 生命周期 |
| 运行时 | `rdc_tool/runtime/`、`rdc_tool/core/` | worker 内执行 `rd.*` 操作：路由、操作实现与回放服务（结构见下文） |
| 契约 | `rdc_tool/operation_definitions.py`、`rdc_tool/runtime_catalog.py` | 操作定义唯一真源；catalog 与参考文档由它生成 |
| 执行边界 | `rdc_tool/native_calls.py`、`rdc_tool/progress.py`、`rdc_tool/timeout_policy.py` | 原生调用唯一入口、每请求的进度与取消作用域、执行预算与控制期限 |
| 平台 | `rdc_tool/platform/` | 所有操作系统差异 |

## 运行时结构

`rdc_tool/runtime/` 只在 worker 进程内运行（入口 `worker_main.py`，daemon 以模块名启动它），自上而下分四层：

| 层 | 模块 | 职责 |
|---|---|---|
| 执行 | `dispatch.py`、`routing.py` | 一次操作的完整执行：context 就绪、preview 同步、路由、canonical 结果、操作日志与进程身份；路由按命名空间找到操作模块，并做参数校验、前置条件与 replay 健康作用域 |
| 操作 | `operations/<ns>.py` | 每个 `rd.<ns>` 一个模块，暴露 `dispatch(action, args)`，处理的动作集合与 catalog 完全一致 |
| 服务 | replay 服务组（`replay_access`、`session_recovery`、`shader_patches`、`truth_matrix`、`visual_target`）、`preview_sync`、`remote_target`、`remote_session`、`texture_export`、`pixel_trace`、`shader_values`、`shader_debug`、`vfs_tree`、`discovery`、`observation`、`runtime_lifecycle` | 回放访问与恢复、可视目标与真值元数据、远端连接、导出、像素历史、着色器值、VFS 与发现 |
| 记录与基础 | `context_records`、`remote_records`、`oplog`、`settings`；`live_state`、`envelope`、`coerce`、`renderdoc_api`、`action_index`、`texture_naming`、`artifact_payloads` | context 状态与快照、操作日志、配置；进程内对象与每次调用的上下文、结果信封、参数转换、RenderDoc 绑定访问 |

规则：

- 模块之间以 `module.name` 引用，每个函数只存在于一个命名空间；测试替换一次即对所有调用方生效。
- 可变的进程内状态只在 `live_state`；可被替换的外部协作者（如 `remote_bootstrap`、`timeout_policy`）同样以模块引用。
- 阻塞的原生工作只经 `rdc_tool/native_calls.py` 进入 replay executor（`renderdoc_api._offload` 只在其上记录拒绝作用域的效果）：调用方的 context 变量随调用进入执行线程，名称变化或至多每 0.5 秒发送一个 native_call enter 帧、超过 1 秒的调用发送 exit 帧，取消先等待原生调用返回再生效。它位于 `runtime/` 之外，`core/` 的服务同样使用它；`tests/test_native_calls.py` 保证没有其他执行器入口。
- 每请求的上下文（进度 reporter、`RequestScope` 的 request id、trace id、预算与取消事件）在 `rdc_tool/progress.py` 中，`core/` 与 `runtime/` 都可读取；在单个原生调用内循环的代码（调试器步进、ADB 传输、远端 bootstrap）轮询其取消事件。
- 唯一允许的循环是 replay 服务组之间的互相恢复与探测；服务层不导入操作层与执行层（VFS 读取重新进入完整执行流程时在函数内显式导入 `dispatch`）。
- `rdc_tool/runtime` 之外的代码不导入它。`tests/test_runtime_layering.py` 守住以上规则与路由覆盖。

### 操作结果

每个操作返回 `envelope.Success` 或 `envelope.Failure`，两者在构造时就把值转成 JSON 安全的数据（`envelope.success(**data, meta=, projections=)`、`envelope.failure(message, code=, category=, details=)`，`capability_failure` 是 `category=capability` 的便捷形式）。`dispatch` 只做一次类型分派，生成 canonical envelope（`schema_version`、`ok`、`data`、`artifacts`、`error`、`meta`、`projections`）：

- `Success.data` 原样成为 `data`；`artifacts` 由 data 中的路径字段经 artifact publisher 发布；`meta` 不能覆盖 envelope 自己的 `trace_id`、`transport`、`duration_ms`。
- `Failure` 成为 `error`，`code` 必填，不存在默认错误码之外的猜测。
- 其他任何返回值都是 `internal_error`，不会被当作成功；envelope 字段名（`ok`、`data`、`error` 等）不能作为 data 字段。
- 操作之间组合时直接读取对方的 `Success.data` 或原样返回对方的 `Failure`，不解析字符串。

## 平台层

`rdc_tool/platform/` 是业务代码与操作系统之间唯一的接缝：每个契约只有一套共享逻辑，操作系统原语分别实现在 `_windows.py` 与 `_posix.py`（Win32 preview 宿主在 `_windows_preview.py`）。`tests/test_platform_boundary.py` 保证平台包之外不出现 `os.name`、`sys.platform`、`msvcrt`、`fcntl`、`ctypes`、`creationflags` 等主机判断。

| 契约 | 模块 | 语义 |
|---|---|---|
| 主机 | `host.py` | `host_target()`（如 `windows-x64`、`linux-x64`）；唯一读取操作系统信息的位置 |
| 锁 | `locks.py` | `path_lock`：进程内 mutex 与文件锁共用一个单调截止时间，文件锁只做非阻塞重试；`HeldLock`：进程生命周期内持有 |
| 进程 | `process.py` | `ProcessIdentity(pid, birth)` 与 `probe()`：PID 复用或僵尸为 `EXITED`，不可读为 `UNKNOWN`（既不证明退出也不授权终止）；`kill_tree` 先确认身份：领导独立进程组的 daemon 整组结束，同组内的 worker 先暂停自身与仍在同一 session 的后代、再从叶到根逐个复核身份后结束（Windows 为 `taskkill /T`）；`SpawnProfile` 决定 daemon、worker、工具的启动方式；`start_tool` 启动需要轮询的主机工具 |
| IPC | `ipc.py` | 本机 endpoint（Windows named pipe；POSIX 私有 0700 目录内的 Unix socket），每个连接先完成 HMAC 认证再解码请求 |
| 原生加载 | `native.py` | 让确切的 RenderDoc 原生库可加载，并观察进程实际映射的文件 |
| preview | `preview.py` | 原生 preview 窗口是主机能力；无实现的主机返回结构化 `preview_unsupported_platform` |

## 契约真源

`rdc_tool/operation_definitions.py` 是操作名称、参数、结果、前置条件与影响声明的唯一真源；`spec/tool_catalog.json` 与 `docs/tool-reference.md` 是生成物，生成与校验方式见 [docs/doc-governance.md](docs/doc-governance.md)。

## 主机布局与原生身份

`rdc_tool/runtime_paths.py` 的 `HOST_LAYOUTS` 为每个支持的主机（`windows-x64`、`linux-x64`）声明运行目录、原生库、Python 绑定、捆绑 Python、launcher 与主机工具；安装根目录就是 `rdc_tool` 包所在位置，运行路径一律由布局派生，不接受环境变量覆盖。未知主机以 `unsupported_host` 拒绝。

`binaries/native_build.json` 是全目标共享的原生构建回执，`rdc_tool/runtime_identity.py` 按“存在即严格、缺席仅报告”校验它，并独立观察进程实际加载的原生库与绑定。回执结构、目标集合与资格规则见 [docs/release-baseline.md](docs/release-baseline.md)。
