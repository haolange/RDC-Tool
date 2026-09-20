---
kind: error_handling
name: RDC 错误处理体系：CoreError 分类、SessionError 与统一响应信封
category: error_handling
scope:
    - '**'
source_files:
    - rdc_tool/core/errors.py
    - rdc_tool/core/session_manager.py
    - rdc_tool/core/contracts.py
    - rdc_tool/tool_router.py
    - rdc_tool/server_runtime.py
    - rdc_tool/daemon/server.py
    - rdc_tool/handlers/util.py
---

## 1. 整体方案

RDC 采用“领域异常 + 统一信封”的分层错误处理模型：
- 业务/运行时层抛出结构化异常（`CoreError` 及其子类、`SessionError`）。
- 调用栈顶层通过 `map_exception` 把任意 Python 异常归一化为 `CoreError`，再经由 `canonical_error` / `canonical_success` 输出统一的 JSON 信封 `{ok, data, error: {code, category, message, details}, meta}`。
- 守护进程（named pipe）和工具路由层在协议边界处捕获异常并转换为 `{ok: False, error: {code, message}}` 的 RPC 响应。

该模式贯穿 CLI → 守护进程 → 工具路由 → handler → core engine → session_manager → RenderDoc C API 的全链路。

## 2. 关键文件与包

| 文件 | 职责 |
|---|---|
| `rdc_tool/core/errors.py` | 定义 `CoreError` 基类及 `ValidationError` / `NotFoundError` / `AssertionFailedError` / `RuntimeToolError` / `PermissionToolError` / `IOToolError` / `InternalToolError` 七种分类；提供 `map_exception(exc)` 将任意 `Exception` 映射为 `CoreError`。 |
| `rdc_tool/core/session_manager.py` | 定义 `SessionError(Exception)`，其 `detail` 字段为 `ErrorDetail(code, message, details)`；所有 RenderDoc 会话/回放相关失败均抛此异常。 |
| `rdc_tool/core/contracts.py` | 定义成功/失败统一信封构造器 `canonical_success` / `canonical_error`，以及 schema_version、tool_version、artifact 等契约常量。 |
| `rdc_tool/tool_router.py` | 基于 catalog 注册操作，在执行前做参数校验（`validate_operation_arguments`）与前置依赖检查（`_enforce_prerequisites`），失败时返回带 `code`/`category`/`details` 的结构化错误字典。 |
| `rdc_tool/server_runtime.py` | 运行时核心：记录操作阶段、上下文快照、最近操作历史；多处直接 raise `CoreError`（如上下文容量超限、session_not_found）；捕获 `SessionError` 并转为上层错误。 |
| `rdc_tool/daemon/server.py` | named-pipe 守护进程：每个请求经 `_auth` 鉴权后分派到 `_handle_*`；所有 handler 返回 `{ok, result/error}`；连接级 try/except 兜底为 `{ok: False, error: {code: "daemon_error", ...}}`。 |
| `rdc_tool/handlers/util.py` | 最薄透的 handler 转发层，实际逻辑委托给 `server_runtime._dispatch_util`。 |

## 3. 架构与约定

### 3.1 异常分类体系（`CoreError` 族）

`CoreError` 是数据类异常，固定包含四个字段：
- `code`: 机器可读的错误码（如 `validation_error`、`not_found`、`runtime_error`、`permission_error`、`io_error`、`internal_error`、`assertion_failed`）。
- `message`: 人类可读的消息。
- `category`: 用于客户端路由/统计的分类（`validation` / `not_found` / `runtime` / `permission` / `io` / `internal` / `assertion_failed`）。
- `details`: 可选的附加信息字典。

子类仅负责填充固定的 `code`+`category`，消息与 details 由调用方传入。新增错误类型应遵循同一模式：继承 `CoreError` 并在 `__init__` 中固化 code/category。

### 3.2 异常归一化（`map_exception`）

位于 `rdc_tool/core/errors.py` 的 `map_exception` 是**唯一**的异常→结构化错误转换点，规则如下（按顺序匹配）：
1. 已是 `CoreError` → 原样返回。
2. 捕获 `SessionError`（延迟 import 避免循环依赖）→ 取其 `detail.code`/`detail.message`/`detail.details`，并按 `code` 是否以 `_not_found` 结尾或等于 `session_not_found` 推断 `category` 为 `not_found` 或 `runtime`。
3. `FileNotFoundError` → `NotFoundError`。
4. `PermissionError` → `PermissionToolError`。
5. `ValueError` / `TypeError` / `KeyError` → `ValidationError`。
6. `OSError` → `IOToolError`。
7. 其他任何 `Exception` → `InternalToolError`。

这意味着：**所有非显式处理的底层异常最终都会降级为 `internal_error`**，便于监控告警。

### 3.3 Session 层错误（`SessionError`）

`SessionManager` 封装 RenderDoc 本地/远程回放生命周期，所有状态不一致或底层 API 失败都抛出 `SessionError(code=..., message=..., details=...)`。常见 code 包括：
- `session_conflict`、`capture_already_open`、`controller_missing`、`output_missing`、`session_not_found`、`remote_endpoint_required`、`no_remote_server`、`remote_capture_copy_failed`、`renderdoc_error`。

这些错误被上层（`server_runtime.py` 等）通过 `map_exception` 自动归类为 `not_found` 或 `runtime`。

### 3.4 统一响应信封

`contracts.canonical_success` 与 `canonical_error` 产出结构一致的字典：
```json
{
  "schema_version": "3.0.0",
  "tool_version": "...",
  "result_kind": "...",
  "ok": true/false,
  "data": {...},
  "artifacts": [],
  "error": {"code": "...", "category": "...", "message": "...", "details": {}},
  "meta": {"trace_id": "...", "transport": "core", "duration_ms": 0},
  "projections": {}
}
```
所有工具 handler 应返回此格式（或能被上层包装为此格式）。失败路径必须设置 `ok=False` 且 `error` 非空。

### 3.5 守护进程协议边界

`DaemonRuntime.handle_request` 对每个 RPC 方法返回 `{ok, result/error}` 字典。鉴权失败返回 `unauthorized`，未知 method 返回 `unknown_method`，参数缺失返回 `bad_request`，worker 执行失败返回 `worker_error`，连接级未捕获异常返回 `daemon_error`。这种设计使跨进程通信不依赖异常传播，而是通过结构化错误字段传递。

### 3.6 工具路由层的前置校验

`tool_router.build_operation_registry` 在每个操作执行前：
1. 调用 `validate_operation_arguments(tool_name, args)`，若抛 `ValueError` 则返回 `{success: False, error_message, code: "validation_error", category: "validation"}`。
2. 检查 catalog 声明的 `prerequisites`（如 `capture_file_id`、`session_id`、`remote_id`、`active_event_id`、`capability.remote`），不满足时返回 `_structured_prereq_error`，code 形如 `missing_prerequisite_<requirement>`。

这保证了 handler 内部无需重复校验输入合法性。

## 4. 约定与约束

- **禁止裸 raise Exception**：业务层应使用 `CoreError` 或其子类；只有无法归类的底层异常才允许由 `map_exception` 兜底降级为 `internal_error`。
- **禁止绕过信封**：对外暴露的接口（handler 返回值、daemon RPC 响应、CLI 输出）必须使用 `canonical_success` / `canonical_error` 或等价结构，确保下游消费者可依据 `ok`/`error.code` 判断结果。
- **SessionError 的 detail 必须完整**：`SessionError` 构造时必须提供 `code` 与 `message`，`details` 建议包含 `source_layer`、`operation`、`backend_type`、`classification`、`fix_hint` 等字段，以便上层生成可诊断的错误详情。
- **分类一致性**：`category` 字段必须取自预定义集合（`validation` / `not_found` / `runtime` / `permission` / `io` / `internal` / `assertion_failed`），不得随意发明新分类。
- **守护进程不传播异常**：`serve_forever` 中的连接处理使用 try/except 包裹，任何未捕获异常都会被转换为 `{ok: False, error: {code: "daemon_error", message: str(exc)}}`，保证单个连接故障不影响 daemon 存活。
- **操作追踪**：`server_runtime` 通过 `_record_operation_start` / `_upsert_operation_entry` 维护 `recent_operations`，其中包含 `error_code`、`error_message`、`duration_ms`、`recovery_attempted` 等字段，用于审计与重试策略。
- **RenderDoc 状态检查集中化**：`session_manager._check_status` 统一将 RenderDoc status 对象转换为 `SessionError(renderdoc_error)`，并附带 `build_renderdoc_error_details` 生成的诊断信息，避免各调用点重复实现状态判断。

## 5. 适用性说明

本仓库是一个完整的 Python 工具运行时，具备明确的异常分类体系、统一的响应信封、守护进程协议级错误封装以及工具路由层的前置校验，因此错误处理是高度组织化的关注点，适用于本知识卡片。
