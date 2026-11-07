## 1. 采用的系统/方法

该仓库使用一个自研的 Python 异常分类体系，围绕 `rdc_tool/core/errors.py` 中的 `CoreError` 基类构建。所有业务层异常都继承自 `CoreError`，并通过统一的 `map_exception(exc)` 函数将底层原生异常（`FileNotFoundError`、`PermissionError`、`ValueError`、`TypeError`、`KeyError`、`OSError`）以及 `SessionManager.SessionError` 归一化为 `CoreError`，从而为上层 CLI/daemon 提供稳定的错误码与退出码映射。

- **基类**：`CoreError(Exception)`，携带四个稳定字段：`code: str`、`message: str`、`category: str`、`details: Dict[str, Any]`。
- **预定义子类**：`ValidationError`、`NotFoundError`、`AssertionFailedError`、`RuntimeToolError`、`PermissionToolError`、`IOToolError`、`InternalToolError`，每个子类固定其 `code` 和 `category`。
- **独立异常族**：`session_manager.py` 中定义了 `SessionError(Exception)`，它不是 `CoreError` 的子类，而是通过 `detail: ErrorDetail(code, message, details)` 属性承载同样的三元组语义；`map_exception` 通过类型检查将其桥接回 `CoreError`。
- **顶层入口**：CLI 入口 `server.py` 与核心调度器 `core/engine.py` 在各自的最外层 try/except 中使用 `map_exception` 捕获未处理异常，保证返回给调用方的始终是结构化错误。

## 2. 关键文件与包

| 文件 | 职责 |
|---|---|
| `rdc_tool/core/errors.py` | 唯一错误分类中心：`CoreError`、7 个业务子类、`map_exception` |
| `rdc_tool/core/session_manager.py` | 定义 `SessionError` 及其 `ErrorDetail`，用于会话生命周期错误 |
| `rdc_tool/core/engine.py` | 操作调度器，统一用 `NotFoundError` / `InternalToolError` 包装不支持或内部失败 |
| `rdc_tool/server.py` | CLI/daemon 服务器顶层异常处理器，调用 `map_exception` |
| `rdc_tool/server_runtime.py` | 运行时控制面主逻辑，大量直接 raise `CoreError` / `RuntimeToolError` |
| `rdc_tool/core/renderdoc_status.py` | 封装 RenderDoc 状态到 `RuntimeToolError` |
| `rdc_tool/core/perf_service.py` | 性能服务中对 `CoreError` 的直接使用示例 |
| `tests/` 下多份测试 | 断言预期抛出的 `CoreError` / `RuntimeToolError`，是错误契约的补充文档 |

## 3. 架构与约定

### 3.1 三层错误形态

1. **业务语义异常**：如 `NotFoundError("capture not found")`、`ValidationError("max_bytes must be non-negative")`，由领域代码直接 raise。
2. **平台/第三方异常**：如 `FileNotFoundError`、`PermissionError`、`OSError`，被 `map_exception` 在边界处转换为对应的 `CoreError` 子类。
3. **会话异常**：`SessionError` 通过 `SessionError(code="session_not_found", message=..., details={...})` 表达，并由 `map_exception` 根据 `detail.code` 的后缀（如 `_not_found`）推导 category。

### 3.2 错误传播路径

```
业务层 (raise CoreError/RuntimeToolError/SessionError)
→ server_runtime.py 等调用栈
→ core/engine.py 或 server.py 的顶层 except Exception
→ map_exception(exc) → CoreError
→ 返回给 CLI/daemon 客户端
```

`server_runtime.py` 中还存在大量 `except CoreError as exc:` 的重抛与包装模式，例如在清理阶段把多个错误聚合成 `RuntimeToolError(..., details={"cleanup_errors": errors})`，形成“聚合错误”的常见形态。

### 3.3 错误域划分

- `category` 字段承担“错误域”语义：`validation`、`not_found`、`assertion_failed`、`runtime`、`permission`、`io`、`internal`、`capability`。
- `code` 字段作为跨进程的稳定标识符，例如 `shader_stage_unsupported`、`invalid_shader_stage`、`session_requires_restart`、`replay_restore_failed`、`invalid_max_bytes`、`remote_version_mismatch`、`controller_missing`、`session_conflict`、`capture_already_open` 等，供外部消费者（CI、日志分析、诊断工具）按字符串匹配。

### 3.4 与 RenderDoc 状态的桥接

`renderdoc_status.build_renderdoc_error_details()` 与 `SessionManager` 结合，将 RenderDoc C API 的状态文本转译为 `CoreError` 的 `message` + `details["renderdoc_status"]`，再经由 `map_exception` 统一输出。

## 4. 观察到的约定与约束

- **约定：所有业务异常应继承 `CoreError` 或其子类**。证据：`errors.py` 定义了完整子类族，`server_runtime.py` 中几乎所有 `raise` 都是 `CoreError(code=..., category=..., message=..., details=...)` 或 `RuntimeToolError(message, details=...)`。
- **约定：底层原生异常不在业务层直接向上抛出**，应在边界处经 `map_exception` 转换。证据：`core/engine.py` 与 `server.py` 在顶层 `except Exception` 后统一调用 `map_exception`。
- **约定：`SessionError` 不继承 `CoreError`**，而是通过 `self.detail = ErrorDetail(code, message, details)` 传递等价结构，并在 `map_exception` 中被显式识别并桥接。这是 `errors.py` 中对 `SessionError` 的特殊分支所强制的行为。
- **约定：`code` 采用小写下划线命名，且以领域概念为单位**（如 `shader_stage_unsupported`、`session_not_found`、`remote_capture_copy_failed`），便于外部匹配。
- **约定：`category` 使用有限集合**（见 `errors.py` 各子类的 hard-coded 值），新增类别需在 `map_exception` 中显式处理（目前仅对 `SessionError` 做 `_not_found` 后缀推断）。
- **约定：可恢复性错误的 details 中常包含 `cleanup_errors` 列表**，用于记录资源清理阶段的多个子错误（见 `server_runtime.py` 多处 `details={"cleanup_errors": errors}`）。
- **约束：`map_exception` 是异常归一化的权威入口**——任何未被显式 catch 的异常最终都会落入该函数的 `return InternalToolError(str(exc))` 兜底分支，因此新增异常类型时不应绕过它。
- **约束：`SessionError` 的 `detail.code` 若以 `_not_found` 结尾，会被 `map_exception` 归类为 `not_found` category**；否则归为 `runtime`。这是当前实现中唯一自动推导 category 的逻辑。
- **测试契约**：多项测试（如 `test_remote_runtime.py`、`test_texture_export_metadata.py`、`test_android_helper_repair.py`、`test_server_event_pipeline_resource.py`）通过 `pytest.raises(RuntimeToolError|CoreError, match=...)` 断言具体错误消息片段，构成错误行为的回归保障。