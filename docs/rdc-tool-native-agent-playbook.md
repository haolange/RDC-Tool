# rdc-tool-native Agent Playbook

本 playbook 是 Agent 使用 `rdc-tool` 的 canonical rdc-tool-native SOP。它刻意保持为普通仓库文档，而不是某个宿主专属的 skill 文件。运行时契约保持 CLI-only、JSON 优先。

## 适用范围

Agent 需要经 `rdc-tool` 检查、排查、导出或调试 RenderDoc `.rdc` capture 时使用本 playbook，包括远端 Android 回放会话。支持的主机见 [release-baseline.md](release-baseline.md)。不适用于无关的 GPU 工具或产品范围之外的平台。

需要精确的 catalog 操作时用 `rdc-tool call <rd.*> --format json`。高频检查才用面向人的 facade 命令：`event`、`pipeline`、`shader`、`export`、`pixel` 与 `resource`。facade 命令调用的仍是同一套 canonical `rd.*` 工具。

## 基本规则

- 运行时是否就绪未知或环境有变化时，运行 `rdc-tool --json doctor`；否则沿用当前有效的成功结果。
- 窄范围发现。语义搜索用 `rdc-tool tools search <term>`，列出某个领域用 `rdc-tool tools list --namespace <domain>`，使用不熟悉的操作前先 `rdc-tool tools describe <rd.*> --json`。search 可能返回多个领域的相关操作。
- 非简单的 capture 任务使用 `--daemon-context <id>`，并在各次调用中保持一致，避免状态在 Agent 任务之间泄漏。
- 执行依赖会话状态的操作前，用 `rdc-tool context status --json` 查看所选 context。有助于任务连续性时用 `rdc-tool context update --key notes --value "..." --json` 写入 notes。有意清理本任务的 context 时用 `rdc-tool context clear --json`；状态过期时按下文的恢复顺序操作。
- 目标未知时，按需有界地浏览 VFS：`rdc-tool vfs ls --path / --format tsv`、`rdc-tool vfs cat --path /context --format json`，或有界树 `rdc-tool vfs tree --path /draws --depth 2 --max-nodes 2000 --format json`。已知事件、资源或所需工具时直接查询。宽范围 `/draws` 树节点有意以 `detail_deferred=true` 推迟完整事件详情；对选定事件用 `event show`、定向 `vfs cat` 或 canonical 工具。不要宽范围展开 `/resources`、`/textures` 或 `/buffers`，改用 `vfs ls`、定向 `vfs cat` 或 canonical 工具。
- JSON 是 canonical 格式。TSV 只是列表与导航面的投影。
- 控制输出规模。先用摘要、VFS 路径与具体的资源/事件 ID，再请求大 payload。
- 不猜测会话。所选 daemon context 没有活动会话时，先打开 capture 或传 `--session-id`。

## 输出规模

用列表与摘要命令定位未知目标或限制大 payload；已知目标直接查询：

```bat
rdc-tool --daemon-context case-1 event list --format tsv
rdc-tool --daemon-context case-1 pipeline show --event-id 42 --format json
rdc-tool --daemon-context case-1 resource list --format tsv
```

facade 有意隐藏低频参数；需要 `max_nodes`、`max_events`、投影或过滤等 catalog 选项时，用原始 `rdc-tool call`。纹理统计、直方图、差异与 base64 buffer 读取都留在内存中。只有导出或证据请求需要持久化时，才把文件写到所配置的 `RDC_TOOL_INTERMEDIATE_ROOT` 下。复杂 JSON 用 `--args-file`，多行 HLSL/GLSL 替换源码尤其如此。

## 故障恢复

命令返回 `session_required` 时，对该 `--daemon-context` 运行 `rdc-tool context status --json`，然后重新打开 capture 或传入目标 `--session-id`。

`rd.capture.open_replay` 返回 `local_replay_unsupported`（category `capability`）表示本机运行库无法本地回放该 capture 的 API；details 给出 `capture_api`、`host_target` 与 `recovery_hint`。改用支持该 API 的主机，或按配方 7 走远端回放。

preview、远端回放、shader 替换或导出失败时，保留失败的 JSON payload，其中通常含 `failure_stage`、`failure_reason`、`resolved_event_id`、`binding_truth_level` 或 `edit_plan`。除非 payload 推荐了下一个工具，不要靠更换编码或 target 重试。

context 看起来过期时，先查看状态，再经 canonical 回放资源路径关闭回放。清理失败或返回 `stale_session_requires_restart` 时，重启该 daemon context：

```bat
rdc-tool --daemon-context case-1 context status --json
rdc-tool --daemon-context case-1 call rd.capture.close_replay --args-file close_replay_args.json --format json
rdc-tool --daemon-context case-1 context clear --json
rdc-tool --daemon-context case-1 daemon stop
```

## 配方

按任务选择相关配方，只运行需要的步骤。就绪检查与浏览遵循上面的条件；示例不是跨配方的强制顺序。

### 1. 打开 capture

```bat
rdc-tool --daemon-context case-1 --json doctor
rdc-tool --daemon-context case-1 capture open --file "C:\captures\case.rdc" --frame-index 0
rdc-tool --daemon-context case-1 context status --json
rdc-tool --daemon-context case-1 vfs ls --path / --format tsv
```

成功时 context 状态含 `session_locator`，带 capture、session、frame 与活动事件标识。

### 2. 未知帧排查

```bat
rdc-tool --daemon-context case-1 event list --format tsv
rdc-tool --daemon-context case-1 vfs tree --path /draws --depth 2 --max-nodes 2000 --format json
rdc-tool --daemon-context case-1 context update --key notes --value "unknown frame triage" --json
```

先找出可疑的 marker/drawcall，再只检查候选 event ID。

### 3. 管线与资源检查

```bat
rdc-tool --daemon-context case-1 pipeline show --event-id 42 --format json
rdc-tool --daemon-context case-1 pipeline section --event-id 42 --stage ps --format json
rdc-tool --daemon-context case-1 resource list --format tsv
rdc-tool --daemon-context case-1 resource show --resource-id <resource-id> --format json
rdc-tool --daemon-context case-1 resource usage --resource-id <resource-id> --format json
```

`pipeline show` 给出紧凑状态，`pipeline section` 给出单个 shader stage。原始调用可用 `detail=summary|full` 与 `sections` 限制 `rd.pipeline.get_state`。资源发现是 `rd.resource.list_all(kind=all|texture|buffer|descriptor_store)`；资源使用保留真实 event ID 与写入分类。

### 4. 可视导出与 preview

```bat
rdc-tool --daemon-context case-1 session preview on
rdc-tool --daemon-context case-1 session preview status
rdc-tool --daemon-context case-1 export screenshot --event-id 42 --out intermediate\artifacts\case-1\event42.png
```

几何重要时，查看 `context status --json` 中的 `preview.display`，它是 framebuffer、fit 与窗口尺寸的稳定 preview 状态面。原生 preview 窗口只在 Windows 主机提供；其他主机上 `session preview on` 返回 `preview_unsupported_platform`，改用 `export screenshot` 或无窗口的 `rd.session.observe`。

`rd.export.mesh` 把 post-VS 位置或 `space=vs_input` 几何写成 OBJ。对 `vs_input`，`include_attributes=true` 导出显式解码的 float POSITION/NORMAL/TEXCOORD0，面索引中的 v/vn/vt 一一对应，坐标保持原始输入空间。packed normal 编码、含糊语义、混合 instance 属性、不支持的拓扑与不完整 readback 都会被拒绝，不写占位文件。post-VS OBJ 只含位置，不能借用输入法线。

### 5. 像素调试

```bat
rdc-tool --daemon-context case-1 pixel value --event-id 42 --resource-id <texture-id> --x 320 --y 180 --format json
rdc-tool --daemon-context case-1 pixel history --event-id 42 --resource-id <texture-id> --x 320 --y 180 --format json
```

显式给出 `texture_id`、`x` 与 `y`。目标纹理未知时，先检查管线输出或 VFS draw 节点。

### 6. 依据 edit_plan 编辑 shader

```bat
rdc-tool --daemon-context case-1 shader source --event-id 42 --stage ps --format json
rdc-tool --daemon-context case-1 shader disasm --event-id 42 --stage ps --format json
rdc-tool --daemon-context case-1 shader constants --event-id 42 --stage ps --slot 0 --format json
```

编辑前先读 `edit_plan`。`captured_source_editable=false` 表示捕获的反汇编只读。DXIL/DXBC 完整替换时，经 `source_path` 或 `source_text` 提供完整 HLSL，并给出 `entry` 与 `target`（如 `ps_6_6`）；编译失败不会调用 `ReplaceResource`，替换失败会报告清理与 context 证据。若为 `runtime_full_replace_supported=false`，按返回的失败原因处理，不要自造 source encoding。

### 7. Android 远端打开与回放

设备、包名、activity 与 capture 路径都依赖环境，因此经 `rdc-tool call` 显式使用远端工具：

```bat
rdc-tool --daemon-context android-1 call rd.remote.connect --args-file intermediate\logs\remote_connect_args.json --format json
rdc-tool --daemon-context android-1 call rd.remote.ping --args-file intermediate\logs\remote_ping_args.json --format json
rdc-tool --daemon-context android-1 call rd.capture.open_file --args-file intermediate\logs\remote_open_file_args.json --format json
rdc-tool --daemon-context android-1 call rd.capture.open_replay --args-file intermediate\logs\remote_open_replay_args.json --format json
rdc-tool --daemon-context android-1 context status --json
```

`rd.capture.open_replay` 的参数带 `rd.capture.open_file` 返回的 `capture_file_id`，以及 `rd.remote.connect` 返回的 `options.remote_id`，这样远端回放不会回退到本地。之后被消耗的远端句柄不能当作空闲连接复用；状态报告 `remote_handle_consumed` 时，经远端生命周期工具重新连接或恢复。完整的 Android 验收流程见 [android-remote-cli-smoke-prompt.md](android-remote-cli-smoke-prompt.md)。

### 8. 缺陷报告证据

收集最小的可复现证据集。没有固定的报告打包操作；由专业工作流显式选择每项观察与导出：

```bat
rdc-tool --daemon-context case-1 version --json
rdc-tool --daemon-context case-1 --json doctor
rdc-tool --daemon-context case-1 context status --json
rdc-tool --daemon-context case-1 event show --event-id 42 --format json
rdc-tool --daemon-context case-1 pipeline show --event-id 42 --format json
rdc-tool --daemon-context case-1 export screenshot --event-id 42 --out intermediate\artifacts\case-1\bug-event42.png
```

报告包含确切命令、JSON payload、artifact 路径、可分享时的 capture SHA256，以及会话是本机回放（注明主机目标）还是远端 Android。不要把私有 capture 或本机绝对路径写进已提交的文档或发布元数据。

## 两个 capture 与只读批处理（独立 CLI）

本配方面向人工或独立 CLI 使用。RDC-Agent 的 General 应改用其 Analyzer 方法 Skill 中的 owning-session 应用流程。

1. 在同一个 `--daemon-context compare` 中，分别对 A 与 B 调用 `rd.capture.open_file`，各自保留返回的 `capture_file_id`。
2. 对每个句柄调用 `rd.capture.open_replay`，保留两个 `session_id`。不同 capture 有不同会话。重新打开同一个**句柄**会复用其回放；再次调用 `open_file` 会产生新的 capture 身份，即使文件相同。
3. 用显式会话分别查询 `rd.session.get_replay_events`、action 详情与管线状态。每条观察都带上 capture 文件哈希、context、session 与 event 身份。不要把 ResourceId 当作跨文件的稳定键。
4. 用 marker 路径加 shader 内容哈希、原生 debug 名称与管线事实比较观察。缺失的键保持 null；marker 名称重复不意味着唯一匹配。没有 marker 时，拓扑、附件与事件邻域只是启发式，需要找反例验证。

预先确定的查询可以共用一个客户端进程：

```jsonl
{"operation":"rd.session.get_replay_events","args":{"session_id":"session-A"}}
{"operation":"rd.session.get_replay_events","args":{"session_id":"session-B"}}
```

保存为 `queries.jsonl`，然后运行 `rdc-tool --daemon-context compare batch queries.jsonl`。使用实际发现的 ID，而不是这里的占位值。batch 只接受没有写入或生命周期变化的 catalog effect；回放位置类 effect 仍由现有 worker 串行执行。canonical `ok=false`、解析/校验/传输错误会立即停止并以非零退出，保留此前与失败的 envelope。合法的空数据继续执行。Ctrl-C 在进行中的请求完成或返回超时/错误后停止调度；取消请求不能证明原生工作已停止。借用的 daemon 继续运行。

发现：`tools list --namespace mesh --json`、`tools search usage --json`，再 `tools describe <operation> --json`。describe 是权威结果，不要另抄 catalog 白名单。

断言与证据组织由调用方负责：陈述期望事实，保留原始 envelope 与 capture 身份/哈希，再比较实际字段。按 capture/event/operation 分组回归观察，保留 unsupported/error 边界。不要虚构运行时断言、DAG 或证据包操作。

mesh `get_drawcall_mesh_config` 返回有界的 VS 输入行（默认 128 个 draw 索引），带显式的输入语义、格式、绑定与 instance 来源。NORMAL 与 TEXCOORD0 的值来自实际输入字节；归一化整数值是 shader 输入，不是推断出的法线向量。post-transform 行单独给出：原生位置，加上经核验的 D3D11/12 stream-zero float signature 输出。TEXCOORD 输出标签不能证明法线语义。OBJ 属性要求 `space=vs_input` 与 float 语义；未绑定 GS 是显式的成功未绑定结果，不是完整 mesh。`truncated=null` 表示无法从无界原生视图确定总大小。shader hash 基于记录的 rawBytes；debug_name 排除自动生成的名称，二者都可能为 null。resource_name 保留原生 shader 显示名；debug_source_files 是源码文件名，从不替代 debug 名称。mesh/texture 标签等资源名不是 shader 名称。shader 源码/二进制编码以操作当前的 enum 为准，不要用猜测的编码重试。

usage 的 `usage_name` 对应确切的原生 enum 值；read/write 可能为 null，仅绑定的访问不可观察。color/depth 附件与可解析的 event ID 支持知识层的资源版本图，但不能证明引擎 RenderGraph、逐像素访问或资源未被使用。观察与推断出的依赖分开记录。

先释放自己的 context，再只停止自己拥有的 daemon，并检查其终止回执。临时回放位置查询需要恢复证据；恢复失败会隔离该回放，并阻止后续结论。
