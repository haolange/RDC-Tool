# Agent Integration

Agents should call `rdc-tool` through their shell tool. The public user command is `rdc-tool`.

Recommended probes:

```bat
rdc-tool --version
rdc-tool --json doctor
rdc-tool context status --json
rdc-tool tools search pipeline --json
rdc-tool tools describe rd.pipeline.get_state --json
rdc-tool vfs ls --path / --format tsv
```

Canonical agent lifecycle:

```bat
rdc-tool --daemon-context task-123 --json doctor
rdc-tool --daemon-context task-123 context status --json
rdc-tool --daemon-context task-123 capture open --file "C:\captures\case.rdc"
rdc-tool --daemon-context task-123 capture open --file "C:\captures\android.rdc" --remote-id "<remote_id_from_rd.remote.connect>"
rdc-tool --daemon-context task-123 vfs tree --path /draws --depth 2 --max-nodes 2000 --format json
rdc-tool --daemon-context task-123 event list --format tsv
rdc-tool --daemon-context task-123 pipeline show --event-id 42 --format json
rdc-tool --daemon-context task-123 context update --key notes --value "triaged" --json
rdc-tool --owner-pid %PID% --daemon-context task-123 context clear --json
rdc-tool --owner-pid %PID% --daemon-context task-123 daemon stop
```

`context clear` only releases that namespace's replay/preview/remote/snapshot. `daemon stop` stops that namespace's daemon and worker. Hosts must pass `--owner-pid` so a dead launcher can reap the daemon after the lease, even if a request count is stuck. Do not treat clear success as process exit.

After enabling preview for an opened capture, agents should inspect `preview.display` in `context status --json` for framebuffer, window, and fit geometry instead of inferring geometry from screenshots alone.

Shader edit/replace tools expose an `edit_plan` object in JSON payloads. Agents should treat it as the machine-readable usage contract: it says whether the current shader text can be edited, which edit inputs are allowed, which patch ops are safe, whether a toolchain such as `spirv-as` is required, and which tool to call next when replacement is unsupported. A `can_replace=false` plan is a safe stop, not a signal to retry with a different text encoding.

`--daemon-context <id>` selects a continuous runtime namespace. It is not a daemon-mode switch; omitting it uses the `default` namespace. JSON is the canonical protocol. TSV is an optional tabular projection for list/navigation commands; use JSON for nested runtime state.

For visible smoke, use bash so every CLI command and result appears in the agent terminal:

```bash
bash scripts/smoke_cli.sh
```

`rdc-tool` is CLI-only. Agents should integrate through shell commands and the canonical JSON envelope.

CLI callers should fetch the catalog from the same configured `rdc-tool` executable they invoke and freeze its fingerprint with the turn/session binding. Do not load a second catalog path or translate removed names. Use `tools list --namespace` for an exact domain; free-text search intentionally returns related cross-domain matches.


The generated reader-facing tool list is [Tool reference](tool-reference.md). Migration destinations are in [Tool interface convergence](tool-interface-upgrade.md). The task-level SOP is [rdc-tool-native agent playbook](rdc-tool-native-agent-playbook.md).

## RenderDoc runtime baseline

The current assembled and verified baseline is **RenderDoc 1.45**. RDC-Tool does not track every upstream minor release: a newer runtime becomes the baseline only after matching runtime packaging, catalog checks, tests and release gates pass. RenderDoc 1.44 and earlier official GUI releases are not separate assembly targets. Use the replay path matching this bundled runtime. Capture-format compatibility follows upstream RenderDoc.

RDC-Agent **0.6.x** pairs with RDC-Tool **1.0.0** and the current RenderDoc **1.45** runtime. Catalog definitions and fingerprints, not package version numbers, authorize operations. Local PNG export does not prove Android device presentation.

## RDC-Agent 集成验收（2026-10-28）

本次消费者实测使用 RDC-Tool 源码基线 `3c3bfff6fbaa36499c9170c81aada4142de15b6d`，冻结 catalog 指纹 `e1e6fd9158e829d7dd4422726e47189ef3ae992c965474d11b1200a327a5d110`。本轮没有修改 Tool 的操作定义、原生实现或安装，也没有制作或发布新包；本节只同步真实集成结果。

- RDC-Agent 在 Android 远端同一 capture 上完成自主定位、shader 分析、一次精度许可修改及一次语义不变重建对照。两次替换均真实应用、撤销，恢复图与基线一致，恢复后替换集合为空。身份、lease、签名回执和原生审批保持生效。
- 初次独审因冻结的 40 次工具额度耗尽返回 partial。用户随后明确批准一个仅核对三项现存材料的只读补审：回执时序、两次历史替换集合、ASM 常量；实际 34/48 次工具调用完成，没有重开回放或重跑实验。原结果、消费和期限保留，没有修改 Tool 来绕过 Harness 门禁。
- 最终报告接受当前 capture 的局部修正、已观察区域的有限画质和真实恢复；不代表工程源码已部署、跨设备验证、驱动内部机制已证明或所有像素无损。画质属于 Agent 评审，具体候选的发色方向另有用户确认。
- 回放由正式入口关闭，随后核验自有 daemon、worker 退出；保留用户 helper、原始 capture 和必要证据，删除隔离凭据及中间资产。`context clear` 成功仍不能代替进程退出证明。

消费者实际 Main SHA-256 为 `952658f0484006186f974cc6afad4edcc95af8d2578a998b8b84f4d0cef8c64b`；最终报告 `invart-c7be1f318789-1793169763702`，内容 SHA-256 `d1437b485ffa0d850e2f7a1bbd607e625a286952340518b0ca2122dd4db8b9e3`。完整范围与验证记录见 [RDC-Agent Acceptance Ledger](https://github.com/haolange/RDC-Agent/blob/main/docs/product/acceptance-ledger.md)。这些是本次消费链路证据，不能代替 Tool 后续源码变更或发行包的验证。