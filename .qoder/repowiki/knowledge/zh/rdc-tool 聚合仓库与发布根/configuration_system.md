## 1. 采用的方案

仓库没有使用任何外部配置库（如 Pydantic、ConfigParser、TOML/YAML），而是采用**纯 Python dataclass + 环境变量**的方式，通过 `RdcToolConfig.from_env()` 将环境变量映射为结构化配置对象。路径解析由 `runtime_paths.py` 单独负责，运行时目录在启动时自动创建。

## 2. 关键文件与包

- `rdc_tool/config.py` — 全部配置模型的声明中心。定义了 `BackendConfig`、`ReplayConfig`、`WorkerConfig`、`ArtifactConfig`、`DatabaseConfig`、`BisectConfig`、`ConfidenceWeightsConfig`、`SnapshotRetentionConfig`、`RuntimeLimitsConfig`、`AdaptiveBisectConfig`、`PatchConfig`、`ReportConfig` 以及顶层聚合类 `RdcToolConfig`。
- `rdc_tool/runtime_paths.py` — 工具根目录、运行时目录、artifacts/logs/worker-state 等路径的解析与创建。
- `rdc_tool/environment.py` — 已废弃的 `RDX_*` 前缀环境变量校验，启动即报错并给出替换建议。
- `docs/configuration.md` — 用户与维护者配置文档，描述 `RDC_TOOL_ROOT`、`RDC_TOOL_INTERMEDIATE_ROOT`、`RDC_TOOL_PYTHON` 等语义。
- `rdc_tool/server_runtime.py` — 唯一集中调用 `RdcToolConfig.from_env()` 的位置，并将结果缓存到模块级 `_config`，供各 handler 读取。

## 3. 架构与约定

### 3.1 配置模型
所有配置项都是 `@dataclass`，默认值集中在类型定义中，作为“零配置”时的行为基线。例如 `BackendConfig.type = "local"`、`ReplayConfig.headless = True`、`ReportConfig.generate_html/markdown/json = True`。

### 3.2 加载顺序
1. **默认值**：构造 `RdcToolConfig()` 获得默认配置。
2. **环境变量覆盖**：`from_env()` 逐个检查 `os.environ` 中的 `RDC_TOOL_*` 变量，覆盖对应字段；布尔值接受 `"1"` / `"true"` / `"yes"`（大小写不敏感）。
3. **运行时路径**：`runtime_root()` → `intermediate/runtime`，`artifacts_dir()` → `intermediate/artifacts`，`logs_dir()` → `intermediate/logs`；可通过 `RDC_TOOL_INTERMEDIATE_ROOT` 隔离整个 intermediate 树。
4. **目录初始化**：`ensure_runtime_dirs()` 在首次访问时 `mkdir(parents=True, exist_ok=True)` 确保这些目录存在。

### 3.3 工具根目录解析
`tools_root()` 优先级：
1. `RDC_TOOL_ROOT`（若存在且是有效目录）。
2. 当前 `rdc_tool/` 包所在父目录。
两者不一致时打印一次警告（`_WARNED_ROOT_OVERRIDE` 全局开关避免重复输出）。

### 3.4 已弃用配置保护
`validate_environment()` 扫描所有以 `RDX_` 开头的环境变量，抛出 `ValueError` 并列出每个键应替换成的 `RDC_TOOL_*` 形式，防止旧配置被静默忽略。

### 3.5 配置注入点
`server_runtime.py` 在进程启动阶段执行 `_config = RdcToolConfig.from_env()`，后续通过模块级 `_config` 或 `get_config()` 访问；其他模块（如 `core/experiment_runner.py`）可显式传入 `RdcToolConfig` 实例以便测试覆盖。

## 4. 约定与约束

- **命名空间**：所有用户可见配置均使用 `RDC_TOOL_` 前缀的环境变量（如 `RDC_TOOL_RENDERDOC_PATH`、`RDC_TOOL_ARTIFACT_STORE`、`RDC_TOOL_GPU_VENDOR`、`RDC_TOOL_HEADLESS`、`RDC_TOOL_BISECT_CONFIDENCE_SHARPNESS`、`RDC_TOOL_MAX_CONTEXTS`、`RDC_TOOL_LOG_LEVEL` 等），由 `config.py` 的 `from_env()` 显式列举，新增配置必须在此注册，否则不会被加载。
- **路径隔离**：`RDC_TOOL_INTERMEDIATE_ROOT` 将整个 intermediate 树（runtime/artifacts/logs/pytest）重定向到任意目录，便于 CI/任务级隔离；`RDC_TOOL_ROOT` 仅重定位工具自身根目录。
- **向后兼容断言**：`environment.validate_environment` 对 `RDX_*` 变量进行主动拒绝，不是静默降级——这是唯一一处真正“强制”的规则。
- **无持久化配置文件**：仓库未实现 JSON/YAML/TOML 配置文件加载，所有外部输入走环境变量；`database.path` 与 `artifact.store_path` 默认指向 `runtime_root()` 和 `artifacts_dir()` 下的 SQLite 与文件存储。
- **调试/维护者专用**：`RDC_TOOL_PYTHON` 在 `docs/configuration.md` 中标明为 maintainer/debug override，不属于 GA 发布包的必需配置。
- **占位型配置**：`renderdoc_module_path`、`log_level` 等字段虽存在于 dataclass 中，但 `from_env()` 尚未为其设置对应的环境变量分支，属于预留扩展点。