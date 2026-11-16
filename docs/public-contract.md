# 公共契约

本文列出调用方可以依赖的 `rdc-tool` 行为：入口、结果信封、操作集、错误码与各类操作的结果语义。进程、context 与 preview 生命周期见 [session-model.md](session-model.md)，现象与恢复步骤见 [troubleshooting.md](troubleshooting.md)，分层结构见 [ARCHITECTURE.md](../ARCHITECTURE.md)，原生运行库身份见 [release-baseline.md](release-baseline.md)，环境变量见 [configuration.md](configuration.md)。

## 入口

公开命令只有 `rdc-tool`。发行包另带平台 launcher（`bin/rdc-tool.cmd`、`bin/rdc-tool`）与“同安装捆绑 Python + `cli/run_cli.py`”入口，用于安装诊断、维护与 RDC-Agent 集成。`rdc-tool version --json` 报告工具版本、`schema_version`、主机目标、安装根目录、入口路径与兼容性元数据；安装根目录由 `rdc_tool` 包所在位置决定。

## 结果信封

所有命令与操作都返回 canonical JSON 信封（`schema_version` 为 `3.0.0`）：`tool_version`、`result_kind`、`ok`、`data`、`artifacts`、`error`（`code`、`category`、`message`、`details`）、`meta` 与 `projections`。操作集变化时信封保持不变。

canonical JSON 不输出非标准裸数值 `NaN`、`Infinity`、`-Infinity`。原生着色器或 capture 数据中的非有限浮点值保留为字符串 `"NaN"`、`"Infinity"`、`"-Infinity"`，有限值仍是数字。这些标记描述观察到的原生值，不是替代的零值或成功测量；解读数值数组时须把它们当作非有限数据。

## 操作集

`rdc_tool/operation_definitions.py` 是操作名称、参数、结果、前置条件与影响声明的唯一真源；注册表、`spec/tool_catalog.json`、[tool-reference.md](tool-reference.md) 与 CLI discovery 都由它生成，描述同一操作集与内容 fingerprint。调用方按实际 catalog 与 fingerprint 校验能力，不以包版本号或固定数量代替。

未知操作与未知参数在执行前失败；运行时不翻译旧名称或含糊的参数别名。已移除的操作没有 alias 或转发处理，升级后遇到 `not_found` 的处理见 [troubleshooting.md](troubleshooting.md)。旧操作的处置结论只记录在[历史处置记录](tool-interface-upgrade.md)中，它不是迁移表或 alias 映射，运行时也不读取。

## Context 命名空间

`--daemon-context <id>` 选择一个隔离的运行时命名空间（省略时为 `default`）。它不是所有权声明或任务交接机制；调用方在自己的编排层选择和管理 context id。context、daemon 与 worker 的生命周期见 [session-model.md](session-model.md)。

## 进程身份

经 worker 执行的操作在 `meta.process_identity` 中报告进程身份，`rd.session.get_context` 也在 `data.process_identity` 中给出。CLI discovery、`version` 与 `doctor` 不执行 worker 操作，不建立进程连续性。真实的 daemon 子进程报告自己与父 daemon 的 PID 及 OS 进程诞生标识 `start_generation`（Windows 取进程创建 FILETIME，Linux 组合 boot ID 与进程启动 ticks）。这些值来自实时 OS 查询，而非持久化的 replay ID 或可编辑的 context 字段。父进程归属缺失、诞生时间不可读或平台不支持时返回 `status: unavailable` 与原因，不输出零值身份。

每个实验阶段都要比较完整的 daemon 与 worker 身份（`pid` + `start_generation`）：PID 复用或 worker 重建即是新进程，即使 capture、context、replay ID 不变也不能证明连续性；不可用的身份仍是未知，不能作为连续性依据。这只是进程来源证明，不证明原生计算、恢复或设备呈现。这些只读查询不恢复回放、不声明 helper 所有权、不增加生命周期或 shell 权限，也不暴露 daemon 密钥。

## Daemon 与状态错误

以下错误使用标准错误信封，category 为 `runtime`。它们不会停止当前 owner、清除 context 状态或创建替代 daemon，也不表示回放需要恢复；锁与所有权机制见 [session-model.md](session-model.md)。

| `error.code` | 含义 | `error.details` |
|---|---|---|
| `daemon_start_lock_timeout` | 30 秒内未取得该 context 的启动锁 | `context_id`、`failed_step=daemon_start_lock`、`waiting_for`（`thread_mutex` 或 `file_lock`）、`elapsed_seconds`、`timeout_seconds`、`recovery_hint` |
| `state_lock_timeout` | 10 秒内未取得持久化 context 状态或快照文件的锁 | `context_id`、`lock_path`、`waiting_for`、`elapsed_seconds`、`timeout_seconds`、`recovery_hint` |
| `daemon_owner_unavailable` | 无法确认 daemon 所有权 | `context_id`、`state_path`、`reason`、`recovery_hint` |

这些上限没有对应的 CLI 选项。`daemon_owner_unavailable` 覆盖：owner 锁仍被持有而状态文件缺失或无效、存活 owner 的 status 探测失败、状态发布或响应处理期间 owner 身份改变，以及启动失败后无法确认进程退出。它保留现有回放与恢复状态，从不授权自动替换或重试回放。非争用错误走各自的错误路径。诊断、daemon 响应与 CLI 输出都不包含 daemon IPC 密钥。

## 回放与主机能力

`rd.capture.open_replay` 在创建本地回放前检查 capture 的 `LocalReplaySupport`。本主机运行库不能回放该 capture 的图形 API（例如 Linux 上的 D3D capture）时返回 `local_replay_unsupported`（category `capability`，details 含 `capture_api`、`host_target`、`recovery_hint`），不会创建回放；恢复方式是先 `rd.remote.connect`，再通过 `options.remote_id` 远端回放。同 context 同 capture 的会话复用见 [session-model.md](session-model.md)。

原生 preview 窗口只在 Windows 提供。其他主机上 `rd.session.open_preview` 返回 `preview_unsupported_platform`（category `capability`），`rd.core.get_capabilities` 报告 `preview_window.available=false`；无窗口的 `rd.session.observe` 在所有主机可用。

`rd.core.get_capabilities(detail_level=summary)` 与普通 context 读取不会恢复 replay controller。`full` 只对所选 session 走常规 session 恢复路径，并在回放线程上探测原生能力。`current_session_probe` 区分 verified、unavailable（带 reason/code）与 not_currently_probed。延迟恢复或探测失败不能证明着色器功能不受支持。持久化的 endpoint 元数据不是 live 连接回执；当前进程已加载的数量不是持久化 session 的数量。没有目标的 Present 事件不能否定在实际 draw 上检查着色器的能力。

## 回放健康与时间点读取

访问 replay controller 的操作在首次访问前和发布结果前各检查一次原生 `GetFatalErrorStatus`；语义参数校验仍在访问 controller 之前完成。`replay_fatal_error` 需要受控恢复；健康探测缺失或无效为 `replay_health_unavailable`，绝不假定健康。RenderDoc 在 fatal 错误后可能返回默认零值、空对象或 API 属性，这些都不是成功测量；健康状态下的零值或空结果仍然有效。生命周期清理始终可用。该检查只发现不可用的回放，不说明远端连接失败的原因，也不证明实验已恢复。执行作用域见 [session-model.md](session-model.md)。

纹理与缓冲读取区分 `current` 与 `capture_initial`。初始读取需要记录的初始数据来源，并恢复原事件；来源不可用是错误，从不回退到当前数据。恢复失败会隔离 session。内联字节有上限，是否持久化由显式输出请求决定。

整帧计时用 GPU timestamp 测量经验证的单队列上的完整回放：不含初始状态重建，包含回放调度间隙。它不是原应用的帧时间、CPU 耗时或事件耗时之和。结果附带方法、范围、单位、采样条件与各次样本；后端不支持或队列覆盖不完整时不能产生有效测量。

`rd.perf.get_frame_timing` 需要 RenderDoc 原生 `FrameGPUDuration` counter。运行时枚举缺少它或当前回放未枚举它时返回 `frame_timing_unavailable`（category `capability`）；原生 counter 采样失败或不完整返回 `frame_timing_sample_failed`（category `runtime`）。details 标明 counter 与原因并附恢复提示。该操作从不以事件耗时之和或 CPU 时间代替。

## 捕获、资源与管线数据

capture 缩略图读取嵌入的 capture 数据，不需要回放。结构化 API 查询提供捕获的 chunk、类型化字段与有界续读，不是完整的进程 API trace。资源详情提供记录的初始化 chunk 与关系；descriptor store 提供有界范围，包括空槽与未访问的 descriptor。

资源身份对原生 ID、十进制字符串与 `ResourceId::<decimal>` 字符串使用同一精确匹配，不做浮点转换或子串匹配。资源详情复用已完成的 texture/buffer/descriptor-store/description 清单。清单中确实没有时，在绑定补全之前返回 `validation/resource_not_found`，附 `effects_attempted=false`、`context_preserved=true` 与 `failure_stage=resolve_resource`；清单读取失败从不获得这一证明。该错误是拒绝，不是空的成功资源，也不表示资源贡献为零。

`rd.resource.list_all` 在 `kind=all` 时增加 `identity_inventory`：来自 GetTextures、GetBuffers、GetDescriptorStores 与 GetResources（与资源详情解析相同的四个原生清单）的完整、精确、去重身份普查。只有四项读取都成功后才报告 scope `all_native_resource_identities`、`complete=true`、`resource_ids`、`count` 与各自的 `source_counts`。ID 始终是字符串，包括大于 2^53 的值。现有 `resources` 行及其表格投影只描述 texture、buffer 与 descriptor store，不在其中不代表不在完整原生普查中。带过滤的 `kind` 不声明全局身份完整性。原生清单读取失败是错误，绝不是空的完整普查或状态保持证明。普查只确立身份归属，不说明像素使用、因果或渲染贡献。

数值纹理读回按声明的原生通道顺序解码 packed R10G10B10A2_UNORM 与 B10G10R10A2_UNORM（10 位颜色、2 位 alpha 归一化）；mip/slice/sample 与区域选择语义不变。packed 名称不授权猜测其他分量类型；读回不足与不支持的格式仍是错误。

`rd.texture.get_region_values` 在采样并转换后的读回不超过 256 个标量时返回完整内联 `values` 数组；更大时返回 `values: null` 与 `values_status: omitted_limit`，不会静默截断，`inline_value_limit` 声明该上限。`values_path` 下的完整 NPZ 表示同一数组，供精确批量读取。区域与整纹理统计在实际 stride 样本上共用同一计算；总体与逐通道的有限 min/max/mean 以及 NaN/Inf 计数分别给出。解码的分量标签不能证明物理 alpha 或混合语义。非有限的内联样本使用 canonical 字符串标记。这些输出用于数值检查，不是自动质量验收。

请求的管线 section 保留 viewport/scissor 与输出槽索引及原生事实。限定只作用于请求的 section：未采集的模型默认值不会降低已返回绑定的限定，也不暗示省略的着色器/输出状态已被检查；请求的事实确实缺失时保留降级限定。API 不适用、数据缺失与失败相互区分；capture 中没有的动态声明仍为未知。

按阶段的管线查询不区分大小写地接受 VS/HS/DS/GS/PS/CS/MS/AS。未知名称返回 `validation/invalid_shader_stage`；可识别但不支持的 RT 阶段或原生运行库没有的阶段返回 `capability/shader_stage_unsupported`。这些拒绝发生在访问回放之前，附 `effects_attempted=false`、`context_preserved=true` 与 `failure_stage=validate_stage`。不会回退到 Pixel 或 Compute 却保留另一阶段的标签。

## 事件、VFS 与网格

`rd.event.search_actions` 的 `flags_include` / `flags_exclude` 接受原生 RenderDoc ActionFlags 成员名（如 `Drawcall`、`Dispatch`、`Present`），不接受 `is_draw` 等投影字段。无效 flag 名或数组形状在获取 controller 或加载 action 索引之前被拒绝，返回 canonical `validation_error` 并附 `effects_attempted: false`、`context_preserved: true`；其他失败不继承这一证明。

VFS `/draws` 节点把 canonical `rd.event.get_action_tree` 的分页原样保留为 `node.pagination`（树根为 `tree.pagination`），与现有 action 根 `data` 和导航 `entries` 并列。`ls`（含表格投影）、`cat` 与 `resolve` 暴露同样的来源覆盖事实；有界列表不是完整的 action 清单。树结果合并上游分页截断与自身的输出节点预算（包括 `depth=0`）：仅上游截断时报告 `upstream_pagination_truncated`；VFS 预算超限报告 `max_nodes_exceeded`，两者同时出现时以后者为准，节点的来源分页仍可读取。仅请求深度本身不标记截断。导航从不绕过 canonical 深度、分页或节点上限来拼出完整视图；显式分页与事件选择请用 canonical action tree 工具。

顶点输入查询在原始着色器输入坐标中解码声明的格式、偏移、绑定、索引与实例率；值保留语义名称，未知或含糊的语义映射保持不支持。归一化整数 NORMAL 数据不自动是几何法线。变换后的签名输出使用独立验证的原生打包，从不以输入属性代替。D3D11/12 stream-zero float 输出打包与 Vulkan VS 逐顶点 stream-zero float32 std430 打包是不同的 API 布局。Vulkan 要求唯一的前导 float4 Position、唯一的显式 varying location 且与原生 stride 完全一致；其按 API/阶段标记的布局提供原生 location/builtin、变量名、分量掩码（不可用时为 null）、标量类型、字节偏移与分量数，逐行键为 `location:N` / `builtin:Name`。其他 Vulkan 阶段、类型、速率、含糊 location 或不匹配的布局保持明确不支持；原始字节不完整时失败，解码出的非有限值为 null。仅有原生分量掩码不能证明光栅接口上的分量或插值映射；顶点输出可用也不代表光栅插值、sample/primitive 覆盖或像素着色器操作数已确立。OBJ 法线/UV 导出需要显式的 VS 输入空间与匹配的 float 属性；VS 之后的 OBJ 只含位置。

`rd.mesh.get_post_transform_data` 可选接受 VS `first_index`/`index_count` 窗口。序号以索引元素计，`decode_index_data.index_offset` 仍以字节计。窗口模式要求显式 `max_vertices`（1..256）与 1..4096 个索引，只用原生 MeshFormat 资源对象读取最多 1 MiB 的实际索引及被引用的输出行。稀疏行保留原顶点身份、源字节偏移、原始索引字节与索引到行的映射；不枚举任意内部 ID，也不以输入数据替代输出数据。原生 base vertex 与有限视图边界会被检查，无界的原生视图在窗口边界字段中保持 null。读取不足与预算失败是错误，从不以补零的成功返回。restart 匹配只是候选，不是已证明的光栅图元，并使顶点映射不完整。窗口完整性与整次 draw 的完整性是两回事。在改变事件或读取数据之前发生的参数无效及特定的缓冲解析/范围/预算拒绝附带明确的无副作用与 context 保持证明；清单读取、原生健康检查或产生副作用之后的失败保持结果不确定，消费者不得凭错误名推断状态已保持。

## 像素历史与截图

Pixel History 保留原生报告的值，不承诺可执行的逐片元混合账本。shader-out 通道须结合输出格式与后端/构建语义解读。原生 Vulkan 实现可能把超出目标分量数的通道置零、在最后一个片元上留下事件最终的 post-modification 值，并由量化的深度比较重建逐片元深度测试标志。缺失目标通道中的零值不能独立确立原始着色器输出；失败片元旁变化的 post-modification 值也不能独立把写入归因于该片元。这些实现相关的限定不能证明已安装的本地或远端二进制的源码版本。应保留原始值与未知有效性，结合事件绑定的纹理读取、管线状态与有效的着色器调试输出，再推断混合或深度问题。

`rd.texture.get_pixel_history` 接受 `texture_id` 或 `target` 之一，不能同时提供。`target` 可以指定纹理或实际 `rt_index` 输出槽；互斥或缺失的目标在获取历史之前失败。

`rd.export.screenshot` 先解析经过验证的 Present 目标，否则可以以降级来源导出事件的实际输出或事件绑定。两者都不存在时返回 `preview_event_output_unavailable`，details 中保留 Present 解析失败原因；capture 中无关的纹理不得当作 framebuffer 证据。显式纹理导出仍可用 `rd.export.texture`。应用事件后目标解析失败时，Tool 先恢复先前的原生事件再返回错误；只有恢复成功才带 `replay_state_restored:true`、`restored_event_id` 与 `artifact_write_attempted:false`。缺少先前事件或恢复失败没有可用证明，所属消费者必须隔离该回放。这不会把缺失的 Present 目标变成 framebuffer 证据。

## 着色器源码与反汇编

`rd.shader.get_source` 只读取捕获的 `ShaderDebugInfo.files`，保留原生文件顺序、文件名与内容，第一个文件是入口源码。文件名从不授权读取主机上的该路径。`source_debug_information=false` 只表示不支持源码级调试，不代表没有嵌入源码文本。源码编码、入口名与编译 flags 来自原生调试元数据，不可用时为 null。文件列表为空或入口内容缺失时返回明确的源码不可用结果（保留已有的 include 文本）；原生元数据缺失与原生读取失败返回不同的错误。源码不可用时绝不产生可编辑、可构建或可替换的 edit plan。读取失败会验证先前事件已恢复，恢复失败仍是明确的恢复失败。

`rd.shader.get_reflection` 在 `reflection.debug_info` 下暴露 RenderDoc 事件绑定的 `debugInfo.debuggable`、`sourceDebugInformation` 与 `debugStatus`。原生字段缺失为 `null`；空状态只表示没有说明。源码调试信息与着色器可调试性是两个事实，`debuggable: true` 不保证 `DebugPixel` 对特定像素返回可用的 debugger 句柄。

`rd.shader.get_disassembly` 接受 `auto`、当前存在的确切反汇编目标，或显式的原始 `SPIR-V ASM` 请求。不可用的目标在应用事件之前被拒绝，canonical 校验错误包含可用目标以及 `effects_attempted: false`、`context_preserved: true`；这两个字段只证明本次请求未尝试回放副作用，其他反汇编失败仍按常规的不确定结果恢复契约处理。成功结果包含原生 `available_targets`、`available_targets_status` 与 `available_targets_error`；完整的空列表、查询失败与原生接口缺失相互区分。它们枚举原生反汇编视图，不保证 GPU ISA 可用，也不代表 Tool 独立的原始 SPIR-V 汇编回退；`target`、`is_raw_spirv_asm` 与 `edit_plan` 需分别解读。

原始 SPIR-V 分类要求出现实际的 opcode 行。文件头、注释、诊断信息或后端接受的源码编码提示本身都不能确立可编辑的汇编；显式原始目标与外部原始反汇编回退也必须返回指令。其他原生视图保留原文供查看；信息性或失败的原生视图响应不能通过推断的原始 ASM edit plan 授权编译或替换。opcode 识别只是格式检查，不是完整验证或 GPU 执行证据，常规的编译与替换校验仍然必需。

`rd.export.shader_bundle.disassembly_target` 选择与 `rd.shader.get_disassembly` 相同的确切视图（默认 `auto`）。要把可编辑的汇编存为工作区文件以便独立编译，须显式请求 `SPIR-V ASM`；默认展示视图不是汇编器输入。bundle 记录返回的目标、编码、原始 ASM 限定、源码哈希与 edit plan，以及文件的确切 UTF-8 哈希与大小。显式目标失败或不匹配时保持 unavailable 且 `complete=false`，导出器从不替换为其他视图。导出不代表具备编译或替换能力。

## 常量缓冲

`rd.shader.get_constant_buffer_contents.slot` 是该阶段反射 `constantBlocks` 中从零开始的索引，与 RenderDoc `GetConstantBlock`、`GetCBufferVariableContents` 的用法一致，不是 API 特定的固定绑定号；`set_or_space` 保留反射的原生 set/space。当前 `UsedDescriptor.descriptor` 提供缓冲身份、字节偏移与大小。原生常量缓冲解码传入阶段绑定的 `ResourceId` 对象，从不传其序列化 ID 字符串；可用的原始字节回退明确标为降级，不证明结构化解码成功。数据缺失仍是错误。已知的 `constant_buffer_data_unavailable` 失败会先恢复并验证原活动事件，再附上 context/session/event 恢复证明；原事件未知或恢复失败时不能声称已保持。该证明不是实验回滚，也不是成功的常量缓冲读取。

`max_bytes` 是每个块的输入字节预算（默认 1048576）；0 表示不限制块大小，负值无效。允许的输入不覆盖反射块、绑定过短、范围未知或缓冲支撑的块未绑定时，不调用原生完整布局解码器，这类输入不会产生由填充推出的类型化零值。`input_coverage` 报告所需范围、绑定大小、预算与允许范围；`decode_input_bytes` 记录传给解码器的长度参数，不是独立观察到的字节读取回执。`decode_status` 区分已解码值、不可解码与显式原始回退。完整输入解码出的零是合法值；仅元数据查询不声称解码了值。

原始回退只读取允许的常量块范围并核对实际字节数；读回过短、为空或过长都失败，不会成为成功的空块。`raw_fallback.byte_size` 是观察到的字节数，`requested_bytes` 是实际的有界请求，`block_bytes` 是所需范围。`truncated` 指块覆盖；`preview_bytes` 与 `preview_truncated` 另外描述最多 256 字节的十六进制预览，完整读取块不代表预览包含全部字节。常量缓冲 dump 把请求的解码不可用与有界原始前缀传播为 `partial`，并在保存的 JSON 中保留逐块错误与覆盖信息。这些字段确立输入限定，不证明着色器执行或原生 GPU 计算；没有覆盖信息的旧输出不会被追认。

## 着色器编译与替换

`rd.shader.compile` 通过 `source_text` 或 `source_path` 接受原始 SPIR-V ASM。原生声明了 ASM 编码时使用它；在只接受二进制 SPIR-V 的后端上，使用与 PatchEngine 相同的本地 `spirv-as` 汇编路径，再把生成的模块交给 `BuildTargetShader`。它从不替换资源。结果区分请求的 `source_encoding` 与实际的 `build_encoding`；`build_input` 标识原生构建接受的确切字节，并附 `device_binary_observed: false`。汇编得到的 SPIR-V 导出为 `artifact_kind: assembled-spirv-build-input`，它就是该模块，不是设备代码或原生读回；其他原生读回导出标为 `native-shader-readback`。输入/编码拒绝与本地汇编失败发生在原生构建之前，明确返回 `effects_attempted: false` 与 `context_preserved: true`；`BuildTargetShader` 开始后的异常或失败不获得这些保证，应用继续隔离不确定的原生结果。汇编/反汇编临时文件使用配置的 intermediate 运行目录，成功、拒绝与超时时都会释放。

整源替换时，即使捕获源码不可用，`edit_plan` 仍保留引擎已验证的 `user_full_source` 编码/构建能力。`original_shader_hash` 对 `rd.shader.get_source` 选出的捕获入口源码（第一个原生调试源文件）求哈希，从不对提供的替换文本、include、主机文件内容或着色器二进制求哈希；无法读取入口源码时为现有的未知值 `""`，结果消息说明原因，整源编译仍可继续。`rd.shader.edit_and_replace.expected_source_hash` 绑定打补丁前当前绑定的**原始**源码，与整份替换文件/文本的哈希不同；不匹配或来源不可用时在编译或替换之前以校验错误拒绝，附 `replacement_attempted=false` 与 `context_preserved=true`，消费者保留原有的身份与无变更证明检查。`applied_to_shader_hash` 描述提供的替换源码，构建输入来源描述实际的编译器字节。

成功的 `rd.shader.edit_and_replace` 结果保留 `replacement.compile.build_input`：本次调用传给 `BuildTargetShader` 的确切字节、其 SHA-256 与大小、编码、原着色器 ID，以及返回并传给 `ReplaceResource` 的目标着色器 ID。这是构建输入来源，不是着色器读回或设备 ISA 证明（`device_binary_observed: false`）。对二进制 SPIR-V 输入，只有存在完整、对齐、可识别的文件头时，`spirv_header` 才暴露实际的头字（含 `id_bound`），且不校验指令语义；文本输入、畸形文件头与空操作构建不会合成二进制 bound。构建失败不报告已应用目标的证明。前后源码哈希与构建输入字节哈希相互独立。请求 patch artifact 时，同一字节序列保存为 `artifacts.build_input`（SPIR-V 模块输入为 .spv，源码输入为 .txt），否则不额外写字节 artifact；原始字节不进入普通模型 JSON 序列化。没有该来源信息的历史结果不会被追认。事件绑定的 `extract_binary` 继续检查绑定的反射，不会静默选择替换目标。

`rd.shader.edit_and_replace` 的 diff 被拒绝时仍是 `shader_patch_diff_failed` 校验失败。文本 diff 在编译或替换之前应用失败时，Tool 明确报告 `failure_stage: apply_patch`、`replacement_attempted: false` 与 `context_preserved: true`。回放可能已导航到请求的事件，因此这不是无副作用声明，也不是恢复证明、干预或回滚。未知、原生或替换失败不继承这一证明；消费者在允许下一个请求前仍要核验冻结的所属 lease。

SPIR-V 精度 patch 的目标是 ID 操作数：`variables` 接受 `%7` 或 ID 记号 `7`，两者解析为同一精确操作数，同时用于匹配报告与编辑应用。操作数两侧空白被忽略；畸形或空操作数被拒绝，绝不变成全局编辑。显式的空 `variables` 数组保留文档规定的全部 decoration 范围。该操作不会根据大小写、着色器阶段或变量编号前缀推断目标。

着色器回滚与 worker 丢失的语义见 [session-model.md](session-model.md)。

## 着色器调试

`rd.shader.debug_start` 在接受原生 trace 之前，用请求事件的 Pixel History 校验目标。显式目标单独使用；否则从该事件的输出目标中选择，只有列不出事件输出时才考虑默认输出。当前事件零命中时不能建立绑定目标的 trace，即使原生 `debugger` 非空。`ShaderDebugTrace` 没有 `valid` 字段。

着色器调试句柄限定于所属回放 session。`rd.shader.get_debug_state` 与 `rd.debug.*` 对缺失或外来句柄在获取 controller 或应用事件之前返回 canonical `shader_debug_handle_invalid` 校验失败，附 `effects_attempted: false` 与 `context_preserved: true`；有效的调试状态请求保留其应用事件的行为。校验之后的原生失败不继承这一证明。重新打开同一 capture 不会让历史调试句柄重新有效。

原生着色器调试按顺序消费 RenderDoc `ContinueDebug` 返回的每个状态。PC 指单调的 trace `stepIndex`，不是 SPIR-V result ID 或源码行。变量快照累积类型化的 `ShaderVariableChange.before/after` 更新，并移除离开作用域的变量；初始空快照有效。`get_variables` 使用字面名称过滤、有界成员深度与显式截断。只实现了指令单步与非负 PC 目标/断点；不支持的源码位置与单步模式在访问原生之前失败。调用栈保留原生函数名，未知源文件/行报告为 null。表达式求值只支持当前变量的确切名称或 JSON 字面量。原生 trace 释放失败时保留句柄并传播错误。

`rd.shader.get_debug_state.summary` 把动态 trace PC 与原生 `next_instruction` 分开报告。原生 `instInfo` 是稀疏的有序区间映射：前一条目一直适用到下一条目，跨循环与分支也一样。`source_location` 不可用时为 null，未知的源索引/行/列保持 null。从 1 开始的 `disassembly_line` 只指 RenderDoc 原生调试反汇编，从不自动对应原始 SPIR-V ASM、SSA ID 或设备 ISA。`full` 额外给出最多 64 个当前可变变量（成员深度 2）与 64 个原生调用栈名称，并附计数与截断标志；更聚焦的视图用普通变量查询获取。两种视图都不承诺任意 SSA/寄存器可见性或常量/不可变值。单步、run-to 与断点的状态响应复用同一摘要投影。`has_native_state: false` 把初始 PC 0 占位与已观察的原生状态区分开。无效的详细级别在访问原生之前被拒绝，并附无副作用证明。终止的 continue/step 结果保留明确的结束原因；单独查询的状态仍是最后观察到的原生状态。

## 图像比较

图像文件差异比较解码后的归一化 RGBA 值，按所选指标 `mse`、`max_abs`、`psnr`、`ssim` 计算（默认前三项）。未知或空的指标选择明确失败，不会静默省略请求的指标。完全相同时 PSNR 为 JSON null 并附 `psnr_status=infinite`。SSIM 使用有效的 11x11 Gaussian 窗口、sigma 1.5、总体协方差、数据范围 1，取 RGBA 各通道得分的均值；请求 SSIM 时任一维度小于 11 像素的图像失败。不缩放、不对齐图像。差异 PNG 是不透明 RGB，alpha 差异以灰度可视化，而非输出透明度。差异分数描述变化，不说明是否修复了渲染。参考：Wang et al., https://www.cns.nyu.edu/pub/eero/wang03-reprint.pdf。

`rd.util.diff_images` 可选在两张尺寸相同的源图中比较显式像素 `region`（`x`、`y`、`width`、`height`）。空、畸形或越界的矩形被拒绝而不是裁剪。指标报告原始 `source_size` 与有效 `region`；导出的差异图尺寸等于区域尺寸。SSIM 的 11 像素下限作用于所选区域。省略 region 时测量整图。这支持分别测量目标区与对照区，不改变输入图像或回放身份。

## 主机工具

Windows 安装自带 ADB 及其所需 DLL、`spirv-as` 与 `spirv-dis`。默认按安装目录相对路径解析，从不搜索 PATH 或外部 SDK；显式覆盖（变量见 [configuration.md](configuration.md)）无效时明确失败。所有 Android bootstrap 与 capture 传输路径使用同一解析器。doctor 在 `host_tools` 中报告实际路径、来源与可用性，并拒绝缺失或损坏的捆绑文件。健康的安装不需要连接 Android 设备。

## Android 远端

### 准备与借用

`rd.remote.connect` 在调用方的 daemon context 中完成 Android 准备与连接（catalog 声明 `preparation_policy: automatic`）。选择设备或调用它即授权自动准备目标 RenderDoc helper：设备上已有 helper 在运行时借用它，不安装、不改配置、不启动；没有运行的 helper 时准备并启动自有 helper，缺包则安装，versionCode 不同则覆盖安装或降级，签名冲突则卸载重装（会清除该包数据）。原生握手报告版本不兼容时，核对身份后停止该 helper 并覆盖安装。每次变更前都核对所选设备、已知 helper 包名与可读的已安装身份，无法识别时返回 `android_helper_state_unknown`。busy 端点从不修复或抢占；兼容性由原生握手决定，APK 字节不同不会导致兼容服务被替换。Android versionName 可能是源码提交哈希而非数字版本。

自有 helper 按设备 SDK 级别解析 RenderDoc 配置目录（低于 30 为 `Android/data`，30 起为 `Android/media`）。只有本次连接安装或覆盖了 APK 且设备上缺少 `renderdoc.conf` 时才推送空的默认配置（`options.push_config=false` 可关闭）；已有普通文件保持不变，SDK 或文件状态未知时在启动前失败。

helper PID 不是服务占用的证据：成功要求实际的 RenderDoc 连接与 Ping。一个超时预算覆盖 bootstrap 与连接，socket 就绪等待不超过 15 秒。借用的服务只关闭连接；只有经验证的自有 PID 与 ADB forward 可以被移除。进程与 forward 所有权独立于安装事实，历史 bootstrap 元数据从不授予新的变更权限。连接内与跨 daemon 重启的资源归属见 [session-model.md](session-model.md)。

### 诊断与取消

诊断区分设备可用性、包/安装失败、busy、不兼容与取消。`details.remote.stage` 标明 checking/installing/starting/verifying，进行中的阶段经 daemon `active_operation` 报告。取消会 join 自有的主机原生动作，只清理已取得的进程与 forward 资源；主机进程退出不能证明设备 PackageManager 已到终态。已完成的安装作为事实记录，不会为假装回滚而卸载。正常复用与清理保留借用的 helper 与用户配置。

### 已安装 APK 身份

Android bootstrap 的 `apk_sha256` 始终是本地目标 APK 的 SHA256，`installed_identity` 是 PackageManager 身份事实摘要，二者都不能替代设备上已安装文件的哈希。准备或借用完成后，只读 `pm path` 与设备 `sha256sum` 采样所选 helper 的单一 `base.apk`，通过 `installed_apk_path`、`installed_apk_sha256`、`apk_identity_status=matched|different|unavailable` 与 `apk_identity_reason` 返回。缺包、split/多路径、格式错误或不可读取时为 unavailable；目标不可读时仍可保留已观察的设备路径与哈希，但不能声称匹配。此比较不决定兼容性、借用或安装修复，不 pull 整包、不落盘，也不能证明运行进程已加载该原生库。采样使用原连接 deadline 与取消信号；普通诊断失败只降低该观察，deadline 与取消保持原有失败及清理语义。

### 未决安装

安装前只读查询 `dumpsys package installs` 的 active sessions。目标包或未知包的未终结 session，以及无法判读的 vendor 状态，返回 `remote_install_unconfirmed`，不继续安装、卸载或 abandon；包名明确的无关安装不影响已有兼容连接。`mDestroyed=true` 不能单独证明结束：必须观察到实际的成功/失败结果且 stage 不再 in-use。错误只返回必要的 session 事实，不回传其他应用的历史。

缺失的安装回执在原连接预算内只读核验；未能确证才返回 `remote_install_unconfirmed`，之后统一重试连接，禁止盲目重装。未决状态的唯一结构化标志是 `error.details.device_action`：`kind=android_install`、`state=unconfirmed`，附设备、目标包/APK hash、必要的 sessions 与 `observation=pending|unreadable`。安装超时为 `android_apk_install_timeout`；已确认的 `installation.installed_apk` / `uninstalled_existing` 事实仍保留，取消回执也不得抹去未决状态。包当前不存在、主机进程退出或 abandon 应答成功都不能替代设备端终态证明。

应用内解除未决安装使用唯一的只读操作 `rd.remote.inspect_installation`，参数只有 `device_serial`，必须在非 `default` 的所属 context 中调用。它复用连接前的设备校验、同安装 APK 包名/SHA256 与 PackageManager active-session 检查；不安装、卸载、启动 helper、建立连接或 abandon。结果 `installation_state=clear|pending|unknown` 与 `observation=verified|pending|unreadable` 分别表示可核实的状态与观察范围。`clear` 只证明没有相关的未决安装，不证明 helper 已安装、兼容或已连接；应用确认冻结的 CLI/catalog 与原目标 APK 身份一致后，才能继续用户本次明确请求的正常准备。pending/unknown 保留原未决事实与设备占用。

### 超时策略

`rd.remote.connect.timeout_policy` 由 `timeout_policy.py` 单源生成，声明 `argument`、`default_timeout_ms`、`worker_grace_ms`、`transport_grace_ms` 与 `process_grace_ms`。调用方显式传入本机 native budget；worker 在该 budget 之后保留 85 秒用于 join 与清理，CLI transport 再保留 5 秒，宿主进程再保留 5 秒接收最终回执。调用方不得根据描述猜测，也不得在缺少 policy 时默认放行。

### 设备呈现

`rd.session.observe` 经所属远端回放连接完成原生设备呈现，`remote_display` 的状态语义见 [session-model.md](session-model.md)。PNG 输出不能证明设备呈现。原生 client/helper 协议与运行库清单成对配套，不兼容的 helper 被拒绝，不做兼容转发。可复用的 Android 开发签名 keystore 保存在可丢弃的构建目录之外，使同安装 helper 的后续升级保留应用数据。
