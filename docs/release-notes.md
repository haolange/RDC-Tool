# Release Notes

## 尚未发布 — 原生回放与完整运行环境收敛

- 修复多subpass Pixel History中断、恢复及推进协调，保持附件内容和查询后状态；真实Android验证结果与独立像素读回一致。
- 已定位Store/Don't Care为load诊断；保存原始load/store状态并正确投影，保留原生诊断图案。
- 收敛Android连接、传输、进程归属、取消/断连及forward清理，准确区分不支持、合法空结果和运行失败。
- 仓库默认Python、DLL/PYD、双ABI APK与所需工具整套匹配；源码、构建、文件及实际加载身份可核验。
- 正式打包强制clean源码、同源运行时及整包验收，拒绝混加载和漂移，失败回滚；CI通过全量测试及严格doctor后才交付验证包。
- 本地1172 tests/2subtests、原生与真实Android/Agent链路通过；9项工具因样本条件N/A，其他硬件与复杂组合未外推。此次上传源码不等于发布新版Release。

## 1.1.0 — 2026-10-29

- 汇总原生事件取证与远端回放能力，补齐 shader 编译、替换、设备恢复与回放证据契约。
- Shader patch 绑定精确目标 ID 与原始源码，拒绝有歧义或来源不匹配的替换。
- 同一 daemon context 启动串行化，锁竞争共用有界 deadline，避免重复启动和无限等待。
- 发行包记录清洁源码提交号、完整文件哈希及一致版本的 Python distribution metadata；升级清除上一份发行清单中已替代的程序文件。
- 修复 bash smoke 入口变量，沿用 RenderDoc 1.45 基线及同安装捆绑 Python/CLI 绑定；实际能力以 catalog 指纹和参数契约校验。

## 1.0.2 — 2026-09-23

The `rd.session.*` worker budget is now 60 seconds. CLI daemon transport adds the shared 5-second response buffer for a 65-second deadline. This addresses session observations that serialize replay navigation, target selection, and image export. Operation definitions and result contracts are unchanged. RDC-Agent's outer CLI wait defaults to 120 seconds.

Run `rdc-tool-1.0.2-windows-x64.zip` on Windows x64. Verify the archive with `SHA256SUMS`; the archive contains its manifest, license inventory, and SBOM.
## 1.0.1 — 2026-09-20

The following sections describe the 1.0.0 baseline. Version 1.0.1 includes the complete Apache-2.0 text as the archive root LICENSE and supersedes the damaged license asset in the v1.0.0 zip. The old tag and original asset remain unchanged. Package qualification verifies actual license bytes against source, version metadata, manifest and SHA256SUMS; staging is released on success or failure. Runtime operation contracts are unchanged.

For RDC-Agent, extract the Windows x64 zip and select its `rdc-tool` folder in Settings → Tools, then verify and apply. `install.cmd` remains the optional standalone CLI installation entry.

Release verification owns an isolated runtime directory. Success, failure and cancellation clear contexts before stopping their daemons; cleanup errors fail qualification and retain recovery state instead of silently ignoring locked files. Caller runtime state is not reused.

## 1.0.0 — Operation interface convergence

- Removed redundant projections, workflow/report wrappers and generic file utilities. The subsequent 73-operation review identified 18 necessary capability gaps; restoration adds four real operations and expands existing queries. The current set is derived from definitions, with no old-name aliases or forwarding handlers.
- Moved operation names, schemas, prerequisites, scope, effects, evidence kinds, and path inputs into one code-owned definition set. Catalog, discovery, and reference output carry a deterministic content fingerprint.
- Added `rdc-tool tools describe <name>` and full catalog discovery. `rd.core.list_tools(query=...)` now owns canonical query discovery.
- Consolidated pipeline state, event tree browsing, resource kinds and usage, texture statistics, pixel-history targets, and VS/GS post-transform mesh reads into bounded canonical operations.
- Texture statistics, histograms, and numeric differences reuse in-memory readback. Unsupported layouts, non-finite inputs, invalid ranges, and backend read failures fail explicitly.
- Kept `rd.session.observe` window-free and atomic. Standalone preview remains an independent human-facing lifecycle.
- See [Tool interface convergence](tool-interface-upgrade.md) for every previous operation's disposition.

## CLI runtime baseline

- `rdc-tool` is a CLI-only RenderDoc `.rdc` runtime.
- The public user command is `rdc-tool`; release packages keep `bin/rdc-tool.cmd`, `bin/rdc-tool`, and `bundled-python cli/run_cli.py` as launcher files.
- This is the first GA public contract baseline. Pre-GA ownership, lease, baton, handoff, and runtime materialization experiments are intentionally outside the public contract.
- CLI daemon contexts are isolated runtime namespaces chosen by the caller; business orchestration remains outside this package.
- Workers use the packaged runtime binaries in place instead of materializing per-run binary copies.
- `rd.remote.connect` documents both direct RenderDoc endpoints and Android adb bootstrap via `options.transport`.
- Added stable `version` and shell completion commands.
- Release packaging produces a Windows x64 self-contained zip with checksums, manifest, license inventory, and SBOM.
- Install lifecycle is handled by `scripts/rdc_tool_install.ps1`.
- Release validation uses catalog validation, pytest, markdown health, bash CLI smoke, manifest integrity, bundled runtime checks, and package verification.

