## 1. 使用的框架与总体方案

仓库使用 Python 标准库 `logging`，没有引入第三方日志框架。日志通过根 logger (`logging.getLogger()`) 集中控制级别，并通过每个模块级的 `logger = logging.getLogger(__name__)` 实例产出结构化命名空间（如 `rdc_tool.core.engine`、`rdc_tool.daemon.server`、`rdc_tool.server`）。

## 2. 关键文件

- `rdc_tool/cli.py`：CLI 入口，设置根 logger 默认级别为 `WARNING`。
- `rdc_tool/daemon/server.py`：守护进程进程初始化 `basicConfig`，定义终端输出格式。
- `rdc_tool/config.py`：`RdcToolConfig.log_level` 字段，从环境变量 `RDC_TOOL_LOG_LEVEL` 覆盖。
- `rdc_tool/server_runtime.py`：运行时通过 RPC action `set_log_level` 动态调整全局日志级别并写回配置。
- 各业务模块（`core/engine.py`、`core/event_graph.py`、`core/pipeline_service.py`、`core/render_service.py`、`core/perf_service.py`、`core/report_builder.py`、`core/session_manager.py`、`core/verifiers.py`、`core/experiment_runner.py`、`core/patch_engine.py`、`utils/artifact_store.py`、`utils/scheduler.py`、`daemon/worker.py`、`server_runtime.py`）均按模块名创建 logger。

## 3. 架构与约定

### 3.1 日志级别来源（优先级从高到低）

1. **CLI 进程**：`cli.py` 在启动时调用 `logging.getLogger().setLevel(...)`，默认 `WARNING`；实际值取自环境变量 `RDC_TOOL_LOG_LEVEL`（大写映射到 `logging.*` 常量），若非法则回退 `WARNING`。
2. **守护进程进程**：`daemon/server.py` 用 `--log-level` CLI 参数（默认 `INFO`）调用 `logging.basicConfig(level=..., format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")`，这是守护进程唯一的 sink 配置点。
3. **运行时服务（子进程）**：`server_runtime.py` 暴露 `set_log_level` RPC action，将传入 level 大写后直接 `logging.getLogger().setLevel(level)`，并通过 `_apply_runtime_config({"log_level": level})` 同步写回 `RdcToolConfig.log_level`。
4. **配置对象**：`RdcToolConfig.log_level` 默认值为 `"INFO"`，构造时若检测到 `RDC_TOOL_LOG_LEVEL` 环境变量即覆盖该字段；`_serialize_runtime_config()` 会将其作为字符串小写返回给调用方（见 `server_runtime.py:294`）。

### 3.2 日志输出格式

仅守护进程通过 `basicConfig` 显式指定格式：`%(asctime)s [%(name)s] %(levelname)s: %(message)s`。CLI 和运行时代码未再设置 handler/formatter，因此继承守护进程的 root handler（当由守护进程 fork/exec 产生）或走 Python 默认 stderr 输出（当独立 CLI 启动）。

### 3.3 模块级 logger 命名空间

所有业务模块统一使用 `logger = logging.getLogger(__name__)`，形成以包路径为前缀的命名空间（例如 `rdc_tool.core.perf_service`、`rdc_tool.core.report_builder`、`rdc_tool.core.verifiers`、`rdc_tool.daemon.server`、`rdc_tool.server`）。部分模块采用硬编码 logger 名称（如 `rdc_tool.core.perf_service`、`rdc_tool.core.report_builder`、`rdc_tool.core.verifiers`、`rdc_tool.server`），其余使用 `__name__`，属于风格差异但语义等价。

### 3.4 运行时动态调级 API

`server_runtime.py` 暴露两个相关 RPC action：
- `get_config`：返回包含 `log_level` 字段的配置快照（小写）。
- `set_log_level`：接收 `{"level": <string>}`，大写后写入 root logger 并持久化到配置。

此外，操作定义 `operation_definitions.py` 还声明了 `rd.core.set_log_level` 这一对外契约接口，供上层工具链调用。

## 4. 约定与约束

- **环境变量统一入口**：`RDC_TOOL_LOG_LEVEL` 是 CLI 与配置对象的共同输入源，分别用于立即设置 root logger 级别和填充 `RdcToolConfig.log_level`。
- **大小写处理**：所有 level 字符串在进入 `logging` 之前会被 `.upper()` 规范化；序列化返回时用小写。
- **无效 level 容错**：CLI 使用 `getattr(logging, ..., logging.WARNING)` 对非法值做回退；守护进程 `basicConfig` 也使用相同模式回退 `INFO`。
- **单一 sink 原则**：仅 `daemon/server.py` 调用 `logging.basicConfig` 配置 sink；其他模块只负责产出日志，不注册 handler。
- **无结构化字段**：日志消息以纯文本拼接为主，未发现统一的 JSON 结构化字段、trace-id、span-id 等结构化日志约定。
- **默认级别策略**：CLI 默认 `WARNING`（抑制 INFO/DEBUG 噪声），守护进程默认 `INFO`，运行时配置默认 `INFO`。
- **运行时可观测性**：`get_logs` action（在 `server_runtime.py:6297` 附近）提供按时间戳过滤的日志读取能力，配合 `since_ms` 参数拉取历史日志。

## 5. 证据范围说明

以上结论基于对 `rdc_tool/` 下 17 个使用 `logging` 的文件以及 CLI、config、daemon、server_runtime 四个核心文件的抽样验证；未检查的文件可能遵循相同模式，但该断言未被穷举证明。