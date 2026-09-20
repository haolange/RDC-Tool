---
kind: logging_system
name: 基于 Python logging + JSON 结构化输出的日志系统
category: logging_system
scope:
    - '**'
source_files:
    - rdc_tool/daemon/server.py
    - rdc_tool/runtime_paths.py
    - rdc_tool/io_utils.py
    - rdc_tool/cli.py
---

## 1. 使用的系统与框架

仓库采用 **Python 标准库 `logging`** 作为唯一日志框架，未引入 loguru、structlog、sentry 等第三方方案。CLI 进程本身不直接输出日志，而是通过 JSON 协议与守护进程通信；守护进程（`rdc_tool/daemon/server.py`）在启动时调用 `logging.basicConfig(...)` 配置根 logger，并暴露 `--log-level` 参数控制级别。

## 2. 关键文件

- `rdc_tool/daemon/server.py`：定义模块级 logger `logger = logging.getLogger("rdc_tool.daemon")`，并在 `main()` 中通过 `logging.basicConfig(level=..., format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")` 初始化控制台输出。
- `rdc_tool/runtime_paths.py`：提供 `logs_dir()` 返回 `intermediate/logs`，以及 `ensure_runtime_dirs()` 确保该目录存在；同时在该文件中对 `RDC_TOOL_ROOT` 覆盖场景使用 `print(..., file=sys.stderr)` 输出单条警告（仅一次）。
- `rdc_tool/io_utils.py`：提供 `safe_json_text`、`safe_stream_write`、`atomic_append_jsonl` 等工具，用于将结构化事件以 JSONL 形式追加写入 `runtime_logs_*.jsonl`（位于 `intermediate/runtime/rdc_cli/`），这是运行时 worker 产出的结构化日志。
- `rdc_tool/cli.py`：导入 `logging` 但实际只通过 `_print_json` / `_write_stdout` 输出 JSON 结果，不产生传统日志行。
- `binaries/windows/x64/python/Lib/logging/...`：为打包进分发的 CPython 标准库，非项目源码。

## 3. 架构与约定

- **双通道输出**：
  - 诊断/运维日志：由 daemon 进程通过 `logging` 输出到 stderr，格式固定为 `%(asctime)s [%(name)s] %(levelname)s: %(message)s`，可通过 `--log-level` 调整（INFO/DEBUG/WARNING/ERROR）。所有 daemon 内部日志均使用命名 logger `rdc_tool.daemon`。
  - 运行时结构化日志：worker 通过 `io_utils.atomic_append_jsonl` 向 `intermediate/runtime/rdc_cli/runtime_logs_<session>.jsonl` 追加 JSON 行，每行一个事件对象，便于外部采集与分析。
- **无全局日志级别开关**：CLI 入口没有解析 `--log-level` 或环境变量来统一设置日志级别；只有 daemon 支持该参数。这意味着 CLI 进程本身不产生结构化日志。
- **错误路径统一走 JSON 协议**：CLI 和 handler 的错误通过 `canonical_error` 构造 `{ok: false, error: {code, category, message, details}}` 的 JSON 结构返回给调用方，而不是依赖日志级别过滤。
- **日志位置集中化**：所有运行时产物（状态、快照、JSONL 日志、artifacts）都落在 `intermediate/` 下，由 `runtime_paths` 统一管理，避免散落。

## 4. 约定与约束

- 守护进程必须通过 `--log-level` 启动才能启用 `logging` 输出；默认级别为 `INFO`。
- 所有 daemon 内部日志必须使用模块级 `logger = logging.getLogger("rdc_tool.daemon")`，不得直接使用 `print` 输出调试信息（除 `runtime_paths.py` 中对 `RDC_TOOL_ROOT` 覆盖的一次性 stderr 警告）。
- 运行时事件日志必须以 JSON 行（JSONL）格式追加写入，字段需经 `safe_json_text` 处理以保证 UTF-8 可序列化。
- 日志目录 `intermediate/logs` 由 `ensure_runtime_dirs()` 保证创建，消费方不应自行决定日志落盘路径。
- 不存在按模块划分的独立 logger 树；整个 daemon 共用单一 root handler，因此无法按组件粒度过滤日志级别。
- 测试与脚本中未发现对 `logging` 的配置或断言，说明日志行为主要通过集成测试验证而非单元测试。