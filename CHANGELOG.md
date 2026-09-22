# 变更记录 `Changelog`

## 待发布 `Unreleased`

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
