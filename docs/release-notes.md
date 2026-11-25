# 发布说明

## 尚未发布

### 主机布局与发行包

- 发行包按主机构建，命名为 `rdc-tool-<version>-<host_target>.zip`：源码部分对所有主机相同，`binaries/` 只带本主机运行目录、两个 Android helper 与共享回执 `binaries/native_build.json`。目前发布的是 `windows-x64`。
- 新增 Linux x64 主机布局（`binaries/linux/x64`，launcher `bin/rdc-tool`）；正式的 Linux 产物随下一轮同源构建提供，尚未发布 Linux 包。
- `bin/rdc-tool` 按主机选择捆绑解释器：Linux x86_64 运行捆绑的 python3.14，MSYS/Cygwin 运行 Windows 捆绑 Python；未知主机或缺少解释器以退出码 2 拒绝。安装根目录由 launcher 与包的位置推导，可在任意工作目录运行，运行路径不再接受环境变量覆盖。
- 原生 preview 窗口只在 Windows 上提供；其他主机的 `rd.session.open_preview` 返回结构化错误 `preview_unsupported_platform`，`rd.core.get_capabilities` 的 `preview_window.available` 为 `false`。无窗口的 `rd.session.observe` 在所有主机可用。
- `rd.capture.open_replay` 在本地回放前检查本主机运行库能否回放该 capture 的图形 API，不能时返回 `local_replay_unsupported`（category `capability`），例如在 Linux 上回放 D3D capture。
- 持久化状态锁最多等待 10 秒，超时返回 `state_lock_timeout`。
- 原生构建回执迁到全目标共享的 `binaries/native_build.json`；doctor 按目标报告 `verified`/`absent`，所需目标缺失时列出 `missing_targets`。

### daemon、CLI 与配置

- `version --json` 报告本安装提供的 catalog 身份（`data.catalog.fingerprint` 与 `tool_count`），与 `tools list --json` 一致；RDC-Agent 按（版本，指纹）成对校验，与其打包快照不一致时明确报错。
- daemon 在解码任何请求前完成 HMAC 握手；IPC key 经 stdin 传递，不再出现在命令行参数和任何 CLI 输出中。`daemon status`/`start` 的输出字段 `pipe_name` 改为 `endpoint`。升级前留下的旧格式 state 会被判为无效，重新 `daemon start` 即可。
- 删除未文档化的 `daemon start --pipe-name` 与 CLI 私有别名 `--context-id`；`rdc-tool --version`、`version --json` 与 help 只有一套输出。
- `rd.core.set_config` 只接受实际生效的键（`artifact_dir`、`log_level`、`snapshot_retention`、`runtime_limits`），未知键报错。
- 运行路径相关的环境变量（如 `RDC_TOOL_ROOT`）已删除，安装位置即运行根目录；现存变量以 [配置](configuration.md) 为准。

### 原生回放与完整运行环境收敛（2026-11-04 上传）

- 修复多 subpass Pixel History 的中断、恢复与推进协调，保持附件内容与查询后的状态；真实 Android 验证结果与独立像素读回一致。
- 查明已定位的 Store/Don't Care 现象属于 load 诊断；保存原始 load/store 状态并正确投影，保留原生诊断图案。
- 收敛 Android 连接、传输、进程归属、取消/断连与 forward 清理，准确区分不支持、合法空结果和运行失败。
- 仓库默认的 Python、DLL/PYD、双 ABI APK 与所需工具整套匹配；源码、构建、文件与实际加载身份均可核验。
- 正式打包强制要求干净源码、同源运行库与整包验收，拒绝混加载与漂移，失败时回滚；CI 通过全量测试与严格 doctor 后才交付验证包。
- 当时本地 1172 个测试与 2 个 subtest、原生链路以及真实 Android/Agent 链路通过；9 项工具因样本条件为 N/A，其他硬件与复杂组合未外推。上传源码不等于发布新的 Release。

## 1.1.2 — 2026-10-29

- 修复 Windows 后台 worker 的 Android 冷启动：用同安装的 ADB 有界启动 server；显式指定设备时按冻结的 serial 查询 get-state，只在 `device` 状态下继续准备。
- 未指定 serial 时保留明确的设备枚举并校验响应；空响应、未授权与离线分别报错，不静默切换设备，也不增加隐藏重试。
- ADB 子进程在 Windows 上使用分离的进程组，继续沿用连接 deadline、取消与退出回收；不改变 helper 归属、catalog 或用户数据边界。

## 1.1.1 — 2026-10-29

- Windows 安装包自带 ADB 36.0.2 及所需 DLL，以及 SPIRV-Tools v2026.4 的汇编/反汇编程序；来源、哈希与许可证固定并写入 SBOM。
- ADB 与 SPIR-V 工具默认使用本安装自带的版本；保留显式的高级覆盖，覆盖无效时直接失败；删除 PATH/SDK 静默搜索。
- doctor、runtime manifest 重新生成与发布门禁验证完整工具链；未连接设备与安装损坏分别报告。
- 修复非交互 ADB 继承 stdin 导致输出丢失的问题，连接与传输统一使用受控的标准输入；不改变操作 catalog 与用户数据边界。

## 1.1.0 — 2026-10-29

- 汇总原生事件取证与远端回放能力，补齐 shader 编译、替换、设备恢复与回放证据契约。
- Shader patch 绑定精确的目标 ID 与原始源码，拒绝有歧义或来源不匹配的替换。
- 同一 daemon context 的启动串行化，锁竞争共用有界 deadline，避免重复启动和无限等待。
- 发行包记录干净源码的提交号、完整文件哈希以及版本一致的 Python distribution metadata；升级时清除上一份发行清单中已被替代的程序文件。
- 修复 bash smoke 入口变量；本版沿用 RenderDoc 1.45 基线与同安装捆绑 Python/CLI 绑定，实际能力以 catalog 指纹和参数契约校验。

## 1.0.2 — 2026-09-23

`rd.session.*` 的 worker 预算调整为 60 秒，CLI daemon 传输再加上共享的 5 秒响应缓冲，截止时间为 65 秒。这解决了需要串行完成回放导航、目标选择与图像导出的会话观察超时问题。操作定义与结果契约不变。RDC-Agent 外层 CLI 等待默认 120 秒。

在 Windows x64 上使用 `rdc-tool-1.0.2-windows-x64.zip`，用 `SHA256SUMS` 校验归档；归档内含 manifest、许可证清单与 SBOM。

发行身份：`v1.0.2` 指向 `07f613f3420d7a7b7480f5a8114c7ebc9f13c3b3`；ZIP sha256 `a7480ad08080e41c8133c2e9021bee1b5c8be260a70f57e9656bb0156680b1ae`，`SHA256SUMS` sha256 `4cf27faed3dd0396fbfa87950af1d2d736a0814e20470668caf48ded237d6f48`。

## 1.0.1 — 2026-09-20

以下各节描述 1.0.0 基线。1.0.1 把完整的 Apache-2.0 文本作为归档根目录的 LICENSE，取代 v1.0.0 ZIP 中损坏的许可证文件；旧 tag 与原资产保持不变。包资格校验逐字节核对许可证与源码、版本元数据、manifest 和 SHA256SUMS；暂存目录在成功或失败时都会释放。运行时操作契约不变。

RDC-Agent 用户解压 Windows x64 ZIP 后，在 设置 → Tools 中选择其中的 `rdc-tool` 目录，验证并应用即可。`install.cmd` 仍是可选的独立 CLI 安装入口。

发布验证使用自有的隔离运行目录。成功、失败与取消都会先清理 context 再停止 daemon；清理出错时资格校验失败并保留恢复状态，不静默忽略被占用的文件。不复用调用方的运行状态。

## 1.0.0 — 操作接口收敛

- 删除冗余的投影、workflow/report 包装与通用文件工具。随后对 73 个操作的复查发现 18 处必要的能力缺口，恢复时新增 4 个真实操作并扩展已有查询。当前集合由定义派生，没有旧名别名或转发处理器。
- 把操作名称、schema、前置条件、作用域、影响、证据类型与路径输入收进一套代码内定义。catalog、discovery 与参考输出带确定性的内容 fingerprint。
- 新增 `rdc-tool tools describe <name>` 与完整 catalog discovery；`rd.core.list_tools(query=...)` 负责 canonical 查询发现。
- 把管线状态、事件树浏览、资源类型与用途、纹理统计、像素历史目标以及 VS/GS 变换后的网格读取收敛为有界的 canonical 操作。
- 纹理统计、直方图与数值差异复用内存读回。不支持的布局、非有限输入、无效范围与后端读取失败都显式报错。
- `rd.session.observe` 保持无窗口且原子；独立 preview 仍是面向人工的独立生命周期。
- 旧操作的逐项处置见 [工具接口历史处置记录](tool-interface-upgrade.md)。

## 1.0.0 — CLI 运行时基线

- `rdc-tool` 是 CLI-only 的 RenderDoc `.rdc` 运行时。
- 公开用户命令是 `rdc-tool`；发行包保留 `bin/rdc-tool.cmd`、`bin/rdc-tool` 与捆绑 Python + `cli/run_cli.py` 作为 launcher 文件。
- 这是首个 GA 公共契约基线。pre-GA 的 ownership、lease、baton、handoff 与运行时 materialization 实验有意不纳入公共契约。
- CLI daemon context 是调用方选择的隔离运行时命名空间；业务编排不在本包范围内。
- worker 原地使用打包的运行库二进制，不再为每次运行复制一份二进制。
- `rd.remote.connect` 的文档同时说明直连 RenderDoc endpoint 与经 `options.transport` 的 Android adb bootstrap。
- 新增稳定的 `version` 与 shell completion 命令。
- 发行打包生成 Windows x64 自包含 ZIP，附带 checksum、manifest、许可证清单与 SBOM。
- 安装生命周期由 `scripts/rdc_tool_install.ps1` 处理。
- 发布验证包括 catalog 校验、pytest、markdown 健康检查、bash CLI smoke、manifest 完整性、捆绑运行库检查与包校验。
