# Agent 集成

Agent 通过自己的 shell 工具调用 `rdc-tool`，面向用户的公开命令只有 `rdc-tool`。`rdc-tool` 是 CLI-only 的，集成面就是 shell 命令与 canonical JSON envelope。

推荐的探测命令：

```bat
rdc-tool --version
rdc-tool --json doctor
rdc-tool context status --json
rdc-tool tools search pipeline --json
rdc-tool tools describe rd.pipeline.get_state --json
rdc-tool vfs ls --path / --format tsv
```

标准的 Agent 生命周期：

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

`context clear` 只释放该命名空间的 replay、preview、remote 与快照；`daemon stop` 停止该命名空间的 daemon 与 worker。宿主必须传 `--owner-pid`：launcher 意外退出后，即使请求计数卡住，daemon 也会在租约到期后被回收。`context clear` 成功不代表进程已经退出。

在已打开的 capture 上启用 preview 后，Agent 应读取 `context status --json` 中的 `preview.display` 获取 framebuffer、窗口与适配几何，而不是只凭截图推断。原生 preview 窗口只在 Windows 上提供；其他主机返回 `preview_unsupported_platform`，无窗口观察使用 `rd.session.observe`。

Shader 编辑/替换工具在 JSON 结果中提供 `edit_plan` 对象，Agent 应把它当作机器可读的使用契约：它说明当前 shader 文本能否编辑、允许哪些编辑输入、哪些 patch 操作是安全的、是否需要 `spirv-as` 等工具链，以及不支持替换时下一步该调用哪个工具。`can_replace=false` 表示应当安全停止，不是换一种文本编码重试的信号。

`--daemon-context <id>` 选择持续的运行时命名空间，不是 daemon 模式开关；省略时使用 `default` 命名空间。JSON 是 canonical 协议；TSV 只是列表/导航命令的可选表格投影，嵌套的运行时状态用 JSON。

需要可见的 smoke 时用 bash 运行，让每条 CLI 命令及其结果都出现在 Agent 终端里：

```bash
bash scripts/smoke_cli.sh
```

精确列出一个领域用 `tools list --namespace <domain>`；自由文本搜索有意返回跨领域的相关结果。生成的工具清单见 [工具参考](tool-reference.md)，任务级 SOP 见 [rdc-tool-native agent playbook](rdc-tool-native-agent-playbook.md)，旧操作的去向见 [工具接口历史处置记录](tool-interface-upgrade.md)（不是当前契约，也不是别名映射）。

## 与 RDC-Agent 配对

本节是 RDC-Tool 与 RDC-Agent 配对契约的唯一说明，其他文档只链接到这里。

- **发现**：RDC-Agent 通过 `rdc-tool version --json` 与 `rdc-tool tools list --full --json` 读取所选安装的版本信息与完整 catalog。
- **校验与冻结**：RDC-Agent 按内容 fingerprint 校验 catalog，并在每个 turn 内冻结它。catalog 只取自实际调用的同一安装，不加载第二份 catalog，也不翻译已删除的名称。
- **授权**：能否调用某个操作由 catalog 定义与 fingerprint 决定；包版本号只是安装信息，不授权也不选择接口。
- **调用**：RDC-Agent 用该安装的捆绑 Python 运行同一安装的 `cli/run_cli.py`（Windows 上为 `<installation>/binaries/windows/x64/python/python.exe`）。shell 包装器和跨安装的组合都会被拒绝；配置方式见 [安装](install.md)。
- **证据边界**：本地 PNG 导出不能证明 Android 设备已呈现画面。

RenderDoc 运行库基线见 [发布基线](release-baseline.md)。

## 历史验收记录：RDC-Agent 集成（2026-10-28）

> 本节是 2026-10-28 的一次消费链路实测记录，只说明当时的源码与安装，不验证当前代码或之后的发行包。

这次实测使用 RDC-Tool 源码基线 `3c3bfff6fbaa36499c9170c81aada4142de15b6d`，冻结的 catalog 指纹记录在验收台账中。当时没有修改 Tool 的操作定义、原生实现或安装，也没有制作或发布新包，只同步了真实集成结果。

- RDC-Agent 在 Android 远端的同一 capture 上完成了自主定位、shader 分析、一次精度许可内的修改和一次语义不变的重建对照。两次替换都真实应用并撤销，恢复后的图像与基线一致，替换集合为空；身份、lease、签名回执与原生审批保持有效。
- 首次独立评审因冻结的 40 次工具额度用尽而返回 partial。用户随后明确批准一次只核对三项现存材料（回执时序、两次历史替换集合、ASM 常量）的只读补审，实际用 34/48 次工具调用完成，没有重开回放或重跑实验。原结果、消费记录与期限保留，没有为绕过 Harness 门禁而修改 Tool。
- 最终报告接受当前 capture 的局部修正、已观察区域的有限画质和真实恢复；这不代表工程源码已部署、已跨设备验证、驱动内部机制已被证明或所有像素无损。画质属于 Agent 评审，具体候选的发色方向另由用户确认。
- 回放由正式入口关闭，随后核验自有 daemon 与 worker 已退出；保留用户 helper、原始 capture 与必要证据，删除隔离凭据和中间资产。`context clear` 成功不能代替进程退出的证明。

消费者实际 Main SHA-256 为 `952658f0484006186f974cc6afad4edcc95af8d2578a998b8b84f4d0cef8c64b`；最终报告 `invart-c7be1f318789-1793169763702`，内容 SHA-256 为 `d1437b485ffa0d850e2f7a1bbd607e625a286952340518b0ca2122dd4db8b9e3`。完整范围与验证记录见 [RDC-Agent 验收台账](https://github.com/haolange/RDC-Agent/blob/main/docs/product/acceptance-ledger.md)。这些只是当时消费链路的证据，不能代替 Tool 后续源码变更或发行包的验证。
