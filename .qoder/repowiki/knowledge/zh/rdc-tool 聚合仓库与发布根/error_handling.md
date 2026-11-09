## 1. 采用的体系

仓库使用一个自有的、轻量级的 Python 异常分类体系，围绕 `rdc_tool/core/errors.py` 中的 `CoreError` 基类组织。所有业务错误均属于该分类树；同时保留 Python 原生异常（`ValueError`、`OSError`、`PermissionError` 等）在局部代码中直接 raise，由调用点通过 `map_exception()` 统一映射为 `CoreError`。

此外，会话/回放子系统有一个独立的 `SessionError(Exception)`（定义于 `core/session_manager.py`），用于承载来自底层 replay 的 `ErrorDetail(code, message, details)`；`map_exception` 会把它包装成 `CoreError`。

CLI 和 daemon worker 中大量使用裸 `RuntimeError` / `ValueError` / `InterruptedError`，这些是面向进程边界的快速失败信号，不进入统一的 `CoreError` 体系。

## 2. 关键文件

- `rdc_tool/core/errors.py` — 核心分类与 `map_exception` 适配器。
- `rdc_tool/core/session_manager.py` — `SessionError` + `ErrorDetail`，作为与底层 replay 的边界。
- `rdc_tool/server_runtime.py` — 最大的 `CoreError` 生产者与消费者：构造带稳定 `code`/`category`/`details` 的错误，并在多处 `except CoreError` 分支处理。
- `rdc_tool/core/engine.py`、`rdc_tool/server.py` — 两处显式调用 `map_exception(exc)` 把任意异常归一化后返回给上层。
- `rdc_tool/cli.py`、`rdc_tool/cli_batch.py`、`rdc_tool/daemon/worker.py` — CLI/Worker 边界，主要用裸 `RuntimeError`/`ValueError` 暴露给进程外调用者。

## 3. 架构与约定

### 3.1 分类层次

```text
Exception
└── CoreError(code: str, message: str, category: str, details: Dict)
    ├── ValidationError("validation")
    ├── NotFoundError("not_found")
    ├── AssertionFailedError("assertion_failed")
    ├── RuntimeToolError("runtime")
    ├── PermissionToolError("permission")
    ├── IOToolError("io")
    └── InternalToolError("internal")
```

每个子类固定一个 `code` 和 `category`，并通过 `__str__` 只输出 `message`。`details` 是可选的结构化附加信息。

### 3.2 `map_exception` 适配策略

`map_exception(exc)` 是一个单入口降级器，按以下优先级工作：

1. 如果已经是 `CoreError`，原样返回。
2. 如果是 `SessionError`，从 `exc.detail.code/message/details` 取出字段，并依据 code 是否以 `_not_found` 结尾或等于 `session_not_found` 决定 `category` 为 `not_found` 还是 `runtime`。
3. `FileNotFoundError` → `NotFoundError`。
4. `PermissionError` → `PermissionToolError`。
5. `ValueError`/`TypeError`/`KeyError` → `ValidationError`。
6. `OSError` → `IOToolError`。
7. 其余全部 → `InternalToolError`。

这个函数是 `core/engine.py` 和 `server.py` 捕获底层异常后的唯一出口，保证向 RPC/CLI 侧返回稳定的 `CoreError`。

### 3.3 `ServerRuntime` 的直抛模式

`server_runtime.py` 中大多数业务校验与运行时失败直接 `raise CoreError(code=..., category=..., message=..., details=...)`，而不是先抛原生异常再被捕获。例如 shader stage 不支持、capture_initial/replay 恢复失败、session 冲突、`invalid_max_bytes` 等。调用方普遍 `except CoreError as exc:` 读取 `exc.code`/`exc.category`/`exc.details` 做分支决策。

### 3.4 SessionError 的双层语义

`SessionError` 不是 `CoreError` 的子类，它携带一个 `ErrorDetail` 对象。这是为了让底层 replay 的错误码（如 `session_not_found`）能原样透传到上层，再由 `map_exception` 根据 code 后缀推断 category。这构成了一条“底层 → SessionError → CoreError”的转换链。

## 4. 约定与约束

- **稳定错误码**：`CoreError.code` 是对外契约的一部分（注释写明 "stable categories for exit-code mapping"）。新增错误应复用已有 category 并为 `code` 取具名字符串，而非随意生成消息。
- **Category 含义**：`validation`/`not_found`/`assertion_failed`/`runtime`/`permission`/`io`/`internal` 是已观察到的稳定取值集合，用于下游分类（如退出码映射）。
- **细节结构化**：业务错误应把可机器消费的上下文放入 `details` dict，而不是塞进 message。
- **边界分离**：
  - 库层/服务层：优先抛 `CoreError` 或其子类，或使用 `map_exception` 包裹原生异常。
  - CLI/Worker 进程边界：直接使用 `RuntimeError`/`ValueError`/`InterruptedError`，因为进程退出即表示失败，无需跨进程序列化 `CoreError`。
- **SessionError 透传**：涉及底层 replay 的错误必须经 `SessionError` 传递，以便 `map_exception` 保留原始 code。
- **未覆盖的原生异常兜底**：任何未被 `map_exception` 显式匹配的异常都会被包装为 `InternalToolError`，这充当了“不可预期错误”的收集桶。

注意：以上分类体系仅存在于 Python 侧；仓库中未见 panic/recover 概念（Go 风格），也未见中间件式的错误拦截框架——错误传播主要通过函数返回值 + 异常冒泡实现。