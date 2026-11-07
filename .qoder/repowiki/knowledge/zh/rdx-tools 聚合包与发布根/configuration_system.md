## 1. 采用的方案

仓库没有使用 YAML/TOML/JSON 等外部配置文件，也没有引入第三方配置库。运行时配置完全通过 Python `dataclass` 定义结构、默认值与类型约束，并通过 `os.environ` 读取 `RDC_TOOL_*` 前缀的环境变量进行覆盖。路径解析由 `rdc_tool/runtime_paths.py` 提供（`artifacts_dir` / `logs_dir` / `runtime_root`），因此“根目录”和“中间产物目录”也是通过环境变量派生出来的。

## 2. 核心文件

- `rdc_tool/config.py`：唯一集中声明所有配置数据结构的模块。
- `docs/configuration.md`：对外文档，说明用户与维护者两套环境变量入口以及 `preview` 行为约束。
- `rdc_tool/runtime_paths.py`：解析 `RDC_TOOL_ROOT` / `RDC_TOOL_INTERMEDIATE_ROOT`，并强制回写 `RDC_TOOL_ROOT`。
- `rdc_tool/server_runtime.py`：在进程启动处调用 `RdcToolConfig.from_env()` 构造全局 `_config`。
- `rdc_tool/host_tools.py`：额外用 `RDC_TOOL_ANDROID_ADB_PATH` / `RDC_TOOL_SPIRV_TOOLS_PATH` 覆盖宿主工具路径。
- `rdc_tool/core/artifact_publisher.py`：用 `RDC_TOOL_ARTIFACT_MODE` / `RDC_TOOL_S3_*` 等环境变量驱动远端上传行为。
- `rdc_tool/daemon/worker.py`、`rdc_tool/runtime_bootstrap.py`、`rdc_tool/runtime_worker.py`：子进程间通过注入 `RDC_TOOL_CONTEXT_ID` / `RDC_TOOL_DAEMON_PID` / `RDC_TOOL_RUNTIME_DLL_DIR` / `RDC_TOOL_RENDERDOC_PATH` / `RDC_TOOL_WORKER_SOURCE_MANIFEST` 传递运行期上下文。

## 3. 架构与约定

### 3.1 配置模型

`RdcToolConfig` 是顶层 dataclass，组合了以下子段（全部带默认值）：

| 子段 | 作用 |
|---|---|
| `BackendConfig` | 后端类型、GPU vendor/index、远程主机/端口/协议/认证 |
| `ReplayConfig` | headless、优化等级、输出分辨率、纹理回读上限、replay 超时 |
| `WorkerConfig` | 每 GPU worker 数、远程控制器数、队列大小、worker 超时 |
| `ArtifactConfig` | 存储路径、最大容量、哈希算法、压缩开关 |
| `DatabaseConfig` | metadata.db / fingerprints.db 路径（默认位于 `runtime_root()`） |
| `BisectConfig` | bisect 策略、迭代次数、置信度阈值、early stop、confidence profile |
| `ConfidenceWeightsConfig` | sharpness / consistency / range_factor 权重 |
| `SnapshotRetentionConfig` | 快照总数与 per-type 限制 |
| `RuntimeLimitsConfig` | context/session/capture/memory/recent operations 等硬限制 |
| `AdaptiveBisectConfig` | adaptive mode 与历史存储路径 |
| `PatchConfig` | patch ops 上限、崩溃自动 revert、shader 保留 |
| `ReportConfig` | HTML/Markdown/JSON 生成与缩略图嵌入，默认输出到 `logs_dir()` |

顶层还暴露两个裸字段：`renderdoc_module_path: Optional[str]`、`log_level: str = "INFO"`。

### 3.2 加载顺序

1. dataclass 默认值作为基线。
2. `RdcToolConfig.from_env()` 逐个读取 `os.environ`，仅当键存在时才覆盖对应字段。
3. `server_runtime.py` 在进程初始化阶段调用 `from_env()` 得到单例 `_config`，其余模块直接引用它。
4. 某些组件（如 `artifact_publisher.py`、`host_tools.py`）不经过 `RdcToolConfig`，而是各自 `os.environ.get(...)` 读取自己的键——这是已观察到的分散模式，并非统一入口。

### 3.3 环境变量命名空间

所有用户可见配置项统一以 `RDC_TOOL_` 为前缀，并按语义分组：

- 根与路径：`RDC_TOOL_ROOT`、`RDC_TOOL_INTERMEDIATE_ROOT`、`RDC_TOOL_ARTIFACT_STORE`、`RDC_TOOL_DATA_DIR`、`RDC_TOOL_REPORT_DIR`
- 日志与渲染：`RDC_TOOL_LOG_LEVEL`、`RDC_TOOL_HEADLESS`、`RDC_TOOL_RENDERDOC_PATH`、`RDC_TOOL_RUNTIME_DLL_DIR`
- Bisect 与自适应：`RDC_TOOL_BISECT_CONFIDENCE_SHARPNESS` / `CONSISTENCY` / `RANGE_FACTOR`、`RDC_TOOL_BISECT_PROFILE`、`RDC_TOOL_BISECT_ADAPTIVE_MODE`、`RDC_TOOL_BISECT_HISTORY_STORE`
- 资源限额：`RDC_TOOL_CONTEXT_ARTIFACT_TOTAL_LIMIT` / `PER_TYPE_LIMIT`、`RDC_TOOL_MAX_CONTEXTS` / `MAX_SESSIONS_PER_CONTEXT` / `MAX_CAPTURE_FILES` / `MAX_CAPTURE_SIZE_BYTES` / `MAX_ESTIMATED_REPLAY_MEMORY_BYTES` / `REPLAY_MEMORY_MULTIPLIER` / `MAX_RECENT_OPERATIONS`
- 宿主工具：`RDC_TOOL_ANDROID_ADB_PATH`、`RDC_TOOL_SPIRV_TOOLS_PATH`
- 发布与 S3：`RDC_TOOL_ARTIFACT_MODE`、`RDC_TOOL_REMOTE_ARTIFACT_MIN_BYTES`、`RDC_TOOL_ARTIFACT_DIR`、`RDC_TOOL_S3_ENDPOINT` / `BUCKET` / `REGION` / `ACCESS_KEY` / `SECRET_KEY` / `PRESIGN_SECONDS`
- 进程间：`RDC_TOOL_CONTEXT_ID`、`RDC_TOOL_DAEMON_PID`、`RDC_TOOL_WORKER_SOURCE_MANIFEST`

`environment.py` 中把旧名 `RDX_TOOLS_ROOT` 映射到 `RDC_TOOL_ROOT`，用于兼容迁移。

### 3.4 路径解析约定

`runtime_paths.py` 规定：优先 `RDC_TOOL_ROOT`，否则从脚本位置推断；若发现 `RDC_TOOL_ROOT` 指向无效路径会打印 warning。`ensure_rdc_tool_root()` 会在未设置时强制回写 `RDC_TOOL_ROOT`，因此后续模块可假定该环境变量存在。开发场景下 `intermediate/runtime`、`intermediate/artifacts`、`intermediate/logs` 均派生自 `RDC_TOOL_INTERMEDIATE_ROOT`。

## 4. 约定与约束

- **单一配置源**：除 `artifact_publisher.py` 与 `host_tools.py` 的少量散读外，应用配置集中在 `rdc_tool/config.py` 的 dataclass 中，不存在 `.yaml` / `.toml` / `.json` 配置文件格式。
- **环境变量前缀**：用户配置项统一使用 `RDC_TOOL_` 前缀，且全部大写；维护者专用项（如 `RDC_TOOL_PYTHON`、`RDC_TOOL_INTERMEDIATE_ROOT`）在 `docs/configuration.md` 中明确标注为非 GA 包所需。
- **可选覆盖**：`from_env()` 对每个 `os.environ.get` 都做了空串检查，缺失键不会报错——即所有 `RDC_TOOL_*` 配置都是可选的，dataclass 默认值始终生效。
- **布尔解析约定**：`RDC_TOOL_HEADLESS` 采用 `p.lower() in ("1", "true", "yes")` 判定，其他布尔型字段目前无显式解析逻辑（按 dataclass 默认值）。
- **路径解析**：`RDC_TOOL_ROOT` 无效时会打 warning 但不中止；`ensure_rdc_tool_root()` 会在首次调用时写入该变量，使后续代码可安全读取。
- **进程隔离**：`RDC_TOOL_CONTEXT_ID`、`RDC_TOOL_DAEMON_PID`、`RDC_TOOL_RUNTIME_DLL_DIR`、`RDC_TOOL_RENDERDOC_PATH`、`RDC_TOOL_WORKER_SOURCE_MANIFEST` 由 daemon/worker/bootstrap 在 fork/exec 子进程时注入，用于隔离同一机器上多个并发 session。
- **兼容性映射**：`environment.py` 把旧环境变量 `RDX_TOOLS_ROOT` 映射为 `RDC_TOOL_ROOT`，属于向后兼容层。
- **预览约束**：`docs/configuration.md` 指出 preview 使用 `screen_cap_ratio` 保持窗口尺寸有界，这是对预览行为的约束性描述。
- **运行时限额语义**：文档明确 `runtime_limits.max_contexts` 统计的是“活跃占用”（daemon pid、worker pid、owner pid、live replay/preview），持久化的 `runtime_state_*.json` 不计入容量。

## 5. 值得注意的分歧点

- `server_runtime.py` 是唯一通过 `RdcToolConfig.from_env()` 消费配置的入口；但 `core/artifact_publisher.py` 直接读取 `RDC_TOOL_ARTIFACT_MODE` / `RDC_TOOL_S3_*`，`host_tools.py` 直接读取 `RDC_TOOL_ANDROID_ADB_PATH` / `RDC_TOOL_SPIRV_TOOLS_PATH`，这些键不在 `RdcToolConfig` 中。新增配置时如果只放在 dataclass 里而不补充到 `from_env()` 或散读处，不会被实际生效。
- 没有 schema 校验、配置文件热重载、加密 secret 管理或 feature flag 系统；配置即“一组带默认值的 dataclass + 同名环境变量”。