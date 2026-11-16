# 配置

## 用户配置

用户使用对应主机的自包含发布包（Windows 通过 `install.cmd` / `scripts/rdc_tool_install.ps1` 安装）。发布包自带 Python、RenderDoc 运行库和主机工具，不需要安装 Python、创建虚拟环境或运行包管理器。

安装根目录由 `rdc_tool` 包自身的位置决定，运行库位置由主机布局决定（例如 `binaries/windows/x64`、`binaries/linux/x64`），都不接受环境变量覆盖：配对的原生构建回执始终约束实际加载的文件。

| 变量 | 作用 |
|---|---|
| `RDC_TOOL_ANDROID_ADB_PATH` | 使用指定的 `adb` 可执行文件（绝对路径），替代安装包自带的 adb；路径无效时报错，不回退 |
| `RDC_TOOL_SPIRV_TOOLS_PATH` | 使用指定目录下的 `spirv-as` / `spirv-dis`（绝对路径），替代自带版本；无效时报错，不回退 |
| `ANDROID_ADB_SERVER_ADDRESS`、`ANDROID_ADB_SERVER_PORT`、`ADB_SERVER_SOCKET` | adb 标准变量，指定要连接的 adb server（仅支持 TCP） |
| `RDC_TOOL_LOG_LEVEL` | 运行时日志级别（默认 `WARNING`/`INFO`） |

## 维护者配置

| 变量 | 作用 |
|---|---|
| `RDC_TOOL_INTERMEDIATE_ROOT` | 开发、测试与发布验证的运行目录根（默认 `intermediate/`）；所有运行路径（`runtime`、`artifacts`、`logs`）都从它派生，用于隔离一次任务自己的测试或 smoke |
| `RDC_TOOL_ARTIFACT_DIR` | artifact 输出目录（默认 `<intermediate>/artifacts`） |
| `RDC_TOOL_CONTEXT_ARTIFACT_TOTAL_LIMIT`、`RDC_TOOL_CONTEXT_ARTIFACT_PER_TYPE_LIMIT` | 每个 context 快照保留的 artifact 总数与单类上限 |
| `RDC_TOOL_MAX_CONTEXTS`、`RDC_TOOL_MAX_SESSIONS_PER_CONTEXT`、`RDC_TOOL_MAX_CAPTURE_FILES`、`RDC_TOOL_MAX_CAPTURE_SIZE_BYTES`、`RDC_TOOL_MAX_ESTIMATED_REPLAY_MEMORY_BYTES`、`RDC_TOOL_REPLAY_MEMORY_MULTIPLIER`、`RDC_TOOL_MAX_RECENT_OPERATIONS` | 运行时资源上限（同 `rd.core.set_config` 的 `runtime_limits`） |
| `RDC_TOOL_REMOTE_DEVICE_SERIAL` | Android 远端 smoke 选择的设备序列号 |

`runtime_limits.max_contexts` 只统计**实时占用**：一个 context 的 daemon、worker 或 owner 进程仍存活，或当前进程持有 live replay/preview 时才占用名额。持久化的 `runtime_state_*.json` 只是恢复与列举用的命名空间，空的或已死的记录不占名额；`RDC_TOOL_INTERMEDIATE_ROOT` 隔离的是目录，不替代实时占用计算。

## 内部变量

`RDC_TOOL_CONTEXT_ID`、`RDC_TOOL_DAEMON_PID`、`RDC_TOOL_DAEMON_BIRTH` 由 daemon 在启动 worker 时设置，用于 worker 证明自己与父 daemon 的进程身份，不是配置项。

## preview 运行约束

preview 使用 `screen_cap_ratio` 限制窗口尺寸，同时保持 framebuffer 的几何比例。
