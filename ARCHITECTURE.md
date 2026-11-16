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

## 分层与依赖方向

依赖只能自上而下：

| 层 | 模块 | 职责 |
|---|---|---|
| 入口 | `bin/rdc-tool`、`bin/rdc-tool.cmd`、`cli/run_cli.py`、`rdc_tool/cli.py` | 选择同安装的 Python，解析命令，输出 canonical JSON |
| daemon | `rdc_tool/daemon/` | context 所有权、state 文件（`daemon/state.py` 唯一所有者）、IPC 服务、worker 生命周期 |
| 运行时 | `rdc_tool/server_runtime.py`、`rdc_tool/core/` | `rd.*` 操作实现与回放服务 |
| 契约 | `rdc_tool/operation_definitions.py`、`rdc_tool/runtime_catalog.py` | 操作定义唯一真源；catalog 与参考文档由它生成 |
| 平台 | `rdc_tool/platform/` | 所有操作系统差异 |

## 平台层

`rdc_tool/platform/` 是业务代码与操作系统之间唯一的接缝：每个契约只有一套共享逻辑，操作系统原语分别实现在 `_windows.py` 与 `_posix.py`（Win32 preview 宿主在 `_windows_preview.py`）。`tests/test_platform_boundary.py` 保证平台包之外不出现 `os.name`、`sys.platform`、`msvcrt`、`fcntl`、`ctypes`、`creationflags` 等主机判断。

| 契约 | 模块 | 语义 |
|---|---|---|
| 主机 | `host.py` | `host_target()`（如 `windows-x64`、`linux-x64`）；唯一读取操作系统信息的位置 |
| 锁 | `locks.py` | `path_lock`：进程内 mutex 与文件锁共用一个单调截止时间，文件锁只做非阻塞重试；`HeldLock`：进程生命周期内持有 |
| 进程 | `process.py` | `ProcessIdentity(pid, birth)` 与 `probe()`：PID 复用或僵尸为 `EXITED`，不可读为 `UNKNOWN`（既不证明退出也不授权终止）；`kill_tree` 先确认身份；`SpawnProfile` 决定 daemon、worker、工具的启动方式 |
| IPC | `ipc.py` | 本机 endpoint（Windows named pipe；POSIX 私有 0700 目录内的 Unix socket），每个连接先完成 HMAC 认证再解码请求 |
| 原生加载 | `native.py` | 让确切的 RenderDoc 原生库可加载，并观察进程实际映射的文件 |
| preview | `preview.py` | 原生 preview 窗口是主机能力；无实现的主机返回结构化 `preview_unsupported_platform` |

## 契约真源

`rdc_tool/operation_definitions.py` 是操作名称、参数、结果、前置条件与影响声明的唯一真源；`spec/tool_catalog.json` 与 `docs/tool-reference.md` 是生成物，生成与校验方式见 [docs/doc-governance.md](docs/doc-governance.md)。
