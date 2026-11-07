## 1. 使用的框架与工具

仓库没有引入第三方日志库，全部使用 Python 标准库 `logging`。所有日志输出通过 `logging.getLogger()` 获取根 logger，并通过 `logging.basicConfig` 或 `logger.setLevel` 配置级别与格式。

## 2. 关键文件

- `rdc_tool/config.py`：`RdcToolConfig.log_level` 字段（默认 `"INFO"`），`from_env` 中从 `RDC_TOOL_LOG_LEVEL` 环境变量读取。
- `rdc_tool/cli.py`：CLI 入口 `main()` 在启动时设置根 logger 级别；默认 `WARNING`，由 `RDC_TOOL_LOG_LEVEL` 覆盖。
- `rdc_tool/daemon/server.py`：Daemon 进程通过 `--log-level` 参数 + `logging.basicConfig(..., format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")` 初始化。
- `rdc_tool/server_runtime.py`：运行时暴露 `rd.core.set_log_level` 动作，调用 `logging.getLogger().setLevel(level)` 并同步持久化到 `_config.log_level`。
- 业务模块（如 `core/session_manager.py`、`core/engine.py`、`handlers/*.py`、`utils/scheduler.py` 等）直接 import `logging` 并使用 `getLogger(__name__)`。

## 3. 架构与约定

### 3.1 日志级别来源优先级

| 来源 | 默认值 | 生效位置 |
|---|---:|---|
| CLI (`main`) | `WARNING` | `cli.py:1791`，`logging.getLogger().setLevel(...)` |
| Daemon 命令行 `--log-level` | `INFO` | `daemon/server.py:718`，`basicConfig(level=...)` |
| 环境变量 `RDC_TOOL_LOG_LEVEL` | — | `config.py:145` 写入 `cfg.log_level`；`server_runtime.py:6293` 运行时动态设置 |

CLI 和 Daemon 各自维护自己的 root logger 实例，因此 `RDC_TOOL_LOG_LEVEL` 对两者的影响路径不同：CLI 在 `main()` 中直接解析环境变量后设置；Daemon 通过 `--log-level` 参数传入，环境变量经 `RdcToolConfig.from_env` 作为运行期配置被 `server_runtime` 消费。

### 3.2 运行时动态调整

`server_runtime.py` 中的 `set_log_level` 动作是运行时唯一能改变全局日志级别的通道：它先调用 `logging.getLogger().setLevel(level)`，再调用 `_apply_runtime_config({"log_level": level})` 将新级别写回持久化的 `_runtime.config`，以便后续重启或子进程继承。

### 3.3 日志格式

仅 Daemon 显式设置了 formatter：
```
%(asctime)s [%(name)s] %(levelname)s: %(message)s
```
CLI 未设置 formatter，沿用 stdlib 默认格式（无时间戳、无 logger name）。其他模块只设置 level，不自定义 formatter。

### 3.4 结构化字段

仓库未实现结构化日志（JSON、key=value 等）。所有日志均为纯文本行，包含 logger name、level 和 message 三个维度。

## 4. 约定与约束

- **所有日志通过 stdlib `logging`**：代码搜索未发现 `print` / `sys.stderr` 替代方案用于业务日志。
- **级别字符串大小写不敏感**：CLI、Daemon 和 server_runtime 均使用 `.upper()` 后再查 `logging` 常量或传给 `setLevel`。
- **CLI 默认 WARNING**：比 Daemon 默认的 INFO 更保守，避免生产环境过度输出。
- **环境变量名固定为 `RDC_TOOL_LOG_LEVEL`**：由 `config.py:145` 硬编码读取，并由 spec/tool_catalog.json 与文档列为受支持的配置项。
- **运行时修改会持久化**：`set_log_level` 同时更新内存 `_config.log_level` 与磁盘 `_runtime.config`，保证子进程/重启后一致。
- **无统一 handler 抽象**：每个进程入口自行 `basicConfig` 或 `setLevel`，没有集中注册的 sink 策略。