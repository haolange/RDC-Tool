# 工具

`rdc_tool/operation_definitions.py` 是操作定义的唯一真源，声明每个 `rd.*` 操作的输入约束、前置条件、作用域、影响、证据类型与路径输入。注册、`spec/tool_catalog.json`、CLI discovery 与生成的参考文档都由它派生；当前的操作数量与 catalog fingerprint 以 `rdc-tool tools list --json` 或 [工具参考](tool-reference.md) 为准。公开传输是 CLI，直接调用操作用 `rdc-tool call <rd.*>`。

```bat
rdc-tool tools list --json
rdc-tool tools list --full --json
rdc-tool tools search texture --json
rdc-tool tools describe rd.texture.compute_stats --json
rdc-tool context status --json
rdc-tool context update --key notes --value "triaged" --json
rdc-tool call rd.session.get_context --format json
rdc-tool call rd.session.update_context --args-file .\args.json --format json
```

`rdc-tool context status|update|list|clear` 是面向 Agent 的标准 context 接口。底层 catalog 工具 `rd.session.get_context` 与 `rd.session.update_context` 保留，用于精确的工具传输与测试。

`tools search` 匹配操作名、分组、描述与参数文本，因此可能返回多个领域的相关操作。精确列出一个领域用 `tools list --namespace <domain>`，查看单个操作的完整契约用 `tools describe <rd.*>`。完整 discovery 带内容 fingerprint，嵌入应用可以冻结与实际执行一致的定义。

会话工具见 [session-model.md](session-model.md)，Agent 使用规则见 [agent-model.md](agent-model.md)。选择精确工具之前，先用 VFS 探索运行时：

```bat
rdc-tool vfs ls --path / --format tsv
rdc-tool vfs cat --path /context --format json
rdc-tool vfs tree --path /draws --depth 2 --max-nodes 2000 --format json
```

`/draws` 的宽树节点只是摘要。节点报告 `detail_deferred=true` 时，用 `event show`、定向 `vfs cat` 或 `rd.event.get_action_details` 获取该事件。不要宽展开 `/resources`、`/textures` 或 `/buffers`，改用列表与定向的 canonical 工具。

JSON 是稳定协议。TSV 只是列表/导航输出的表格投影；嵌套的 context、管线、shader 与 preview 数据始终是 JSON。

`rd.session.open_preview` 经 daemon 背后的 CLI 运行时打开 preview 窗口；`preview.display` 由 context/session 状态返回，用于检查几何。原生 preview 窗口只在 Windows 上提供；其他主机返回结构化错误 `preview_unsupported_platform`（`rd.core.get_capabilities` 报告 `preview_window.available=false`），无窗口观察 `rd.session.observe` 在所有主机可用。

生成的参考文档是 [tool-reference.md](tool-reference.md)。高频 facade 命令有 `rdc-tool event`、`rdc-tool pipeline`、`rdc-tool shader`、`rdc-tool export`、`rdc-tool pixel` 与 `rdc-tool resource`，它们都分派到 canonical `rd.*` 工具，默认输出 JSON。

`rd.pipeline.get_state` 是统一的状态查询：用 `detail=summary|full` 和可选的 `sections` 选择 shader、输出目标、拓扑、viewport/scissor、blend、depth/stencil 或绑定。`rd.event.get_action_tree` 负责有界的树浏览与表格投影；`rd.session.get_replay_events` 是供嵌入式导航使用的完整轻量事件索引。`rd.resource.list_all(kind=all|texture|buffer)` 负责资源发现。纹理统计类操作读入内存，不生成 artifact；只有 `get_data`、导出与显式保存证据才会写盘。

简单的单行参数可以用 `--args-json`。多行 shader 源码、Windows 路径、内嵌引号或任何复杂 JSON，请把对象写进 UTF-8 文件后用 `--args-file`；`--args-json` 解析失败时，CLI 错误会提示改用这种方式。
