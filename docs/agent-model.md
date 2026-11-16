# Agent 模型

Agent 把 `rdc-tool` 当作纯 CLI 使用，经 shell 工具调用 `rdc-tool` 命令。命令入口是安装内的 launcher：Windows 为 `bin/rdc-tool.cmd`；`bin/rdc-tool` 在 Linux x86_64 上使用捆绑的 `python3.14`，在 MSYS/Cygwin 下使用 Windows 捆绑 Python。缺少捆绑 Python 时 launcher 直接失败，不回退到系统 Python。RDC-Agent 的配对方式见 [agent-integration.md](agent-integration.md)。

## 就绪与 context

运行时是否就绪未知或环境有变化时，运行 `rdc-tool --json doctor`；否则沿用当前有效的成功结果。执行依赖会话状态的操作前，先用 `rdc-tool context status` 查看所选 context。需要保持任务连续性时，用 `rdc-tool context update` 写入范围内的 notes 或 focus。`session_locator` 汇总所选 daemon context 当前的 capture、session 与 event。

多个 daemon context 彼此隔离。非简单的 capture 任务使用显式 `--daemon-context <id>`，并在各次调用中保持一致。daemon 状态输出报告 `endpoint`，从不输出 IPC 密钥。

## 发现

按需窄范围发现：`rdc-tool tools search <term>` 查找相关操作，`rdc-tool tools list --namespace <domain>` 列出某个领域，`rdc-tool tools describe <rd.*>` 返回单个操作完整的参数、结果与影响契约。search 会匹配描述与参数，结果可能跨领域。声明的 scope 或 effect 只用于编排，从不授予权限；嵌入宿主在执行前仍要校验身份、会话归属、路径与操作影响。

## 浏览

目标未知时，按需有界地浏览 VFS：`rdc-tool vfs ls --path / --format tsv`、`rdc-tool vfs cat --path /context --format json`，或有界树 `rdc-tool vfs tree --path /draws --depth 2 --max-nodes 2000 --format json`。已知事件、资源或所需工具时直接查询。宽范围 `/draws` 树节点只是摘要；节点报告 `detail_deferred=true` 时，用 `event show`、定向 `vfs cat` 或 canonical 工具 `rd.event.get_action_details` 查看该事件。不要宽范围展开 `/resources`、`/textures` 或 `/buffers`，改用 `vfs ls` 与定向 `vfs cat` 或 canonical `rd.*` 工具。JSON 是 canonical 格式；TSV 只用于表格导航与列表投影。

## 有界读取

- 管线读取用 `rd.pipeline.get_state(detail=summary, sections=[...])`；只有确实需要完整状态时才请求 `full`。
- `rd.event.get_action_tree` 用于浏览，报告分页、已输出节点与截断情况，不要当作完整帧索引；嵌入宿主用 `rd.session.get_replay_events`。
- 资源历史是 `rd.resource.get_usage`，条目保留原始 event ID 并标识写入。
- 纹理统计类查询留在内存中；只有显式的 readback 或导出请求才持久化数据。

## 回放与远端

本机运行库无法本地回放 capture 所用的 API 时，`rd.capture.open_replay` 在创建回放前返回 `local_replay_unsupported`（category `capability`，details 含 `capture_api`、`host_target`、`recovery_hint`）。此时改用支持该 API 的主机，或经 `rd.remote.connect` 连接远端并在 `options.remote_id` 中传入远端句柄。

远端状态报告 `remote_handle_consumed` 时，不要复用该远端句柄；按需用远端生命周期工具重新连接、ping 或重新打开回放。

## Shader 编辑

修改文本前，先读取 `rd.shader.get_source`、`rd.shader.get_disassembly`、`rd.shader.compile` 或 `rd.shader.edit_and_replace` 返回的 `edit_plan`。调试源码不可用时，`edit_plan.recommended_next_tool` 指明是经 `rd.shader.get_disassembly` 查看 IR，还是经 `rd.shader.extract_binary` 导出原始容器。plan 允许时，SPIR-V ASM 可以按文本编辑。DXIL/DXBC 反汇编为 `captured_source_editable=false`，不得按文本编辑；完整替换是另一条路径：用户经 `source_text` 或 `source_path` 提供完整 HLSL/GLSL，并给出 `entry` 与 `target`，运行时报告 `runtime_full_replace_supported`。

`source_target` 指 RenderDoc 返回的表示，例如 `SPIR-V ASM` 或 `DXIL`；`source_encoding` 指回放后端如何解释替换输入。二者相关但不能互换，以 `edit_plan` 与工具返回的值为准。

## 观察

人工观察者需要 preview 窗口时，Agent 经 CLI 命令使用 `rd.session.open_preview`。`preview.display` 是窗口与 framebuffer 几何的稳定状态面。原生 preview 窗口只在 Windows 主机提供；其他主机上 `rd.core.get_capabilities` 报告 `preview_window.available=false`，`rd.session.open_preview` 返回 capability 错误 `preview_unsupported_platform`。

嵌入消费者用 `rd.session.get_replay_events` 与 `rd.session.observe` 完成完整事件导航与无窗口 PNG 观察，二者在所有支持的主机上可用。原子应用与部分失败契约见 [session-model.md](session-model.md) 的嵌入回放观察一节。这些操作不替代独立 CLI 的 `rd.session.open_preview` / `preview.display` 窗口流程。

## 恢复型数据查询

capture 级缩略图读取使用应用所属的 capture 身份。结构化调用、descriptor、初始化关系与管线 section 提供基础事实，因果分析与报告由 Skill 组合。临时回放读取返回恢复证明，并保持在应用的串行租约内。帧证据比较原生测量方法、完整范围、采样条件与 capture 身份，实际 replacement 状态由宿主核验。

## 参考

任务级 SOP 见 [rdc-tool-native agent playbook](rdc-tool-native-agent-playbook.md)。精确的 catalog 覆盖见 [Tool reference](tool-reference.md)，它由 `rdc_tool/operation_definitions.py` 生成。
