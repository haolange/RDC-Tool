---
kind: configuration_system
name: 基于环境变量与 dataclass 的运行时配置系统
category: configuration_system
scope:
    - '**'
source_files:
    - rdx/config.py
    - rdx/runtime_paths.py
    - rdx/runtime_state.py
    - rdx/timeout_policy.py
    - docs/configuration.md
    - pyproject.toml
    - cli/run_cli.py
---

## 1. 使用的方案

RDX 工具运行时没有引入外部配置框架（如 YAML/JSON/TOML 配置文件），而是采用 **纯 Python dataclass + 环境变量** 的方式管理所有运行时配置。核心入口是 `rdx/config.py`，通过 `RdxConfig.from_env()` 将一组以 `RDX_` 为前缀的环境变量映射到强类型的 dataclass 字段；路径解析由 `rdx/runtime_paths.py` 集中提供；持久化上下文状态由 `rdx/runtime_state.py` 以 JSON 文件形式落盘。

## 2. 关键文件

- `rdx/config.py`：定义全部配置结构体（`BackendConfig`、`ReplayConfig`、`WorkerConfig`、`ArtifactConfig`、`DatabaseConfig`、`BisectConfig`、`ConfidenceWeightsConfig`、`SnapshotRetentionConfig`、`RuntimeLimitsConfig`、`AdaptiveBisectConfig`、`PatchConfig`、`ReportConfig`）以及聚合根 `RdxConfig`，并提供 `from_env()` 从环境变量加载。
- `rdx/runtime_paths.py`：统一解析 `tools_root`、`binaries_root`、`bundled_python_executable`、`intermediate_root`、`runtime_root`、`cli_runtime_dir`、`worker_state_dir`、`artifacts_dir`、`pytest_dir`、`logs_dir` 等路径，并负责创建目录。
- `rdx/runtime_state.py`：维护每个 daemon context 的持久化状态（`runtime_state.json` / `runtime_state_<ctx>.json`）、日志（`runtime_logs.jsonl`）、并发锁（`.lock` 文件 + `msvcrt.locking`）和默认 limits。
- `rdx/timeout_policy.py`：集中声明各操作超时策略常量，并通过 `operation_timeout_s` / `transport_timeout_s` / `daemon_exec_timeout_s` 计算超时。
- `docs/configuration.md`：面向用户与维护者的配置说明文档，明确 `RDX_TOOLS_ROOT`、`RDX_INTERMEDIATE_ROOT`、`RDX_PYTHON` 等环境变量的用途。
- `pyproject.toml`：通过 `[project.scripts] rdx = "rdx.cli:main"` 暴露 CLI 入口，同时声明依赖（aiofiles、jinja2、numpy、Pillow、pydantic）。

## 3. 架构与约定

### 3.1 配置加载顺序

1. **dataclass 默认值**：每个字段都有合理的默认值（例如 `backend.type="local"`、`replay.headless=True`、`runtime_limits.max_contexts=8`）。
2. **环境变量覆盖**：`RdxConfig.from_env()` 在构造后逐个检查 `os.environ.get("RDX_*")`，若存在则覆盖对应字段。新增配置项时必须在 `from_env()` 中显式注册映射。
3. **路径派生**：`runtime_paths.py` 中的路径函数优先读取 `RDX_TOOLS_ROOT`、`RDX_INTERMEDIATE_ROOT`，否则回退到包根下的相对路径；`ensure_runtime_dirs()` 会在首次访问时自动创建 `intermediate/runtime`、`intermediate/artifacts`、`intermediate/logs` 等目录。
4. **持久化状态合并**：`runtime_state.py` 的 `normalize_context_state()` 会先构建 `default_context_state()`，再合并磁盘上的旧状态，并对缺失/非法字段做归一化与裁剪（如 `recent_operations` 按 `max_recent_operations` 截断）。

### 3.2 环境变量命名规范

所有可配置项统一使用 `RDX_` 前缀，并按领域分组：
- 路径类：`RDX_TOOLS_ROOT`、`RDX_INTERMEDIATE_ROOT`、`RDX_ARTIFACT_STORE`、`RDX_DATA_DIR`、`RDX_REPORT_DIR`、`RDX_RENDERDOC_PATH`、`RDX_SPIRV_TOOLS_PATH`、`RDX_BISECT_HISTORY_STORE`
- 行为开关：`RDX_HEADLESS`、`RDX_LOG_LEVEL`、`RDX_GPU_VENDOR`
- 限制类：`RDX_MAX_CONTEXTS`、`RDX_MAX_SESSIONS_PER_CONTEXT`、`RDX_MAX_CAPTURE_FILES`、`RDX_MAX_CAPTURE_SIZE_BYTES`、`RDX_MAX_ESTIMATED_REPLAY_MEMORY_BYTES`、`RDX_REPLAY_MEMORY_MULTIPLIER`、`RDX_MAX_RECENT_OPERATIONS`
- Bisect/置信度：`RDX_BISECT_CONFIDENCE_SHARPNESS`、`RDX_BISECT_CONFIDENCE_CONSISTENCY`、`RDX_BISECT_CONFIDENCE_RANGE_FACTOR`、`RDX_BISECT_PROFILE`、`RDX_BISECT_ADAPTIVE_MODE`
- 上下文隔离：`RDX_CONTEXT_ID`（由 `cli/run_cli.py` 设置并传递给 daemon）

### 3.3 运行时目录布局

```
<RDX_TOOLS_ROOT>/
├── binaries/windows/x64/          # renderdoc.dll、renderdoc.pyd、Python 运行时
├── intermediate/
│   ├── runtime/                   # 当前运行期数据
│   │   ├── rdx_cli/               # runtime_state.json, runtime_logs.jsonl
│   │   └── worker-state/
│   ├── artifacts/                 # 产物存储（受 ArtifactConfig 控制）
│   ├── pytest/
│   └── logs/                      # 报告输出（ReportConfig.output_path）
```

可通过 `RDX_INTERMEDIATE_ROOT` 将整个 `intermediate/` 树迁移到任意位置，实现任务级隔离。

### 3.4 超时策略

`timeout_policy.py` 将所有操作的超时集中在一个模块中，按操作名前缀分级：`rd.session.*` 使用短超时，`rd.event.*`、`rd.pipeline.*` 等重型操作使用较长超时，`rd.macro.*`、`rd.vfs.*` 使用最长超时。CLI 调用 daemon 时通过 `daemon_exec_timeout_s(operation, args)` 计算最终超时，并在失败时返回结构化错误载荷。

## 4. 约定与约束

- **无配置文件**：仓库中没有 `.yaml`、`.toml`、`.env`、`.ini` 等应用级配置文件；所有可调参数均通过环境变量注入。
- **dataclass 即 schema**：`config.py` 中的 dataclass 就是配置的权威 schema，新增字段必须同步更新 `from_env()` 中的解析逻辑，否则该字段无法被外部覆盖。
- **路径解析单一入口**：所有路径必须通过 `runtime_paths.py` 中的函数获取，禁止硬编码字符串路径，以保证 `RDX_TOOLS_ROOT` / `RDX_INTERMEDIATE_ROOT` 覆盖生效。
- **上下文隔离**：每个 daemon context 拥有独立的 `runtime_state.json` / `runtime_logs.jsonl`，文件名由 `normalize_context_id(context)` 决定；`default` 上下文使用无后缀的文件名。
- **并发安全**：状态文件读写通过 `.lock` 文件 + `msvcrt.locking` 保证跨进程互斥；内存中使用 `_STATE_MUTEXES` 字典为同一 context 提供线程级锁。
- **向后兼容**：`runtime_state.py` 对历史状态的加载采用“默认值 + 增量合并”模式，未知字段会被忽略，确保旧版本生成的状态文件仍可被新版本读取。
- **文档即契约**：`docs/configuration.md` 明确区分用户配置（`RDX_TOOLS_ROOT`）与维护者调试配置（`RDX_PYTHON`、`RDX_INTERMEDIATE_ROOT`），GA 发布包不应要求用户设置这些变量。
- **测试隔离**：pytest 通过 `RDX_INTERMEDIATE_ROOT` 指向独立目录，避免污染开发环境的 `intermediate/` 目录。

## 5. 适用性判断

本仓库确实实现了完整的配置系统：通过 dataclass 定义类型安全的配置模型，通过 `RDX_*` 环境变量完成运行时注入，通过 `runtime_paths.py` 统一管理路径，通过 `runtime_state.py` 持久化上下文状态。因此该类别适用。

confidence: high