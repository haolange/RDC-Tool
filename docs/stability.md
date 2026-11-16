# 稳定性

`rdc-tool` 把 CLI 入口与 canonical JSON envelope 视为稳定契约。

稳定的公开命令：

- `rdc-tool`

发行包内的 launcher 文件：

- `bin/rdc-tool.cmd`（Windows）
- `bin/rdc-tool`（Linux x86_64 运行捆绑的 python3.14；MSYS/Cygwin 运行 Windows 捆绑 Python）
- 捆绑 Python + `cli/run_cli.py`

launcher 按自身位置确定安装根目录，可在任意工作目录运行。

稳定的面向 Agent 命令：

- `context status|update|list|clear`
- `vfs ls|cat|tree|resolve`
- `diff pipeline|image`
- `assert pipeline|image`

稳定的 JSON envelope 字段：

- `schema_version`
- `tool_version`
- `result_kind`
- `ok`
- `data`
- `artifacts`
- `error`
- `meta`
- `projections`

退出码：

- `0`：成功
- `1`：运行时、断言或工具操作失败
- `2`：参数、准备、安装或启动失败

## 当前契约策略

- 代码中的操作定义就是当前契约；已删除的名称与参数别名会被拒绝。
- 消费方校验实际的 catalog、fingerprint、参数契约与所需能力；包版本号既不选择也不授权接口。与 RDC-Agent 的配对契约见 [Agent 集成](agent-integration.md)。
- 工具专属的 JSON `data` 可以新增字段（如 shader 的 `edit_plan`），前提是让 Agent 使用更安全，且不改变已有字段。
- JSON 是 canonical Agent 协议。
- TSV 只在命令文档声明了表格输出时（如 `vfs ls`）作为稳定的表格投影。
- `--daemon-context <id>` 选择持续的运行时命名空间；省略时使用 `default`。
- 接口变更同步更新同一套定义、消费方、测试与文档；不引入按版本命名的运行时路径或兼容别名。

## 主机相关的结构化错误

失败通过 envelope 的 `error` 返回，`category` 区分能力缺失（`capability`）与运行失败（`runtime`）；合法的空结果、读取失败与不支持分别表达，不以空值掩盖。

- `local_replay_unsupported`（`capability`）：本主机运行库无法本地回放该 capture 的图形 API（例如在 Linux 上回放 D3D capture），在创建回放之前返回。换到支持该 API 的主机，或用 `rd.remote.connect` 连接远端回放。
- `preview_unsupported_platform`（`capability`）：本主机没有原生 preview 窗口（目前只有 Windows 提供），`rd.core.get_capabilities` 的 `preview_window.available` 为 `false`。无窗口观察使用 `rd.session.observe`。
- `state_lock_timeout`（`runtime`）：持久化状态锁最多等待 10 秒。等并发写入结束后重试，不要删除锁文件。

## RenderDoc 运行库基线

当前基线与升级规则见 [发布基线](release-baseline.md)。RDC-Tool 不自动跟随上游每个版本；capture 格式兼容性遵循上游 RenderDoc。本地 PNG 导出不能证明 Android 设备已呈现画面。
