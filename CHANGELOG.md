# 变更记录 `Changelog`

## 待发布 `Unreleased`

## 1.1.2 — 2026-10-29

- 修复 Windows 后台 worker 的 Android 冷启动：使用同安装 ADB 有界启动 server，显式设备按冻结 serial 查询 get-state，仅在 device 状态继续准备。
- 未指定 serial 时保留明确枚举并校验响应；空响应与未授权、离线分别失败，不静默切换设备、不增加隐藏重试。
- ADB 子进程在 Windows 使用分离进程组，继续复用连接 deadline、取消和退出回收；不改变 helper 归属、catalog 或用户数据边界。

## 1.1.1 — 2026-10-29

- Windows 安装自包含 ADB 36.0.2、所需 DLL 与 SPIRV-Tools v2026.4 汇编/反汇编程序，固定来源、哈希与许可证并写入 SBOM。
- ADB/SPIR-V 默认解析本安装；保留显式高级覆盖，无效覆盖直接失败，删除 PATH/SDK 静默搜索与无调用配置。
- doctor、runtime manifest 重生成和发行门禁验证完整工具链；未连接设备与安装损坏分别报告。
- 修复非交互 ADB 继承 stdin 导致输出丢失，连接与传输统一使用受控标准输入；不改变操作 catalog 与用户数据边界。


## 1.1.0 — 2026-10-29

- 汇总原生事件取证与远端回放能力，补齐 shader 编译、替换、设备恢复与回放证据契约。
- Shader patch 绑定精确目标 ID 与原始源码，拒绝有歧义或来源不匹配的替换。
- 同一 daemon context 启动串行化，锁竞争共用有界 deadline，避免重复启动和无限等待。
- 发行包记录清洁源码提交号、完整文件哈希及一致版本的 Python distribution metadata；升级清除上一份发行清单中已替代的程序文件。
- 修复 bash smoke 入口变量，沿用 RenderDoc 1.45 基线及同安装捆绑 Python/CLI 绑定；实际能力以 catalog 指纹和参数契约校验。

## 1.0.2 — 2026-09-23

- 将 `rd.session.*` worker 操作预算统一提高到 60 秒；CLI daemon transport 继续增加 5 秒响应缓冲，门限为 65 秒。
- 与 RDC-Agent 默认 120 秒外层 CLI 等待对齐；操作目录与 IPC/result contract 不变。
- 补充 session timeout 策略测试、故障排查说明与会话模型文档。

## 1.0.1 — 2026-09-20

- 恢复完整 Apache-2.0 LICENSE 并收入新 zip，不修改 v1.0.0 tag 或旧资产。
- 核对发行版本、CHANGELOG、manifest、SBOM、license inventory 与 checksum；包内 LICENSE 必须与当前源码逐字节一致。
- 打包使用独立暂存目录，成功或失败均释放；Agent 可直接选择解压目录。
- 发行验证使用隔离运行目录，成功、失败或取消时先释放 context 再停止自有 daemon；清理失败使门禁失败并保留恢复信息，不吞掉占用错误。

## 1.0.0

### Breaking

- Breaking: 产品和公共命令统一为 `rdc-tool`，旧 `rdx` / `rdx-tools` 入口不提供转发或兼容别名。嵌入宿主绑定同安装捆绑 Python 与 `cli/run_cli.py`。

### 首个 GA baseline

- 发布口径锁定为 1.0.0 首个 GA baseline；pre-GA 的 owner/lease/baton/handoff 与 runtime materialization 实验不进入 1.0 公共契约。
- 收敛 CLI context 模型：`--daemon-context` 仅表示隔离 runtime namespace，不承载业务编排或任务交接语义。
- 移除 worker runtime materialization/cache 设计，worker 直接使用 packaged runtime binaries 与 `pymodules`。
- 明确 `rd.remote.connect` 的 direct RenderDoc 与 Android adb bootstrap 参数契约。
- 加固 release package 验证：发布包必须与当前 release source tree manifest 一致，且不得携带 pre-GA runtime cache / owner-handoff surface。
- 新增持久化 `context/session` state，支持本地 `.rdc` warm resume、多 session `current_session_id` 选择、trace-linked operation history、runtime metrics 与 bounded event-tree pagination。
- 新增 `rd.session.list_sessions`、`rd.session.select_session`、`rd.session.resume`、`rd.core.get_operation_history`、`rd.core.get_runtime_metrics`、`rd.core.list_tools`、`rd.core.search_tools` 与 `rd.core.get_tool_graph`。
- 新增只读 `rd.vfs.*` tools，以及配套的 CLI `vfs` commands，用于在 draws、passes、resources、pipeline、context 与 artifacts 上执行 JSON-first 导航。
- 修复 `scripts/release_gate.py`，使 `rg` fallback 能区分 literal/path scan 与 regex scan，并避免在无效 regex assembly 时崩溃。
- 新增 `pyproject.toml`，让依赖、pytest markers 与本地开发 entrypoints 可复现，同时不改变 repo-first runtime model。
- 新增聚焦 VFS 的 tests 与 release-gate regression coverage。
- 新增 stable/GA CLI surface：`--version`、`version --json`、`completion powershell|bash|zsh|fish`、自包含 Windows x64 release package、安装生命周期脚本、package verification 与 1.x 兼容承诺文档。
